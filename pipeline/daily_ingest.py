"""Step 2: Daily feature ingestion pipeline.

Reads raw CSVs from data/generated/{log_type}/{YYYY-MM-DD}.csv
and aggregates into one row per user per day in the daily_features table.

Usage:
    python -m pipeline.daily_ingest                  # all dates
    python -m pipeline.daily_ingest --start 2025-01-01 --end 2025-01-31
    python -m pipeline.daily_ingest --date 2025-01-15  # single day
"""

import argparse
import os
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import numpy as np

from pipeline.db_connect import get_connection

DATA_DIR = Path(os.getenv("DATA_DIR", "data/generated"))

WORKING_HOURS = (8, 18)

UPSERT_SQL = """
    INSERT INTO daily_features (
        user_id, feature_date,
        auth_total, auth_success, auth_fail_rate, auth_off_hours_ratio,
        auth_unique_sources, auth_unique_dests, auth_methods,
        file_total, file_restricted_ratio, file_confidential_ratio,
        file_write_ratio, file_unique_paths, file_total_bytes,
        net_bytes_out, net_unique_dsts, net_external_ratio,
        dns_unique_domains, dns_nxdomain_ratio,
        endpoint_total, endpoint_suspicious_ratio, endpoint_max_risk,
        endpoint_mean_risk, endpoint_unique_processes,
        app_total, app_unique_apps, app_admin_actions, app_export_count,
        app_error_ratio,
        priv_total, priv_elevations, priv_denied_ratio
    ) VALUES (
        %s, %s,
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, %s, %s
    ) ON CONFLICT (user_id, feature_date) DO UPDATE SET
        auth_total = EXCLUDED.auth_total,
        auth_success = EXCLUDED.auth_success,
        auth_fail_rate = EXCLUDED.auth_fail_rate,
        auth_off_hours_ratio = EXCLUDED.auth_off_hours_ratio,
        auth_unique_sources = EXCLUDED.auth_unique_sources,
        auth_unique_dests = EXCLUDED.auth_unique_dests,
        auth_methods = EXCLUDED.auth_methods,
        file_total = EXCLUDED.file_total,
        file_restricted_ratio = EXCLUDED.file_restricted_ratio,
        file_confidential_ratio = EXCLUDED.file_confidential_ratio,
        file_write_ratio = EXCLUDED.file_write_ratio,
        file_unique_paths = EXCLUDED.file_unique_paths,
        file_total_bytes = EXCLUDED.file_total_bytes,
        net_bytes_out = EXCLUDED.net_bytes_out,
        net_unique_dsts = EXCLUDED.net_unique_dsts,
        net_external_ratio = EXCLUDED.net_external_ratio,
        dns_unique_domains = EXCLUDED.dns_unique_domains,
        dns_nxdomain_ratio = EXCLUDED.dns_nxdomain_ratio,
        endpoint_total = EXCLUDED.endpoint_total,
        endpoint_suspicious_ratio = EXCLUDED.endpoint_suspicious_ratio,
        endpoint_max_risk = EXCLUDED.endpoint_max_risk,
        endpoint_mean_risk = EXCLUDED.endpoint_mean_risk,
        endpoint_unique_processes = EXCLUDED.endpoint_unique_processes,
        app_total = EXCLUDED.app_total,
        app_unique_apps = EXCLUDED.app_unique_apps,
        app_admin_actions = EXCLUDED.app_admin_actions,
        app_export_count = EXCLUDED.app_export_count,
        app_error_ratio = EXCLUDED.app_error_ratio,
        priv_total = EXCLUDED.priv_total,
        priv_elevations = EXCLUDED.priv_elevations,
        priv_denied_ratio = EXCLUDED.priv_denied_ratio,
        computed_at = now()
"""


def _safe_ratio(numerator, denominator):
    return float(numerator / denominator) if denominator > 0 else 0.0


def _is_off_hours(ts_str: str) -> bool:
    try:
        hour = pd.Timestamp(ts_str).hour
        return hour < WORKING_HOURS[0] or hour >= WORKING_HOURS[1]
    except Exception:
        return False


def _read_csv(log_type: str, day_str: str) -> pd.DataFrame | None:
    path = DATA_DIR / log_type / f"{day_str}.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, dtype=str)
        return df
    except Exception:
        return None


def _aggregate_auth(df: pd.DataFrame | None) -> dict:
    if df is None or df.empty:
        return {}
    result = {}
    for uid, grp in df.groupby("user_id"):
        total = len(grp)
        success = int((grp["success"].str.lower() == "true").sum())
        fail_rate = _safe_ratio(total - success, total)
        off_hours = sum(1 for ts in grp["timestamp"] if _is_off_hours(ts))
        off_hours_ratio = _safe_ratio(off_hours, total)
        unique_sources = grp["source_ip"].nunique()
        unique_dests = grp["dest_system"].nunique()
        methods = grp["auth_method"].nunique()
        result[uid] = {
            "auth_total": total,
            "auth_success": success,
            "auth_fail_rate": fail_rate,
            "auth_off_hours_ratio": off_hours_ratio,
            "auth_unique_sources": unique_sources,
            "auth_unique_dests": unique_dests,
            "auth_methods": methods,
        }
    return result


def _aggregate_file_access(df: pd.DataFrame | None) -> dict:
    if df is None or df.empty:
        return {}
    result = {}
    for uid, grp in df.groupby("user_id"):
        total = len(grp)
        restricted = int((grp.get("data_classification", pd.Series()) == "restricted").sum())
        confidential = int((grp.get("data_classification", pd.Series()) == "confidential").sum())
        writes = int(grp["operation"].isin(["write", "create", "append", "copy", "move"]).sum())
        unique_paths = grp["file_path"].nunique()
        bytes_col = grp.get("file_size_bytes", pd.Series(dtype=float))
        total_bytes = int(pd.to_numeric(bytes_col, errors="coerce").fillna(0).sum())
        result[uid] = {
            "file_total": total,
            "file_restricted_ratio": _safe_ratio(restricted, total),
            "file_confidential_ratio": _safe_ratio(confidential, total),
            "file_write_ratio": _safe_ratio(writes, total),
            "file_unique_paths": unique_paths,
            "file_total_bytes": total_bytes,
        }
    return result


def _build_auth_device_sessions(auth_df: pd.DataFrame | None) -> dict[str, str]:
    """Build device→user map from auth events for the same day.

    For each device, picks the user with the most auth events on that device.
    Used as fallback when device ownership map has no entry.
    """
    if auth_df is None or auth_df.empty:
        return {}
    dev_col = None
    for col in ("device_id", "destination_id", "dest_system"):
        if col in auth_df.columns:
            dev_col = col
            break
    if dev_col is None or "user_id" not in auth_df.columns:
        return {}
    pairs = auth_df.groupby([dev_col, "user_id"]).size().reset_index(name="count")
    best = pairs.sort_values("count", ascending=False).drop_duplicates(dev_col)
    return dict(zip(best[dev_col], best["user_id"]))


def _aggregate_network(df: pd.DataFrame | None, devices_to_users: dict,
                       auth_sessions: dict | None = None) -> dict:
    """Aggregate network flows. Maps device_id -> user_id via ownership, then auth sessions."""
    if df is None or df.empty:
        return {}
    result = {}
    if "device_id" not in df.columns:
        return {}
    for dev_id, grp in df.groupby("device_id"):
        uid = devices_to_users.get(dev_id)
        if not uid and auth_sessions:
            uid = auth_sessions.get(dev_id)
        if not uid:
            continue
        bytes_out = int(pd.to_numeric(grp.get("bytes_out", pd.Series(dtype=float)),
                                       errors="coerce").fillna(0).sum())
        unique_dsts = grp["dst_ip"].nunique() if "dst_ip" in grp.columns else 0
        external = 0
        if "dst_ip" in grp.columns:
            external = int(grp["dst_ip"].apply(
                lambda x: not str(x).startswith(("10.", "172.", "192.168."))
            ).sum())
        total = len(grp)
        if uid not in result:
            result[uid] = {"net_bytes_out": 0, "net_unique_dsts": 0,
                           "_net_external": 0, "_net_total": 0}
        result[uid]["net_bytes_out"] += bytes_out
        result[uid]["net_unique_dsts"] += unique_dsts
        result[uid]["_net_external"] += external
        result[uid]["_net_total"] += total

    for uid in result:
        t = result[uid]["_net_total"]
        result[uid]["net_external_ratio"] = _safe_ratio(result[uid]["_net_external"], t)
        del result[uid]["_net_external"]
        del result[uid]["_net_total"]
    return result


def _aggregate_dns(df: pd.DataFrame | None, devices_to_users: dict,
                   auth_sessions: dict | None = None) -> dict:
    if df is None or df.empty:
        return {}
    result = {}

    has_user_id = "user_id" in df.columns
    if has_user_id:
        user_groups = df[df["user_id"].notna()].groupby("user_id")
        for uid, grp in user_groups:
            if not uid or str(uid) == "nan":
                continue
            unique_domains = grp["query_name"].nunique() if "query_name" in grp.columns else 0
            total = len(grp)
            nxdomain = int((grp.get("response_code", pd.Series()) == "NXDOMAIN").sum())
            if uid not in result:
                result[uid] = {"dns_unique_domains": 0, "_dns_nx": 0, "_dns_total": 0}
            result[uid]["dns_unique_domains"] += unique_domains
            result[uid]["_dns_nx"] += nxdomain
            result[uid]["_dns_total"] += total

        for uid in result:
            t = result[uid]["_dns_total"]
            result[uid]["dns_nxdomain_ratio"] = _safe_ratio(result[uid]["_dns_nx"], t)
            del result[uid]["_dns_nx"]
            del result[uid]["_dns_total"]
        return result

    if "device_id" not in df.columns:
        return {}
    for dev_id, grp in df.groupby("device_id"):
        uid = devices_to_users.get(dev_id)
        if not uid and auth_sessions:
            uid = auth_sessions.get(dev_id)
        if not uid:
            continue
        unique_domains = grp["query_name"].nunique() if "query_name" in grp.columns else 0
        total = len(grp)
        nxdomain = int((grp.get("response_code", pd.Series()) == "NXDOMAIN").sum())
        if uid not in result:
            result[uid] = {"dns_unique_domains": 0, "_dns_nx": 0, "_dns_total": 0}
        result[uid]["dns_unique_domains"] += unique_domains
        result[uid]["_dns_nx"] += nxdomain
        result[uid]["_dns_total"] += total

    for uid in result:
        t = result[uid]["_dns_total"]
        result[uid]["dns_nxdomain_ratio"] = _safe_ratio(result[uid]["_dns_nx"], t)
        del result[uid]["_dns_nx"]
        del result[uid]["_dns_total"]
    return result


def _aggregate_endpoint(df: pd.DataFrame | None, devices_to_users: dict) -> dict:
    if df is None or df.empty:
        return {}
    result = {}
    user_col = "user_id" if "user_id" in df.columns else None

    for _, row in df.iterrows():
        uid = row.get("user_id") if user_col else devices_to_users.get(row.get("device_id"))
        if not uid or uid == "SYSTEM":
            uid = devices_to_users.get(row.get("device_id"))
        if not uid:
            continue
        if uid not in result:
            result[uid] = {"_risks": [], "_processes": set(), "_total": 0}
        risk = pd.to_numeric(row.get("risk_score", 0), errors="coerce")
        if pd.notna(risk):
            result[uid]["_risks"].append(int(risk))
        if row.get("process_name"):
            result[uid]["_processes"].add(row["process_name"])
        result[uid]["_total"] += 1

    final = {}
    for uid, data in result.items():
        risks = data["_risks"]
        total = data["_total"]
        suspicious = sum(1 for r in risks if r >= 50)
        final[uid] = {
            "endpoint_total": total,
            "endpoint_suspicious_ratio": _safe_ratio(suspicious, total),
            "endpoint_max_risk": max(risks) if risks else 0,
            "endpoint_mean_risk": float(np.mean(risks)) if risks else 0.0,
            "endpoint_unique_processes": len(data["_processes"]),
        }
    return final


def _aggregate_app(df: pd.DataFrame | None) -> dict:
    if df is None or df.empty:
        return {}
    result = {}
    for uid, grp in df.groupby("user_id"):
        total = len(grp)
        unique_apps = grp["app_id"].nunique() if "app_id" in grp.columns else 0
        admin_actions = int((grp.get("event_type", pd.Series()) == "admin_action").sum())
        exports = int((grp.get("event_type", pd.Series()) == "export").sum())
        errors = 0
        if "response_code" in grp.columns:
            codes = pd.to_numeric(grp["response_code"], errors="coerce")
            errors = int((codes >= 400).sum())
        result[uid] = {
            "app_total": total,
            "app_unique_apps": unique_apps,
            "app_admin_actions": admin_actions,
            "app_export_count": exports,
            "app_error_ratio": _safe_ratio(errors, total),
        }
    return result


def _aggregate_privilege(df: pd.DataFrame | None) -> dict:
    if df is None or df.empty:
        return {}
    result = {}
    uid_col = "actor_user_id" if "actor_user_id" in df.columns else "user_id"
    for uid, grp in df.groupby(uid_col):
        total = len(grp)
        elevations = int((grp.get("operation", pd.Series()) == "access_elevation").sum())
        denied = int((grp.get("approved", pd.Series()).str.lower() == "false").sum())
        result[uid] = {
            "priv_total": total,
            "priv_elevations": elevations,
            "priv_denied_ratio": _safe_ratio(denied, total),
        }
    return result


def _load_device_user_map() -> dict:
    """Build device_id -> user_id lookup from entities/devices.csv and users.csv.

    Primary source: devices.csv owner_user_id column.
    Supplement: users.csv primary_device_id column — if a device has no owner
    in devices.csv but a user claims it as their primary_device_id, add that
    mapping. This ensures users like USR-118 whose primary device (DEV-001)
    is a shared server still get network/DNS features attributed correctly.
    """
    path = DATA_DIR / "entities" / "devices.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str)
    mapping = {}
    if "owner_user_id" in df.columns:
        for _, row in df.iterrows():
            if pd.notna(row.get("owner_user_id")) and row["owner_user_id"]:
                mapping[row["device_id"]] = row["owner_user_id"]

    # Supplement with reverse lookup from users.csv primary_device_id
    users_path = DATA_DIR / "entities" / "users.csv"
    if users_path.exists():
        udf = pd.read_csv(users_path, dtype=str)
        for _, row in udf.iterrows():
            dev = row.get("primary_device_id")
            uid = row.get("user_id")
            if dev and pd.notna(dev) and uid and dev not in mapping:
                mapping[dev] = uid

    return mapping


def _get_all_user_ids() -> set:
    path = DATA_DIR / "entities" / "users.csv"
    if not path.exists():
        return set()
    df = pd.read_csv(path, dtype=str)
    return set(df["user_id"].tolist())


def ingest_day(conn, day: date, devices_to_users: dict, all_users: set) -> int:
    """Ingest all 7 log types for a single day. Returns row count."""
    day_str = day.isoformat()

    auth_csv = _read_csv("auth", day_str)
    auth_sessions = _build_auth_device_sessions(auth_csv)
    auth_data = _aggregate_auth(auth_csv)
    file_data = _aggregate_file_access(_read_csv("file_access", day_str))
    net_data = _aggregate_network(_read_csv("network", day_str), devices_to_users, auth_sessions)
    dns_data = _aggregate_dns(_read_csv("dns", day_str), devices_to_users, auth_sessions)
    endpoint_data = _aggregate_endpoint(_read_csv("endpoint", day_str), devices_to_users)
    app_data = _aggregate_app(_read_csv("app", day_str))
    priv_data = _aggregate_privilege(_read_csv("privilege", day_str))

    active_users = set()
    for d in [auth_data, file_data, net_data, dns_data, endpoint_data, app_data, priv_data]:
        active_users.update(d.keys())

    active_users = active_users.intersection(all_users)

    if not active_users:
        return 0

    rows = []
    for uid in sorted(active_users):
        auth = auth_data.get(uid, {})
        file = file_data.get(uid, {})
        net = net_data.get(uid, {})
        dns = dns_data.get(uid, {})
        ep = endpoint_data.get(uid, {})
        app = app_data.get(uid, {})
        priv = priv_data.get(uid, {})

        row = (
            uid, day,
            auth.get("auth_total", 0),
            auth.get("auth_success", 0),
            auth.get("auth_fail_rate", 0.0),
            auth.get("auth_off_hours_ratio", 0.0),
            auth.get("auth_unique_sources", 0),
            auth.get("auth_unique_dests", 0),
            auth.get("auth_methods", 0),
            file.get("file_total", 0),
            file.get("file_restricted_ratio", 0.0),
            file.get("file_confidential_ratio", 0.0),
            file.get("file_write_ratio", 0.0),
            file.get("file_unique_paths", 0),
            file.get("file_total_bytes", 0),
            net.get("net_bytes_out", 0),
            net.get("net_unique_dsts", 0),
            net.get("net_external_ratio", 0.0),
            dns.get("dns_unique_domains", 0),
            dns.get("dns_nxdomain_ratio", 0.0),
            ep.get("endpoint_total", 0),
            ep.get("endpoint_suspicious_ratio", 0.0),
            ep.get("endpoint_max_risk", 0),
            ep.get("endpoint_mean_risk", 0.0),
            ep.get("endpoint_unique_processes", 0),
            app.get("app_total", 0),
            app.get("app_unique_apps", 0),
            app.get("app_admin_actions", 0),
            app.get("app_export_count", 0),
            app.get("app_error_ratio", 0.0),
            priv.get("priv_total", 0),
            priv.get("priv_elevations", 0),
            priv.get("priv_denied_ratio", 0.0),
        )
        rows.append(row)

    with conn.cursor() as cur:
        from psycopg2.extras import execute_batch
        execute_batch(cur, UPSERT_SQL, rows, page_size=500)
    conn.commit()

    return len(rows)


def discover_dates(start: date | None = None, end: date | None = None) -> list[date]:
    """Find all dates that have CSV data available."""
    auth_dir = DATA_DIR / "auth"
    if not auth_dir.exists():
        return []
    dates = []
    for f in sorted(auth_dir.glob("*.csv")):
        try:
            d = date.fromisoformat(f.stem)
            if start and d < start:
                continue
            if end and d > end:
                continue
            dates.append(d)
        except ValueError:
            continue
    return dates


def main():
    parser = argparse.ArgumentParser(description="Ingest raw CSVs into daily_features")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--date", type=str, help="Single date (YYYY-MM-DD)")
    args = parser.parse_args()

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None
    if args.date:
        start = end = date.fromisoformat(args.date)

    dates = discover_dates(start, end)
    print(f"Found {len(dates)} days of data to ingest")
    if not dates:
        print("No data found. Run the simulator first.")
        return

    devices_to_users = _load_device_user_map()
    all_users = _get_all_user_ids()
    print(f"Device-to-user map: {len(devices_to_users)} devices, {len(all_users)} users")

    conn = get_connection()
    total_rows = 0
    t0 = time.time()

    for i, d in enumerate(dates):
        n = ingest_day(conn, d, devices_to_users, all_users)
        total_rows += n
        if (i + 1) % 10 == 0 or i == len(dates) - 1:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(dates)}] {d} — {n} users — "
                  f"total {total_rows:,} rows — {elapsed:.1f}s")

    conn.close()
    elapsed = time.time() - t0
    print(f"\nDone. {total_rows:,} rows ingested across {len(dates)} days in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
