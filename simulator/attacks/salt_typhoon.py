"""Salt Typhoon attack scenario: Telecom infrastructure interception campaign.

Models the real-world Salt Typhoon (GhostEmperor) campaign:
  - State-sponsored actor targeting telecommunications providers
  - Goal: intercept communications, access lawful intercept systems
  - Compromises edge network devices and core routing infrastructure
  - Kernel-level persistence on network appliances
  - Accesses call detail records (CDR), SMS metadata, email routing
  - DNS tunneling for low-bandwidth command channel
  - Long-term persistent surveillance capability
  - Blends exfiltration with normal inter-segment traffic

Key behavioral signals for UEBA:
  - Unusual cross-segment network flows (especially to/from restricted segments)
  - Access to telecom databases and CDR systems outside normal role
  - DNS tunneling patterns (high query volume to uncommon subdomains)
  - Bulk reads from communication metadata stores
  - Network device configuration changes
  - Gradual increase in data transfer volume to staging areas
"""

from datetime import date, datetime, timedelta
import string
import numpy as np

from .base import AttackScenario

_TELECOM_DATABASES = [
    "/telecom/cdr/call-detail-records.db",
    "/telecom/cdr/sms-metadata.db",
    "/telecom/cdr/voicemail-index.db",
    "/telecom/lawful-intercept/li-config.xml",
    "/telecom/lawful-intercept/target-list.enc",
    "/telecom/lawful-intercept/warrant-queue.db",
    "/telecom/routing/bgp-config.xml",
    "/telecom/routing/mpls-tunnels.conf",
    "/telecom/provisioning/subscriber-db.sql",
    "/telecom/provisioning/number-portability.csv",
    "/network/core/router-configs.tar.gz",
    "/network/core/switch-acls.conf",
]

_DNS_TUNNEL_DOMAINS = [
    "cdn-check.microsoftupdate-service.com",
    "telemetry.azure-cdn-edge.net",
    "api.graph-analytics-prod.com",
    "sync.onedrive-business-relay.com",
    "update.windows-defender-atp.net",
]

_STAGING_PATHS = [
    "/tmp/.cache/systemd-resolved",
    "/var/log/.journal-checkpoint",
    "/opt/telemetry/.metrics-buffer",
    "/tmp/.cache/font-config",
]


class SaltTyphoonAttack(AttackScenario):
    """Telecom infrastructure interception: edge compromise → CDR access → exfiltration.

    4 phases over ~100 days:
      Phase 1 (days 1-10):  Edge device compromise, establish foothold
      Phase 2 (days 11-40): Network infrastructure mapping, config access
      Phase 3 (days 41-75): CDR/communications data collection
      Phase 4 (days 76+):   Staged exfiltration via DNS tunneling
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.duration_days = config.get("duration_days", 100)
        self.target_user = config.get("target_user", "USR-118")
        user_device_map = config.get("_user_device_map", {})
        self.target_device = config.get("target_device",
                                        user_device_map.get(self.target_user, "DEV-118"))
        self.c2_domain = config.get("c2_domain", "cdn-check.microsoftupdate-service.com")
        self.exfil_ip = config.get("exfil_ip", "198.18.0.77")
        self._start_date = (
            self.start if isinstance(self.start, date)
            else datetime.fromisoformat(self.start).date()
        )
        self._end_date = self._start_date + timedelta(days=self.duration_days)

    def is_active(self, current_date: date) -> bool:
        return self._start_date <= current_date <= self._end_date

    def _days_elapsed(self, current_date: date) -> int:
        return (current_date - self._start_date).days

    def _phase(self, current_date: date) -> int:
        progress = self._days_elapsed(current_date) / max(self.duration_days, 1)
        if progress < 0.10:
            return 1
        if progress < 0.40:
            return 2
        if progress < 0.75:
            return 3
        return 4

    def _daily_probability(self, current_date: date) -> float:
        phase = self._phase(current_date)
        return {1: 0.40, 2: 0.60, 3: 0.80, 4: 0.90}[phase]

    def modify_auth_events(self, user_id, events, current_date, rng):
        if not self.is_active(current_date) or user_id != self.target_user:
            return events
        if rng.random() > self._daily_probability(current_date):
            return events

        phase = self._phase(current_date)

        if phase == 1:
            if rng.random() < 0.50:
                ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                    hours=float(rng.uniform(1, 4))
                )
                events.append({
                    "timestamp": ts.isoformat(),
                    "user_id": user_id,
                    "event_type": "login",
                    "source_ip": f"10.0.4.{rng.integers(200, 254)}",
                    "auth_method": "ssh_key",
                    "success": True,
                    "destination_device": f"NET-{rng.integers(1, 20):03d}",
                    "destination_zone": "dmz",
                    "off_hours": True,
                    "attack_id": self.id,
                    "label": "salt_edge_compromise",
                })

        elif phase >= 2:
            n_logins = rng.integers(2, 4 + max(0, phase - 2) * 2)
            zones = ["restricted", "management"] if phase >= 3 else ["internal", "dmz"]
            for _ in range(n_logins):
                zone = rng.choice(zones)
                method = rng.choice(["ssh_key", "kerberos", "ntlm"])
                hour = float(rng.choice([
                    rng.uniform(2, 5),
                    rng.uniform(11, 15),
                    rng.uniform(22, 23.5),
                ]))
                ts = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=hour)
                events.append({
                    "timestamp": ts.isoformat(),
                    "user_id": user_id,
                    "event_type": "login",
                    "source_ip": f"10.0.4.{200 + hash(user_id) % 3}",
                    "destination_ip": f"10.0.{rng.integers(10, 30)}.{rng.integers(1, 50)}",
                    "destination_zone": zone,
                    "auth_method": method,
                    "success": True,
                    "off_hours": hour < 7 or hour > 19,
                    "attack_id": self.id,
                    "label": "salt_infrastructure_access",
                })

        return events

    def modify_network_flows(self, device_id, flows, current_date, rng):
        return flows

    def inject_events(self, current_date, rng):
        if not self.is_active(current_date):
            return {}
        if rng.random() > self._daily_probability(current_date):
            return {}

        phase = self._phase(current_date)
        days_in = self._days_elapsed(current_date)
        network_events = []
        dns_events = []
        file_events = []
        endpoint_events = []

        # DNS tunneling command channel — volume ramps with phase
        n_dns = rng.integers(3, 6 + phase * 3)
        for _ in range(n_dns):
            subdomain_len = rng.integers(16, 48)
            subdomain = "".join(rng.choice(list(string.ascii_lowercase + string.digits),
                                           size=subdomain_len))
            domain = rng.choice(_DNS_TUNNEL_DOMAINS)
            full_domain = f"{subdomain}.{domain}"
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(0, 24))
            )
            dns_events.append({
                "timestamp": ts.isoformat(),
                "device_id": self.target_device,
                "query_domain": full_domain,
                "query_type": rng.choice(["TXT", "MX", "A", "CNAME"]),
                "response": f"10.{rng.integers(0, 255)}.{rng.integers(0, 255)}.{rng.integers(1, 254)}",
                "attack_id": self.id,
                "label": "salt_dns_tunnel",
            })

        # Cross-segment network traffic (phase 2+)
        if phase >= 2:
            n_flows = rng.integers(5, 10 + phase * 4)
            restricted_segments = [
                ("10.0.10.{n}", 3306),   # telecom database
                ("10.0.10.{n}", 5432),   # postgres CDR
                ("10.0.20.{n}", 443),    # LI system
                ("10.0.20.{n}", 8443),   # management API
                ("10.0.3.{n}", 22),      # restricted SSH
                ("10.0.3.{n}", 161),     # SNMP
            ]
            for _ in range(n_flows):
                dst_tmpl, port = restricted_segments[rng.integers(0, len(restricted_segments))]
                dst_ip = dst_tmpl.format(n=rng.integers(1, 50))

                bytes_mult = 2 + (phase - 2) * 5
                ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                    hours=float(rng.uniform(0, 24))
                )
                network_events.append({
                    "timestamp": ts.isoformat(),
                    "src_ip": f"10.0.5.{rng.integers(10, 50)}",
                    "dst_ip": dst_ip,
                    "dst_port": port,
                    "bytes_out": int(rng.integers(1000, 20000) * bytes_mult),
                    "bytes_in": int(rng.integers(5000, 500000) * bytes_mult),
                    "protocol": "tcp",
                    "device_id": self.target_device,
                    "attack_id": self.id,
                    "label": "salt_cross_segment",
                })

        # Telecom database / CDR access (phase 3+)
        if phase >= 3:
            n_files = rng.integers(8, 20 + (phase - 2) * 5)
            progress = min(days_in / self.duration_days, 1.0)
            max_db_idx = min(int(progress * len(_TELECOM_DATABASES)), len(_TELECOM_DATABASES) - 1)

            for _ in range(n_files):
                db_path = _TELECOM_DATABASES[rng.integers(0, max_db_idx + 1)]
                classification = "restricted" if "intercept" in db_path else "confidential"
                ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                    hours=float(rng.uniform(1, 23))
                )
                file_events.append({
                    "timestamp": ts.isoformat(),
                    "user_id": self.target_user,
                    "source_device_id": self.target_device,
                    "operation": rng.choice(["read", "read", "copy", "copy"]),
                    "file_path": db_path,
                    "file_size_bytes": int(rng.integers(500_000, 100_000_000)),
                    "data_classification": classification,
                    "success": True,
                    "attack_id": self.id,
                    "label": "salt_cdr_access",
                })

        # Data staging and exfiltration (phase 4)
        if phase >= 4:
            # Multiple staging writes per day
            n_staging = int(rng.integers(2, 6))
            for _ in range(n_staging):
                staging_path = rng.choice(_STAGING_PATHS)
                ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                    hours=float(rng.uniform(1, 5))
                )
                file_events.append({
                    "timestamp": ts.isoformat(),
                    "user_id": self.target_user,
                    "source_device_id": self.target_device,
                    "operation": "write",
                    "file_path": staging_path,
                    "file_size_bytes": int(rng.integers(5_000_000, 200_000_000)),
                    "data_classification": "restricted",
                    "success": True,
                    "attack_id": self.id,
                    "label": "salt_data_staging",
                })

            if rng.random() < 0.80:
                ts2 = datetime.combine(current_date, datetime.min.time()) + timedelta(
                    hours=float(rng.uniform(2, 5))
                )
                network_events.append({
                    "timestamp": ts2.isoformat(),
                    "src_ip": f"10.0.5.{rng.integers(10, 50)}",
                    "dst_ip": self.exfil_ip,
                    "dst_port": 443,
                    "bytes_out": int(rng.integers(5_000_000, 50_000_000)),
                    "bytes_in": int(rng.integers(100, 2000)),
                    "protocol": "tcp",
                    "device_id": self.target_device,
                    "attack_id": self.id,
                    "label": "salt_exfiltration",
                })

        # Rootkit / persistence on network device (phase 2+, periodic)
        if phase >= 2 and rng.random() < 0.40:
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(2, 4))
            )
            endpoint_events.append({
                "timestamp": ts.isoformat(),
                "device_id": self.target_device,
                "user_id": self.target_user,
                "event_type": "process_start",
                "process_name": rng.choice(["kworker", "systemd-networkd", "dhclient"]),
                "command_line": rng.choice([
                    "/usr/lib/systemd/systemd-networkd --update-resolv",
                    "/sbin/dhclient -nw -pf /var/run/dhclient.pid",
                    "[kworker/u8:2-events_unbound]",
                ]),
                "parent_process": "init",
                "attack_id": self.id,
                "label": "salt_rootkit_persistence",
            })

        result = {}
        if network_events:
            result["network"] = network_events
        if dns_events:
            result["dns"] = dns_events
        if file_events:
            result["file"] = file_events
        if endpoint_events:
            result["endpoint"] = endpoint_events
        return result

    @property
    def mitre_techniques(self):
        return [
            "T1557",      # Adversary-in-the-Middle
            "T1040",      # Network Sniffing
            "T1005",      # Data from Local System
            "T1071.004",  # DNS Protocol (C2)
            "T1041",      # Exfiltration Over C2 Channel
            "T1014",      # Rootkit
            "T1556",      # Modify Authentication Process
            "T1048.003",  # Exfiltration Over Unencrypted Protocol
        ]

    @property
    def involved_entities(self):
        return {
            "users": [self.target_user],
            "devices": [self.target_device],
            "ips": [self.exfil_ip],
        }
