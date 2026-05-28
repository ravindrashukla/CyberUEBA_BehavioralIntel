"""Ransomware deployment via compromised RDP (6-hour burst)."""

from datetime import date, datetime, timedelta
import numpy as np

from .base import AttackScenario

# External RDP attacker IP
_ATTACKER_IP = ("45.155.205.99", "Russia")

# Devices that get infected during lateral spread
_SPREAD_TARGETS = [
    ("DEV-101", "10.0.3.15"),
    ("DEV-204", "10.0.4.22"),
    ("DEV-310", "10.0.7.8"),
    ("SRV-017", "10.0.10.5"),
    ("SRV-042", "10.0.10.42"),
    ("SRV-055", "10.0.10.55"),
    ("DEV-455", "10.0.8.31"),
    ("DEV-512", "10.0.9.10"),
    ("SRV-089", "10.0.11.89"),
    ("DEV-600", "10.0.12.3"),
]

# Suspicious ransomware-related process names
_RANSOM_PROCESSES = [
    "encrypt.exe",
    "locker.exe",
    "crypt32svc.exe",
    "svchost_update.exe",
    "winlogon_helper.exe",
]

# Ransom note filenames
_RANSOM_NOTES = [
    "README_DECRYPT.txt",
    "HOW_TO_RECOVER.html",
    "DECRYPT_INSTRUCTIONS.txt",
]

# File extensions targeted for encryption
_TARGET_EXTENSIONS = [
    ".docx", ".xlsx", ".pdf", ".pptx", ".sql", ".bak",
    ".csv", ".json", ".xml", ".zip", ".tar.gz", ".mdb",
]


class Ransomware(AttackScenario):
    """Ransomware deployment via compromised RDP — fast and loud.

    Duration: 6 hours on a single day.
    Hour 1: Initial RDP access to DEV-342 from external IP.
    Hour 2: Reconnaissance — network scans, SMB enumeration.
    Hour 3: Lateral spread — authentication to multiple devices.
    Hour 4-5: Encryption — massive file_write events, suspicious processes.
    Hour 6: Ransom note deployment across all accessed devices.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.duration_hours = config.get("duration_hours", 6)
        self.initial_device = config.get("initial_device", "DEV-342")
        self.initial_device_ip = config.get("initial_device_ip", "10.0.6.42")
        self._start_date = (
            self.start if isinstance(self.start, date) else datetime.fromisoformat(self.start).date()
        )

    def is_active(self, current_date: date) -> bool:
        return current_date == self._start_date

    def modify_auth_events(
        self, user_id: str, events: list[dict], current_date: date, rng
    ) -> list[dict]:
        # All attack injection via inject_events
        return events

    def modify_network_flows(
        self, device_id: str, flows: list[dict], current_date: date, rng
    ) -> list[dict]:
        # All attack injection via inject_events
        return flows

    def inject_events(self, current_date: date, rng) -> dict[str, list[dict]]:
        if not self.is_active(current_date):
            return {}

        auth_events = []
        network_events = []
        file_events = []
        endpoint_events = []

        # Attack starts at a random hour in early morning (attacker targets off-hours)
        attack_start = datetime.combine(current_date, datetime.min.time()) + timedelta(
            hours=float(rng.uniform(1, 4))
        )

        self._inject_hour1_rdp(attack_start, rng, auth_events, network_events)
        self._inject_hour2_recon(attack_start, rng, network_events, endpoint_events)
        self._inject_hour3_lateral(attack_start, rng, auth_events, network_events)
        self._inject_hour4_5_encryption(attack_start, rng, file_events, endpoint_events)
        self._inject_hour6_ransom_note(attack_start, rng, file_events)

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

    def _inject_hour1_rdp(self, attack_start, rng, auth_events, network_events):
        """Hour 1: Initial RDP access from external IP."""
        attacker_ip, attacker_country = _ATTACKER_IP

        # Multiple RDP auth attempts then success
        num_failures = rng.integers(3, 8)
        for i in range(num_failures):
            fail_time = attack_start + timedelta(seconds=float(rng.uniform(0, 300)))
            auth_events.append({
                "timestamp": fail_time.isoformat(),
                "user_id": "Administrator",
                "event_type": "auth_failure",
                "source_ip": attacker_ip,
                "geo_country": attacker_country,
                "auth_method": "rdp",
                "destination_device": self.initial_device,
                "failure_reason": "invalid_password",
                "attack_id": self.id,
            })

        # Successful RDP login
        success_time = attack_start + timedelta(minutes=float(rng.uniform(5, 15)))
        auth_events.append({
            "timestamp": success_time.isoformat(),
            "user_id": "Administrator",
            "event_type": "auth_success",
            "source_ip": attacker_ip,
            "geo_country": attacker_country,
            "auth_method": "rdp",
            "destination_device": self.initial_device,
            "failure_reason": None,
            "attack_id": self.id,
            "label": "rdp_compromise",
        })

        # RDP session network flow
        network_events.append({
            "timestamp": success_time.isoformat(),
            "src_ip": attacker_ip,
            "dst_ip": self.initial_device_ip,
            "dst_port": 3389,
            "bytes_out": int(rng.integers(50000, 200000)),
            "bytes_in": int(rng.integers(100000, 500000)),
            "protocol": "tcp",
            "duration_ms": int(rng.integers(300000, 600000)),
            "device_id": self.initial_device,
            "attack_id": self.id,
            "label": "rdp_session",
        })

    def _inject_hour2_recon(self, attack_start, rng, network_events, endpoint_events):
        """Hour 2: Network reconnaissance — scans and SMB enumeration."""
        recon_start = attack_start + timedelta(hours=1)

        # Port scanning — many short connections to internal subnet
        num_scan_targets = rng.integers(50, 150)
        for _ in range(num_scan_targets):
            scan_time = recon_start + timedelta(seconds=float(rng.uniform(0, 3000)))
            target_ip = f"10.0.{rng.integers(1, 13)}.{rng.integers(1, 255)}"
            network_events.append({
                "timestamp": scan_time.isoformat(),
                "src_ip": self.initial_device_ip,
                "dst_ip": target_ip,
                "dst_port": int(rng.choice([445, 135, 139, 3389, 22, 80, 443, 5985])),
                "bytes_out": int(rng.integers(40, 200)),
                "bytes_in": int(rng.integers(0, 100)),
                "protocol": "tcp",
                "duration_ms": int(rng.integers(10, 500)),
                "device_id": self.initial_device,
                "attack_id": self.id,
                "label": "network_scan",
            })

        # Reconnaissance tools
        recon_tools = ["netscan.exe", "nbtscan.exe", "net.exe", "nltest.exe", "arp.exe"]
        for tool in rng.choice(recon_tools, size=rng.integers(3, 6), replace=False):
            tool_time = recon_start + timedelta(minutes=float(rng.uniform(5, 45)))
            endpoint_events.append({
                "timestamp": tool_time.isoformat(),
                "device_id": self.initial_device,
                "user_id": "Administrator",
                "event_type": "process_start",
                "process_name": tool,
                "command_line": f"{tool} /all" if tool == "net.exe" else f"{tool} 10.0.0.0/8",
                "attack_id": self.id,
                "label": "reconnaissance",
            })

    def _inject_hour3_lateral(self, attack_start, rng, auth_events, network_events):
        """Hour 3: Lateral spread to multiple devices via SMB/WMI."""
        lateral_start = attack_start + timedelta(hours=2)

        # Spread to 6-10 devices
        num_targets = rng.integers(6, 11)
        chosen_targets = [_SPREAD_TARGETS[i] for i in rng.choice(
            len(_SPREAD_TARGETS), size=min(num_targets, len(_SPREAD_TARGETS)), replace=False
        )]

        for device_id, device_ip in chosen_targets:
            move_time = lateral_start + timedelta(minutes=float(rng.uniform(0, 55)))

            # Auth to target device
            auth_events.append({
                "timestamp": move_time.isoformat(),
                "user_id": "Administrator",
                "event_type": "auth_success",
                "source_ip": self.initial_device_ip,
                "destination_device": device_id,
                "destination_ip": device_ip,
                "auth_method": rng.choice(["ntlm", "wmi", "psexec"]),
                "failure_reason": None,
                "attack_id": self.id,
                "label": "ransomware_lateral",
            })

            # SMB file copy (deploying ransomware binary)
            network_events.append({
                "timestamp": move_time.isoformat(),
                "src_ip": self.initial_device_ip,
                "dst_ip": device_ip,
                "dst_port": 445,
                "bytes_out": int(rng.integers(500000, 2000000)),
                "bytes_in": int(rng.integers(100, 5000)),
                "protocol": "tcp",
                "duration_ms": int(rng.integers(1000, 10000)),
                "device_id": self.initial_device,
                "attack_id": self.id,
                "label": "ransomware_deploy",
            })

    def _inject_hour4_5_encryption(self, attack_start, rng, file_events, endpoint_events):
        """Hour 4-5: Mass file encryption across infected devices."""
        encrypt_start = attack_start + timedelta(hours=3)

        # All infected devices begin encrypting
        all_devices = [(self.initial_device, self.initial_device_ip)] + _SPREAD_TARGETS[:8]

        for device_id, device_ip in all_devices:
            # Ransomware process starts
            proc_time = encrypt_start + timedelta(minutes=float(rng.uniform(0, 15)))
            process_name = rng.choice(_RANSOM_PROCESSES)
            endpoint_events.append({
                "timestamp": proc_time.isoformat(),
                "device_id": device_id,
                "user_id": "SYSTEM",
                "event_type": "process_start",
                "process_name": process_name,
                "command_line": f"{process_name} --encrypt --all-drives",
                "parent_process": "svchost.exe",
                "attack_id": self.id,
                "label": "ransomware_execution",
            })

            # Mass file writes — 50-200 per device (encryption events)
            num_files = rng.integers(50, 201)
            for _ in range(num_files):
                write_time = proc_time + timedelta(seconds=float(rng.uniform(0, 6000)))
                ext = rng.choice(_TARGET_EXTENSIONS)
                filename = f"{''.join(rng.choice(list('abcdefghijklmnopqrstuvwxyz'), size=8))}{ext}.encrypted"
                drive = rng.choice(["C:", "D:", "E:"])
                dept = rng.choice(["finance", "engineering", "hr", "shared", "projects"])

                file_events.append({
                    "timestamp": write_time.isoformat(),
                    "source_device_id": device_id,
                    "user_id": "SYSTEM",
                    "operation": "write",
                    "file_path": f"{drive}\\{dept}\\{filename}",
                    "file_size_bytes": int(rng.integers(1000, 5_000_000)),
                    "data_classification": "internal",
                    "success": True,
                    "attack_id": self.id,
                    "label": "file_encryption",
                })

            # Shadow copy deletion
            shadow_time = proc_time + timedelta(minutes=float(rng.uniform(1, 5)))
            endpoint_events.append({
                "timestamp": shadow_time.isoformat(),
                "device_id": device_id,
                "user_id": "SYSTEM",
                "event_type": "process_start",
                "process_name": "vssadmin.exe",
                "command_line": "vssadmin delete shadows /all /quiet",
                "attack_id": self.id,
                "label": "shadow_copy_delete",
            })

    def _inject_hour6_ransom_note(self, attack_start, rng, file_events):
        """Hour 6: Ransom note deployment across all accessed devices."""
        note_start = attack_start + timedelta(hours=5)

        all_devices = [(self.initial_device, self.initial_device_ip)] + _SPREAD_TARGETS[:8]
        note_filename = rng.choice(_RANSOM_NOTES)

        for device_id, device_ip in all_devices:
            # Drop ransom note in multiple directories
            num_notes = rng.integers(5, 15)
            for _ in range(num_notes):
                drop_time = note_start + timedelta(minutes=float(rng.uniform(0, 30)))
                drive = rng.choice(["C:", "D:"])
                dept = rng.choice(["", "Users\\Public", "finance", "engineering", "hr", "shared"])
                path = f"{drive}\\{dept}\\{note_filename}" if dept else f"{drive}\\{note_filename}"

                file_events.append({
                    "timestamp": drop_time.isoformat(),
                    "source_device_id": device_id,
                    "user_id": "SYSTEM",
                    "operation": "write",
                    "file_path": path,
                    "file_size_bytes": int(rng.integers(2000, 8000)),
                    "data_classification": "internal",
                    "success": True,
                    "attack_id": self.id,
                    "label": "ransom_note",
                })

    @property
    def mitre_techniques(self) -> list[str]:
        return ["T1021.001", "T1046", "T1570", "T1486", "T1490"]

    @property
    def involved_entities(self) -> dict[str, list[str]]:
        return {
            "users": ["Administrator"],
            "devices": [self.initial_device] + [d[0] for d in _SPREAD_TARGETS],
            "ips": [_ATTACKER_IP[0]],
        }
