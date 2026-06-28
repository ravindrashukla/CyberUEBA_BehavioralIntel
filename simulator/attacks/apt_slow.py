"""Slow APT scenario: C2 beacon + gradual data staging over 180 days."""

from datetime import date, datetime, timedelta
import string
import numpy as np

from .base import AttackScenario

# Sensitive directory hierarchy (progressively deeper = more sensitive)
_DIRECTORIES = [
    "/shared/docs/general",
    "/shared/docs/projects",
    "/engineering/repos",
    "/engineering/internal-tools",
    "/engineering/architecture",
    "/finance/budgets",
    "/hr/org-charts",
    "/security/policies",
    "/security/audit-logs",
    "/executive/strategy",
]


def _generate_dga_domain(rng, length=None):
    """Generate a realistic DGA-like domain (random consonant/vowel patterns)."""
    if length is None:
        length = rng.integers(8, 16)
    chars = []
    vowels = "aeiou"
    consonants = "bcdfghjklmnpqrstvwxyz"
    for i in range(length):
        if i % 3 == 1:
            chars.append(rng.choice(list(vowels)))
        else:
            chars.append(rng.choice(list(consonants)))
    tlds = [".com", ".net", ".org", ".info"]
    return "".join(chars) + rng.choice(tlds)


class APTSlowAttack(AttackScenario):
    """Slow APT with C2 beacon, DGA DNS, and gradual data staging.

    Duration: 180 days.
    Per-day deviation is intentionally tiny. Detection requires observing
    cumulative drift over weeks/months via behavioral trajectory analysis.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.duration_days = config.get("duration_days", 180)
        self.target_user = config.get("target_user", "USR-234")
        # Resolve device from entity data if available, fall back to config/default
        user_device_map = config.get("_user_device_map", {})
        self.target_device = config.get("target_device",
                                        user_device_map.get(self.target_user, "DEV-234"))
        self.c2_ip = config.get("c2_ip", "198.51.100.47")
        # Stealthy: 2-3 beacons per day (every 8-12 hours)
        self.beacon_interval_min = config.get("beacon_interval_min", 720)
        self.beacon_jitter_min = config.get("beacon_jitter_min", 90)
        default_interval = max(5, self.duration_days // 10)
        self.staging_interval_days = config.get("staging_interval_days", default_interval)
        self.staging_file_min = config.get("staging_file_min", 1)
        self.staging_file_max = config.get("staging_file_max", 4)
        self.dga_probability = config.get("dga_probability", 0.4)
        self._start_date = (
            self.start if isinstance(self.start, date) else datetime.fromisoformat(self.start).date()
        )
        self._end_date = self._start_date + timedelta(days=self.duration_days)

    def is_active(self, current_date: date) -> bool:
        return self._start_date <= current_date <= self._end_date

    def _days_elapsed(self, current_date: date) -> int:
        return (current_date - self._start_date).days

    def _sensitivity_level(self, current_date: date) -> int:
        """0-9 index into _DIRECTORIES based on progression through attack."""
        progress = self._days_elapsed(current_date) / self.duration_days
        return min(int(progress * len(_DIRECTORIES)), len(_DIRECTORIES) - 1)

    def modify_auth_events(
        self, user_id: str, events: list[dict], current_date: date, rng
    ) -> list[dict]:
        if not self.is_active(current_date):
            return events
        if user_id != self.target_user:
            return events

        days_in = self._days_elapsed(current_date)
        # One minor privilege escalation per month (days 30, 60, 90, 120, 150)
        escalation_interval = max(10, self.duration_days // 6)
        if days_in > 0 and days_in % escalation_interval == 0:
            escalation_ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(9, 17))
            )
            events.append({
                "timestamp": escalation_ts.isoformat(),
                "user_id": user_id,
                "event_type": "privilege_change",
                "source_ip": f"10.0.5.{rng.integers(10, 50)}",
                "new_role": f"level_{(days_in // 30) + 1}",
                "justification": rng.choice([
                    "project requirement", "manager approved",
                    "cross-team collaboration", "temporary access",
                ]),
                "attack_id": self.id,
                "label": "apt_privilege_escalation",
            })

        return events

    def modify_network_flows(
        self, device_id: str, flows: list[dict], current_date: date, rng
    ) -> list[dict]:
        if not self.is_active(current_date):
            return flows
        if device_id != self.target_device:
            return flows
        # C2 beacon flows are injected via inject_events; existing flows unchanged
        return flows

    def inject_events(self, current_date: date, rng) -> dict[str, list[dict]]:
        if not self.is_active(current_date):
            return {}

        network_events = []
        dns_events = []
        file_events = []

        days_in = self._days_elapsed(current_date)

        # --- C2 Beacon: ~2-3 beacons per day, skip ~25% of days ---
        end_of_day = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=24)
        if rng.random() < 0.25:
            beacon_time = end_of_day
        else:
            beacon_time = datetime.combine(current_date, datetime.min.time()) + timedelta(
                minutes=float(rng.uniform(0, self.beacon_interval_min))
            )

        while beacon_time < end_of_day:
            # Tiny packets — designed to blend with background noise
            bytes_out = int(rng.integers(100, 500))
            bytes_in = int(rng.integers(50, 300))

            network_events.append({
                "timestamp": beacon_time.isoformat(),
                "src_ip": f"10.0.5.34",  # target device internal IP
                "dst_ip": self.c2_ip,
                "dst_port": 443,
                "bytes_out": bytes_out,
                "bytes_in": bytes_in,
                "protocol": "tcp",
                "duration_ms": int(rng.integers(50, 500)),
                "device_id": self.target_device,
                "attack_id": self.id,
                "label": "c2_beacon",
            })

            # Next beacon with jitter
            interval = self.beacon_interval_min + rng.uniform(
                -self.beacon_jitter_min, self.beacon_jitter_min
            )
            beacon_time += timedelta(minutes=float(max(interval, 20)))

        # --- DGA DNS: 0-1 queries per day, mostly resolving (stealthy) ---
        if rng.random() < self.dga_probability:
            query_time = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(8, 18))
            )
            dns_events.append({
                "timestamp": query_time.isoformat(),
                "device_id": self.target_device,
                "query_domain": _generate_dga_domain(rng),
                "query_type": "A",
                "response": rng.choice([self.c2_ip, self.c2_ip, self.c2_ip, "NXDOMAIN"]),
                "attack_id": self.id,
                "label": "dga_dns",
            })

        # --- Data staging: every staging_interval_days ---
        if days_in > 0 and days_in % self.staging_interval_days == 0:
            sensitivity = self._sensitivity_level(current_date)
            # Access progressively more sensitive directories
            accessible_dirs = _DIRECTORIES[: sensitivity + 1]
            # Read 1-3 files (stealthy — fewer files, looks like normal browsing)
            num_files = rng.integers(self.staging_file_min, self.staging_file_max)
            staging_start = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(10, 16))
            )

            for i in range(num_files):
                # Bias toward more sensitive dirs as attack progresses
                weights = np.arange(1, len(accessible_dirs) + 1, dtype=float)
                weights /= weights.sum()
                dir_idx = rng.choice(len(accessible_dirs), p=weights)
                chosen_dir = accessible_dirs[dir_idx]

                file_ts = staging_start + timedelta(minutes=float(rng.uniform(0, 30)))
                filename = f"{''.join(rng.choice(list(string.ascii_lowercase), size=6))}.{''.join(rng.choice(['pdf', 'xlsx', 'docx', 'csv']))}"

                file_events.append({
                    "timestamp": file_ts.isoformat(),
                    "user_id": self.target_user,
                    "source_device_id": self.target_device,
                    "operation": "read",
                    "file_path": f"{chosen_dir}/{filename}",
                    "file_size_bytes": int(rng.integers(10_000, 500_000)),
                    "data_classification": "confidential",
                    "success": True,
                    "attack_id": self.id,
                    "label": "data_staging",
                    "sensitivity_tier": dir_idx,
                })

        result = {}
        if network_events:
            result["network"] = network_events
        if dns_events:
            result["dns"] = dns_events
        if file_events:
            result["file"] = file_events
        return result

    @property
    def mitre_techniques(self) -> list[str]:
        return ["T1071", "T1573", "T1074", "T1048"]

    @property
    def involved_entities(self) -> dict[str, list[str]]:
        return {
            "users": [self.target_user],
            "devices": [self.target_device],
            "ips": [self.c2_ip],
        }
