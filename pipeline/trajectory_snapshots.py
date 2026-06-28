"""Step 4: Trajectory snapshot pipeline.

Reads behavioral_snapshots from DB, computes velocity/acceleration/regime
per user per day using a rolling window of prior snapshots, and writes
trajectory_snapshots + trajectory_events.

For each user on each day, the pipeline looks back at the last N days of
behavioral snapshots (configurable, default 30) and computes:
  - Velocity/acceleration/stability/regime from composite embedding series
  - Per-zone drift magnitudes (cosine distance from first to current)
  - Per-context drift magnitudes
  - Regime detection and trajectory events

Usage:
    python -m pipeline.trajectory_snapshots
    python -m pipeline.trajectory_snapshots --window 30
    python -m pipeline.trajectory_snapshots --start 2025-02-01
"""

import argparse
import json
import time
from datetime import date

import numpy as np

from pipeline.db_connect import get_connection
from pipeline.temporal_store import record_trajectory_event, temporal_write
from embeddings.composer import cosine_similarity
from models.temporal_trajectory import (
    compute_trajectory_features, compute_velocity_vector, detect_regime,
)

WINDOW_DAYS = 30
VELOCITY_ANOMALY_THRESHOLD = 0.15

ZONE_COLS = [
    "zone_identity", "zone_access_pattern", "zone_data_behavior",
    "zone_network_footprint", "zone_risk_posture",
]
CONTEXT_COLS = [
    "composite_normal_ops", "composite_insider_inv",
    "composite_apt_hunt", "composite_privilege_audit",
]
CONTEXT_COL_TO_NAME = {
    "composite_normal_ops": "normal_ops",
    "composite_insider_inv": "insider_investigation",
    "composite_apt_hunt": "apt_hunt",
    "composite_privilege_audit": "privilege_audit",
}

UPSERT_SQL = """
    INSERT INTO trajectory_snapshots (
        entity_type, entity_id, cutoff_date,
        velocity_magnitude, acceleration, stability,
        regime_shifts, trend_consistency, total_drift,
        current_regime, zone_drifts, context_drifts,
        velocity_vector, relationship_drift
    ) VALUES (
        %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s,
        %s, %s::jsonb, %s::jsonb,
        %s, %s
    ) ON CONFLICT (entity_type, entity_id, cutoff_date) DO UPDATE SET
        velocity_magnitude = EXCLUDED.velocity_magnitude,
        acceleration = EXCLUDED.acceleration,
        stability = EXCLUDED.stability,
        regime_shifts = EXCLUDED.regime_shifts,
        trend_consistency = EXCLUDED.trend_consistency,
        total_drift = EXCLUDED.total_drift,
        current_regime = EXCLUDED.current_regime,
        zone_drifts = EXCLUDED.zone_drifts,
        context_drifts = EXCLUDED.context_drifts,
        velocity_vector = EXCLUDED.velocity_vector,
        relationship_drift = EXCLUDED.relationship_drift,
        computed_at = now()
"""


def _vec_to_pgvector(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in v) + "]"


def _pgvector_to_array(s) -> np.ndarray | None:
    """Parse a pgvector string '[0.1,0.2,...]' into numpy array."""
    if s is None:
        return None
    if isinstance(s, np.ndarray):
        return s
    if isinstance(s, (list, tuple)):
        return np.array(s, dtype=np.float32)
    s_str = str(s).strip()
    if s_str.startswith("[") and s_str.endswith("]"):
        vals = s_str[1:-1].split(",")
        return np.array([float(v) for v in vals], dtype=np.float32)
    return None


def _fetch_user_snapshot_window(conn, user_id: str, cutoff: date, window: int) -> list[dict]:
    """Fetch behavioral snapshots for a user within a lookback window."""
    sql = """
        SELECT cutoff_date, composite,
               zone_identity, zone_access_pattern, zone_data_behavior,
               zone_network_footprint, zone_risk_posture,
               composite_normal_ops, composite_insider_inv,
               composite_apt_hunt, composite_privilege_audit
        FROM behavioral_snapshots
        WHERE entity_type = 'user' AND entity_id = %s
          AND cutoff_date <= %s
          AND cutoff_date > %s::date - %s
        ORDER BY cutoff_date
    """
    with conn.cursor() as cur:
        cur.execute(sql, (user_id, cutoff, cutoff, window))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return rows


def _compute_zone_drifts(snapshots: list[dict]) -> dict:
    """Compute per-zone drift (1 - cosine(first, last)) from snapshot series."""
    if len(snapshots) < 2:
        return {z: 0.0 for z in ZONE_COLS}
    first = snapshots[0]
    last = snapshots[-1]
    result = {}
    for z in ZONE_COLS:
        v1 = _pgvector_to_array(first.get(z))
        v2 = _pgvector_to_array(last.get(z))
        if v1 is not None and v2 is not None:
            result[z.replace("zone_", "")] = float(1.0 - cosine_similarity(v1, v2))
        else:
            result[z.replace("zone_", "")] = 0.0
    return result


def _compute_context_drifts(snapshots: list[dict]) -> dict:
    """Compute per-context drift from snapshot series."""
    if len(snapshots) < 2:
        return {c: 0.0 for c in CONTEXT_COLS}
    first = snapshots[0]
    last = snapshots[-1]
    result = {}
    for c in CONTEXT_COLS:
        v1 = _pgvector_to_array(first.get(c))
        v2 = _pgvector_to_array(last.get(c))
        ctx_name = CONTEXT_COL_TO_NAME[c]
        if v1 is not None and v2 is not None:
            result[ctx_name] = float(1.0 - cosine_similarity(v1, v2))
        else:
            result[ctx_name] = 0.0
    return result


def _available_dates(conn, start: date = None, end: date = None) -> list[date]:
    sql = "SELECT DISTINCT cutoff_date FROM behavioral_snapshots WHERE entity_type = 'user'"
    params = []
    if start:
        sql += " AND cutoff_date >= %s"
        params.append(start)
    if end:
        sql += " AND cutoff_date <= %s"
        params.append(end)
    sql += " ORDER BY cutoff_date"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [row[0] for row in cur.fetchall()]


def _get_user_ids(conn) -> list[str]:
    sql = "SELECT DISTINCT entity_id FROM behavioral_snapshots WHERE entity_type = 'user'"
    with conn.cursor() as cur:
        cur.execute(sql)
        return [row[0] for row in cur.fetchall()]


def process_day(conn, cutoff: date, user_ids: list[str], window: int) -> tuple[int, int]:
    """Process one day: compute trajectories for all users. Returns (snapshot_count, event_count)."""
    traj_rows = []
    events_to_insert = []

    for uid in user_ids:
        snapshots = _fetch_user_snapshot_window(conn, uid, cutoff, window)
        if len(snapshots) < 2:
            continue

        composite_series = []
        for s in snapshots:
            v = _pgvector_to_array(s["composite"])
            if v is not None:
                composite_series.append(v)

        if len(composite_series) < 2:
            continue

        feats = compute_trajectory_features(composite_series)
        vel_vec = compute_velocity_vector(composite_series)
        regime = detect_regime(feats)
        zone_drifts = _compute_zone_drifts(snapshots)
        ctx_drifts = _compute_context_drifts(snapshots)

        row = (
            "user", uid, cutoff,
            feats["velocity_magnitude"],
            feats["acceleration"],
            feats["stability"],
            feats["regime_shifts"],
            feats["trend_consistency"],
            feats["total_drift"],
            regime,
            json.dumps(zone_drifts),
            json.dumps(ctx_drifts),
            _vec_to_pgvector(vel_vec),
            None,
        )
        traj_rows.append(row)

        if regime == "regime_shift":
            events_to_insert.append({
                "entity_type": "user",
                "entity_id": uid,
                "event_date": cutoff,
                "event_type": "regime_shift",
                "severity": "high" if feats["total_drift"] > 0.1 else "medium",
                "magnitude": feats["total_drift"],
                "shift_type": "abrupt" if feats["regime_shifts"] > 0.3 else "gradual",
                "direction": "degrading" if feats["acceleration"] > 0 else "lateral",
                "contributing_factors": {
                    "zone_drifts": zone_drifts,
                    "velocity": feats["velocity_magnitude"],
                    "acceleration": feats["acceleration"],
                },
            })
        elif regime == "accelerating" and feats["total_drift"] > 0.05:
            events_to_insert.append({
                "entity_type": "user",
                "entity_id": uid,
                "event_date": cutoff,
                "event_type": "behavioral_shift",
                "severity": "medium",
                "magnitude": feats["total_drift"],
                "shift_type": "gradual",
                "direction": "degrading",
                "contributing_factors": {
                    "zone_drifts": zone_drifts,
                    "velocity": feats["velocity_magnitude"],
                    "acceleration": feats["acceleration"],
                },
            })
        elif regime == "drifting":
            events_to_insert.append({
                "entity_type": "user",
                "entity_id": uid,
                "event_date": cutoff,
                "event_type": "trend_change",
                "severity": "medium" if feats["total_drift"] > 0.05 else "low",
                "magnitude": feats["total_drift"],
                "shift_type": "gradual",
                "direction": "degrading" if feats["acceleration"] > 0 else "lateral",
                "contributing_factors": {
                    "zone_drifts": zone_drifts,
                    "velocity": feats["velocity_magnitude"],
                    "acceleration": feats["acceleration"],
                },
            })

        # Anomaly check — independent of regime (not elif)
        if feats["velocity_magnitude"] > VELOCITY_ANOMALY_THRESHOLD:
            events_to_insert.append({
                "entity_type": "user",
                "entity_id": uid,
                "event_date": cutoff,
                "event_type": "anomaly",
                "severity": "high" if feats["velocity_magnitude"] > 0.3 else "medium",
                "magnitude": feats["velocity_magnitude"],
                "shift_type": "abrupt",
                "direction": "degrading",
                "contributing_factors": {
                    "velocity": feats["velocity_magnitude"],
                    "acceleration": feats["acceleration"],
                    "total_drift": feats["total_drift"],
                },
            })

    if traj_rows:
        from psycopg2.extras import execute_batch
        with conn.cursor() as cur:
            execute_batch(cur, UPSERT_SQL, traj_rows, page_size=200)
        conn.commit()

    for ev in events_to_insert:
        record_trajectory_event(conn, **ev)
        conn.commit()

    return len(traj_rows), len(events_to_insert)


def main():
    parser = argparse.ArgumentParser(description="Compute trajectory snapshots from behavioral embeddings")
    parser.add_argument("--start", type=str, help="Start date")
    parser.add_argument("--end", type=str, help="End date")
    parser.add_argument("--window", type=int, default=WINDOW_DAYS,
                        help=f"Lookback window in days (default: {WINDOW_DAYS})")
    args = parser.parse_args()

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    conn = get_connection()
    dates = _available_dates(conn, start, end)
    user_ids = _get_user_ids(conn)
    print(f"Found {len(dates)} days, {len(user_ids)} users")
    print(f"Rolling window: {args.window} days")

    if not dates:
        print("No behavioral snapshots found. Run pipeline.behavioral_snapshots first.")
        conn.close()
        return

    total_snaps = 0
    total_events = 0
    t0 = time.time()

    for i, d in enumerate(dates):
        n_snaps, n_events = process_day(conn, d, user_ids, args.window)
        total_snaps += n_snaps
        total_events += n_events
        if (i + 1) % 10 == 0 or i == len(dates) - 1:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(dates)}] {d} — {n_snaps} traj, {n_events} events — "
                  f"total {total_snaps:,} snapshots, {total_events} events — {elapsed:.1f}s")

    conn.close()
    elapsed = time.time() - t0
    print(f"\nDone. {total_snaps:,} trajectory snapshots, {total_events} events in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
