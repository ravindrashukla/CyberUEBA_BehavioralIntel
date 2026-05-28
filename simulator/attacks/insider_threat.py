"""Insider threat scenario: Disgruntled employee gradually escalating over 8 months.

ATK-004: USR-156 slowly shifts from normal behavior to data exfiltration.
No single day looks obviously malicious — detection requires CUSUM or
behavioral embedding drift comparison over weeks/months.

This is the KEY test case for trajectory/drift detection.
"""

from datetime import date, datetime, timedelta

import numpy as np

from .base import AttackScenario

# Job search domains (Phase 1-2: mood shift)
_JOB_SITES = [
    "linkedin.com", "indeed.com", "glassdoor.com", "monster.com",
    "ziprecruiter.com", "hired.com", "levels.fyi",
]

# Cloud storage / personal exfil targets (Phase 4)
_PERSONAL_CLOUD = [
    "drive.google.com", "dropbox.com", "onedrive.live.com",
    "box.com", "mega.nz", "wetransfer.com",
]

# Personal email domains
_PERSONAL_EMAIL_DOMAINS = [
    "gmail.com", "protonmail.com", "yahoo.com", "outlook.com",
]

# File paths by sensitivity tier
_FILE_PATHS = {
    "normal": [
        "/engineering/team-alpha/src/",
        "/engineering/team-alpha/docs/",
        "/engineering/shared/libs/",
        "/shared/docs/general/",
    ],
    "curious": [
        "/hr/org-charts/",
        "/hr/compensation/",
        "/finance/budgets/",
        "/legal/contracts/",
        "/product/roadmap/",
    ],
    "recon": [
        "/security/network-maps/",
        "/engineering/architecture/",
        "/executive/strategy/",
        "/compliance/classification/",
        "/it-ops/asset-inventory/",
    ],
    "exfil": [
        "/executive/m-and-a/",
        "/finance/projections/",
        "/engineering/source-code/proprietary/",
        "/security/credentials/",
        "/hr/personnel-records/",
    ],
}

# Network shares outside Engineering department
_OTHER_DEPT_SHARES = [
    "//fs01/finance$", "//fs01/hr$", "//fs01/legal$",
    "//fs01/executive$", "//fs02/security$", "//fs02/compliance$",
]

_DOC_EXTENSIONS = ["pdf", "docx", "xlsx", "pptx", "csv", "txt"]
_ARCHIVE_EXTENSIONS = ["zip", "7z", "tar.gz", "rar"]


def _off_hours_time(rng, current_date: date, direction: str) -> datetime:
    """Generate a plausible off-hours timestamp."""
    base = datetime.combine(current_date, datetime.min.time())
    if direction == "early":
        return base + timedelta(hours=float(rng.uniform(5.0, 7.5)))
    else:
        return base + timedelta(hours=float(rng.uniform(19.0, 23.5)))


def _random_filename(rng, extensions: list[str]) -> str:
    """Generate a random but realistic-looking filename."""
    prefixes = ["report", "summary", "draft", "export", "backup", "data", "notes", "review"]
    prefix = rng.choice(prefixes)
    suffix = "".join(rng.choice(list("0123456789"), size=int(rng.integers(3, 6))))
    ext = rng.choice(extensions)
    return f"{prefix}_{suffix}.{ext}"


class InsiderThreatAttack(AttackScenario):
    """Disgruntled employee escalating access over 8 months.

    Phases (gradual, overlapping):
      Months 1-2: Mood shift — off-hours logins (1-2/week), job site browsing
      Months 3-4: Curiosity — files outside scope, org charts, HR systems
      Months 5-6: Reconnaissance — mapping sensitive data, cross-dept network shares,
                  downloading classification-sensitive documents
      Months 7-8: Exfiltration — USB devices, large copies, email to personal accounts,
                  cloud storage uploads, bulk data transfer

    Design goals:
      - No single day looks obviously malicious
      - Each phase adds 1-3 anomalous events per day on normal behavior
      - Drift detectable only via CUSUM (accumulated small deviations) or
        behavioral embedding comparison across weeks
      - Individual events all have innocent explanations

    Injects into: auth_logs, file_access, dns_logs, network_flows, endpoint_telemetry
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.escalation_months = config.get("escalation_months", 8)
        self.target_user = config.get("user", "USR-156")
        # Resolve device from entity data if available, fall back to config/default
        user_device_map = config.get("_user_device_map", {})
        self.target_device = config.get("device",
                                        user_device_map.get(self.target_user, "DEV-156"))
        self._start_date = (
            self.start if isinstance(self.start, date) else datetime.fromisoformat(self.start).date()
        )
        self._end_date = self._start_date + timedelta(days=self.escalation_months * 30)
        self._duration_days = (self._end_date - self._start_date).days

    def is_active(self, current_date: date) -> bool:
        return self._start_date <= current_date <= self._end_date

    def _days_elapsed(self, current_date: date) -> int:
        return (current_date - self._start_date).days

    def _phase(self, current_date: date) -> int:
        """Return phase 1-4 based on month within the attack.

        Phase 1 (months 1-2): Subtle mood shift
        Phase 2 (months 3-4): Curiosity / scope creep
        Phase 3 (months 5-6): Reconnaissance
        Phase 4 (months 7-8): Exfiltration prep + action
        """
        progress = self._days_elapsed(current_date) / max(self._duration_days, 1)
        if progress < 0.25:
            return 1
        elif progress < 0.50:
            return 2
        elif progress < 0.75:
            return 3
        else:
            return 4

    def _daily_anomaly_probability(self, current_date: date) -> float:
        """Probability anomalous events fire today. Ramps over time."""
        progress = self._days_elapsed(current_date) / self._duration_days
        # 60% early -> 95% in final phase
        return 0.60 + 0.35 * progress

    def modify_auth_events(
        self, user_id: str, events: list[dict], current_date: date, rng
    ) -> list[dict]:
        if not self.is_active(current_date):
            return events
        if user_id != self.target_user:
            return events

        phase = self._phase(current_date)

        # Phase 1+: Off-hours logins — ramps from ~2/week to ~4/week
        off_hours_prob = {1: 0.20, 2: 0.30, 3: 0.40, 4: 0.50}[phase]
        if rng.random() < off_hours_prob:
            direction = rng.choice(["early", "late"])
            ts = _off_hours_time(rng, current_date, direction)
            events.append({
                "timestamp": ts.isoformat(),
                "user_id": user_id,
                "event_type": "login",
                "source_ip": f"10.0.3.{rng.integers(100, 200)}",
                "auth_method": rng.choice(["password", "sso", "vpn"]),
                "success": True,
                "device_id": self.target_device,
                "off_hours": True,
                "attack_id": self.id,
                "label": "insider_off_hours_login",
            })

        # Phase 3+: Permission elevation requests (~once per month)
        if phase >= 3:
            days_into_phase3 = self._days_elapsed(current_date) - int(self._duration_days * 0.50)
            if days_into_phase3 > 0 and days_into_phase3 % 30 == 0:
                ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                    hours=float(rng.uniform(9, 17))
                )
                events.append({
                    "timestamp": ts.isoformat(),
                    "user_id": user_id,
                    "event_type": "privilege_change",
                    "source_ip": f"10.0.3.{rng.integers(100, 200)}",
                    "new_role": rng.choice([
                        "cross-team-reader", "architecture-viewer",
                        "finance-readonly", "security-auditor",
                    ]),
                    "justification": rng.choice([
                        "cross-functional project", "architecture review",
                        "audit preparation", "incident response support",
                    ]),
                    "attack_id": self.id,
                    "label": "insider_privilege_escalation",
                })

        # Phase 4: Logins from new/unusual devices (~5% of days)
        if phase == 4 and rng.random() < 0.05:
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(19.0, 22.0))
            )
            events.append({
                "timestamp": ts.isoformat(),
                "user_id": user_id,
                "event_type": "login",
                "source_ip": f"192.168.{rng.integers(1, 10)}.{rng.integers(100, 250)}",
                "auth_method": "vpn_token",
                "success": True,
                "device_id": f"DEV-EXT-{rng.integers(900, 999)}",
                "new_device": True,
                "attack_id": self.id,
                "label": "insider_new_device_login",
            })

        return events

    def modify_network_flows(
        self, device_id: str, flows: list[dict], current_date: date, rng
    ) -> list[dict]:
        if not self.is_active(current_date):
            return flows
        if device_id != self.target_device:
            return flows
        # Network-level injection handled in inject_events
        return flows

    def inject_events(self, current_date: date, rng) -> dict[str, list[dict]]:
        if not self.is_active(current_date):
            return {}

        # Not every day has anomalous events — especially early on
        if rng.random() > self._daily_anomaly_probability(current_date):
            return {}

        phase = self._phase(current_date)
        file_events = []
        dns_events = []
        network_events = []
        endpoint_events = []

        # === PHASE 1+ (Months 1-2): Job site browsing ===
        if phase >= 1:
            self._inject_job_site_dns(current_date, phase, rng, dns_events)

        # === PHASE 2+ (Months 3-4): File scope creep ===
        if phase >= 2:
            self._inject_scope_creep_files(current_date, phase, rng, file_events)

        # === PHASE 3+ (Months 5-6): Reconnaissance ===
        if phase >= 3:
            self._inject_recon_activity(current_date, rng, file_events, network_events)

        # === PHASE 4 (Months 7-8): Exfiltration ===
        if phase >= 4:
            self._inject_exfil_activity(current_date, rng, file_events, network_events,
                                        endpoint_events, dns_events)

        result = {}
        if file_events:
            result["file"] = file_events
        if dns_events:
            result["dns"] = dns_events
        if network_events:
            result["network"] = network_events
        if endpoint_events:
            result["endpoint"] = endpoint_events
        return result

    # --- Phase-specific injection helpers ---

    def _inject_job_site_dns(self, current_date: date, phase: int, rng, dns_events: list):
        """Phase 1+: Browse job sites during lunch. Low frequency to stay under radar."""
        # 1 query per day max — blends with normal web browsing
        max_queries = {1: 2, 2: 2, 3: 2, 4: 2}[phase]
        num_queries = int(rng.integers(1, max_queries))
        for _ in range(num_queries):
            # Lunch break or end-of-day browsing
            hour = float(rng.choice([
                rng.uniform(11.5, 13.5),  # lunch
                rng.uniform(17.0, 18.5),  # end of day
            ]))
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=hour)
            dns_events.append({
                "timestamp": ts.isoformat(),
                "device_id": self.target_device,
                "user_id": self.target_user,
                "query_domain": rng.choice(_JOB_SITES),
                "query_type": "A",
                "response": f"{rng.integers(52, 200)}.{rng.integers(1, 254)}.{rng.integers(1, 254)}.{rng.integers(1, 254)}",
                "attack_id": self.id,
                "label": "insider_job_search",
            })

    def _inject_scope_creep_files(self, current_date: date, phase: int, rng,
                                   file_events: list):
        """Phase 2+: Access files outside normal scope. Sensitivity escalates.

        Volume and classification severity increase each phase to create
        measurable drift in file_restricted_ratio and file_confidential_ratio.
        """
        daily_prob = {2: 0.75, 3: 0.85, 4: 0.95}[phase]
        if rng.random() > daily_prob:
            return

        if phase == 2:
            paths = _FILE_PATHS["curious"]
            num_files = int(rng.integers(5, 12))
            classifications = ["confidential", "confidential", "confidential", "internal"]
            write_prob = 0.10
            size_range = (10_000, 200_000)
        elif phase == 3:
            paths = _FILE_PATHS["curious"] + _FILE_PATHS["recon"]
            num_files = int(rng.integers(10, 20))
            classifications = ["restricted", "restricted", "confidential", "confidential", "confidential"]
            write_prob = 0.25
            size_range = (50_000, 2_000_000)
        else:
            paths = _FILE_PATHS["recon"] + _FILE_PATHS["exfil"]
            num_files = int(rng.integers(15, 30))
            classifications = ["restricted", "restricted", "restricted", "confidential"]
            write_prob = 0.40
            size_range = (100_000, 10_000_000)

        for _ in range(num_files):
            if rng.random() < 0.35:
                hour = float(rng.uniform(18.0, 22.0))
            else:
                hour = float(rng.uniform(9.0, 17.5))
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=hour)

            chosen_dir = rng.choice(paths)
            filename = _random_filename(rng, _DOC_EXTENSIONS)
            operation = "write" if rng.random() < write_prob else "read"

            file_events.append({
                "timestamp": ts.isoformat(),
                "user_id": self.target_user,
                "source_device_id": self.target_device,
                "operation": operation,
                "file_path": f"{chosen_dir}{filename}",
                "file_size_bytes": int(rng.integers(*size_range)),
                "data_classification": rng.choice(classifications),
                "success": True,
                "in_normal_scope": False,
                "attack_id": self.id,
                "label": "insider_scope_creep",
            })

    def _inject_recon_activity(self, current_date: date, rng, file_events: list,
                               network_events: list):
        """Phase 3+: Map network shares, access sensitive directories."""
        if rng.random() < 0.55:
            num_shares = int(rng.integers(2, 5))
            for _ in range(num_shares):
                ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                    hours=float(rng.uniform(10.0, 16.0))
                )
                network_events.append({
                    "timestamp": ts.isoformat(),
                    "src_ip": "10.0.3.156",
                    "dst_ip": f"10.0.1.{rng.integers(1, 10)}",
                    "dst_port": 445,
                    "bytes_out": int(rng.integers(500, 10000)),
                    "bytes_in": int(rng.integers(2000, 50000)),
                    "protocol": "tcp",
                    "duration_ms": int(rng.integers(100, 3000)),
                    "device_id": self.target_device,
                    "user_id": self.target_user,
                    "smb_command": rng.choice([
                        "tree_connect", "query_directory", "enumerate_shares",
                    ]),
                    "target_share": rng.choice(_OTHER_DEPT_SHARES),
                    "attack_id": self.id,
                    "label": "insider_recon_smb",
                })

        # Multiple sensitive file reads per day during recon
        n_recon_files = int(rng.integers(3, 8))
        for _ in range(n_recon_files):
            if rng.random() < 0.65:
                ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                    hours=float(rng.uniform(9.0, 17.0))
                )
                recon_dir = rng.choice(_FILE_PATHS["recon"] + _FILE_PATHS["exfil"])
                filename = _random_filename(rng, _DOC_EXTENSIONS)
                operation = rng.choice(["read", "read", "read", "copy"])
                file_events.append({
                    "timestamp": ts.isoformat(),
                    "user_id": self.target_user,
                    "source_device_id": self.target_device,
                    "operation": operation,
                    "file_path": f"{recon_dir}{filename}",
                    "file_size_bytes": int(rng.integers(100_000, 10_000_000)),
                    "data_classification": rng.choice(["restricted", "restricted", "confidential"]),
                    "success": True,
                    "in_normal_scope": False,
                    "attack_id": self.id,
                    "label": "insider_recon_sensitive_read",
                })

    def _inject_exfil_activity(self, current_date: date, rng, file_events: list,
                               network_events: list, endpoint_events: list,
                               dns_events: list):
        """Phase 4: USB, large copies, email to personal, cloud uploads, bulk transfer."""
        days_into_phase4 = self._days_elapsed(current_date) - int(self._duration_days * 0.75)

        # --- USB device connections (~25% of days) ---
        if rng.random() < 0.25:
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(17.5, 21.0))
            )
            usb_serial = f"USB-{rng.integers(10000, 99999)}"
            endpoint_events.append({
                "timestamp": ts.isoformat(),
                "device_id": self.target_device,
                "user_id": self.target_user,
                "event_type": "usb_connect",
                "usb_device_class": "mass_storage",
                "usb_vendor": rng.choice(["SanDisk", "Kingston", "Samsung", "WD"]),
                "usb_serial": usb_serial,
                "attack_id": self.id,
                "label": "insider_usb_connect",
            })
            num_copies = int(rng.integers(3, 8))
            for i in range(num_copies):
                copy_ts = ts + timedelta(minutes=float(rng.uniform(1, 12) * (i + 1)))
                src_dir = rng.choice(_FILE_PATHS["exfil"] + _FILE_PATHS["recon"])
                filename = _random_filename(rng, _DOC_EXTENSIONS + _ARCHIVE_EXTENSIONS)
                file_events.append({
                    "timestamp": copy_ts.isoformat(),
                    "user_id": self.target_user,
                    "source_device_id": self.target_device,
                    "operation": "copy",
                    "file_path": f"{src_dir}{filename}",
                    "dest_path": f"E:\\{filename}",
                    "file_size_bytes": int(rng.integers(500_000, 20_000_000)),
                    "data_classification": rng.choice(["restricted", "restricted", "confidential"]),
                    "success": True,
                    "attack_id": self.id,
                    "label": "insider_usb_exfil",
                })

        # --- Email to personal account (~25% of days) ---
        if rng.random() < 0.25:
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(16.0, 19.0))
            )
            personal_domain = rng.choice(_PERSONAL_EMAIL_DOMAINS)
            attachment_bytes = int(rng.integers(200_000, 5_000_000))
            network_events.append({
                "timestamp": ts.isoformat(),
                "src_ip": "10.0.3.156",
                "dst_ip": f"142.{rng.integers(200, 255)}.{rng.integers(1, 254)}.{rng.integers(1, 254)}",
                "dst_port": 443,
                "bytes_out": attachment_bytes,
                "bytes_in": int(rng.integers(1000, 5000)),
                "protocol": "tcp",
                "duration_ms": int(rng.integers(2000, 10000)),
                "device_id": self.target_device,
                "user_id": self.target_user,
                "attack_id": self.id,
                "label": "insider_email_exfil",
            })
            dns_events.append({
                "timestamp": ts.isoformat(),
                "device_id": self.target_device,
                "user_id": self.target_user,
                "query_domain": f"smtp.{personal_domain}",
                "query_type": "MX",
                "response": f"142.{rng.integers(200, 255)}.{rng.integers(1, 254)}.{rng.integers(1, 254)}",
                "attack_id": self.id,
                "label": "insider_personal_email_dns",
            })

        # --- Cloud storage uploads (~25% early, ~40% late in phase) ---
        cloud_prob = 0.25 + 0.20 * min(days_into_phase4 / 60.0, 1.0)
        if rng.random() < cloud_prob:
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(18.0, 22.0))
            )
            cloud_target = rng.choice(_PERSONAL_CLOUD)
            dns_events.append({
                "timestamp": ts.isoformat(),
                "device_id": self.target_device,
                "user_id": self.target_user,
                "query_domain": cloud_target,
                "query_type": "A",
                "response": f"{rng.integers(34, 200)}.{rng.integers(1, 254)}.{rng.integers(1, 254)}.{rng.integers(1, 254)}",
                "attack_id": self.id,
                "label": "insider_cloud_storage_dns",
            })
            upload_bytes = int(rng.integers(500_000, 20_000_000))
            network_events.append({
                "timestamp": ts.isoformat(),
                "src_ip": "10.0.3.156",
                "dst_ip": f"{rng.integers(34, 200)}.{rng.integers(1, 254)}.{rng.integers(1, 254)}.{rng.integers(1, 254)}",
                "dst_port": 443,
                "bytes_out": upload_bytes,
                "bytes_in": int(rng.integers(5000, 20000)),
                "protocol": "tcp",
                "duration_ms": int(rng.integers(5000, 30000)),
                "device_id": self.target_device,
                "user_id": self.target_user,
                "attack_id": self.id,
                "label": "insider_cloud_exfil",
            })

        # --- Archive tool usage (~30% of days) ---
        if rng.random() < 0.30:
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(17.0, 20.0))
            )
            endpoint_events.append({
                "timestamp": ts.isoformat(),
                "device_id": self.target_device,
                "user_id": self.target_user,
                "event_type": "process_start",
                "process_name": rng.choice(["7z.exe", "WinRAR.exe", "tar.exe"]),
                "command_line": rng.choice([
                    "7z a -p archive.7z C:\\staging\\*",
                    "WinRAR.exe a -hp docs.rar C:\\temp\\export\\*",
                    "tar.exe -czf backup.tar.gz ./collected/",
                ]),
                "attack_id": self.id,
                "label": "insider_archive_tool",
            })

        # --- Trickle data transfer (final weeks, ~30% of days) ---
        if days_into_phase4 > int(self._duration_days * 0.15) and rng.random() < 0.30:
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(21.0, 23.5))
            )
            network_events.append({
                "timestamp": ts.isoformat(),
                "src_ip": "10.0.3.156",
                "dst_ip": f"{rng.integers(50, 200)}.{rng.integers(1, 254)}.{rng.integers(1, 254)}.{rng.integers(1, 254)}",
                "dst_port": 443,
                "bytes_out": int(rng.integers(1_000_000, 20_000_000)),
                "bytes_in": int(rng.integers(5000, 20000)),
                "protocol": "tcp",
                "duration_ms": int(rng.integers(5000, 30000)),
                "device_id": self.target_device,
                "user_id": self.target_user,
                "attack_id": self.id,
                "label": "insider_trickle_exfil",
            })

    @property
    def mitre_techniques(self) -> list[str]:
        return [
            "T1078",  # Valid Accounts
            "T1083",  # File and Directory Discovery
            "T1005",  # Data from Local System
            "T1039",  # Data from Network Shared Drive
            "T1052",  # Exfiltration Over Physical Medium (USB)
            "T1048",  # Exfiltration Over Alternative Protocol
            "T1567",  # Exfiltration Over Web Service (cloud storage)
        ]

    @property
    def involved_entities(self) -> dict[str, list[str]]:
        return {
            "users": [self.target_user],
            "devices": [self.target_device],
            "ips": ["10.0.3.156"],
        }
