"""Behavioral signal serialization for application entities.

Each function computes stats from log DataFrames filtered by app_id and time window,
then serializes the findings as 3-5 sentence English prose for embedding.
"""

from datetime import datetime

import pandas as pd


def _app_events(app_id: str, logs: dict, window_start, window_end) -> pd.DataFrame:
    """Filter application events for the given app within the time window."""
    app = logs.get("app")
    if app is None or app.empty:
        return pd.DataFrame()
    mask = (
        (app["app_id"] == app_id)
        & (app["timestamp"] >= window_start)
        & (app["timestamp"] <= window_end)
    )
    return app.loc[mask]


def access_signal(app_id: str, logs: dict, window_start, window_end) -> str:
    """Access patterns: unique users, login frequency, geographic spread, new users."""
    events = _app_events(app_id, logs, window_start, window_end)
    if events.empty:
        return f"No access activity recorded for application {app_id} in this period."

    unique_users = events["user_id"].nunique()
    logins = events[events["event_type"] == "login"]
    login_count = len(logins)

    # Geographic spread via auth logs cross-reference
    auth = logs.get("auth")
    geo_locations = set()
    if auth is not None and not auth.empty:
        app_users = events["user_id"].unique()
        auth_window = auth[
            (auth["timestamp"] >= window_start)
            & (auth["timestamp"] <= window_end)
            & (auth["user_id"].isin(app_users))
        ]
        geo_locations = set(auth_window["geo_location"].unique())
    geo_count = len(geo_locations)

    # New users: users who appear only in the second half of the window
    midpoint = window_start + (window_end - window_start) / 2
    first_half_users = set(events.loc[events["timestamp"] < midpoint, "user_id"].unique())
    second_half_users = set(events.loc[events["timestamp"] >= midpoint, "user_id"].unique())
    new_users = second_half_users - first_half_users
    n_new = len(new_users)

    return (
        f"Application {app_id} was accessed by {unique_users} unique users with "
        f"{login_count:,} login events during this period. "
        f"Users connected from {geo_count} distinct geographic locations. "
        f"{n_new} users appeared for the first time in the latter half of the window, "
        f"suggesting {'active onboarding' if n_new > unique_users * 0.2 else 'stable user base'}."
    )


def queries_signal(app_id: str, logs: dict, window_start, window_end) -> str:
    """Query patterns: event types, data volumes queried, API call frequency."""
    events = _app_events(app_id, logs, window_start, window_end)
    if events.empty:
        return f"No query activity recorded for application {app_id} in this period."

    total_events = len(events)
    type_counts = events["event_type"].value_counts()

    # Data volume
    total_volume = int(events["data_volume_bytes"].sum())
    avg_volume = int(events["data_volume_bytes"].mean())

    # API calls specifically
    api_calls = events[events["event_type"] == "api_call"]
    n_api = len(api_calls)
    queries = events[events["event_type"] == "query"]
    n_queries = len(queries)

    # Top event types
    top_types = type_counts.head(3)
    type_summary = ", ".join(f"{t} ({c:,})" for t, c in top_types.items())

    def _format_bytes(n: int) -> str:
        if n >= 1_073_741_824:
            return f"{n / 1_073_741_824:.1f} GB"
        if n >= 1_048_576:
            return f"{n / 1_048_576:.1f} MB"
        if n >= 1024:
            return f"{n / 1024:.1f} KB"
        return f"{n} bytes"

    return (
        f"Application {app_id} processed {total_events:,} events; top types: {type_summary}. "
        f"Total data volume was {_format_bytes(total_volume)} with an average of "
        f"{_format_bytes(avg_volume)} per event. "
        f"API calls accounted for {n_api:,} events and data queries for {n_queries:,}, "
        f"indicating {'API-heavy' if n_api > n_queries else 'query-heavy'} usage patterns."
    )


def errors_signal(app_id: str, logs: dict, window_start, window_end) -> str:
    """Error patterns: error rate, 4xx vs 5xx, permission denials, unusual patterns."""
    events = _app_events(app_id, logs, window_start, window_end)
    if events.empty:
        return f"No error data recorded for application {app_id} in this period."

    total = len(events)

    # Error events by type
    error_events = events[events["event_type"] == "error"]
    n_errors = len(error_events)
    error_rate = n_errors / total * 100

    # Response code analysis
    codes_4xx = events[(events["response_code"] >= 400) & (events["response_code"] < 500)]
    codes_5xx = events[events["response_code"] >= 500]
    n_4xx = len(codes_4xx)
    n_5xx = len(codes_5xx)

    # Permission denials (403)
    permission_denials = events[events["response_code"] == 403]
    n_denied = len(permission_denials)

    # Trend: error rate in first half vs second half
    midpoint = window_start + (window_end - window_start) / 2
    first_half = events[events["timestamp"] < midpoint]
    second_half = events[events["timestamp"] >= midpoint]
    first_error_rate = len(first_half[first_half["event_type"] == "error"]) / max(len(first_half), 1) * 100
    second_error_rate = len(second_half[second_half["event_type"] == "error"]) / max(len(second_half), 1) * 100

    trend = "increasing" if second_error_rate > first_error_rate * 1.2 else (
        "decreasing" if second_error_rate < first_error_rate * 0.8 else "stable"
    )

    return (
        f"Application {app_id} error rate is {error_rate:.1f}% ({n_errors:,} error events "
        f"out of {total:,} total). "
        f"Client errors (4xx): {n_4xx:,}, server errors (5xx): {n_5xx:,}, "
        f"with {n_denied:,} permission denials (403). "
        f"Error trend is {trend} across the window (first half: {first_error_rate:.1f}%, "
        f"second half: {second_error_rate:.1f}%)."
    )


def performance_signal(app_id: str, logs: dict, window_start, window_end) -> str:
    """Performance: response times, throughput, unusual latency spikes."""
    events = _app_events(app_id, logs, window_start, window_end)
    if events.empty:
        return f"No performance data recorded for application {app_id} in this period."

    # Duration statistics
    durations = events["duration_ms"]
    mean_ms = float(durations.mean())
    p50_ms = float(durations.median())
    p95_ms = float(durations.quantile(0.95))
    max_ms = float(durations.max())

    # Throughput: events per hour
    events_copy = events.copy()
    events_copy["hour"] = events_copy["timestamp"].dt.hour
    hourly_throughput = events_copy.groupby("hour").size()
    avg_throughput = float(hourly_throughput.mean())
    peak_throughput = int(hourly_throughput.max())

    # Latency spikes: events with duration > 3x median
    spike_threshold = p50_ms * 3
    spikes = events[events["duration_ms"] > spike_threshold]
    n_spikes = len(spikes)
    spike_pct = n_spikes / len(events) * 100

    return (
        f"Application {app_id} response times: mean {mean_ms:.0f}ms, median {p50_ms:.0f}ms, "
        f"p95 {p95_ms:.0f}ms, max {max_ms:.0f}ms. "
        f"Throughput averaged {avg_throughput:.0f} events/hour with a peak of {peak_throughput:,}. "
        f"{n_spikes:,} latency spikes ({spike_pct:.1f}%) exceeded 3x the median response time, "
        f"{'indicating intermittent performance degradation' if spike_pct > 5 else 'within normal operating parameters'}."
    )


def config_signal(app_id: str, logs: dict, window_start, window_end) -> str:
    """Configuration: config changes, permission requests, policy modifications."""
    events = _app_events(app_id, logs, window_start, window_end)
    if events.empty:
        return f"No configuration activity recorded for application {app_id} in this period."

    # Config changes
    config_changes = events[events["event_type"] == "config_change"]
    n_config = len(config_changes)

    # Permission requests
    perm_requests = events[events["event_type"] == "permission_request"]
    n_perm = len(perm_requests)

    # Users making config changes
    config_users = config_changes["user_id"].nunique() if not config_changes.empty else 0
    perm_users = perm_requests["user_id"].nunique() if not perm_requests.empty else 0

    # Action detail breakdown for config changes
    if not config_changes.empty:
        action_counts = config_changes["action_detail"].value_counts()
        top_actions = ", ".join(f"{a} ({c})" for a, c in action_counts.head(3).items())
    else:
        top_actions = "none"

    # Privilege operations cross-reference
    priv = logs.get("privilege")
    priv_changes = 0
    if priv is not None and not priv.empty:
        # Policy changes that might relate to this app
        priv_window = priv[
            (priv["timestamp"] >= window_start)
            & (priv["timestamp"] <= window_end)
            & (priv["operation"] == "policy_change")
        ]
        priv_changes = len(priv_window)

    return (
        f"Application {app_id} had {n_config} configuration changes by {config_users} users "
        f"and {n_perm} permission requests from {perm_users} users. "
        f"Top config actions: {top_actions}. "
        f"{priv_changes} related privilege-level policy modifications occurred in the same window, "
        f"{'suggesting elevated administrative activity' if n_config + n_perm > 10 else 'indicating routine maintenance levels'}."
    )
