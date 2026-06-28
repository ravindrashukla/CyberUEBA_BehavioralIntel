"""Step 6: Entity materialization from DB.

Reads behavioral_snapshots, trajectory_snapshots, and trajectory_events from
PostgreSQL to construct CyberEntity objects. Replaces the in-memory
build_entity_zoo() that re-computed everything from CSVs.

Data flow:
    behavioral_snapshots  → zone_embeddings, composite, contextual composites
    trajectory_snapshots  → PhaseState (velocity, acceleration, regime)
    trajectory_events     → recent events/alerts
    user profiles (CSV)   → static profile metadata

Usage:
    from pipeline.entity_materialize import materialize_entity_zoo
    zoo = materialize_entity_zoo(conn, cutoff_date=date(2025, 5, 10))
"""

import logging
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.db_connect import get_connection
from models.cyber_entity import CyberEntity, PhaseState, EMBED_DIM
from models.hierarchical_zones import USER_ZONE_ORDER, ALL_CONTEXTS
from models.relationship_embeddings import compute_user_device_vector, hadamard

logger = logging.getLogger(__name__)


ZONE_DB_COLS = {
    "identity": "zone_identity",
    "access_pattern": "zone_access_pattern",
    "data_behavior": "zone_data_behavior",
    "network_footprint": "zone_network_footprint",
    "risk_posture": "zone_risk_posture",
}

CONTEXT_DB_COLS = {
    "normal_ops": "composite_normal_ops",
    "insider_investigation": "composite_insider_inv",
    "apt_hunt": "composite_apt_hunt",
    "privilege_audit": "composite_privilege_audit",
}


def _pgvec_to_np(val) -> np.ndarray | None:
    """Parse pgvector string or value into numpy array."""
    if val is None:
        return None
    if isinstance(val, np.ndarray):
        return val.astype(np.float32)
    if isinstance(val, (list, tuple)):
        return np.array(val, dtype=np.float32)
    s = str(val).strip()
    if s.startswith("[") and s.endswith("]"):
        vals = s[1:-1].split(",")
        return np.array([float(v) for v in vals], dtype=np.float32)
    return None


def _load_user_profiles() -> dict:
    """Load user profiles from entity CSV."""
    path = Path(os.getenv("DATA_DIR", "data/generated")) / "entities" / "users.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str)
    profiles = {}
    for _, row in df.iterrows():
        profiles[row["user_id"]] = {
            "user_id": row["user_id"],
            "role": row.get("role", "unknown"),
            "department": row.get("department", "unknown"),
            "clearance": row.get("clearance", "standard"),
            "tenure_days": int(row.get("tenure_days", 0) or 0),
            "user_type": row.get("user_type", "employee"),
            "primary_device_id": row.get("primary_device_id", ""),
        }
    return profiles


def _load_device_user_map() -> dict[str, list[str]]:
    """Build user_id -> list[device_id] mapping."""
    path = Path(os.getenv("DATA_DIR", "data/generated")) / "entities" / "devices.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str)
    mapping: dict[str, list[str]] = {}
    if "owner_user_id" in df.columns:
        for _, row in df.iterrows():
            uid = row.get("owner_user_id")
            did = row.get("device_id")
            if uid and did and str(uid) != "nan":
                mapping.setdefault(uid, []).append(did)
    return mapping


def _fetch_device_snapshots(conn, device_ids: list[str]) -> dict[str, list[dict]]:
    """Load behavioral snapshots for device entities from DB.

    Returns dict mapping device_id -> list of snapshot dicts, ordered by date.
    Returns empty dict if no device snapshots exist (e.g. Gap 6 not yet resolved).
    """
    if not device_ids:
        return {}

    # Deduplicate while preserving order
    unique_ids = list(dict.fromkeys(device_ids))

    placeholders = ",".join(["%s"] * len(unique_ids))
    sql = f"""
        SELECT entity_id, cutoff_date, composite,
               zone_identity, zone_access_pattern, zone_data_behavior,
               zone_network_footprint, zone_risk_posture,
               composite_normal_ops, composite_insider_inv,
               composite_apt_hunt, composite_privilege_audit
        FROM behavioral_snapshots
        WHERE entity_type = 'device' AND entity_id IN ({placeholders})
        ORDER BY entity_id, cutoff_date
    """
    device_snapshots: dict[str, list[dict]] = {}
    with conn.cursor() as cur:
        cur.execute(sql, tuple(unique_ids))
        cols = [d[0] for d in cur.description]
        for row in cur:
            d = dict(zip(cols, row))
            did = d["entity_id"]
            if did not in device_snapshots:
                device_snapshots[did] = []
            device_snapshots[did].append(d)

    return device_snapshots


def _fetch_snapshot_series(conn, entity_id: str, window_days: int = 130) -> list[dict]:
    """Fetch behavioral snapshots for an entity ordered by date."""
    sql = """
        SELECT cutoff_date, composite,
               zone_identity, zone_access_pattern, zone_data_behavior,
               zone_network_footprint, zone_risk_posture,
               composite_normal_ops, composite_insider_inv,
               composite_apt_hunt, composite_privilege_audit
        FROM behavioral_snapshots
        WHERE entity_type = 'user' AND entity_id = %s
        ORDER BY cutoff_date
    """
    with conn.cursor() as cur:
        cur.execute(sql, (entity_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _fetch_latest_trajectory(conn, entity_id: str) -> dict | None:
    """Fetch the latest trajectory snapshot for an entity."""
    sql = """
        SELECT velocity_magnitude, acceleration, stability,
               regime_shifts, trend_consistency, total_drift,
               current_regime, zone_drifts, context_drifts,
               velocity_vector, cutoff_date
        FROM trajectory_snapshots
        WHERE entity_type = 'user' AND entity_id = %s
        ORDER BY cutoff_date DESC
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (entity_id,))
        if cur.rowcount == 0:
            return None
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)) if row else None


def _fetch_trajectory_events(conn, entity_id: str, limit: int = 50) -> list[dict]:
    """Fetch recent trajectory events for an entity."""
    sql = """
        SELECT event_date, event_type, severity, magnitude,
               shift_type, direction, contributing_factors
        FROM trajectory_events
        WHERE entity_type = 'user' AND entity_id = %s
        ORDER BY event_date DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (entity_id, limit))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _fetch_all_user_ids(conn) -> list[str]:
    """Get all distinct user entity IDs from behavioral_snapshots."""
    sql = "SELECT DISTINCT entity_id FROM behavioral_snapshots WHERE entity_type = 'user' ORDER BY entity_id"
    with conn.cursor() as cur:
        cur.execute(sql)
        return [row[0] for row in cur.fetchall()]


def _build_phase_state(traj: dict | None) -> PhaseState:
    """Construct PhaseState from trajectory_snapshots row."""
    if traj is None:
        return PhaseState()

    vel_vec = _pgvec_to_np(traj.get("velocity_vector"))
    if vel_vec is None:
        vel_vec = np.zeros(EMBED_DIM, dtype=np.float32)

    return PhaseState(
        velocity_vector=vel_vec,
        velocity_magnitude=float(traj.get("velocity_magnitude", 0.0)),
        acceleration=float(traj.get("acceleration", 0.0)),
        stability=float(traj.get("stability", 1.0)),
        regime_shifts=float(traj.get("regime_shifts", 0.0)),
        trend_consistency=float(traj.get("trend_consistency", 1.0)),
        total_drift=float(traj.get("total_drift", 0.0)),
        current_regime=str(traj.get("current_regime", "stable")),
    )


def materialize_entity(
    conn,
    entity_id: str,
    profile: dict,
    snapshots: list[dict] | None = None,
) -> CyberEntity | None:
    """Construct a CyberEntity from DB data.

    Args:
        conn: DB connection
        entity_id: user ID
        profile: static profile dict
        snapshots: pre-fetched snapshot series (optional, fetched if None)

    Returns:
        CyberEntity or None if insufficient data
    """
    if snapshots is None:
        snapshots = _fetch_snapshot_series(conn, entity_id)

    if len(snapshots) < 2:
        return None

    last_snap = snapshots[-1]
    zone_embeddings = {}
    for zone_name, db_col in ZONE_DB_COLS.items():
        vec = _pgvec_to_np(last_snap.get(db_col))
        if vec is not None:
            zone_embeddings[zone_name] = vec

    composite = _pgvec_to_np(last_snap.get("composite"))

    zone_snapshot_series = {z: [] for z in USER_ZONE_ORDER}
    composite_snapshots = []
    contextual_composites = {ctx: [] for ctx in ALL_CONTEXTS}

    for snap in snapshots:
        comp = _pgvec_to_np(snap.get("composite"))
        if comp is not None:
            composite_snapshots.append(comp)

        for zone_name, db_col in ZONE_DB_COLS.items():
            vec = _pgvec_to_np(snap.get(db_col))
            if vec is not None:
                zone_snapshot_series[zone_name].append(vec)

        for ctx, db_col in CONTEXT_DB_COLS.items():
            vec = _pgvec_to_np(snap.get(db_col))
            if vec is not None:
                contextual_composites[ctx].append(vec)

    traj = _fetch_latest_trajectory(conn, entity_id)
    phase = _build_phase_state(traj)

    events = _fetch_trajectory_events(conn, entity_id)
    risk_scores = {}
    if events:
        high_count = sum(1 for e in events if e.get("severity") == "high")
        med_count = sum(1 for e in events if e.get("severity") == "medium")
        risk_scores["high_events"] = high_count
        risk_scores["medium_events"] = med_count
        risk_scores["total_events"] = len(events)

    entity = CyberEntity(
        entity_type="user",
        entity_id=entity_id,
        profile=profile,
        zone_embeddings=zone_embeddings,
        composite_embedding=composite,
        phase_state=phase,
        relationships={},
        risk_scores=risk_scores,
        computed_at=str(last_snap.get("cutoff_date", "")),
        data_gaps=[],
        context="normal_ops",
        zone_snapshot_series=zone_snapshot_series,
        composite_snapshots=composite_snapshots,
    )

    entity._contextual_composites = contextual_composites
    entity._trajectory_events = events

    zone_trajs = {}
    from models.temporal_trajectory import compute_zone_trajectories
    zone_trajs = compute_zone_trajectories(zone_snapshot_series)
    entity._zone_trajectories = zone_trajs

    return entity


def materialize_entity_zoo(
    conn,
    user_ids: list[str] | None = None,
    include_relationships: bool = True,
) -> dict[str, CyberEntity]:
    """Materialize all user entities from DB tables.

    Args:
        conn: DB connection
        user_ids: specific users (None = all)
        include_relationships: compute UserDevice Hadamard products

    Returns:
        dict mapping user_id -> CyberEntity
    """
    if user_ids is None:
        user_ids = _fetch_all_user_ids(conn)

    profiles = _load_user_profiles()
    device_map = _load_device_user_map() if include_relationships else {}

    print(f"  Materializing {len(user_ids)} entities from DB...")

    all_snapshots = {}
    print("  Loading behavioral snapshots...")
    if len(user_ids) <= 500:
        placeholders = ",".join(["%s"] * len(user_ids))
        sql = f"""
            SELECT entity_id, cutoff_date, composite,
                   zone_identity, zone_access_pattern, zone_data_behavior,
                   zone_network_footprint, zone_risk_posture,
                   composite_normal_ops, composite_insider_inv,
                   composite_apt_hunt, composite_privilege_audit
            FROM behavioral_snapshots
            WHERE entity_type = 'user' AND entity_id IN ({placeholders})
            ORDER BY entity_id, cutoff_date
        """
        params = tuple(user_ids)
    else:
        sql = """
            SELECT entity_id, cutoff_date, composite,
                   zone_identity, zone_access_pattern, zone_data_behavior,
                   zone_network_footprint, zone_risk_posture,
                   composite_normal_ops, composite_insider_inv,
                   composite_apt_hunt, composite_privilege_audit
            FROM behavioral_snapshots
            WHERE entity_type = 'user'
            ORDER BY entity_id, cutoff_date
        """
        params = None
    with conn.cursor() as cur:
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        cols = [d[0] for d in cur.description]
        for row in cur:
            d = dict(zip(cols, row))
            uid = d["entity_id"]
            if uid not in all_snapshots:
                all_snapshots[uid] = []
            all_snapshots[uid].append(d)
    print(f"  Loaded snapshots for {len(all_snapshots)} users")

    # --- Load device behavioral snapshots (separate from user snapshots) ---
    device_snapshots: dict[str, list[dict]] = {}
    if include_relationships and device_map:
        # Collect all device IDs referenced by any user
        all_device_ids = []
        for dev_list in device_map.values():
            all_device_ids.extend(dev_list)
        if all_device_ids:
            device_snapshots = _fetch_device_snapshots(conn, all_device_ids)
            if device_snapshots:
                logger.info(
                    "Loaded device behavioral snapshots for %d devices",
                    len(device_snapshots),
                )
            else:
                logger.info(
                    "No device behavioral snapshots found in DB for %d device IDs "
                    "(device snapshot generation may not be implemented yet — Gap 6). "
                    "User-device relationship embeddings will be skipped.",
                    len(all_device_ids),
                )

    entity_zoo = {}
    for i, uid in enumerate(user_ids):
        profile = profiles.get(uid, {"user_id": uid})
        snaps = all_snapshots.get(uid, [])

        entity = materialize_entity(conn, uid, profile, snapshots=snaps)
        if entity is None:
            continue

        if include_relationships and uid in device_map:
            dev_ids = device_map[uid]
            if dev_ids and entity.composite_snapshots:
                primary_device = dev_ids[0]
                dev_snaps = device_snapshots.get(primary_device)
                if dev_snaps is None:
                    logger.debug(
                        "No device snapshots for %s (device %s) — "
                        "skipping user-device relationship",
                        uid, primary_device,
                    )
                elif len(dev_snaps) < 2:
                    logger.debug(
                        "Insufficient device snapshots for %s (device %s): "
                        "need >= 2, got %d — skipping user-device relationship",
                        uid, primary_device, len(dev_snaps),
                    )
                else:
                    dev_composites = []
                    for ds in dev_snaps:
                        dv = _pgvec_to_np(ds.get("composite"))
                        if dv is not None:
                            dev_composites.append(dv)

                    if dev_composites:
                        min_len = min(len(entity.composite_snapshots), len(dev_composites))
                        rel_snaps = []
                        for j in range(min_len):
                            rel_snaps.append(compute_user_device_vector(
                                entity.composite_snapshots[j], dev_composites[j]
                            ))
                        entity.relationships = {"user_device": rel_snaps[-1]}
                        entity.relationship_snapshots = {"user_device": rel_snaps}
                        logger.debug(
                            "Computed user-device relationship for %s with %d snapshots",
                            uid, len(rel_snaps),
                        )

        entity_zoo[uid] = entity

        if (i + 1) % 50 == 0:
            print(f"    {i + 1}/{len(user_ids)} entities materialized")

    print(f"  Entity zoo complete: {len(entity_zoo)} entities")
    return entity_zoo


def get_entity_summary(conn, entity_id: str) -> dict:
    """Quick summary for a single entity (for Streamlit detail cards)."""
    traj = _fetch_latest_trajectory(conn, entity_id)
    events = _fetch_trajectory_events(conn, entity_id, limit=10)

    sql = """
        SELECT cutoff_date, zone_texts
        FROM behavioral_snapshots
        WHERE entity_type = 'user' AND entity_id = %s
        ORDER BY cutoff_date DESC
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (entity_id,))
        row = cur.fetchone()

    zone_texts = {}
    latest_date = None
    if row:
        latest_date = row[0]
        if row[1]:
            import json
            zone_texts = json.loads(row[1]) if isinstance(row[1], str) else row[1]

    return {
        "entity_id": entity_id,
        "latest_date": str(latest_date) if latest_date else None,
        "trajectory": {
            "velocity_magnitude": float(traj["velocity_magnitude"]) if traj else 0,
            "acceleration": float(traj["acceleration"]) if traj else 0,
            "stability": float(traj["stability"]) if traj else 1,
            "current_regime": traj["current_regime"] if traj else "unknown",
            "total_drift": float(traj["total_drift"]) if traj else 0,
            "zone_drifts": traj.get("zone_drifts") if traj else {},
            "context_drifts": traj.get("context_drifts") if traj else {},
        },
        "recent_events": events,
        "zone_texts": zone_texts,
    }


def get_drift_heatmap_data(conn) -> pd.DataFrame:
    """Fetch trajectory data for all users on latest date for heatmap display."""
    sql = """
        SELECT entity_id, velocity_magnitude, acceleration, stability,
               total_drift, current_regime, zone_drifts, context_drifts
        FROM trajectory_snapshots
        WHERE entity_type = 'user'
          AND cutoff_date = (SELECT max(cutoff_date) FROM trajectory_snapshots WHERE entity_type = 'user')
        ORDER BY total_drift DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not rows:
        return pd.DataFrame()

    flat_rows = []
    for r in rows:
        flat = {
            "entity_id": r["entity_id"],
            "velocity_magnitude": float(r["velocity_magnitude"]),
            "acceleration": float(r["acceleration"]),
            "stability": float(r["stability"]),
            "total_drift": float(r["total_drift"]),
            "current_regime": r["current_regime"],
        }
        import json
        zd = r.get("zone_drifts")
        if zd:
            if isinstance(zd, str):
                zd = json.loads(zd)
            for k, v in zd.items():
                flat[f"zone_{k}"] = float(v)
        cd = r.get("context_drifts")
        if cd:
            if isinstance(cd, str):
                cd = json.loads(cd)
            for k, v in cd.items():
                flat[f"ctx_{k}"] = float(v)
        flat_rows.append(flat)

    return pd.DataFrame(flat_rows)


def get_entity_drift_timeline(conn, entity_id: str) -> pd.DataFrame:
    """Fetch daily trajectory metrics for one entity over time."""
    sql = """
        SELECT cutoff_date, velocity_magnitude, acceleration, stability,
               total_drift, current_regime, zone_drifts
        FROM trajectory_snapshots
        WHERE entity_type = 'user' AND entity_id = %s
        ORDER BY cutoff_date
    """
    with conn.cursor() as cur:
        cur.execute(sql, (entity_id,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not rows:
        return pd.DataFrame()

    flat = []
    for r in rows:
        entry = {
            "cutoff_date": r["cutoff_date"],
            "velocity_magnitude": float(r["velocity_magnitude"]),
            "acceleration": float(r["acceleration"]),
            "stability": float(r["stability"]),
            "total_drift": float(r["total_drift"]),
            "current_regime": r["current_regime"],
        }
        import json
        zd = r.get("zone_drifts")
        if zd:
            if isinstance(zd, str):
                zd = json.loads(zd)
            for k, v in zd.items():
                entry[f"zone_{k}"] = float(v)
        flat.append(entry)

    return pd.DataFrame(flat)


if __name__ == "__main__":
    import time
    conn = get_connection()

    t0 = time.time()
    zoo = materialize_entity_zoo(conn)
    elapsed = time.time() - t0
    print(f"\nMaterialized {len(zoo)} entities in {elapsed:.1f}s")

    for uid in ["USR-156", "USR-234", "USR-042", "USR-118"]:
        if uid in zoo:
            e = zoo[uid]
            ps = e.phase_state
            print(f"\n{uid}: regime={ps.current_regime}, drift={ps.total_drift:.4f}, "
                  f"velocity={ps.velocity_magnitude:.4f}, stability={ps.stability:.4f}")
            print(f"  zones: {list(e.zone_embeddings.keys())}")
            print(f"  snapshots: {len(e.composite_snapshots)} days")
            zt = getattr(e, '_zone_trajectories', {})
            if zt:
                for zn, zf in zt.items():
                    print(f"  {zn}: drift={zf.get('total_drift', 0):.4f}")

    conn.close()
