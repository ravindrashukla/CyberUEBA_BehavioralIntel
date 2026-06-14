"""Step 3: Behavioral snapshot pipeline.

Reads daily_features from DB, serializes 5 zone texts per user per day,
embeds via OpenAI Embedder, composes under 4 contexts,
and writes to behavioral_snapshots table (Gold layer).

Uses interpretive serialization (z-scores, baselines, trend labels) when
population statistics are available — this produces semantically rich text
that makes attack patterns distinguishable in embedding space.

Usage:
    python -m pipeline.behavioral_snapshots                    # auto-detect embedder
    python -m pipeline.behavioral_snapshots --start 2025-01-01 --end 2025-01-31
    python -m pipeline.behavioral_snapshots --embedder mock    # force mock embedder
"""

import argparse
import json
import os
import time
import warnings
from datetime import date

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")


from pipeline.db_connect import get_connection
from embeddings.embedder import Embedder
from models.hierarchical_zones import (
    serialize_zone, serialize_zone_interpretive, BehavioralContext,
    compose_zones, USER_ZONE_ORDER, ALL_CONTEXTS,
)

BASELINE_DAYS = 30
HISTORY_DAYS = 7

UPSERT_SQL = """
    INSERT INTO behavioral_snapshots (
        entity_type, entity_id, cutoff_date,
        zone_identity, zone_access_pattern, zone_data_behavior,
        zone_network_footprint, zone_risk_posture,
        composite,
        composite_normal_ops, composite_insider_inv,
        composite_apt_hunt, composite_privilege_audit,
        zone_texts
    ) VALUES (
        %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s,
        %s, %s, %s, %s,
        %s::jsonb
    ) ON CONFLICT (entity_type, entity_id, cutoff_date) DO UPDATE SET
        zone_identity = EXCLUDED.zone_identity,
        zone_access_pattern = EXCLUDED.zone_access_pattern,
        zone_data_behavior = EXCLUDED.zone_data_behavior,
        zone_network_footprint = EXCLUDED.zone_network_footprint,
        zone_risk_posture = EXCLUDED.zone_risk_posture,
        composite = EXCLUDED.composite,
        composite_normal_ops = EXCLUDED.composite_normal_ops,
        composite_insider_inv = EXCLUDED.composite_insider_inv,
        composite_apt_hunt = EXCLUDED.composite_apt_hunt,
        composite_privilege_audit = EXCLUDED.composite_privilege_audit,
        zone_texts = EXCLUDED.zone_texts,
        computed_at = now()
"""


def _vec_to_pgvector(v: np.ndarray) -> str:
    """Convert numpy array to pgvector literal string."""
    return "[" + ",".join(f"{x:.8f}" for x in v) + "]"


def _load_user_profiles(conn) -> dict:
    """Load user profiles from entity CSV (not DB, since we haven't loaded entities table)."""
    from pathlib import Path
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
        }
    return profiles


def _fetch_daily_features(conn, cutoff_date: date) -> pd.DataFrame:
    """Fetch all users' features for a given date."""
    sql = "SELECT * FROM daily_features WHERE feature_date = %s"
    return pd.read_sql(sql, conn, params=(cutoff_date,))


def _available_dates(conn, start: date = None, end: date = None) -> list[date]:
    """Get distinct dates with daily_features data."""
    sql = "SELECT DISTINCT feature_date FROM daily_features"
    params = []
    clauses = []
    if start:
        clauses.append("feature_date >= %s")
        params.append(start)
    if end:
        clauses.append("feature_date <= %s")
        params.append(end)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY feature_date"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [row[0] for row in cur.fetchall()]


FEATURE_COLS = [
    "auth_total", "auth_fail_rate", "auth_off_hours_ratio",
    "auth_unique_sources", "auth_unique_dests", "auth_methods",
    "file_total", "file_restricted_ratio", "file_confidential_ratio",
    "file_write_ratio", "file_unique_paths", "file_total_bytes",
    "net_bytes_out", "net_unique_dsts", "net_external_ratio",
    "dns_unique_domains", "dns_nxdomain_ratio",
    "endpoint_total", "endpoint_suspicious_ratio",
    "endpoint_max_risk", "endpoint_mean_risk", "endpoint_unique_processes",
    "priv_denied_ratio",
]


def _compute_population_stats(conn, cutoff_date: date) -> tuple[dict, dict]:
    """Compute population mean and std for all features on a given date."""
    sql = "SELECT * FROM daily_features WHERE feature_date = %s"
    df = pd.read_sql(sql, conn, params=(cutoff_date,))
    if df.empty:
        return {}, {}
    pop_mean = {}
    pop_std = {}
    for col in FEATURE_COLS:
        if col in df.columns:
            pop_mean[col] = float(df[col].mean())
            std = float(df[col].std())
            pop_std[col] = std if std > 1e-10 else 1.0
    return pop_mean, pop_std


def _compute_user_baselines(conn, cutoff_date: date, user_ids: list[str]) -> dict[str, dict]:
    """Compute per-user baselines from the first BASELINE_DAYS of data."""
    sql = """
        SELECT user_id, {cols}
        FROM daily_features
        WHERE feature_date < %s
          AND feature_date >= %s::date - %s
    """.format(cols=", ".join(f"AVG({c}) as {c}" for c in FEATURE_COLS))
    sql += " GROUP BY user_id"

    with conn.cursor() as cur:
        cur.execute(sql, (cutoff_date, cutoff_date, BASELINE_DAYS))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    baselines = {}
    for row in rows:
        uid = row["user_id"]
        baselines[uid] = {k: float(v or 0) for k, v in row.items() if k != "user_id"}
    return baselines


def _fetch_recent_history(conn, user_id: str, cutoff_date: date) -> list[dict]:
    """Fetch the last HISTORY_DAYS of features for trend analysis."""
    sql = """
        SELECT feature_date, {cols}
        FROM daily_features
        WHERE user_id = %s AND feature_date < %s
        ORDER BY feature_date DESC
        LIMIT %s
    """.format(cols=", ".join(FEATURE_COLS))
    with conn.cursor() as cur:
        cur.execute(sql, (user_id, cutoff_date, HISTORY_DAYS))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    rows.reverse()
    return [{k: float(v or 0) for k, v in row.items() if k != "feature_date"} for row in rows]


def process_day(conn, cutoff_date: date, profiles: dict, embedder,
                pop_stats: tuple = None, baselines: dict = None,
                day_idx: int = 0) -> int:
    """Process one day: serialize zones -> batch embed -> compose -> write snapshots.

    Collects all zone texts first, then embeds in a single batch call
    (split into sub-batches of 100 by embed_batch) for efficiency.
    """
    df = _fetch_daily_features(conn, cutoff_date)
    if df.empty:
        return 0

    pop_mean, pop_std = pop_stats if pop_stats else ({}, {})
    use_interpretive = bool(pop_mean)

    user_data = []
    all_texts = []
    text_index = []

    for _, row in df.iterrows():
        uid = row["user_id"]
        profile = profiles.get(uid, {"user_id": uid})

        features = {col: float(row[col]) if pd.notna(row[col]) else 0.0
                    for col in df.columns
                    if col not in ("id", "user_id", "feature_date", "computed_at")}

        zone_texts = {}

        if use_interpretive:
            user_baseline = baselines.get(uid, {}) if baselines else {}
            recent = _fetch_recent_history(conn, uid, cutoff_date) if day_idx < 3 or day_idx % 7 == 0 else []
            bctx = BehavioralContext(
                pop_mean=pop_mean,
                pop_std=pop_std,
                user_baseline=user_baseline,
                week_idx=day_idx // 7,
                recent_history=recent,
            )
            for zone_name in USER_ZONE_ORDER:
                text = serialize_zone_interpretive("user", zone_name, profile, features, bctx)
                zone_texts[zone_name] = text
                all_texts.append(text)
                text_index.append((len(user_data), zone_name))
        else:
            for zone_name in USER_ZONE_ORDER:
                text = serialize_zone("user", zone_name, profile, features)
                zone_texts[zone_name] = text
                all_texts.append(text)
                text_index.append((len(user_data), zone_name))

        user_data.append({"uid": uid, "zone_texts": zone_texts, "zone_vecs": {}})

    if not all_texts:
        return 0

    all_vecs = embedder.embed_batch(all_texts)

    for (user_idx, zone_name), vec in zip(text_index, all_vecs):
        user_data[user_idx]["zone_vecs"][zone_name] = vec

    rows = []
    for ud in user_data:
        zone_vecs = ud["zone_vecs"]
        composites = {}
        for ctx in ALL_CONTEXTS:
            composites[ctx] = compose_zones(zone_vecs, context=ctx, entity_type="user")

        row_data = (
            "user", ud["uid"], cutoff_date,
            _vec_to_pgvector(zone_vecs["identity"]),
            _vec_to_pgvector(zone_vecs["access_pattern"]),
            _vec_to_pgvector(zone_vecs["data_behavior"]),
            _vec_to_pgvector(zone_vecs["network_footprint"]),
            _vec_to_pgvector(zone_vecs["risk_posture"]),
            _vec_to_pgvector(composites["normal_ops"]),
            _vec_to_pgvector(composites["normal_ops"]),
            _vec_to_pgvector(composites["insider_investigation"]),
            _vec_to_pgvector(composites["apt_hunt"]),
            _vec_to_pgvector(composites["privilege_audit"]),
            json.dumps(ud["zone_texts"]),
        )
        rows.append(row_data)

    if rows:
        from psycopg2.extras import execute_batch
        with conn.cursor() as cur:
            execute_batch(cur, UPSERT_SQL, rows, page_size=100)
        conn.commit()

    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Build behavioral snapshots from daily_features")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--embedder", choices=["mock", "openai", "auto"], default="auto",
                        help="Embedding backend (default: auto — uses OpenAI if key available)")
    parser.add_argument("--plain", action="store_true",
                        help="Use plain serialization instead of interpretive (for debugging)")
    args = parser.parse_args()

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit(
            "OPENAI_API_KEY is required — real OpenAI embeddings are mandatory "
            "(mock embeddings have been removed)."
        )
    embedder = Embedder()
    print("Using OpenAI embedder (text-embedding-3-small)", flush=True)

    conn = get_connection()
    dates = _available_dates(conn, start, end)
    print(f"Found {len(dates)} days with daily_features", flush=True)
    if not dates:
        print("No data. Run pipeline.daily_ingest first.")
        conn.close()
        return

    profiles = _load_user_profiles(conn)
    print(f"Loaded {len(profiles)} user profiles", flush=True)

    user_ids = list(profiles.keys())
    baselines = None
    use_interpretive = not args.plain

    if use_interpretive:
        print("Computing user baselines for interpretive serialization...", flush=True)
        baselines = _compute_user_baselines(conn, dates[min(BASELINE_DAYS, len(dates) - 1)], user_ids)
        print(f"  Baselines computed for {len(baselines)} users", flush=True)

    total_rows = 0
    t0 = time.time()

    for i, d in enumerate(dates):
        pop_stats = _compute_population_stats(conn, d) if use_interpretive else None
        n = process_day(conn, d, profiles, embedder,
                        pop_stats=pop_stats, baselines=baselines, day_idx=i)
        total_rows += n
        if (i + 1) % 10 == 0 or i == len(dates) - 1:
            elapsed = time.time() - t0
            rate = total_rows / elapsed if elapsed > 0 else 0
            print(f"  [{i+1}/{len(dates)}] {d} — {n} users — "
                  f"total {total_rows:,} snapshots — {elapsed:.1f}s ({rate:.0f}/s)",
                  flush=True)

    conn.close()
    elapsed = time.time() - t0
    print(f"\nDone. {total_rows:,} behavioral snapshots in {elapsed:.1f}s", flush=True)
    print(f"Embedder stats: {embedder.stats()}", flush=True)
    if use_interpretive:
        print("Used INTERPRETIVE serialization (z-scores, baselines, trend labels)")
    else:
        print("Used PLAIN serialization (raw key=value)")


if __name__ == "__main__":
    main()
