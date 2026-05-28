"""Authentication log event generator for UEBA synthetic data."""

import datetime
import numpy as np


def _work_hour_timestamp(current_date, rng, work_start=8, work_end=18, off_hours_pct=0.20):
    """Generate timestamp biased toward work hours."""
    off_hours = list(range(0, work_start)) + list(range(work_end, 24))
    if rng.random() < (1.0 - off_hours_pct) or not off_hours:
        hour = rng.integers(work_start, min(work_end, 24))
        minute = rng.integers(0, 60)
        second = rng.integers(0, 60)
    else:
        hour = rng.choice(off_hours)
        minute = rng.integers(0, 60)
        second = rng.integers(0, 60)
    return datetime.datetime.combine(current_date, datetime.time(int(hour), int(minute), int(second)))


def _pick_auth_method(rng):
    """Select auth method: password 40%, MFA 45%, SSO 10%, certificate 5%."""
    r = rng.random()
    if r < 0.40:
        return "password"
    elif r < 0.85:
        return "mfa"
    elif r < 0.95:
        return "sso"
    else:
        return "certificate"


def _pick_failure_reason(auth_method, rng):
    """Pick a realistic failure reason based on auth method."""
    reasons = {
        "password": ["invalid_password", "account_locked", "expired_password"],
        "mfa": ["mfa_timeout", "invalid_token", "device_not_enrolled"],
        "sso": ["token_expired", "idp_unavailable", "session_expired"],
        "certificate": ["cert_expired", "cert_revoked", "cn_mismatch"],
        "ssh_key": ["key_rejected", "key_expired", "host_key_mismatch"],
        "smart_card": ["card_not_present", "pin_locked", "card_expired"],
        "vpn": ["vpn_timeout", "tunnel_failed", "credential_expired"],
    }
    return rng.choice(reasons.get(auth_method, ["unknown_error"]))


def _generate_ip(base_subnet, rng):
    """Generate IP within a /16 subnet."""
    parts = base_subnet.split(".")
    return f"{parts[0]}.{parts[1]}.{rng.integers(1, 255)}.{rng.integers(1, 255)}"


def generate_auth_logs(users_df, devices_df, role_profiles, user_profiles, current_date, rng) -> list[dict]:
    """Generate authentication log events for all users on a given date.

    Args:
        users_df: DataFrame with columns [user_id, role, primary_device_id, primary_location, subnet]
        devices_df: DataFrame with columns [device_id, device_name, ip_address]
        role_profiles: dict mapping role -> {systems: list, work_start: int, work_end: int,
                       failure_rate: float, travel_pct: float}
        user_profiles: dict mapping user_id -> per-user behavioral profile dict
        current_date: date object for event generation
        rng: numpy random Generator for reproducibility

    Returns:
        List of event dicts.
    """
    events = []
    device_map = devices_df.set_index("device_id").to_dict("index")

    for _, user in users_df.iterrows():
        user_id = user["user_id"]
        role = user["role"]
        role_prof = role_profiles.get(role, {})
        profile = user_profiles.get(user_id, {})

        login_hours = role_prof.get("typical_login_hours", (8, 18))
        work_start = profile.get("work_start", login_hours[0])
        work_end = profile.get("work_end", login_hours[1])
        failure_rate = profile.get("failure_rate", 0.03)
        travel_pct = profile.get("travel_pct", 0.05)

        n_events = rng.poisson(max(1, int(12 * profile.get("activity_multiplier", 1.0))))

        for _ in range(n_events):
            off_pct = profile.get("off_hours_pct", 0.20)
            ts = _work_hour_timestamp(current_date, rng, work_start, work_end, off_hours_pct=off_pct)

            methods = profile.get("auth_methods", ["password", "mfa", "sso", "certificate"])
            weights = profile.get("auth_weights", None)
            if weights and len(weights) == len(methods):
                auth_method = rng.choice(methods, p=weights)
            else:
                auth_method = rng.choice(methods)
            success = rng.random() > failure_rate
            failure_reason = None if success else _pick_failure_reason(auth_method, rng)

            # Device selection: 90% primary device, 10% random assigned
            if rng.random() < 0.90:
                device_id = user["primary_device_id"]
            else:
                device_id = rng.choice(devices_df["device_id"].values)

            device_info = device_map.get(device_id, {})
            source_ip = device_info.get("ip_address", _generate_ip(user.get("subnet", "10.0"), rng))

            # Geographic location
            if rng.random() < (1.0 - travel_pct):
                geo_location = user["primary_location"]
            else:
                geo_location = rng.choice(["remote_vpn", "branch_office", "travel_hotel", "partner_site"])

            dest_systems = ["email", "intranet", "vpn", "fileserver", "erp", "crm", "dev_tools", "cloud_console"]
            dest_system = rng.choice(dest_systems[:role_prof.get("typical_systems_accessed", 4)])

            events.append({
                "timestamp": ts,
                "user_id": user_id,
                "device_id": device_id,
                "source_ip": source_ip,
                "dest_system": dest_system,
                "success": bool(success),
                "auth_method": auth_method,
                "failure_reason": failure_reason,
                "geo_location": geo_location,
            })

    events.sort(key=lambda e: e["timestamp"])
    return events
