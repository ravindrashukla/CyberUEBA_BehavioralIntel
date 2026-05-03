"""User behavioral signal serializers for embedding generation.

Each function takes a user_id, a dict of log DataFrames, and a time window,
then returns a natural language prose string describing that user's behavior
in the given window. These text strings are subsequently embedded via
OpenAI text-embedding-3-small to produce 1536-d behavioral vectors.
"""

from datetime import date

import pandas as pd


def _filter_user_window(df: pd.DataFrame, user_id: str, window_start: date, window_end: date, user_col: str = "user_id") -> pd.DataFrame:
    """Filter a DataFrame to a specific user and time window."""
    if df is None or df.empty:
        return pd.DataFrame()
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    mask = (
        (df[user_col] == user_id)
        & (df["timestamp"].dt.date >= window_start)
        & (df["timestamp"].dt.date <= window_end)
    )
    return df[mask]


def _days_in_window(window_start: date, window_end: date) -> int:
    return max((window_end - window_start).days, 1)


def auth_signal(user_id: str, logs: dict, window_start: date, window_end: date) -> str:
    """Serialize authentication behavior as prose.

    Analyzes: login frequency, success/failure ratio, hours of activity,
    geographic spread, auth methods used, devices accessed.
    """
    df = _filter_user_window(logs.get("auth", pd.DataFrame()), user_id, window_start, window_end)

    if df.empty:
        return f"No authentication activity recorded for {user_id} in this period."

    days = _days_in_window(window_start, window_end)
    total = len(df)
    successes = df["success"].sum()
    success_rate = successes / total * 100

    # Hour distribution
    hours = df["timestamp"].dt.hour
    work_mask = (hours >= 8) & (hours < 18)
    work_pct = work_mask.sum() / total * 100

    # Geographic spread
    locations = df["geo_location"].nunique()
    top_location = df["geo_location"].mode().iloc[0] if not df["geo_location"].mode().empty else "unknown"

    # Auth methods
    methods = df["auth_method"].value_counts(normalize=True)
    method_parts = [f"{m} ({v:.0%})" for m, v in methods.head(3).items()]

    # Devices
    n_devices = df["device_id"].nunique()
    top_device = df["device_id"].mode().iloc[0] if not df["device_id"].mode().empty else "unknown"

    # Dest systems
    n_systems = df["dest_system"].nunique()

    sentences = [
        f"User {user_id} authenticated {total} times over {days} days ({total / days:.0f}/day).",
        f"{success_rate:.0f}% success rate with {total - successes} failures.",
        f"Primary hours 08:00-18:00 ({work_pct:.0f}%), off-hours ({100 - work_pct:.0f}%).",
        f"Accessed from {locations} location(s) (primary: {top_location}). Used {', '.join(method_parts)}.",
        f"Logged into {n_devices} unique device(s) (primary: {top_device}), targeting {n_systems} system(s).",
    ]
    return " ".join(sentences)


def privilege_signal(user_id: str, logs: dict, window_start: date, window_end: date) -> str:
    """Serialize privilege usage: role grants, access elevations, sudo, policy changes.

    Checks both actor and target roles for this user.
    """
    priv_df = logs.get("privilege", pd.DataFrame())
    if priv_df is None or priv_df.empty:
        return f"No privilege operations recorded for {user_id} in this period."

    # User can be actor or target
    mask_time = (
        (priv_df["timestamp"].dt.date >= window_start)
        & (priv_df["timestamp"].dt.date <= window_end)
    )
    actor_df = priv_df[mask_time & (priv_df["actor_user_id"] == user_id)]
    target_df = priv_df[mask_time & (priv_df["target_user_id"] == user_id)]

    if actor_df.empty and target_df.empty:
        return f"No privilege operations recorded for {user_id} in this period."

    days = _days_in_window(window_start, window_end)
    sentences = []

    if not actor_df.empty:
        n_acted = len(actor_df)
        ops = actor_df["operation"].value_counts()
        op_summary = ", ".join(f"{op} ({ct})" for op, ct in ops.head(4).items())
        approved_pct = actor_df["approved"].sum() / n_acted * 100
        sentences.append(
            f"{user_id} performed {n_acted} privileged operation(s) over {days} days: {op_summary}."
        )
        sentences.append(f"Approval rate: {approved_pct:.0f}%.")

    if not target_df.empty:
        n_targeted = len(target_df)
        target_ops = target_df["operation"].value_counts()
        target_summary = ", ".join(f"{op} ({ct})" for op, ct in target_ops.head(3).items())
        sentences.append(
            f"Was target of {n_targeted} operation(s): {target_summary}."
        )

    # Resources touched
    all_ops = pd.concat([actor_df, target_df])
    resources = all_ops["resource"].nunique()
    sentences.append(f"Involved {resources} distinct resource(s).")

    return " ".join(sentences)


def data_access_signal(user_id: str, logs: dict, window_start: date, window_end: date) -> str:
    """Serialize file/data access: volume, classifications touched, operations, scope."""
    df = _filter_user_window(logs.get("file_access", pd.DataFrame()), user_id, window_start, window_end)

    if df.empty:
        return f"No file/data access recorded for {user_id} in this period."

    days = _days_in_window(window_start, window_end)
    total = len(df)

    # Operations breakdown
    ops = df["operation"].value_counts()
    op_parts = [f"{op} ({ct})" for op, ct in ops.head(4).items()]

    # Classifications accessed
    classifications = df["data_classification"].value_counts()
    class_parts = [f"{c} ({ct})" for c, ct in classifications.items()]

    # Volume
    total_bytes = df["file_size_bytes"].sum()
    if total_bytes > 1_073_741_824:
        vol_str = f"{total_bytes / 1_073_741_824:.1f} GB"
    elif total_bytes > 1_048_576:
        vol_str = f"{total_bytes / 1_048_576:.0f} MB"
    else:
        vol_str = f"{total_bytes / 1024:.0f} KB"

    # Success rate
    success_rate = df["success"].sum() / total * 100

    # Unique paths
    n_paths = df["file_path"].nunique()

    sentences = [
        f"User {user_id} performed {total} file operations over {days} days ({total / days:.0f}/day).",
        f"Operations: {', '.join(op_parts)}.",
        f"Data classifications touched: {', '.join(class_parts)}.",
        f"Total volume: {vol_str} across {n_paths} unique path(s). Success rate: {success_rate:.0f}%.",
    ]
    return " ".join(sentences)


def network_signal(user_id: str, logs: dict, window_start: date, window_end: date) -> str:
    """Serialize network behavior: traffic volume, destinations, protocols, anomalous flows.

    Uses the network flow data keyed by user's primary device(s) from the auth logs.
    """
    # Network flows are per-device; correlate via auth logs to find user's devices
    auth_df = logs.get("auth", pd.DataFrame())
    net_df = logs.get("network", pd.DataFrame())

    if net_df is None or net_df.empty:
        return f"No network activity recorded for {user_id} in this period."

    # Find devices this user used in the window
    if auth_df is not None and not auth_df.empty:
        user_auth = _filter_user_window(auth_df, user_id, window_start, window_end)
        user_devices = set(user_auth["device_id"].unique()) if not user_auth.empty else set()
    else:
        user_devices = set()

    if not user_devices:
        return f"No network activity recorded for {user_id} in this period."

    # Filter network flows for user's devices in window
    mask = (
        (net_df["device_id"].isin(user_devices))
        & (net_df["timestamp"].dt.date >= window_start)
        & (net_df["timestamp"].dt.date <= window_end)
    )
    df = net_df[mask]

    if df.empty:
        return f"No network activity recorded for {user_id} in this period."

    days = _days_in_window(window_start, window_end)
    total = len(df)

    # Traffic volume
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

    # Destinations (external vs internal)
    external_mask = ~df["dst_ip"].str.startswith("10.")
    external_pct = external_mask.sum() / total * 100
    n_unique_dst = df["dst_ip"].nunique()

    # Top ports
    top_ports = df["dst_port"].value_counts().head(3)
    port_parts = [f"{port} ({ct})" for port, ct in top_ports.items()]

    sentences = [
        f"User {user_id} generated {total} network flows over {days} days ({total / days:.0f}/day).",
        f"Total traffic: {vol_str}. Protocols: {', '.join(proto_parts)}.",
        f"{n_unique_dst} unique destinations; {external_pct:.0f}% external traffic.",
        f"Top destination ports: {', '.join(port_parts)}.",
    ]
    return " ".join(sentences)


def communication_signal(user_id: str, logs: dict, window_start: date, window_end: date) -> str:
    """Serialize app/communication patterns: apps used, event types, data export volume, errors."""
    df = _filter_user_window(logs.get("app", pd.DataFrame()), user_id, window_start, window_end)

    if df.empty:
        return f"No application activity recorded for {user_id} in this period."

    days = _days_in_window(window_start, window_end)
    total = len(df)

    # Apps accessed
    n_apps = df["app_id"].nunique()

    # Event type distribution
    event_types = df["event_type"].value_counts()
    event_parts = [f"{et} ({ct})" for et, ct in event_types.head(4).items()]

    # Data export volume
    export_df = df[df["event_type"] == "data_export"]
    export_vol = export_df["data_volume_bytes"].sum() if not export_df.empty else 0
    if export_vol > 1_048_576:
        export_str = f"{export_vol / 1_048_576:.1f} MB exported"
    elif export_vol > 1024:
        export_str = f"{export_vol / 1024:.0f} KB exported"
    else:
        export_str = "no data exports"

    # Error rate
    error_count = (df["response_code"] >= 400).sum()
    error_pct = error_count / total * 100

    sentences = [
        f"User {user_id} generated {total} application events over {days} days ({total / days:.0f}/day).",
        f"Accessed {n_apps} unique application(s). Event types: {', '.join(event_parts)}.",
        f"Data movement: {export_str}.",
        f"Error rate: {error_pct:.0f}% ({error_count} events with HTTP 4xx/5xx).",
    ]
    return " ".join(sentences)
