"""Device behavioral signal serializers for embedding generation.

Each function takes a device_id, a dict of log DataFrames, and a time window,
then returns a natural language prose string describing that device's behavior
in the given window. These text strings are subsequently embedded via
OpenAI text-embedding-3-small to produce 1536-d behavioral vectors.
"""

from datetime import date

import pandas as pd


def _filter_device_window(df: pd.DataFrame, device_id: str, window_start: date, window_end: date) -> pd.DataFrame:
    """Filter a DataFrame to a specific device and time window."""
    if df is None or df.empty:
        return pd.DataFrame()
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    mask = (
        (df["device_id"] == device_id)
        & (df["timestamp"].dt.date >= window_start)
        & (df["timestamp"].dt.date <= window_end)
    )
    return df[mask]


def _days_in_window(window_start: date, window_end: date) -> int:
    return max((window_end - window_start).days, 1)


def process_signal(device_id: str, logs: dict, window_start: date, window_end: date) -> str:
    """Serialize process activity: types, frequencies, risk distribution, parent chains.

    Uses endpoint telemetry logs (event_type, process_name, risk_score, parent_process).
    """
    df = _filter_device_window(logs.get("endpoint", pd.DataFrame()), device_id, window_start, window_end)

    if df.empty:
        return f"No process activity recorded for device {device_id} in this period."

    days = _days_in_window(window_start, window_end)
    total = len(df)

    # Event type breakdown
    event_types = df["event_type"].value_counts()
    type_parts = [f"{et} ({ct})" for et, ct in event_types.head(4).items()]

    # Risk distribution
    high_risk = (df["risk_score"] >= 50).sum()
    medium_risk = ((df["risk_score"] >= 20) & (df["risk_score"] < 50)).sum()
    low_risk = (df["risk_score"] < 20).sum()

    # Unique processes
    n_processes = df["process_name"].nunique()
    top_process = df["process_name"].mode().iloc[0] if not df["process_name"].mode().empty else "unknown"

    # Parent process diversity
    n_parents = df["parent_process"].nunique()

    sentences = [
        f"Device {device_id} generated {total} endpoint events over {days} days ({total / days:.0f}/day).",
        f"Event types: {', '.join(type_parts)}.",
        f"Risk distribution: {low_risk} low, {medium_risk} medium, {high_risk} high-risk events.",
        f"{n_processes} unique processes observed (most frequent: {top_process}), spawned from {n_parents} parent process(es).",
    ]
    return " ".join(sentences)


def traffic_signal(device_id: str, logs: dict, window_start: date, window_end: date) -> str:
    """Serialize network traffic: volume, destinations, protocols, port usage."""
    df = _filter_device_window(logs.get("network", pd.DataFrame()), device_id, window_start, window_end)

    if df.empty:
        return f"No network traffic recorded for device {device_id} in this period."

    days = _days_in_window(window_start, window_end)
    total = len(df)

    # Total bytes
    bytes_total = df["bytes_in"].sum() + df["bytes_out"].sum()
    if bytes_total > 1_073_741_824:
        vol_str = f"{bytes_total / 1_073_741_824:.1f} GB"
    elif bytes_total > 1_048_576:
        vol_str = f"{bytes_total / 1_048_576:.0f} MB"
    else:
        vol_str = f"{bytes_total / 1024:.0f} KB"

    # Protocols
    protocols = df["protocol"].value_counts(normalize=True)
    proto_parts = [f"{p} ({v:.0%})" for p, v in protocols.items()]

    # Internal vs external
    external_mask = ~df["dst_ip"].str.startswith("10.")
    external_pct = external_mask.sum() / total * 100
    n_unique_dst = df["dst_ip"].nunique()

    # Top destination ports
    top_ports = df["dst_port"].value_counts().head(4)
    port_parts = [f"{port} ({ct})" for port, ct in top_ports.items()]

    # Average duration
    avg_duration = df["duration_ms"].mean()

    sentences = [
        f"Device {device_id} produced {total} network flows over {days} days ({total / days:.0f}/day).",
        f"Total volume: {vol_str}. Protocols: {', '.join(proto_parts)}.",
        f"{n_unique_dst} unique destinations; {external_pct:.0f}% directed externally.",
        f"Top ports: {', '.join(port_parts)}. Mean flow duration: {avg_duration:.0f} ms.",
    ]
    return " ".join(sentences)


def resource_signal(device_id: str, logs: dict, window_start: date, window_end: date) -> str:
    """Serialize resource usage: DNS queries, file system activity, registry changes.

    Combines DNS logs and endpoint file_write/registry_modify events.
    """
    dns_df = _filter_device_window(logs.get("dns", pd.DataFrame()), device_id, window_start, window_end)
    endpoint_df = _filter_device_window(logs.get("endpoint", pd.DataFrame()), device_id, window_start, window_end)

    if dns_df.empty and endpoint_df.empty:
        return f"No resource activity recorded for device {device_id} in this period."

    days = _days_in_window(window_start, window_end)
    sentences = []

    # DNS analysis
    if not dns_df.empty:
        n_queries = len(dns_df)
        n_unique_domains = dns_df["query_name"].nunique()
        nxdomain_count = (dns_df["response_code"] == "NXDOMAIN").sum()
        internal_mask = dns_df["query_name"].str.contains(r"\.(corp|internal)$", regex=True, na=False)
        internal_pct = internal_mask.sum() / n_queries * 100

        sentences.append(
            f"Device {device_id} issued {n_queries} DNS queries over {days} days ({n_queries / days:.0f}/day), "
            f"resolving {n_unique_domains} unique domain(s). {internal_pct:.0f}% internal, {nxdomain_count} NXDOMAIN failures."
        )

    # File system + registry from endpoint telemetry
    if not endpoint_df.empty:
        fs_df = endpoint_df[endpoint_df["event_type"] == "file_write"]
        reg_df = endpoint_df[endpoint_df["event_type"] == "registry_modify"]

        fs_count = len(fs_df)
        reg_count = len(reg_df)

        if fs_count > 0 or reg_count > 0:
            sentences.append(
                f"File system writes: {fs_count}, registry modifications: {reg_count}."
            )
            if reg_count > 0:
                reg_paths = reg_df["file_path"].nunique()
                sentences.append(f"Registry changes touched {reg_paths} unique key(s).")

    if not sentences:
        return f"No resource activity recorded for device {device_id} in this period."

    return " ".join(sentences)


def auth_signal(device_id: str, logs: dict, window_start: date, window_end: date) -> str:
    """Serialize authentication received: users logging into this device, success rates, timing."""
    auth_df = logs.get("auth", pd.DataFrame())
    if auth_df is None or auth_df.empty:
        return f"No authentication events recorded for device {device_id} in this period."

    # Filter by device_id (this device was the target of auth events)
    mask = (
        (auth_df["device_id"] == device_id)
        & (auth_df["timestamp"].dt.date >= window_start)
        & (auth_df["timestamp"].dt.date <= window_end)
    )
    df = auth_df[mask]

    if df.empty:
        return f"No authentication events recorded for device {device_id} in this period."

    days = _days_in_window(window_start, window_end)
    total = len(df)

    # Users who authenticated to this device
    n_users = df["user_id"].nunique()
    top_user = df["user_id"].mode().iloc[0] if not df["user_id"].mode().empty else "unknown"

    # Success rate
    success_rate = df["success"].sum() / total * 100
    failures = total - df["success"].sum()

    # Timing
    hours = df["timestamp"].dt.hour
    work_mask = (hours >= 8) & (hours < 18)
    work_pct = work_mask.sum() / total * 100

    # Auth methods
    methods = df["auth_method"].value_counts(normalize=True)
    method_parts = [f"{m} ({v:.0%})" for m, v in methods.head(3).items()]

    sentences = [
        f"Device {device_id} received {total} authentication attempts over {days} days ({total / days:.0f}/day).",
        f"{n_users} unique user(s) authenticated (primary: {top_user}). Success rate: {success_rate:.0f}% ({failures} failures).",
        f"Business-hours activity: {work_pct:.0f}%. Auth methods: {', '.join(method_parts)}.",
    ]
    return " ".join(sentences)


def config_signal(device_id: str, logs: dict, window_start: date, window_end: date) -> str:
    """Serialize config state: services changed, driver loads, software activity, compliance posture.

    Uses endpoint telemetry events of type service_change, driver_load, dll_injection.
    """
    df = _filter_device_window(logs.get("endpoint", pd.DataFrame()), device_id, window_start, window_end)

    if df.empty:
        return f"No configuration activity recorded for device {device_id} in this period."

    days = _days_in_window(window_start, window_end)

    # Filter to config-relevant event types
    config_types = ["service_change", "driver_load", "dll_injection"]
    config_df = df[df["event_type"].isin(config_types)]

    if config_df.empty:
        # Still report overall endpoint posture
        total = len(df)
        avg_risk = df["risk_score"].mean()
        max_risk = df["risk_score"].max()
        return (
            f"Device {device_id} had {total} endpoint events over {days} days but no configuration changes. "
            f"Average risk score: {avg_risk:.0f}, peak: {max_risk}."
        )

    n_config = len(config_df)
    config_breakdown = config_df["event_type"].value_counts()
    config_parts = [f"{et} ({ct})" for et, ct in config_breakdown.items()]

    # Risk in config events
    avg_config_risk = config_df["risk_score"].mean()
    high_risk_config = (config_df["risk_score"] >= 50).sum()

    # Processes involved in config changes
    config_processes = config_df["process_name"].nunique()

    sentences = [
        f"Device {device_id} had {n_config} configuration-related event(s) over {days} days: {', '.join(config_parts)}.",
        f"Average risk score for config changes: {avg_config_risk:.0f}, with {high_risk_config} high-risk event(s).",
        f"{config_processes} unique process(es) initiated configuration changes.",
    ]
    return " ".join(sentences)
