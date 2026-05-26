"""Seed behavioral_snapshots table from embedding pipeline.

Runs the SnapshotBuilder for specified months (default: 3) and inserts
results into PostgreSQL via the Database.save_snapshot method.

Usage: python scripts/seed_snapshots.py [--months 3]
"""
import sys
import os
import argparse
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("DATABASE_URL", "postgresql://cyber_ueba:password@localhost:5433/cyber_ueba")

import numpy as np
from embeddings.snapshot_builder import SnapshotBuilder
from services.database import Database


def seed_snapshots(n_months: int = 3, max_users: int = 50, max_devices: int = 50):
    """Build and seed behavioral snapshots into PostgreSQL."""
    from simulator.config import SIM_START

    builder = SnapshotBuilder(data_dir="data/generated", use_mock=True)

    start = SIM_START.replace(day=1)
    inserted = 0

    for month_offset in range(n_months):
        month_start = date(
            start.year + (start.month + month_offset - 1) // 12,
            (start.month + month_offset - 1) % 12 + 1,
            1,
        )
        month_end = date(
            month_start.year + (month_start.month) // 12,
            (month_start.month) % 12 + 1,
            1,
        ) - timedelta(days=1)

        print(f"\n--- Month {month_offset+1}/{n_months}: {month_start} to {month_end} ---")

        # Build user snapshots (limited for speed)
        logs = builder._load_logs_for_window(month_start, month_end)
        entities_dir = builder.data_dir / "entities"

        # Users
        import pandas as pd
        users_df = pd.read_csv(entities_dir / "users.csv")
        from embeddings.snapshot_builder import (
            _summarize_user_auth, _summarize_user_privilege,
            _summarize_user_data_access, _summarize_user_network,
            _summarize_user_communication,
        )
        from embeddings.composer import compose

        auth_df = logs.get("auth", pd.DataFrame())
        file_df = logs.get("file_access", pd.DataFrame())
        priv_df = logs.get("privilege", pd.DataFrame())
        net_df = logs.get("network", pd.DataFrame())
        app_df = logs.get("app", pd.DataFrame())

        for _, user in users_df.head(max_users).iterrows():
            uid = user["user_id"]

            user_auth = auth_df[auth_df["user_id"] == uid] if len(auth_df) > 0 else pd.DataFrame()
            auth_text = _summarize_user_auth(uid, user, user_auth)

            if len(priv_df) > 0 and "actor_user_id" in priv_df.columns:
                user_priv = priv_df[(priv_df["actor_user_id"] == uid) | (priv_df["target_user_id"] == uid)]
            else:
                user_priv = pd.DataFrame()
            priv_text = _summarize_user_privilege(uid, user, user_priv)

            user_file = file_df[file_df["user_id"] == uid] if len(file_df) > 0 and "user_id" in file_df.columns else pd.DataFrame()
            data_text = _summarize_user_data_access(uid, user, user_file)

            network_text = _summarize_user_network(uid, user, net_df)

            user_app = app_df[app_df["user_id"] == uid] if len(app_df) > 0 and "user_id" in app_df.columns else pd.DataFrame()
            comm_text = _summarize_user_communication(uid, user, user_app)

            texts = [auth_text, priv_text, data_text, network_text, comm_text]
            vectors = builder.embedder.embed_batch(texts)

            signal_dict = {
                "auth": vectors[0],
                "privilege": vectors[1],
                "data_access": vectors[2],
                "network": vectors[3],
                "communication": vectors[4],
            }
            composite = compose(signal_dict, "user")

            Database.save_snapshot("user", uid, month_end, signal_dict, composite)
            inserted += 1

        print(f"  Users: {min(max_users, len(users_df))} inserted")

        # Devices (use endpoint + network)
        from embeddings.snapshot_builder import (
            _summarize_device_process, _summarize_device_traffic,
            _summarize_device_resource, _summarize_device_auth,
            _summarize_device_config,
        )
        devices_df = pd.read_csv(entities_dir / "devices.csv")
        endpoint_df = logs.get("endpoint", pd.DataFrame())

        for _, device in devices_df.head(max_devices).iterrows():
            did = device["device_id"]

            dev_endpoint = endpoint_df[endpoint_df["device_id"] == did] if len(endpoint_df) > 0 and "device_id" in endpoint_df.columns else pd.DataFrame()
            process_text = _summarize_device_process(did, device, dev_endpoint)

            dev_net = net_df[net_df["device_id"] == did] if len(net_df) > 0 and "device_id" in net_df.columns else pd.DataFrame()
            traffic_text = _summarize_device_traffic(did, device, dev_net)

            resource_text = _summarize_device_resource(did, device, dev_endpoint)

            dev_auth = auth_df[auth_df["device_id"] == did] if len(auth_df) > 0 and "device_id" in auth_df.columns else pd.DataFrame()
            auth_text = _summarize_device_auth(did, device, dev_auth)

            config_text = _summarize_device_config(did, device)

            texts = [process_text, traffic_text, resource_text, auth_text, config_text]
            vectors = builder.embedder.embed_batch(texts)

            signal_dict = {
                "process": vectors[0],
                "traffic": vectors[1],
                "resource": vectors[2],
                "auth": vectors[3],
                "config": vectors[4],
            }
            composite = compose(signal_dict, "device")

            Database.save_snapshot("device", did, month_end, signal_dict, composite)
            inserted += 1

        print(f"  Devices: {min(max_devices, len(devices_df))} inserted")

    print(f"\n{'='*60}")
    print(f"Total snapshots inserted: {inserted}")
    print(f"Embedder stats: {builder.embedder.stats()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=3)
    parser.add_argument("--max-users", type=int, default=50)
    parser.add_argument("--max-devices", type=int, default=50)
    args = parser.parse_args()

    seed_snapshots(n_months=args.months, max_users=args.max_users, max_devices=args.max_devices)
