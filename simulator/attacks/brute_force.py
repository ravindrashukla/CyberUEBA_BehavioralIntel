"""Brute-force credential stuffing attack scenario (4-hour burst)."""

from datetime import date, datetime, timedelta
import numpy as np

from .base import AttackScenario

# External IPs simulating a botnet spread across foreign regions
_BOTNET_IPS = [
    ("185.234.72.11", "Russia"),
    ("185.234.72.44", "Russia"),
    ("103.25.18.92", "China"),
    ("103.25.18.105", "China"),
    ("103.77.240.33", "China"),
    ("177.54.12.8", "Brazil"),
    ("177.54.12.19", "Brazil"),
    ("185.156.73.60", "Russia"),
    ("45.227.254.11", "Brazil"),
    ("103.136.42.77", "China"),
]

_FAILURE_REASONS = ["invalid_password", "account_locked"]


class BruteForceAttack(AttackScenario):
    """Fast credential stuffing from external botnet.

    Duration: ~4 hours on a single day.
    50 target users receive 20-50 failed logins each from 5-10 external IPs.
    2-3 users with weak passwords eventually succeed, leading to abnormal access.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.duration_hours = config.get("duration_hours", 4)
        target = config.get("target_users", 50)
        if isinstance(target, int):
            self.target_users = [f"USR-{i:03d}" for i in range(300, 300 + target)]
        else:
            self.target_users = target
        self.compromised_users = config.get("compromised_users", ["USR-302", "USR-317", "USR-341"])
        self._start_date = (
            self.start if isinstance(self.start, date) else datetime.fromisoformat(self.start).date()
        )

    def is_active(self, current_date: date) -> bool:
        return current_date == self._start_date

    def modify_auth_events(
        self, user_id: str, events: list[dict], current_date: date, rng
    ) -> list[dict]:
        if not self.is_active(current_date):
            return events
        if user_id not in self.target_users:
            return events
        # Existing legitimate events remain unchanged
        return events

    def modify_network_flows(
        self, device_id: str, flows: list[dict], current_date: date, rng
    ) -> list[dict]:
        # Brute force is auth-layer; no network flow modification needed
        return flows

    def inject_events(self, current_date: date, rng) -> dict[str, list[dict]]:
        if not self.is_active(current_date):
            return {}

        auth_events = []
        network_events = []

        # Pick 5-10 IPs from botnet pool for this campaign
        num_ips = rng.integers(5, 11)
        campaign_ips = [_BOTNET_IPS[i] for i in rng.choice(len(_BOTNET_IPS), size=num_ips, replace=False)]

        # Attack window: random 4-hour block during the day
        start_hour = rng.integers(1, 20)  # avoid midnight wrap complications
        window_start = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=int(start_hour))
        window_end = window_start + timedelta(hours=self.duration_hours)

        for user_id in self.target_users:
            num_attempts = rng.integers(20, 51)
            # Spread attempts across the window
            attempt_offsets = np.sort(rng.uniform(0, self.duration_hours * 3600, size=num_attempts))

            for offset_sec in attempt_offsets:
                ts = window_start + timedelta(seconds=float(offset_sec))
                ip, country = campaign_ips[rng.integers(0, len(campaign_ips))]

                event = {
                    "timestamp": ts.isoformat(),
                    "user_id": user_id,
                    "event_type": "auth_failure",
                    "source_ip": ip,
                    "geo_country": country,
                    "auth_method": "password",
                    "failure_reason": rng.choice(_FAILURE_REASONS),
                    "attack_id": self.id,
                }
                auth_events.append(event)

        # Compromised users: successful login + abnormal access afterward
        for user_id in self.compromised_users:
            # Success happens in last quarter of attack window
            success_offset = rng.uniform(
                self.duration_hours * 3600 * 0.75,
                self.duration_hours * 3600,
            )
            ts = window_start + timedelta(seconds=float(success_offset))
            ip, country = campaign_ips[rng.integers(0, len(campaign_ips))]

            auth_events.append({
                "timestamp": ts.isoformat(),
                "user_id": user_id,
                "event_type": "auth_success",
                "source_ip": ip,
                "geo_country": country,
                "auth_method": "password",
                "failure_reason": None,
                "attack_id": self.id,
                "label": "compromised_credential",
            })

            # Post-compromise: abnormal system access within next 30-90 min
            num_access = rng.integers(3, 8)
            for i in range(num_access):
                access_offset = rng.uniform(60, 5400)  # 1-90 minutes after success
                access_ts = ts + timedelta(seconds=float(access_offset))
                auth_events.append({
                    "timestamp": access_ts.isoformat(),
                    "user_id": user_id,
                    "event_type": "resource_access",
                    "source_ip": ip,
                    "geo_country": country,
                    "resource": rng.choice([
                        "/admin/config", "/hr/payroll", "/finance/reports",
                        "/engineering/source", "/ops/credentials",
                    ]),
                    "attack_id": self.id,
                    "label": "post_compromise_lateral",
                })

            # Small network flows from compromised IP
            for _ in range(rng.integers(2, 5)):
                flow_ts = ts + timedelta(seconds=float(rng.uniform(120, 3600)))
                network_events.append({
                    "timestamp": flow_ts.isoformat(),
                    "src_ip": ip,
                    "dst_ip": f"10.0.{rng.integers(1,255)}.{rng.integers(1,255)}",
                    "dst_port": int(rng.choice([22, 3389, 445, 5985])),
                    "bytes_out": int(rng.integers(500, 5000)),
                    "bytes_in": int(rng.integers(100, 2000)),
                    "protocol": "tcp",
                    "attack_id": self.id,
                })

        result = {"auth": auth_events}
        if network_events:
            result["network"] = network_events
        return result

    @property
    def mitre_techniques(self) -> list[str]:
        return ["T1110", "T1078"]

    @property
    def involved_entities(self) -> dict[str, list[str]]:
        return {
            "users": list(self.target_users),
            "compromised_users": list(self.compromised_users),
            "ips": [ip for ip, _ in _BOTNET_IPS],
        }
