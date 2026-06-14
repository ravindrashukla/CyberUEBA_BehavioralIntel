"""Build monthly behavioral embedding snapshots for all entities."""
import os
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from embeddings.embedder import Embedder
from embeddings.composer import compose


class SnapshotBuilder:
    """Constructs monthly behavioral embeddings from raw log CSVs.

    For each entity in each month, generates 5 signal-specific text descriptions
    from aggregated log data, embeds each into 1536-d, and composes them into
    a single composite vector via weighted average.
    """

    def __init__(self, data_dir: str = "data/generated"):
        self.data_dir = Path(data_dir)
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY is required — real OpenAI embeddings are mandatory "
                "(mock embeddings have been removed)."
            )
        self.embedder = Embedder()

    def build_all_snapshots(
        self, start_month: date = None, end_month: date = None
    ) -> pd.DataFrame:
        """Build monthly snapshots for all entity types.

        Returns DataFrame with columns:
        [entity_type, entity_id, cutoff_date, composite, signal_vectors]
        where composite is a 1536-d vector and signal_vectors is a dict of
        signal_name -> 1536-d vector.
        """
        from simulator.config import SIM_START, SIM_END

        start_month = start_month or SIM_START.replace(day=1)
        end_month = end_month or SIM_END.replace(day=1)

        all_snapshots = []
        current = start_month

        while current < end_month:
            month_end = _next_month(current) - timedelta(days=1)
            print(f"\n--- Building snapshots for {current.isoformat()} ---")

            # Build for each entity type
            user_snaps = self.build_user_snapshots(current, month_end)
            device_snaps = self.build_device_snapshots(current, month_end)
            segment_snaps = self.build_segment_snapshots(current, month_end)
            app_snaps = self.build_app_snapshots(current, month_end)

            all_snapshots.extend(user_snaps)
            all_snapshots.extend(device_snaps)
            all_snapshots.extend(segment_snaps)
            all_snapshots.extend(app_snaps)

            print(
                f"    Users: {len(user_snaps)}, Devices: {len(device_snaps)}, "
                f"Segments: {len(segment_snaps)}, Apps: {len(app_snaps)}"
            )
            current = _next_month(current)

        df = pd.DataFrame(all_snapshots)
        print(f"\nTotal snapshots: {len(df)}")
        print(f"Embedder stats: {self.embedder.stats()}")
        return df

    def build_user_snapshots(self, month_start: date, month_end: date) -> list[dict]:
        """Build snapshots for all users for one month."""
        logs = self._load_logs_for_window(month_start, month_end)
        entities_dir = self.data_dir / "entities"
        users_df = pd.read_csv(entities_dir / "users.csv")

        auth_df = logs.get("auth", pd.DataFrame())
        file_df = logs.get("file_access", pd.DataFrame())
        priv_df = logs.get("privilege", pd.DataFrame())
        net_df = logs.get("network", pd.DataFrame())
        app_df = logs.get("app", pd.DataFrame())

        snapshots = []
        for _, user in users_df.iterrows():
            uid = user["user_id"]

            # Auth signal
            user_auth = auth_df[auth_df["user_id"] == uid] if len(auth_df) > 0 else pd.DataFrame()
            auth_text = _summarize_user_auth(uid, user, user_auth)

            # Privilege signal (actor_user_id or target_user_id)
            if len(priv_df) > 0 and "actor_user_id" in priv_df.columns:
                user_priv = priv_df[(priv_df["actor_user_id"] == uid) | (priv_df["target_user_id"] == uid)]
            else:
                user_priv = pd.DataFrame()
            priv_text = _summarize_user_privilege(uid, user, user_priv)

            # Data access signal
            user_file = file_df[file_df["user_id"] == uid] if len(file_df) > 0 and "user_id" in file_df.columns else pd.DataFrame()
            data_text = _summarize_user_data_access(uid, user, user_file)

            # Network signal
            network_text = _summarize_user_network(uid, user, net_df)

            # Communication signal (derived from app events)
            user_app = app_df[app_df["user_id"] == uid] if len(app_df) > 0 and "user_id" in app_df.columns else pd.DataFrame()
            comm_text = _summarize_user_communication(uid, user, user_app)

            # Embed all 5 signals
            texts = [auth_text, priv_text, data_text, network_text, comm_text]
            vectors = self.embedder.embed_batch(texts)

            signal_dict = {
                "auth": vectors[0],
                "privilege": vectors[1],
                "data_access": vectors[2],
                "network": vectors[3],
                "communication": vectors[4],
            }

            composite = compose(signal_dict, "user")

            snapshots.append({
                "entity_type": "user",
                "entity_id": uid,
                "cutoff_date": month_end,
                "composite": composite,
                "signal_vectors": signal_dict,
            })

        return snapshots

    def build_device_snapshots(self, month_start: date, month_end: date) -> list[dict]:
        """Build snapshots for all devices for one month."""
        logs = self._load_logs_for_window(month_start, month_end)
        entities_dir = self.data_dir / "entities"
        devices_df = pd.read_csv(entities_dir / "devices.csv")

        net_df = logs.get("network", pd.DataFrame())
        endpoint_df = logs.get("endpoint", pd.DataFrame())
        auth_df = logs.get("auth", pd.DataFrame())

        snapshots = []
        for _, device in devices_df.iterrows():
            did = device["device_id"]

            # Process signal (endpoint telemetry)
            dev_endpoint = endpoint_df[endpoint_df["device_id"] == did] if len(endpoint_df) > 0 and "device_id" in endpoint_df.columns else pd.DataFrame()
            process_text = _summarize_device_process(did, device, dev_endpoint)

            # Traffic signal (network flows)
            dev_net = net_df[net_df["device_id"] == did] if len(net_df) > 0 and "device_id" in net_df.columns else pd.DataFrame()
            traffic_text = _summarize_device_traffic(did, device, dev_net)

            # Resource signal
            resource_text = _summarize_device_resource(did, device, dev_endpoint)

            # Auth signal (authentications targeting this device)
            dev_auth = auth_df[auth_df["device_id"] == did] if len(auth_df) > 0 and "device_id" in auth_df.columns else pd.DataFrame()
            auth_text = _summarize_device_auth(did, device, dev_auth)

            # Config signal
            config_text = _summarize_device_config(did, device)

            texts = [process_text, traffic_text, resource_text, auth_text, config_text]
            vectors = self.embedder.embed_batch(texts)

            signal_dict = {
                "process": vectors[0],
                "traffic": vectors[1],
                "resource": vectors[2],
                "auth": vectors[3],
                "config": vectors[4],
            }

            composite = compose(signal_dict, "device")

            snapshots.append({
                "entity_type": "device",
                "entity_id": did,
                "cutoff_date": month_end,
                "composite": composite,
                "signal_vectors": signal_dict,
            })

        return snapshots

    def build_segment_snapshots(self, month_start: date, month_end: date) -> list[dict]:
        """Build snapshots for all network segments for one month."""
        logs = self._load_logs_for_window(month_start, month_end)
        entities_dir = self.data_dir / "entities"
        segments_df = pd.read_csv(entities_dir / "segments.csv")
        devices_df = pd.read_csv(entities_dir / "devices.csv")

        net_df = logs.get("network", pd.DataFrame())
        dns_df = logs.get("dns", pd.DataFrame())

        snapshots = []
        for _, seg in segments_df.iterrows():
            sid = seg["segment_id"]

            # Get devices in this segment
            seg_devices = devices_df[devices_df["segment_id"] == sid]["device_id"].tolist()

            # Volume signal
            seg_net = net_df[net_df["device_id"].isin(seg_devices)] if len(net_df) > 0 and "device_id" in net_df.columns else pd.DataFrame()
            volume_text = _summarize_segment_volume(sid, seg, seg_net)

            # Connections signal
            connections_text = _summarize_segment_connections(sid, seg, seg_net, seg_devices)

            # Protocols signal
            protocols_text = _summarize_segment_protocols(sid, seg, seg_net)

            # Threats signal
            seg_dns = dns_df[dns_df["device_id"].isin(seg_devices)] if len(dns_df) > 0 and "device_id" in dns_df.columns else pd.DataFrame()
            threats_text = _summarize_segment_threats(sid, seg, seg_dns)

            # Exposure signal
            exposure_text = _summarize_segment_exposure(sid, seg, seg_net)

            texts = [volume_text, connections_text, protocols_text, threats_text, exposure_text]
            vectors = self.embedder.embed_batch(texts)

            signal_dict = {
                "volume": vectors[0],
                "connections": vectors[1],
                "protocols": vectors[2],
                "threats": vectors[3],
                "exposure": vectors[4],
            }

            composite = compose(signal_dict, "segment")

            snapshots.append({
                "entity_type": "segment",
                "entity_id": sid,
                "cutoff_date": month_end,
                "composite": composite,
                "signal_vectors": signal_dict,
            })

        return snapshots

    def build_app_snapshots(self, month_start: date, month_end: date) -> list[dict]:
        """Build snapshots for all applications for one month."""
        logs = self._load_logs_for_window(month_start, month_end)
        entities_dir = self.data_dir / "entities"
        apps_df = pd.read_csv(entities_dir / "applications.csv")

        app_df = logs.get("app", pd.DataFrame())

        snapshots = []
        for _, app in apps_df.iterrows():
            aid = app["app_id"]

            app_events = app_df[app_df["app_id"] == aid] if len(app_df) > 0 and "app_id" in app_df.columns else pd.DataFrame()

            # Access signal
            access_text = _summarize_app_access(aid, app, app_events)

            # Queries signal
            queries_text = _summarize_app_queries(aid, app, app_events)

            # Errors signal
            errors_text = _summarize_app_errors(aid, app, app_events)

            # Performance signal
            perf_text = _summarize_app_performance(aid, app, app_events)

            # Config signal
            config_text = _summarize_app_config(aid, app, app_events)

            texts = [access_text, queries_text, errors_text, perf_text, config_text]
            vectors = self.embedder.embed_batch(texts)

            signal_dict = {
                "access": vectors[0],
                "queries": vectors[1],
                "errors": vectors[2],
                "performance": vectors[3],
                "config": vectors[4],
            }

            composite = compose(signal_dict, "app")

            snapshots.append({
                "entity_type": "app",
                "entity_id": aid,
                "cutoff_date": month_end,
                "composite": composite,
                "signal_vectors": signal_dict,
            })

        return snapshots

    def _load_logs_for_window(
        self, window_start: date, window_end: date
    ) -> dict[str, pd.DataFrame]:
        """Load CSV log data for a time window into a dict of DataFrames.

        Only loads files within the date range (one CSV per day per log type).
        """
        log_types = ["auth", "network", "dns", "endpoint", "app", "privilege", "file_access"]
        result = {}

        for log_type in log_types:
            log_dir = self.data_dir / log_type
            if not log_dir.exists():
                result[log_type] = pd.DataFrame()
                continue

            frames = []
            current = window_start
            while current <= window_end:
                csv_path = log_dir / f"{current.isoformat()}.csv"
                if csv_path.exists():
                    try:
                        df = pd.read_csv(csv_path)
                        frames.append(df)
                    except Exception:
                        pass  # skip corrupted files
                current += timedelta(days=1)

            if frames:
                result[log_type] = pd.concat(frames, ignore_index=True)
            else:
                result[log_type] = pd.DataFrame()

        return result

    def save_snapshots(
        self, snapshots: pd.DataFrame, output_path: str = "data/snapshots.parquet"
    ):
        """Save snapshots to parquet file.

        Composite and signal vectors are serialized as binary columns.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize numpy arrays to bytes for parquet storage
        df = snapshots.copy()
        df["composite_bytes"] = df["composite"].apply(lambda v: v.tobytes())
        df["signal_vectors_bytes"] = df["signal_vectors"].apply(
            lambda d: {k: v.tobytes() for k, v in d.items()}.__repr__()
        )

        # Store individual signal vectors as separate binary columns
        # This makes downstream queries easier
        sample_signals = df["signal_vectors"].iloc[0] if len(df) > 0 else {}
        for sig_name in sample_signals:
            df[f"signal_{sig_name}_bytes"] = df["signal_vectors"].apply(
                lambda d, sn=sig_name: d[sn].tobytes() if sn in d else b""
            )

        # Drop non-serializable columns before saving
        save_cols = ["entity_type", "entity_id", "cutoff_date", "composite_bytes"]
        save_cols += [c for c in df.columns if c.startswith("signal_") and c.endswith("_bytes")]
        df[save_cols].to_parquet(output_path, index=False)

        print(f"Snapshots saved to {output_path} ({len(df)} rows)")


# ---------------------------------------------------------------------------
# Signal text summarizers
# These convert raw log aggregates into natural-language behavioral descriptions
# that capture the semantic meaning of entity behavior for embedding.
# ---------------------------------------------------------------------------


def _summarize_user_auth(uid: str, user: pd.Series, auth_df: pd.DataFrame) -> str:
    """Summarize user authentication behavior."""
    n_events = len(auth_df)
    if n_events == 0:
        return (
            f"User {uid} ({user.get('role', 'unknown')}, {user.get('department', 'unknown')}) "
            f"had no authentication events this period."
        )

    n_success = auth_df["success"].sum() if "success" in auth_df.columns else 0
    n_fail = n_events - n_success
    fail_rate = n_fail / n_events if n_events > 0 else 0

    methods = auth_df["auth_method"].value_counts().to_dict() if "auth_method" in auth_df.columns else {}
    locations = auth_df["geo_location"].nunique() if "geo_location" in auth_df.columns else 0
    systems = auth_df["dest_system"].nunique() if "dest_system" in auth_df.columns else 0

    return (
        f"User {uid} ({user.get('role', 'unknown')}, {user.get('department', 'unknown')}): "
        f"{n_events} auth events, {n_success} successes, {n_fail} failures "
        f"(failure_rate={fail_rate:.2f}). "
        f"Auth methods: {methods}. "
        f"Unique locations: {locations}, unique systems: {systems}."
    )


def _summarize_user_privilege(uid: str, user: pd.Series, priv_df: pd.DataFrame) -> str:
    """Summarize user privilege operation behavior."""
    n_events = len(priv_df)
    if n_events == 0:
        return (
            f"User {uid} ({user.get('role', 'unknown')}): "
            f"no privilege escalation operations this period."
        )

    op_types = priv_df["operation"].value_counts().to_dict() if "operation" in priv_df.columns else {}
    targets = priv_df["target_user_id"].nunique() if "target_user_id" in priv_df.columns else 0

    return (
        f"User {uid} ({user.get('role', 'unknown')}): "
        f"{n_events} privilege operations. "
        f"Operation types: {op_types}. "
        f"Unique targets: {targets}."
    )


def _summarize_user_data_access(uid: str, user: pd.Series, file_df: pd.DataFrame) -> str:
    """Summarize user data access patterns."""
    n_events = len(file_df)
    if n_events == 0:
        return (
            f"User {uid} ({user.get('role', 'unknown')}): "
            f"no file access events this period."
        )

    actions = file_df["operation"].value_counts().to_dict() if "operation" in file_df.columns else {}
    classifications = file_df["data_classification"].value_counts().to_dict() if "data_classification" in file_df.columns else {}

    return (
        f"User {uid} ({user.get('role', 'unknown')}): "
        f"{n_events} file accesses. "
        f"Operations: {actions}. "
        f"Data classifications: {classifications}."
    )


def _summarize_user_network(uid: str, user: pd.Series, net_df: pd.DataFrame) -> str:
    """Summarize user network activity (via their primary device)."""
    device_id = user.get("primary_device_id", "")
    if len(net_df) == 0 or "device_id" not in net_df.columns:
        return (
            f"User {uid} ({user.get('role', 'unknown')}): "
            f"no network activity observed from device {device_id}."
        )

    dev_net = net_df[net_df["device_id"] == device_id]
    n_flows = len(dev_net)
    total_bytes_out = dev_net["bytes_out"].sum() if "bytes_out" in dev_net.columns else 0
    unique_dests = dev_net["dst_ip"].nunique() if "dst_ip" in dev_net.columns else 0
    protocols = dev_net["protocol"].value_counts().to_dict() if "protocol" in dev_net.columns else {}

    return (
        f"User {uid} device {device_id}: "
        f"{n_flows} network flows, {total_bytes_out} bytes sent, "
        f"{unique_dests} unique destinations. "
        f"Protocols: {protocols}."
    )


def _summarize_user_communication(uid: str, user: pd.Series, app_df: pd.DataFrame) -> str:
    """Summarize user communication/app interaction patterns."""
    n_events = len(app_df)
    if n_events == 0:
        return (
            f"User {uid} ({user.get('role', 'unknown')}): "
            f"no application events this period."
        )

    event_types = app_df["event_type"].value_counts().to_dict() if "event_type" in app_df.columns else {}
    apps_used = app_df["app_id"].nunique() if "app_id" in app_df.columns else 0
    errors = len(app_df[app_df["event_type"] == "error"]) if "event_type" in app_df.columns else 0

    return (
        f"User {uid} ({user.get('role', 'unknown')}): "
        f"{n_events} app events across {apps_used} applications. "
        f"Event types: {event_types}. "
        f"Error count: {errors}."
    )


def _summarize_device_process(did: str, device: pd.Series, endpoint_df: pd.DataFrame) -> str:
    """Summarize device process/endpoint telemetry."""
    n_events = len(endpoint_df)
    dtype = device.get("device_type", "unknown")
    os_name = device.get("os", "unknown")

    if n_events == 0:
        return (
            f"Device {did} ({dtype}, {os_name}): "
            f"no endpoint telemetry events this period."
        )

    event_types = endpoint_df["event_type"].value_counts().to_dict() if "event_type" in endpoint_df.columns else {}

    return (
        f"Device {did} ({dtype}, {os_name}): "
        f"{n_events} endpoint events. "
        f"Event types: {event_types}."
    )


def _summarize_device_traffic(did: str, device: pd.Series, net_df: pd.DataFrame) -> str:
    """Summarize device network traffic patterns."""
    n_flows = len(net_df)
    dtype = device.get("device_type", "unknown")

    if n_flows == 0:
        return (
            f"Device {did} ({dtype}): "
            f"no outbound network flows this period."
        )

    total_bytes = net_df["bytes_out"].sum() if "bytes_out" in net_df.columns else 0
    unique_dests = net_df["dst_ip"].nunique() if "dst_ip" in net_df.columns else 0
    protocols = net_df["protocol"].value_counts().to_dict() if "protocol" in net_df.columns else {}
    ports = net_df["dst_port"].value_counts().head(5).to_dict() if "dst_port" in net_df.columns else {}

    return (
        f"Device {did} ({dtype}): "
        f"{n_flows} flows, {total_bytes} bytes, "
        f"{unique_dests} unique destinations. "
        f"Protocols: {protocols}. Top ports: {ports}."
    )


def _summarize_device_resource(did: str, device: pd.Series, endpoint_df: pd.DataFrame) -> str:
    """Summarize device resource usage patterns."""
    dtype = device.get("device_type", "unknown")
    os_name = device.get("os", "unknown")

    if len(endpoint_df) == 0:
        return (
            f"Device {did} ({dtype}, {os_name}): "
            f"no resource utilization data this period."
        )

    n_events = len(endpoint_df)
    # Estimate resource pressure from event volume
    events_per_day = n_events / 30.0  # approximate monthly

    return (
        f"Device {did} ({dtype}, {os_name}): "
        f"{n_events} telemetry events, ~{events_per_day:.0f}/day average. "
        f"OS: {os_name}, type: {dtype}."
    )


def _summarize_device_auth(did: str, device: pd.Series, auth_df: pd.DataFrame) -> str:
    """Summarize authentication events targeting this device."""
    n_events = len(auth_df)
    dtype = device.get("device_type", "unknown")

    if n_events == 0:
        return (
            f"Device {did} ({dtype}): "
            f"no authentication events targeting this device."
        )

    n_success = auth_df["success"].sum() if "success" in auth_df.columns else 0
    n_fail = n_events - n_success
    unique_users = auth_df["user_id"].nunique() if "user_id" in auth_df.columns else 0

    return (
        f"Device {did} ({dtype}): "
        f"{n_events} auth events ({n_success} success, {n_fail} failed). "
        f"Unique users: {unique_users}."
    )


def _summarize_device_config(did: str, device: pd.Series) -> str:
    """Summarize device configuration state (static per device)."""
    return (
        f"Device {did}: type={device.get('device_type', 'unknown')}, "
        f"os={device.get('os', 'unknown')}, "
        f"segment={device.get('segment_id', 'unknown')}, "
        f"ip={device.get('ip_address', 'unknown')}."
    )


def _summarize_segment_volume(sid: str, seg: pd.Series, net_df: pd.DataFrame) -> str:
    """Summarize segment traffic volume."""
    n_flows = len(net_df)
    zone = seg.get("zone", "unknown")

    if n_flows == 0:
        return f"Segment {sid} (zone={zone}): no network traffic observed."

    total_bytes = net_df["bytes_out"].sum() if "bytes_out" in net_df.columns else 0

    return (
        f"Segment {sid} (zone={zone}): "
        f"{n_flows} outbound flows, {total_bytes} total bytes."
    )


def _summarize_segment_connections(
    sid: str, seg: pd.Series, net_df: pd.DataFrame, seg_devices: list
) -> str:
    """Summarize segment connection patterns."""
    zone = seg.get("zone", "unknown")

    if len(net_df) == 0:
        return f"Segment {sid} (zone={zone}): no connection data."

    unique_external_dests = net_df["dst_ip"].nunique() if "dst_ip" in net_df.columns else 0
    active_devices = net_df["device_id"].nunique() if "device_id" in net_df.columns else 0

    return (
        f"Segment {sid} (zone={zone}): "
        f"{active_devices}/{len(seg_devices)} devices active, "
        f"{unique_external_dests} unique external destinations."
    )


def _summarize_segment_protocols(sid: str, seg: pd.Series, net_df: pd.DataFrame) -> str:
    """Summarize segment protocol distribution."""
    zone = seg.get("zone", "unknown")

    if len(net_df) == 0 or "protocol" not in net_df.columns:
        return f"Segment {sid} (zone={zone}): no protocol data."

    protocols = net_df["protocol"].value_counts().to_dict()
    ports = net_df["dst_port"].value_counts().head(5).to_dict() if "dst_port" in net_df.columns else {}

    return (
        f"Segment {sid} (zone={zone}): "
        f"protocols={protocols}, top_ports={ports}."
    )


def _summarize_segment_threats(sid: str, seg: pd.Series, dns_df: pd.DataFrame) -> str:
    """Summarize segment threat indicators from DNS."""
    zone = seg.get("zone", "unknown")

    if len(dns_df) == 0:
        return f"Segment {sid} (zone={zone}): no DNS queries observed."

    n_queries = len(dns_df)
    unique_domains = dns_df["query_name"].nunique() if "query_name" in dns_df.columns else 0
    nxdomain = len(dns_df[dns_df["response_code"] == "NXDOMAIN"]) if "response_code" in dns_df.columns else 0

    return (
        f"Segment {sid} (zone={zone}): "
        f"{n_queries} DNS queries, {unique_domains} unique domains, "
        f"{nxdomain} NXDOMAIN responses."
    )


def _summarize_segment_exposure(sid: str, seg: pd.Series, net_df: pd.DataFrame) -> str:
    """Summarize segment external exposure."""
    zone = seg.get("zone", "unknown")
    trust = seg.get("trust_level", "unknown")

    if len(net_df) == 0:
        return (
            f"Segment {sid} (zone={zone}, trust_level={trust}): "
            f"no external exposure data."
        )

    # Approximate: flows to non-10.x.x.x IPs = external
    if "dst_ip" in net_df.columns:
        external = net_df[~net_df["dst_ip"].str.startswith("10.")]
        n_external = len(external)
    else:
        n_external = 0

    return (
        f"Segment {sid} (zone={zone}, trust_level={trust}): "
        f"{n_external} external-bound flows out of {len(net_df)} total."
    )


def _summarize_app_access(aid: str, app: pd.Series, app_df: pd.DataFrame) -> str:
    """Summarize application access patterns."""
    app_name = app.get("app_name", aid)
    criticality = app.get("criticality", "unknown")

    if len(app_df) == 0:
        return f"App {aid} ({app_name}, criticality={criticality}): no access events."

    unique_users = app_df["user_id"].nunique() if "user_id" in app_df.columns else 0
    login_events = len(app_df[app_df["event_type"] == "login"]) if "event_type" in app_df.columns else 0

    return (
        f"App {aid} ({app_name}, criticality={criticality}): "
        f"{unique_users} unique users, {login_events} logins, "
        f"{len(app_df)} total events."
    )


def _summarize_app_queries(aid: str, app: pd.Series, app_df: pd.DataFrame) -> str:
    """Summarize application query patterns."""
    app_name = app.get("app_name", aid)

    if len(app_df) == 0 or "event_type" not in app_df.columns:
        return f"App {aid} ({app_name}): no query data."

    queries = app_df[app_df["event_type"] == "query"]
    api_calls = app_df[app_df["event_type"] == "api_call"]

    return (
        f"App {aid} ({app_name}): "
        f"{len(queries)} queries, {len(api_calls)} API calls."
    )


def _summarize_app_errors(aid: str, app: pd.Series, app_df: pd.DataFrame) -> str:
    """Summarize application error patterns."""
    app_name = app.get("app_name", aid)

    if len(app_df) == 0 or "event_type" not in app_df.columns:
        return f"App {aid} ({app_name}): no error data."

    errors = app_df[app_df["event_type"] == "error"]
    n_errors = len(errors)
    total = len(app_df)
    error_rate = n_errors / total if total > 0 else 0

    return (
        f"App {aid} ({app_name}): "
        f"{n_errors} errors out of {total} events (rate={error_rate:.3f})."
    )


def _summarize_app_performance(aid: str, app: pd.Series, app_df: pd.DataFrame) -> str:
    """Summarize application performance indicators."""
    app_name = app.get("app_name", aid)
    app_type = app.get("app_type", "unknown")

    if len(app_df) == 0:
        return f"App {aid} ({app_name}, type={app_type}): no performance data."

    events_per_day = len(app_df) / 30.0

    return (
        f"App {aid} ({app_name}, type={app_type}): "
        f"{len(app_df)} total events, ~{events_per_day:.0f}/day throughput."
    )


def _summarize_app_config(aid: str, app: pd.Series, app_df: pd.DataFrame) -> str:
    """Summarize application configuration change patterns."""
    app_name = app.get("app_name", aid)
    classification = app.get("data_classification", "unknown")

    if len(app_df) == 0 or "event_type" not in app_df.columns:
        return (
            f"App {aid} ({app_name}, data_class={classification}): "
            f"no config change data."
        )

    config_changes = app_df[app_df["event_type"] == "config_change"]
    perm_requests = app_df[app_df["event_type"] == "permission_request"]

    return (
        f"App {aid} ({app_name}, data_class={classification}): "
        f"{len(config_changes)} config changes, "
        f"{len(perm_requests)} permission requests."
    )


# ---------------------------------------------------------------------------
# Session signals (relationship entity: user + device + time window)
# ---------------------------------------------------------------------------


def _summarize_session_activity(
    session_id: str, user_id: str, device_id: str,
    auth_df: pd.DataFrame, app_df: pd.DataFrame,
) -> str:
    """Summarize session activity patterns."""
    n_auth = len(auth_df)
    n_app = len(app_df)
    if n_auth == 0 and n_app == 0:
        return f"Session {session_id} (user={user_id}, device={device_id}): no activity."

    success = len(auth_df[auth_df["status"] == "success"]) if "status" in auth_df.columns else 0
    fail = n_auth - success

    return (
        f"Session {session_id} (user={user_id}, device={device_id}): "
        f"{n_auth} auth events ({success} success, {fail} fail), "
        f"{n_app} app events."
    )


def _summarize_session_risk(
    session_id: str, user_id: str, device_id: str,
    auth_df: pd.DataFrame, priv_df: pd.DataFrame,
) -> str:
    """Summarize risk accumulation in session."""
    fail = len(auth_df[auth_df["status"] == "failure"]) if "status" in auth_df.columns and len(auth_df) > 0 else 0
    priv_ops = len(priv_df)

    return (
        f"Session {session_id} risk: {fail} failed auths, "
        f"{priv_ops} privilege operations."
    )


def _summarize_session_data_movement(
    session_id: str, user_id: str, device_id: str,
    file_df: pd.DataFrame, net_df: pd.DataFrame,
) -> str:
    """Summarize data movement within session."""
    n_files = len(file_df)
    bytes_out = net_df["bytes_out"].sum() if "bytes_out" in net_df.columns and len(net_df) > 0 else 0

    return (
        f"Session {session_id} data movement: {n_files} file accesses, "
        f"{bytes_out:.0f} bytes outbound network."
    )


def _summarize_session_lateral(
    session_id: str, user_id: str, device_id: str,
    auth_df: pd.DataFrame,
) -> str:
    """Summarize lateral movement indicators in session."""
    if len(auth_df) == 0 or "device_id" not in auth_df.columns:
        return f"Session {session_id}: no lateral movement data."

    other_devices = auth_df[auth_df["device_id"] != device_id]["device_id"].nunique()
    return (
        f"Session {session_id} lateral: user {user_id} authenticated to "
        f"{other_devices} other devices besides {device_id}."
    )


def _summarize_session_temporal(
    session_id: str, user_id: str, device_id: str,
    auth_df: pd.DataFrame,
) -> str:
    """Summarize temporal patterns in session."""
    if len(auth_df) == 0 or "timestamp" not in auth_df.columns:
        return f"Session {session_id}: no temporal data."

    timestamps = pd.to_datetime(auth_df["timestamp"], errors="coerce")
    valid = timestamps.dropna()
    if len(valid) == 0:
        return f"Session {session_id}: no parseable timestamps."

    hours = valid.dt.hour
    off_hours = ((hours < 6) | (hours > 22)).sum()
    span_days = (valid.max() - valid.min()).days + 1

    return (
        f"Session {session_id} temporal: {len(valid)} events over {span_days} days, "
        f"{off_hours} off-hours events."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _next_month(d: date) -> date:
    """Return the first day of the next month."""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)
