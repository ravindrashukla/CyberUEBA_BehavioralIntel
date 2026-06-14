"""Seed session entity snapshots: relationship entities (user + device + time)."""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from embeddings.embedder import Embedder
from embeddings.composer import compose
from embeddings.snapshot_builder import (
    _summarize_session_activity,
    _summarize_session_risk,
    _summarize_session_data_movement,
    _summarize_session_lateral,
    _summarize_session_temporal,
)
from services.database import Database


def load_week(data_dir: Path, week_start: date) -> dict:
    """Load 7 days of logs."""
    log_types = ["auth", "network", "file_access", "app", "privilege"]
    result = {}
    for log_type in log_types:
        log_dir = data_dir / log_type
        if not log_dir.exists():
            result[log_type] = pd.DataFrame()
            continue
        frames = []
        for day_offset in range(7):
            d = week_start + timedelta(days=day_offset)
            csv_path = log_dir / f"{d.isoformat()}.csv"
            if csv_path.exists():
                frames.append(pd.read_csv(csv_path))
        result[log_type] = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return result


def seed_sessions(n_months: int = 6, max_sessions: int = 100, data_dir: str = "data/generated"):
    data_path = Path(data_dir)
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit(
            "OPENAI_API_KEY is required — real OpenAI embeddings are mandatory "
            "(mock embeddings have been removed)."
        )
    embedder = Embedder()
    print("Using REAL OpenAI embeddings (text-embedding-3-small)")
    inserted = 0
    start = date(2025, 1, 1)

    for month_idx in range(n_months):
        month_start = date(
            start.year + (start.month + month_idx - 1) // 12,
            (start.month + month_idx - 1) % 12 + 1,
            1,
        )
        month_end = date(
            month_start.year + (month_start.month) // 12,
            (month_start.month) % 12 + 1,
            1,
        ) - timedelta(days=1)

        print(f"\n--- Month {month_idx+1}/{n_months}: {month_start} ---")

        logs = load_week(data_path, month_start)
        auth_df = logs.get("auth", pd.DataFrame())
        file_df = logs.get("file_access", pd.DataFrame())
        net_df = logs.get("network", pd.DataFrame())
        app_df = logs.get("app", pd.DataFrame())
        priv_df = logs.get("privilege", pd.DataFrame())

        if len(auth_df) == 0 or "user_id" not in auth_df.columns or "device_id" not in auth_df.columns:
            print("  No auth data with user_id + device_id, skipping")
            continue

        # Derive sessions: unique (user_id, device_id) pairs
        session_pairs = auth_df.groupby(["user_id", "device_id"]).size().reset_index(name="event_count")
        session_pairs = session_pairs.sort_values("event_count", ascending=False).head(max_sessions)

        for _, row in session_pairs.iterrows():
            uid = row["user_id"]
            did = row["device_id"]
            session_id = f"SES-{uid[-3:]}-{did[-3:]}"

            # Filter logs for this session
            sess_auth = auth_df[(auth_df["user_id"] == uid) & (auth_df["device_id"] == did)]
            sess_app = app_df[app_df["user_id"] == uid] if "user_id" in app_df.columns and len(app_df) > 0 else pd.DataFrame()
            sess_file = file_df[file_df["user_id"] == uid] if "user_id" in file_df.columns and len(file_df) > 0 else pd.DataFrame()
            sess_net = net_df[net_df["device_id"] == did] if "device_id" in net_df.columns and len(net_df) > 0 else pd.DataFrame()

            if len(priv_df) > 0 and "actor_user_id" in priv_df.columns:
                sess_priv = priv_df[priv_df["actor_user_id"] == uid]
            else:
                sess_priv = pd.DataFrame()

            # User's full auth (for lateral movement detection)
            user_all_auth = auth_df[auth_df["user_id"] == uid]

            texts = [
                _summarize_session_activity(session_id, uid, did, sess_auth, sess_app),
                _summarize_session_risk(session_id, uid, did, sess_auth, sess_priv),
                _summarize_session_data_movement(session_id, uid, did, sess_file, sess_net),
                _summarize_session_lateral(session_id, uid, did, user_all_auth),
                _summarize_session_temporal(session_id, uid, did, sess_auth),
            ]

            vectors = embedder.embed_batch(texts)
            signal_dict = {
                "activity": vectors[0],
                "risk_accum": vectors[1],
                "data_movement": vectors[2],
                "lateral": vectors[3],
                "temporal": vectors[4],
            }
            composite = compose(signal_dict, "session")
            Database.save_snapshot("session", session_id, month_end, signal_dict, composite)
            inserted += 1

        print(f"  Sessions: {len(session_pairs)}")

    print(f"\n{'='*60}")
    print(f"Total session snapshots: {inserted}")
    print(f"Embedder: {embedder.stats()}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--max-sessions", type=int, default=100)
    parser.add_argument("--data-dir", default="data/generated")
    args = parser.parse_args()
    seed_sessions(args.months, args.max_sessions, args.data_dir)
