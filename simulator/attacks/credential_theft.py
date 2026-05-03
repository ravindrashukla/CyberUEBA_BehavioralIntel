"""Credential theft + lateral movement scenario (5-day campaign)."""

from datetime import date, datetime, timedelta
import numpy as np

from .base import AttackScenario

# External attacker IPs (phishing infrastructure)
_ATTACKER_IPS = [
    ("91.215.85.12", "Romania"),
    ("91.215.85.44", "Romania"),
    ("185.100.87.202", "Netherlands"),
]

# Internal devices the attacker laterally moves to
_LATERAL_TARGETS = [
    ("DEV-101", "10.0.3.15", "internal"),
    ("DEV-204", "10.0.4.22", "internal"),
    ("DEV-310", "10.0.7.8", "restricted"),
    ("DEV-455", "10.0.8.31", "restricted"),
    ("DEV-512", "10.0.9.10", "management"),
    ("SRV-017", "10.0.10.5", "restricted"),
    ("SRV-042", "10.0.10.42", "management"),
]

# Credential stores the attacker targets
_CREDENTIAL_STORES = [
    "/etc/shadow",
    "C:\\Windows\\System32\\config\\SAM",
    "HKLM\\SAM",
    "/opt/vault/secrets.db",
    "credential_manager.kdbx",
]

# Staging locations for exfiltration
_STAGING_PATHS = [
    "C:\\Users\\Public\\tmp\\",
    "/tmp/.cache/",
    "C:\\ProgramData\\update_cache\\",
    "/var/tmp/.session/",
]

# Sensitive files to stage for exfiltration
_SENSITIVE_FILES = [
    "employee_roster.xlsx",
    "budget_2026_draft.docx",
    "network_topology.vsd",
    "api_keys_backup.csv",
    "customer_pii_export.csv",
    "security_audit_findings.pdf",
    "executive_compensation.xlsx",
    "source_code_archive.tar.gz",
]


class CredentialTheftLateral(AttackScenario):
    """Phishing → credential theft → lateral movement over 5 days.

    Day 1: Phished user clicks link, attacker obtains credential, unusual external auth.
    Day 2: Credential harvesting — access to credential stores, unusual file reads.
    Day 3-4: Lateral movement — authenticate as compromised user to devices outside
             normal pattern, access higher-clearance segments.
    Day 5: Data staging — large file copies to unusual locations, network exfiltration.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.duration_days = config.get("duration_days", 5)
        self.compromised_user = config.get("compromised_user", "USR-087")
        self.compromised_device = config.get("compromised_device", "DEV-087")
        self._start_date = (
            self.start if isinstance(self.start, date) else datetime.fromisoformat(self.start).date()
        )
        self._end_date = self._start_date + timedelta(days=self.duration_days - 1)

    def is_active(self, current_date: date) -> bool:
        return self._start_date <= current_date <= self._end_date

    def _day_number(self, current_date: date) -> int:
        """1-indexed day number within the campaign."""
        return (current_date - self._start_date).days + 1

    def modify_auth_events(
        self, user_id: str, events: list[dict], current_date: date, rng
    ) -> list[dict]:
        if not self.is_active(current_date):
            return events
        if user_id != self.compromised_user:
            return events
        # Existing legitimate events remain; attack events added via inject_events
        return events

    def modify_network_flows(
        self, device_id: str, flows: list[dict], current_date: date, rng
    ) -> list[dict]:
        if not self.is_active(current_date):
            return flows
        if device_id != self.compromised_device:
            return flows
        # Network attack flows injected via inject_events
        return flows

    def inject_events(self, current_date: date, rng) -> dict[str, list[dict]]:
        if not self.is_active(current_date):
            return {}

        day = self._day_number(current_date)
        auth_events = []
        network_events = []
        file_events = []
        endpoint_events = []

        if day == 1:
            self._inject_day1_phishing(current_date, rng, auth_events, network_events, endpoint_events)
        elif day == 2:
            self._inject_day2_harvesting(current_date, rng, auth_events, file_events, endpoint_events)
        elif day in (3, 4):
            self._inject_day3_4_lateral(current_date, rng, auth_events, network_events)
        elif day == 5:
            self._inject_day5_staging(current_date, rng, file_events, network_events)

        result = {}
        if auth_events:
            result["auth"] = auth_events
        if network_events:
            result["network"] = network_events
        if file_events:
            result["file"] = file_events
        if endpoint_events:
            result["endpoint"] = endpoint_events
        return result

    def _inject_day1_phishing(self, current_date, rng, auth_events, network_events, endpoint_events):
        """Day 1: Phishing click → credential capture → unusual external auth."""
        attacker_ip, attacker_country = _ATTACKER_IPS[0]

        # Phishing email click — suspicious process spawn
        click_time = datetime.combine(current_date, datetime.min.time()) + timedelta(
            hours=float(rng.uniform(9, 12))
        )
        endpoint_events.append({
            "timestamp": click_time.isoformat(),
            "device_id": self.compromised_device,
            "user_id": self.compromised_user,
            "event_type": "process_start",
            "process_name": "outlook.exe",
            "child_process": "powershell.exe",
            "command_line": "powershell -enc <base64_payload>",
            "attack_id": self.id,
            "label": "phishing_execution",
        })

        # Outbound connection to attacker infrastructure (credential exfil)
        exfil_time = click_time + timedelta(seconds=float(rng.uniform(5, 30)))
        network_events.append({
            "timestamp": exfil_time.isoformat(),
            "src_ip": "10.0.2.87",
            "dst_ip": attacker_ip,
            "dst_port": 443,
            "bytes_out": int(rng.integers(2000, 8000)),
            "bytes_in": int(rng.integers(500, 2000)),
            "protocol": "tcp",
            "device_id": self.compromised_device,
            "attack_id": self.id,
            "label": "credential_exfil",
        })

        # Attacker uses stolen credential — auth from external IP at unusual hour
        reuse_time = click_time + timedelta(hours=float(rng.uniform(3, 8)))
        auth_events.append({
            "timestamp": reuse_time.isoformat(),
            "user_id": self.compromised_user,
            "event_type": "auth_success",
            "source_ip": attacker_ip,
            "geo_country": attacker_country,
            "auth_method": "password",
            "failure_reason": None,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "attack_id": self.id,
            "label": "stolen_credential_reuse",
        })

    def _inject_day2_harvesting(self, current_date, rng, auth_events, file_events, endpoint_events):
        """Day 2: Credential harvesting — access credential stores, dump tools."""
        attacker_ip, attacker_country = _ATTACKER_IPS[rng.integers(0, len(_ATTACKER_IPS))]

        # Auth from external IP during off-hours
        harvest_start = datetime.combine(current_date, datetime.min.time()) + timedelta(
            hours=float(rng.uniform(1, 5))
        )
        auth_events.append({
            "timestamp": harvest_start.isoformat(),
            "user_id": self.compromised_user,
            "event_type": "auth_success",
            "source_ip": attacker_ip,
            "geo_country": attacker_country,
            "auth_method": "password",
            "failure_reason": None,
            "attack_id": self.id,
            "label": "off_hours_access",
        })

        # Credential store access attempts
        for i, store in enumerate(rng.choice(_CREDENTIAL_STORES, size=3, replace=False)):
            access_time = harvest_start + timedelta(minutes=float(rng.uniform(5, 60)))
            file_events.append({
                "timestamp": access_time.isoformat(),
                "user_id": self.compromised_user,
                "device_id": self.compromised_device,
                "event_type": "file_read",
                "path": store,
                "bytes_read": int(rng.integers(1000, 50000)),
                "attack_id": self.id,
                "label": "credential_store_access",
            })

        # Credential dumping tool execution
        dump_time = harvest_start + timedelta(minutes=float(rng.uniform(30, 90)))
        endpoint_events.append({
            "timestamp": dump_time.isoformat(),
            "device_id": self.compromised_device,
            "user_id": self.compromised_user,
            "event_type": "process_start",
            "process_name": rng.choice(["mimikatz.exe", "procdump.exe", "comsvcs.dll"]),
            "command_line": "rundll32 comsvcs.dll MiniDump",
            "attack_id": self.id,
            "label": "credential_dump",
        })

    def _inject_day3_4_lateral(self, current_date, rng, auth_events, network_events):
        """Day 3-4: Lateral movement to multiple devices in higher-clearance segments."""
        attacker_ip, attacker_country = _ATTACKER_IPS[rng.integers(0, len(_ATTACKER_IPS))]
        day = self._day_number(current_date)

        # Pick 2-4 lateral targets per day
        num_targets = rng.integers(2, 5)
        # Day 4 targets higher-clearance devices
        if day == 4:
            targets = [t for t in _LATERAL_TARGETS if t[2] in ("restricted", "management")]
        else:
            targets = list(_LATERAL_TARGETS)

        chosen_targets = [targets[i] for i in rng.choice(len(targets), size=min(num_targets, len(targets)), replace=False)]

        # Auth from compromised device IP to each lateral target
        lateral_start = datetime.combine(current_date, datetime.min.time()) + timedelta(
            hours=float(rng.uniform(2, 6))
        )

        for device_id, device_ip, zone in chosen_targets:
            move_time = lateral_start + timedelta(minutes=float(rng.uniform(5, 120)))

            # Authentication to the lateral target
            auth_events.append({
                "timestamp": move_time.isoformat(),
                "user_id": self.compromised_user,
                "event_type": "auth_success",
                "source_ip": "10.0.2.87",
                "destination_device": device_id,
                "destination_ip": device_ip,
                "destination_zone": zone,
                "auth_method": rng.choice(["ntlm", "kerberos", "ssh_key"]),
                "failure_reason": None,
                "attack_id": self.id,
                "label": "lateral_movement",
            })

            # SMB / RDP / WinRM network flow
            network_events.append({
                "timestamp": move_time.isoformat(),
                "src_ip": "10.0.2.87",
                "dst_ip": device_ip,
                "dst_port": int(rng.choice([445, 3389, 5985, 22])),
                "bytes_out": int(rng.integers(1000, 20000)),
                "bytes_in": int(rng.integers(500, 10000)),
                "protocol": "tcp",
                "device_id": self.compromised_device,
                "attack_id": self.id,
                "label": "lateral_connection",
            })

    def _inject_day5_staging(self, current_date, rng, file_events, network_events):
        """Day 5: Data staging and exfiltration."""
        staging_start = datetime.combine(current_date, datetime.min.time()) + timedelta(
            hours=float(rng.uniform(1, 4))
        )

        # Large file copies to staging directory
        staging_dir = rng.choice(_STAGING_PATHS)
        num_files = rng.integers(5, 12)

        for i in range(num_files):
            copy_time = staging_start + timedelta(minutes=float(rng.uniform(0, 60)))
            filename = rng.choice(_SENSITIVE_FILES)
            file_events.append({
                "timestamp": copy_time.isoformat(),
                "user_id": self.compromised_user,
                "device_id": self.compromised_device,
                "event_type": "file_copy",
                "source_path": f"/shared/confidential/{filename}",
                "destination_path": f"{staging_dir}{filename}",
                "bytes_written": int(rng.integers(500_000, 50_000_000)),
                "attack_id": self.id,
                "label": "data_staging",
            })

        # Exfiltration — large outbound network flows to attacker IP
        exfil_start = staging_start + timedelta(hours=float(rng.uniform(1, 3)))
        attacker_ip, _ = _ATTACKER_IPS[0]
        num_flows = rng.integers(3, 8)

        for i in range(num_flows):
            flow_time = exfil_start + timedelta(minutes=float(rng.uniform(0, 90)))
            network_events.append({
                "timestamp": flow_time.isoformat(),
                "src_ip": "10.0.2.87",
                "dst_ip": attacker_ip,
                "dst_port": 443,
                "bytes_out": int(rng.integers(1_000_000, 50_000_000)),
                "bytes_in": int(rng.integers(100, 5000)),
                "protocol": "tcp",
                "duration_ms": int(rng.integers(5000, 60000)),
                "device_id": self.compromised_device,
                "attack_id": self.id,
                "label": "data_exfiltration",
            })

    @property
    def mitre_techniques(self) -> list[str]:
        return ["T1566", "T1078", "T1003", "T1021", "T1074", "T1048"]

    @property
    def involved_entities(self) -> dict[str, list[str]]:
        return {
            "users": [self.compromised_user],
            "devices": [self.compromised_device] + [d[0] for d in _LATERAL_TARGETS],
            "ips": [ip for ip, _ in _ATTACKER_IPS],
        }
