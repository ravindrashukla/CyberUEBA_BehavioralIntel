"""Fast snapshot seeder: loads only 7 days per month to reduce memory/time."""
import sys
import os
import argparse
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from embeddings.embedder import Embedder
from embeddings.composer import compose
from embeddings.snapshot_builder import (
    _summarize_user_auth, _summarize_user_privilege,
    _summarize_user_data_access, _summarize_user_network,
    _summarize_user_communication,
    _summarize_device_process, _summarize_device_traffic,
    _summarize_device_resource, _summarize_device_auth,
    _summarize_device_config,
    _summarize_segment_volume, _summarize_segment_connections,
    _summarize_segment_protocols, _summarize_segment_threats,
    _summarize_segment_exposure,
    _summarize_app_access, _summarize_app_queries,
    _summarize_app_errors, _summarize_app_performance,
    _summarize_app_config,
)
from services.database import Database


def load_week(data_dir: Path, week_start: date) -> dict:
    """Load 7 days of logs — much faster than full month."""
    log_types = ["auth", "network", "endpoint", "file_access", "app", "privilege", "dns"]
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


def seed(n_months: int, max_users: int, max_devices: int, data_dir: str, entity_types: str = "all"):
    data_path = Path(data_dir)
    entities_dir = data_path / "entities"
    users_df = pd.read_csv(entities_dir / "users.csv").head(max_users)
    devices_df = pd.read_csv(entities_dir / "devices.csv")
    segments_df = pd.read_csv(entities_dir / "segments.csv")
    apps_df = pd.read_csv(entities_dir / "applications.csv")

    do_users = entity_types in ("all", "user")
    do_devices = entity_types in ("all", "device")
    do_segments = entity_types in ("all", "segment")
    do_apps = entity_types in ("all", "app")

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

        week_start = month_start
        print(f"\n--- Month {month_idx+1}/{n_months}: {month_start} ---")

        logs = load_week(data_path, week_start)
        auth_df = logs.get("auth", pd.DataFrame())
        file_df = logs.get("file_access", pd.DataFrame())
        priv_df = logs.get("privilege", pd.DataFrame())
        net_df = logs.get("network", pd.DataFrame())
        app_df = logs.get("app", pd.DataFrame())
        endpoint_df = logs.get("endpoint", pd.DataFrame())
        dns_df = logs.get("dns", pd.DataFrame())

        if do_users:
            for _, user in users_df.iterrows():
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
                vectors = embedder.embed_batch(texts)
                signal_dict = {"auth": vectors[0], "privilege": vectors[1], "data_access": vectors[2], "network": vectors[3], "communication": vectors[4]}
                composite = compose(signal_dict, "user")
                Database.save_snapshot("user", uid, month_end, signal_dict, composite)
                inserted += 1
            print(f"  Users: {len(users_df)}")

        if do_devices:
            for _, device in devices_df.head(max_devices).iterrows():
                did = device["device_id"]
                dev_endpoint = endpoint_df[endpoint_df["device_id"] == did] if len(endpoint_df) > 0 and "device_id" in endpoint_df.columns else pd.DataFrame()
                dev_net = net_df[net_df["device_id"] == did] if len(net_df) > 0 and "device_id" in net_df.columns else pd.DataFrame()
                dev_auth = auth_df[auth_df["device_id"] == did] if len(auth_df) > 0 and "device_id" in auth_df.columns else pd.DataFrame()

                texts = [
                    _summarize_device_process(did, device, dev_endpoint),
                    _summarize_device_traffic(did, device, dev_net),
                    _summarize_device_resource(did, device, dev_endpoint),
                    _summarize_device_auth(did, device, dev_auth),
                    _summarize_device_config(did, device),
                ]
                vectors = embedder.embed_batch(texts)
                signal_dict = {"process": vectors[0], "traffic": vectors[1], "resource": vectors[2], "auth": vectors[3], "config": vectors[4]}
                composite = compose(signal_dict, "device")
                Database.save_snapshot("device", did, month_end, signal_dict, composite)
                inserted += 1
            print(f"  Devices: {min(max_devices, len(devices_df))}")

        if do_segments:
            for _, seg in segments_df.iterrows():
                sid = seg["segment_id"]
                seg_device_ids = devices_df[devices_df["segment_id"] == sid]["device_id"].tolist()
                seg_net = net_df[net_df["device_id"].isin(seg_device_ids)] if len(net_df) > 0 and "device_id" in net_df.columns else pd.DataFrame()
                seg_dns = dns_df[dns_df["device_id"].isin(seg_device_ids)] if len(dns_df) > 0 and "device_id" in dns_df.columns else pd.DataFrame()

                texts = [
                    _summarize_segment_volume(sid, seg, seg_net),
                    _summarize_segment_connections(sid, seg, seg_net, seg_device_ids),
                    _summarize_segment_protocols(sid, seg, seg_net),
                    _summarize_segment_threats(sid, seg, seg_dns),
                    _summarize_segment_exposure(sid, seg, seg_net),
                ]
                vectors = embedder.embed_batch(texts)
                signal_dict = {"volume": vectors[0], "connections": vectors[1], "protocols": vectors[2], "threats": vectors[3], "exposure": vectors[4]}
                composite = compose(signal_dict, "segment")
                Database.save_snapshot("segment", sid, month_end, signal_dict, composite)
                inserted += 1
            print(f"  Segments: {len(segments_df)}")

        if do_apps:
            for _, app_row in apps_df.iterrows():
                aid = app_row["app_id"]
                app_events = app_df[app_df["app_id"] == aid] if len(app_df) > 0 and "app_id" in app_df.columns else pd.DataFrame()

                texts = [
                    _summarize_app_access(aid, app_row, app_events),
                    _summarize_app_queries(aid, app_row, app_events),
                    _summarize_app_errors(aid, app_row, app_events),
                    _summarize_app_performance(aid, app_row, app_events),
                    _summarize_app_config(aid, app_row, app_events),
                ]
                vectors = embedder.embed_batch(texts)
                signal_dict = {"access": vectors[0], "queries": vectors[1], "errors": vectors[2], "performance": vectors[3], "config": vectors[4]}
                composite = compose(signal_dict, "app")
                Database.save_snapshot("app", aid, month_end, signal_dict, composite)
                inserted += 1
            print(f"  Apps: {len(apps_df)}")

    print(f"\n{'='*60}")
    print(f"Total inserted: {inserted}")
    print(f"Embedder: {embedder.stats()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--max-users", type=int, default=50)
    parser.add_argument("--max-devices", type=int, default=50)
    parser.add_argument("--data-dir", default="data/generated")
    parser.add_argument("--entity-types", default="all", help="all, segment, app, user, device")
    args = parser.parse_args()
    seed(args.months, args.max_users, args.max_devices, args.data_dir, args.entity_types)
