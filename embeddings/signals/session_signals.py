"""Behavioral signal serialization for session entities (user x device x time).

Each function computes stats from log DataFrames filtered by both user_id AND device_id
within the time window, then serializes findings as 3-5 sentence English prose for embedding.
"""

from datetime import datetime

import pandas as pd


def _session_events(user_id: str, device_id: str, logs: dict, log_key: str,
                    window_start, window_end, user_col: str = "user_id",
                    device_col: str = "device_id") -> pd.DataFrame:
    """Filter events matching both user and device within the time window."""
    df = logs.get(log_key)
    if df is None or df.empty:
        return pd.DataFrame()
    mask = (
        (df[user_col] == user_id)
        & (df[device_col] == device_id)
        & (df["timestamp"] >= window_start)
        & (df["timestamp"] <= window_end)
    )
    return df.loc[mask]


def _all_user_device_events(user_id: str, device_id: str, logs: dict,
                            window_start, window_end) -> pd.DataFrame:
    """Gather all events across log types for this user+device pair."""
    frames = []

    # Auth logs
    auth = _session_events(user_id, device_id, logs, "auth", window_start, window_end)
    if not auth.empty:
        frames.append(auth[["timestamp"]].assign(source="auth"))

    # Endpoint events
    ep = _session_events(user_id, device_id, logs, "endpoint", window_start, window_end)
    if not ep.empty:
        frames.append(ep[["timestamp"]].assign(source="endpoint"))

    # File access events
    fa = _session_events(user_id, device_id, logs, "file_access", window_start, window_end,
                         device_col="source_device_id")
    if not fa.empty:
        frames.append(fa[["timestamp"]].assign(source="file_access"))

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("timestamp")


def activity_signal(session_id: str, user_id: str, device_id: str, logs: dict,
                    window_start, window_end) -> str:
    """Activity pattern: event count, duration, types of actions, intensity curve."""
    all_events = _all_user_device_events(user_id, device_id, logs, window_start, window_end)
    if all_events.empty:
        return (
            f"No activity recorded for session {session_id} "
            f"(user {user_id}, device {device_id}) in this period."
        )

    total_events = len(all_events)

    # Duration
    first_ts = all_events["timestamp"].min()
    last_ts = all_events["timestamp"].max()
    duration = last_ts - first_ts
    duration_minutes = max(duration.total_seconds() / 60, 1)

    # Source breakdown
    source_counts = all_events["source"].value_counts()
    source_summary = ", ".join(f"{s} ({c})" for s, c in source_counts.items())

    # Intensity: events per 15-min bucket
    all_events_copy = all_events.copy()
    all_events_copy["bucket"] = all_events_copy["timestamp"].dt.floor("15min")
    bucket_counts = all_events_copy.groupby("bucket").size()
    peak_intensity = int(bucket_counts.max())
    avg_intensity = float(bucket_counts.mean())

    return (
        f"Session {session_id} generated {total_events:,} events over "
        f"{duration_minutes:.0f} minutes spanning {source_counts.nunique()} activity types: "
        f"{source_summary}. "
        f"Peak intensity reached {peak_intensity} events per 15-minute window versus an "
        f"average of {avg_intensity:.1f}. "
        f"{'Bursty pattern with concentrated peaks' if peak_intensity > avg_intensity * 3 else 'Relatively steady activity distribution'}."
    )


def risk_accum_signal(session_id: str, user_id: str, device_id: str, logs: dict,
                      window_start, window_end) -> str:
    """Risk accumulation: risk scores over session, escalation pattern, high-risk events."""
    # Endpoint events carry risk_score
    ep = _session_events(user_id, device_id, logs, "endpoint", window_start, window_end)

    # Auth failures also contribute risk
    auth = _session_events(user_id, device_id, logs, "auth", window_start, window_end)
    auth_failures = auth[auth["success"] == False] if not auth.empty else pd.DataFrame()

    if ep.empty and auth_failures.empty:
        return (
            f"No risk-relevant events recorded for session {session_id} "
            f"(user {user_id}, device {device_id}) in this period."
        )

    parts = []

    if not ep.empty:
        scores = ep["risk_score"]
        mean_risk = float(scores.mean())
        max_risk = int(scores.max())
        high_risk_events = ep[ep["risk_score"] >= 50]
        n_high = len(high_risk_events)

        # Escalation: compare first-half vs second-half mean risk
        midpoint = window_start + (window_end - window_start) / 2
        first_scores = ep.loc[ep["timestamp"] < midpoint, "risk_score"]
        second_scores = ep.loc[ep["timestamp"] >= midpoint, "risk_score"]
        first_mean = float(first_scores.mean()) if not first_scores.empty else 0
        second_mean = float(second_scores.mean()) if not second_scores.empty else 0

        if second_mean > first_mean * 1.3:
            escalation = "escalating"
        elif second_mean < first_mean * 0.7:
            escalation = "de-escalating"
        else:
            escalation = "stable"

        parts.append(
            f"Endpoint risk scores: mean {mean_risk:.1f}, max {max_risk}, "
            f"with {n_high} high-risk events (score >= 50). "
            f"Risk trajectory is {escalation} (first half avg: {first_mean:.1f}, "
            f"second half avg: {second_mean:.1f})"
        )

    n_auth_fail = len(auth_failures)
    if n_auth_fail > 0:
        parts.append(f"{n_auth_fail} authentication failures contributed additional risk")

    return (
        f"Session {session_id} risk profile: {'. '.join(parts)}."
    )


def data_movement_signal(session_id: str, user_id: str, device_id: str, logs: dict,
                         window_start, window_end) -> str:
    """Data movement: files accessed, data exported, volume transferred, classifications."""
    fa = _session_events(user_id, device_id, logs, "file_access", window_start, window_end,
                         device_col="source_device_id")
    if fa.empty:
        return (
            f"No data movement recorded for session {session_id} "
            f"(user {user_id}, device {device_id}) in this period."
        )

    total_files = len(fa)
    total_bytes = int(fa["file_size_bytes"].sum())

    # Operation breakdown
    op_counts = fa["operation"].value_counts()
    reads = op_counts.get("read", 0)
    writes = op_counts.get("write", 0)
    copies = op_counts.get("copy", 0)
    deletes = op_counts.get("delete", 0)

    # Classification breakdown
    class_counts = fa["data_classification"].value_counts()
    sensitive = class_counts.get("confidential", 0) + class_counts.get("restricted", 0)
    sensitive_pct = sensitive / total_files * 100

    # Exports: copies + moves (potential exfiltration indicators)
    exports = copies + op_counts.get("move", 0)

    def _format_bytes(n: int) -> str:
        if n >= 1_073_741_824:
            return f"{n / 1_073_741_824:.1f} GB"
        if n >= 1_048_576:
            return f"{n / 1_048_576:.1f} MB"
        if n >= 1024:
            return f"{n / 1024:.1f} KB"
        return f"{n} bytes"

    return (
        f"Session {session_id} accessed {total_files:,} files totaling {_format_bytes(total_bytes)}: "
        f"{reads} reads, {writes} writes, {exports} copies/moves, {deletes} deletes. "
        f"{sensitive_pct:.1f}% of accessed files were classified confidential or restricted. "
        f"{'Elevated data export activity warrants review' if exports > total_files * 0.2 else 'Data movement within normal parameters'}."
    )


def lateral_signal(session_id: str, user_id: str, device_id: str, logs: dict,
                   window_start, window_end) -> str:
    """Lateral indicators: new systems accessed, auth to other devices, cross-segment access."""
    auth = logs.get("auth")
    if auth is None or auth.empty:
        return (
            f"No lateral movement data recorded for session {session_id} "
            f"(user {user_id}, device {device_id}) in this period."
        )

    # All auth events for this user in the window
    user_auth = auth[
        (auth["user_id"] == user_id)
        & (auth["timestamp"] >= window_start)
        & (auth["timestamp"] <= window_end)
    ]
    if user_auth.empty:
        return (
            f"No authentication events for session {session_id} "
            f"(user {user_id}, device {device_id}) in this period."
        )

    # Auth to OTHER devices (not the session's primary device)
    other_device_auth = user_auth[user_auth["device_id"] != device_id]
    n_other_devices = other_device_auth["device_id"].nunique()
    n_other_auths = len(other_device_auth)

    # Unique destination systems
    dest_systems = user_auth["dest_system"].nunique()

    # Cross-segment access: check if other devices are in different segments
    network = logs.get("network")
    cross_segment = 0
    if network is not None and not network.empty and not other_device_auth.empty:
        # Get the session device's segment
        device_seg = network.loc[network["device_id"] == device_id, "segment_id"]
        home_segment = device_seg.iloc[0] if not device_seg.empty else None

        if home_segment is not None:
            other_dev_ids = other_device_auth["device_id"].unique()
            other_segs = network.loc[
                network["device_id"].isin(other_dev_ids), "segment_id"
            ].unique()
            cross_segment = sum(1 for s in other_segs if s != home_segment)

    # New systems: systems accessed only in second half
    midpoint = window_start + (window_end - window_start) / 2
    first_systems = set(user_auth.loc[user_auth["timestamp"] < midpoint, "dest_system"].unique())
    second_systems = set(user_auth.loc[user_auth["timestamp"] >= midpoint, "dest_system"].unique())
    new_systems = second_systems - first_systems
    n_new = len(new_systems)

    return (
        f"Session {session_id} lateral indicators: user authenticated to {n_other_devices} "
        f"other devices ({n_other_auths} events) beyond the primary device, "
        f"accessing {dest_systems} distinct systems. "
        f"{cross_segment} cross-segment authentications detected. "
        f"{n_new} new systems were accessed for the first time in the latter half, "
        f"{'suggesting active exploration or lateral movement' if n_new > 3 else 'consistent with normal workflow'}."
    )


def temporal_signal(session_id: str, user_id: str, device_id: str, logs: dict,
                    window_start, window_end) -> str:
    """Temporal pattern: time-of-day, duration vs normal, gaps, acceleration."""
    all_events = _all_user_device_events(user_id, device_id, logs, window_start, window_end)
    if all_events.empty:
        return (
            f"No temporal data recorded for session {session_id} "
            f"(user {user_id}, device {device_id}) in this period."
        )

    timestamps = all_events["timestamp"].sort_values()

    # Time of day distribution
    hours = timestamps.dt.hour
    work_hours_events = ((hours >= 8) & (hours < 18)).sum()
    off_hours_events = len(hours) - work_hours_events
    work_pct = work_hours_events / len(hours) * 100

    # Session span
    first_ts = timestamps.iloc[0]
    last_ts = timestamps.iloc[-1]
    span_minutes = max((last_ts - first_ts).total_seconds() / 60, 1)

    # Gaps: time between consecutive events
    if len(timestamps) > 1:
        diffs = timestamps.diff().dt.total_seconds().dropna()
        max_gap_sec = float(diffs.max())
        median_gap_sec = float(diffs.median())
        # Acceleration: compare inter-event gaps in first half vs second half
        mid_idx = len(diffs) // 2
        first_half_gap = float(diffs.iloc[:mid_idx].median()) if mid_idx > 0 else median_gap_sec
        second_half_gap = float(diffs.iloc[mid_idx:].median()) if mid_idx > 0 else median_gap_sec

        if second_half_gap < first_half_gap * 0.7:
            pace = "accelerating (events becoming more frequent)"
        elif second_half_gap > first_half_gap * 1.3:
            pace = "decelerating (events becoming less frequent)"
        else:
            pace = "steady pace throughout"
    else:
        max_gap_sec = 0
        median_gap_sec = 0
        pace = "single event, no pace pattern"

    # Peak hour
    peak_hour = int(hours.mode().iloc[0]) if not hours.empty else 0

    return (
        f"Session {session_id} temporal profile: {work_pct:.0f}% of activity during business "
        f"hours (08:00-18:00), peak at hour {peak_hour}, spanning {span_minutes:.0f} minutes total. "
        f"Median inter-event gap: {median_gap_sec:.0f}s, max gap: {max_gap_sec:.0f}s. "
        f"Activity pace is {pace}."
    )
