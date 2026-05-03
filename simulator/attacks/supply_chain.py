"""Supply chain compromise: backdoored app update with dormant phase."""

from datetime import date, datetime, timedelta
import string
import numpy as np

from .base import AttackScenario


def _generate_dga_domain(rng, length=None):
    """Generate a DGA-like domain that looks almost legitimate."""
    if length is None:
        length = rng.integers(10, 18)
    # Mix of plausible prefixes + random suffix to look like CDN/analytics
    prefixes = ["cdn-", "api-", "telemetry-", "update-", "sync-", "analytics-", "config-"]
    prefix = rng.choice(prefixes)
    suffix_chars = []
    for _ in range(length - len(prefix)):
        suffix_chars.append(rng.choice(list(string.ascii_lowercase + string.digits)))
    tlds = [".com", ".net", ".io", ".cloud", ".services"]
    return prefix + "".join(suffix_chars) + rng.choice(tlds)


# Devices that have APP-017 installed
_APP017_DEVICES = [
    f"DEV-{i:03d}" for i in [14, 27, 55, 88, 103, 141, 167, 198, 223, 256, 289, 315, 378, 402, 450]
]

# C2 IPs (hosted on legitimate cloud providers to avoid reputation blocks)
_C2_IPS = [
    ("13.107.42.14", "Azure US"),
    ("52.84.150.11", "AWS CloudFront"),
    ("104.18.25.77", "Cloudflare"),
]


class SupplyChainCompromise(AttackScenario):
    """Legitimate app update contains a backdoor that activates after dormancy.

    Dormant phase (90 days): Almost invisible — occasional DNS queries to
    unusual domains from APP-017 devices, very slight traffic increase.

    Active phase (post-dormancy): Periodic C2 callbacks every 4-8 hours,
    gradual data collection, eventual low-volume exfiltration.

    Designed to be extremely subtle — each individual event looks benign.
    Detection requires noticing accumulation of tiny anomalies over time.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.compromised_app = config.get("compromised_app", "APP-017")
        self.dormant_days = config.get("dormant_days", 90)
        self._start_date = (
            self.start if isinstance(self.start, date) else datetime.fromisoformat(self.start).date()
        )
        self._active_date = self._start_date + timedelta(days=self.dormant_days)
        # Attack runs indefinitely once active (or until sim end)
        self._end_date = self._start_date + timedelta(days=365)

    def is_active(self, current_date: date) -> bool:
        return self._start_date <= current_date <= self._end_date

    def _is_dormant(self, current_date: date) -> bool:
        return current_date < self._active_date

    def _days_active(self, current_date: date) -> int:
        """Days since activation (0 during dormancy)."""
        if self._is_dormant(current_date):
            return 0
        return (current_date - self._active_date).days

    def modify_auth_events(
        self, user_id: str, events: list[dict], current_date: date, rng
    ) -> list[dict]:
        # Supply chain attack operates at network/app layer, not auth
        return events

    def modify_network_flows(
        self, device_id: str, flows: list[dict], current_date: date, rng
    ) -> list[dict]:
        if not self.is_active(current_date):
            return flows
        if device_id not in _APP017_DEVICES:
            return flows

        # During dormancy: very slight increase in outbound bytes for affected devices
        if self._is_dormant(current_date):
            # Only 20% chance per device per day to add slight noise
            if rng.random() < 0.20:
                # Pick one existing flow and slightly inflate bytes_out
                if flows:
                    idx = rng.integers(0, len(flows))
                    original = flows[idx].get("bytes_out", 1000)
                    # 5-15% increase — within normal variance
                    flows[idx]["bytes_out"] = int(original * (1 + rng.uniform(0.05, 0.15)))
        return flows

    def inject_events(self, current_date: date, rng) -> dict[str, list[dict]]:
        if not self.is_active(current_date):
            return {}

        dns_events = []
        network_events = []
        app_events = []

        if self._is_dormant(current_date):
            self._inject_dormant_signals(current_date, rng, dns_events)
        else:
            self._inject_active_c2(current_date, rng, network_events, dns_events)
            self._inject_active_collection(current_date, rng, app_events, network_events)

        result = {}
        if dns_events:
            result["dns"] = dns_events
        if network_events:
            result["network"] = network_events
        if app_events:
            result["app"] = app_events
        return result

    def _inject_dormant_signals(self, current_date, rng, dns_events):
        """Dormant phase: subtle DNS queries from a few APP-017 devices."""
        # Only 1-3 devices query per day (not all 15)
        num_querying = rng.integers(1, 4)
        querying_devices = [_APP017_DEVICES[i] for i in rng.choice(
            len(_APP017_DEVICES), size=num_querying, replace=False
        )]

        for device_id in querying_devices:
            # 1 DNS query per device — looks like a failed update check
            query_time = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(6, 22))
            )
            # Domain looks like a legitimate update/CDN endpoint
            domain = _generate_dga_domain(rng)
            dns_events.append({
                "timestamp": query_time.isoformat(),
                "device_id": device_id,
                "query_domain": domain,
                "query_type": "A",
                "response": "NXDOMAIN",
                "source_app": self.compromised_app,
                "attack_id": self.id,
                "label": "dormant_beacon_dns",
            })

    def _inject_active_c2(self, current_date, rng, network_events, dns_events):
        """Active phase: periodic C2 callbacks from subset of devices."""
        days_active = self._days_active(current_date)

        # Gradually increase participating devices: start with 2, grow to all 15
        max_active = min(2 + days_active // 10, len(_APP017_DEVICES))
        # Deterministic subset based on days_active for consistency
        active_devices = _APP017_DEVICES[:max_active]

        c2_ip, c2_label = _C2_IPS[days_active % len(_C2_IPS)]

        for device_id in active_devices:
            # 3-6 callbacks per day (every 4-8 hours)
            num_callbacks = rng.integers(3, 7)
            callback_times = sorted(rng.uniform(0, 24, size=num_callbacks))

            for hour in callback_times:
                cb_time = datetime.combine(current_date, datetime.min.time()) + timedelta(
                    hours=float(hour)
                )

                # DNS lookup before C2 connection (uses DGA domain that resolves)
                dns_events.append({
                    "timestamp": cb_time.isoformat(),
                    "device_id": device_id,
                    "query_domain": _generate_dga_domain(rng),
                    "query_type": "A",
                    "response": c2_ip,
                    "source_app": self.compromised_app,
                    "attack_id": self.id,
                    "label": "c2_dns_lookup",
                })

                # Small C2 network flow — looks like HTTPS API call
                network_events.append({
                    "timestamp": cb_time.isoformat(),
                    "src_ip": f"10.0.{rng.integers(1, 13)}.{rng.integers(1, 255)}",
                    "dst_ip": c2_ip,
                    "dst_port": 443,
                    "bytes_out": int(rng.integers(200, 2000)),
                    "bytes_in": int(rng.integers(100, 1500)),
                    "protocol": "tcp",
                    "duration_ms": int(rng.integers(100, 3000)),
                    "device_id": device_id,
                    "source_app": self.compromised_app,
                    "attack_id": self.id,
                    "label": "c2_callback",
                })

    def _inject_active_collection(self, current_date, rng, app_events, network_events):
        """Active phase: gradual data collection and eventual exfiltration."""
        days_active = self._days_active(current_date)

        # Data collection — unusual queries from APP-017 (looks like internal API calls)
        # Only triggers every 2-3 days
        if days_active % rng.integers(2, 4) != 0:
            return

        # Pick 2-4 devices for collection activity
        num_collectors = rng.integers(2, 5)
        collectors = [_APP017_DEVICES[i] for i in rng.choice(
            len(_APP017_DEVICES), size=min(num_collectors, len(_APP017_DEVICES)), replace=False
        )]

        collection_queries = [
            "SELECT * FROM user_directory",
            "SELECT hostname, ip, os_version FROM device_inventory",
            "SELECT name, email, role FROM employees WHERE clearance > 2",
            "SELECT * FROM network_topology",
            "SELECT key_name, last_rotated FROM api_keys",
            "SELECT * FROM config_secrets",
        ]

        for device_id in collectors:
            query_time = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(9, 17))
            )
            # App-layer data collection event
            app_events.append({
                "timestamp": query_time.isoformat(),
                "device_id": device_id,
                "app_id": self.compromised_app,
                "event_type": "database_query",
                "query": rng.choice(collection_queries),
                "rows_returned": int(rng.integers(10, 500)),
                "attack_id": self.id,
                "label": "data_collection",
            })

        # Exfiltration — starts only after 30+ days active, low volume
        if days_active >= 30:
            # One small exfil per day from one device
            exfil_device = rng.choice(collectors)
            c2_ip, _ = _C2_IPS[days_active % len(_C2_IPS)]
            exfil_time = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(1, 5))
            )
            network_events.append({
                "timestamp": exfil_time.isoformat(),
                "src_ip": f"10.0.{rng.integers(1, 13)}.{rng.integers(1, 255)}",
                "dst_ip": c2_ip,
                "dst_port": 443,
                "bytes_out": int(rng.integers(50_000, 500_000)),
                "bytes_in": int(rng.integers(100, 1000)),
                "protocol": "tcp",
                "duration_ms": int(rng.integers(2000, 15000)),
                "device_id": exfil_device,
                "source_app": self.compromised_app,
                "attack_id": self.id,
                "label": "data_exfiltration",
            })

    @property
    def mitre_techniques(self) -> list[str]:
        return ["T1195.002", "T1071", "T1568", "T1005", "T1041"]

    @property
    def involved_entities(self) -> dict[str, list[str]]:
        return {
            "apps": [self.compromised_app],
            "devices": list(_APP017_DEVICES),
            "ips": [ip for ip, _ in _C2_IPS],
        }
