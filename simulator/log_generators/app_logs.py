"""Application event log generator for UEBA synthetic data."""

import datetime
import numpy as np

from simulator.config import APP_EVENTS_PER_USER_DAY, WORK_HOURS


EVENT_TYPE_WEIGHTS = {
    "login": 0.15,
    "query": 0.30,
    "data_export": 0.10,
    "config_change": 0.05,
    "api_call": 0.25,
    "error": 0.10,
    "permission_request": 0.05,
}

EVENT_TYPES = list(EVENT_TYPE_WEIGHTS.keys())
EVENT_PROBS = list(EVENT_TYPE_WEIGHTS.values())

RESPONSE_CODES = [200, 201, 400, 403, 500]
RESPONSE_CODE_WEIGHTS = [0.55, 0.20, 0.10, 0.08, 0.07]

ACTION_DETAILS = {
    "login": ["sso_login", "password_login", "mfa_login", "api_key_auth"],
    "query": ["select_records", "search_index", "filter_report", "aggregate_metrics", "lookup_entity"],
    "data_export": ["csv_export", "pdf_report", "bulk_download", "api_extract", "scheduled_dump"],
    "config_change": ["update_setting", "modify_policy", "change_threshold", "toggle_feature"],
    "api_call": ["rest_get", "rest_post", "rest_put", "rest_delete", "graphql_query"],
    "error": ["timeout", "validation_error", "resource_not_found", "rate_limited", "internal_error"],
    "permission_request": ["request_read", "request_write", "request_admin", "request_api_scope"],
}

ROLE_APP_COUNT = {
    "IT Admin": (5, 8),
    "Network Engineer": (4, 7),
    "SysAdmin": (5, 8),
    "DBA": (4, 7),
    "Security Analyst": (5, 8),
    "SOC Operator": (4, 7),
    "Software Engineer": (4, 7),
    "Senior Engineer": (4, 7),
    "Staff Engineer": (5, 8),
    "DevOps Engineer": (5, 8),
    "SRE": (5, 8),
    "Cloud Architect": (5, 8),
    "Data Scientist": (4, 7),
    "ML Engineer": (4, 7),
}
DEFAULT_APP_COUNT = (3, 5)


def _work_hour_timestamp(current_date, rng, work_pct=0.90):
    """Generate timestamp biased toward work hours (90/10 split)."""
    work_start, work_end = WORK_HOURS
    if rng.random() < work_pct:
        hour = rng.integers(work_start, work_end)
    else:
        hour = rng.choice(list(range(0, work_start)) + list(range(work_end, 24)))
    minute = rng.integers(0, 60)
    second = rng.integers(0, 60)
    return datetime.datetime.combine(current_date, datetime.time(int(hour), int(minute), int(second)))


def _generate_ip(rng):
    """Generate a random internal IP address."""
    return f"10.{rng.integers(1, 255)}.{rng.integers(1, 255)}.{rng.integers(1, 255)}"


def generate_app_events(users_df, applications_df, current_date, rng) -> list[dict]:
    """Generate application usage events for all users on a given date.

    Args:
        users_df: DataFrame with columns [user_id, role, ...]
        applications_df: DataFrame with columns [app_id, app_name, app_type, ...]
        current_date: date object for event generation
        rng: numpy random Generator for reproducibility

    Returns:
        List of event dicts.
    """
    events = []
    all_app_ids = applications_df["app_id"].values

    for _, user in users_df.iterrows():
        user_id = user["user_id"]
        role = user["role"]

        # Determine how many apps this user accesses
        lo, hi = ROLE_APP_COUNT.get(role, DEFAULT_APP_COUNT)
        n_apps = rng.integers(lo, hi + 1)
        n_apps = min(n_apps, len(all_app_ids))
        user_apps = rng.choice(all_app_ids, size=n_apps, replace=False)

        # Number of events per user per day (Poisson around config mean)
        n_events = rng.poisson(APP_EVENTS_PER_USER_DAY)

        source_ip = _generate_ip(rng)

        for _ in range(n_events):
            ts = _work_hour_timestamp(current_date, rng)
            event_type = rng.choice(EVENT_TYPES, p=EVENT_PROBS)
            app_id = rng.choice(user_apps)
            action_detail = rng.choice(ACTION_DETAILS[event_type])
            response_code = int(rng.choice(RESPONSE_CODES, p=RESPONSE_CODE_WEIGHTS))

            # Data volume varies by event type
            if event_type == "data_export":
                data_volume_bytes = int(rng.integers(100_000, 50_000_000))
            elif event_type in ("query", "api_call"):
                data_volume_bytes = int(rng.integers(500, 500_000))
            elif event_type == "login":
                data_volume_bytes = int(rng.integers(200, 2_000))
            else:
                data_volume_bytes = int(rng.integers(100, 50_000))

            # Duration varies by event type
            if event_type == "query":
                duration_ms = int(rng.integers(50, 5_000))
            elif event_type == "data_export":
                duration_ms = int(rng.integers(1_000, 30_000))
            elif event_type == "api_call":
                duration_ms = int(rng.integers(20, 3_000))
            elif event_type == "error":
                duration_ms = int(rng.integers(5_000, 60_000))
            else:
                duration_ms = int(rng.integers(100, 2_000))

            events.append({
                "timestamp": ts,
                "user_id": user_id,
                "app_id": str(app_id),
                "event_type": event_type,
                "action_detail": action_detail,
                "data_volume_bytes": data_volume_bytes,
                "source_ip": source_ip,
                "response_code": response_code,
                "duration_ms": duration_ms,
            })

    events.sort(key=lambda e: e["timestamp"])
    return events
