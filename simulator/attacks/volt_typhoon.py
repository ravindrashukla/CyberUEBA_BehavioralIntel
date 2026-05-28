"""Volt Typhoon attack scenario: Living-off-the-land persistent infrastructure access.

Models the real-world Volt Typhoon (Bronze Silhouette) campaign:
  - State-sponsored actor targeting critical infrastructure
  - Uses only legitimate admin tools (PowerShell, WMI, certutil, netsh, PsExec)
  - No custom malware — blends with normal IT admin activity
  - Credential harvesting via native OS tools
  - Lateral movement via RDP, SMB, WMI across network segments
  - Pre-positioning for future disruption, not immediate data theft
  - Compromised SOHO router as external proxy for minimal C2

Key behavioral signals for UEBA:
  - Gradual expansion of unique internal destinations (lateral spread)
  - Admin tool execution at unusual hours (off-hours LOTL)
  - Cross-segment network flows (internal → restricted → management)
  - Access to infrastructure documentation outside normal job scope
  - Very low external traffic (no noisy C2 beacon pattern)
"""

from datetime import date, datetime, timedelta
import numpy as np

from .base import AttackScenario

_LOTL_TOOLS = [
    ("powershell.exe", "powershell -ep bypass -c Get-ADUser -Filter *"),
    ("powershell.exe", "powershell -c Invoke-Command -ComputerName {target} -ScriptBlock {{whoami}}"),
    ("wmic.exe", "wmic /node:{target} process list brief"),
    ("wmic.exe", "wmic /node:{target} os get caption,version"),
    ("certutil.exe", "certutil -urlcache -split -f https://update.microsoft.com/check"),
    ("netsh.exe", "netsh advfirewall show allprofiles"),
    ("netsh.exe", "netsh interface portproxy add v4tov4 listenport=8080 connectaddress={target}"),
    ("nltest.exe", "nltest /dclist:corp.local"),
    ("reg.exe", "reg query HKLM\\SAM\\SAM\\Domains\\Account\\Users"),
    ("ntdsutil.exe", "ntdsutil \"activate instance ntds\" ifm \"create full c:\\temp\\ntds\""),
    ("cmdkey.exe", "cmdkey /list"),
    ("vssadmin.exe", "vssadmin create shadow /for=C:"),
    ("tasklist.exe", "tasklist /v /fo csv"),
    ("net.exe", "net user /domain"),
    ("net.exe", "net group \"Domain Admins\" /domain"),
]

_INFRA_DOCS = [
    "/it-ops/network-diagrams/core-topology.vsdx",
    "/it-ops/network-diagrams/wan-links.vsdx",
    "/it-ops/runbooks/firewall-rules.xlsx",
    "/it-ops/runbooks/vpn-config.docx",
    "/it-ops/runbooks/backup-schedules.xlsx",
    "/it-ops/cmdb/asset-inventory.xlsx",
    "/security/policies/incident-response-plan.pdf",
    "/security/policies/access-control-matrix.xlsx",
    "/executive/strategy/infrastructure-roadmap.pptx",
    "/it-ops/scada/plc-configuration.docx",
    "/it-ops/scada/hmi-credentials.xlsx",
    "/it-ops/scada/ot-network-segments.vsdx",
]

_INTERNAL_TARGETS = [
    ("10.0.1.{n}", "management"),
    ("10.0.2.{n}", "internal"),
    ("10.0.3.{n}", "restricted"),
    ("10.0.4.{n}", "dmz"),
    ("10.0.5.{n}", "internal"),
    ("10.0.10.{n}", "management"),
    ("10.0.20.{n}", "restricted"),
]


class VoltTyphoonAttack(AttackScenario):
    """Living-off-the-land APT: credential harvest + lateral movement + pre-positioning.

    4 phases over ~120 days:
      Phase 1 (days 1-14):  Initial VPN access, light recon
      Phase 2 (days 15-45): Credential harvesting via LOTL tools
      Phase 3 (days 46-90): Lateral movement across segments
      Phase 4 (days 91+):   Pre-positioning, infrastructure access
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.duration_days = config.get("duration_days", 120)
        self.target_user = config.get("target_user", "USR-042")
        user_device_map = config.get("_user_device_map", {})
        self.target_device = config.get("target_device",
                                        user_device_map.get(self.target_user, "DEV-042"))
        self.proxy_ip = config.get("proxy_ip", "203.0.113.88")
        self._start_date = (
            self.start if isinstance(self.start, date)
            else datetime.fromisoformat(self.start).date()
        )
        self._end_date = self._start_date + timedelta(days=self.duration_days)
        self._compromised_systems: list[str] = []

    def is_active(self, current_date: date) -> bool:
        return self._start_date <= current_date <= self._end_date

    def _days_elapsed(self, current_date: date) -> int:
        return (current_date - self._start_date).days

    def _phase(self, current_date: date) -> int:
        progress = self._days_elapsed(current_date) / max(self.duration_days, 1)
        if progress < 0.12:
            return 1
        if progress < 0.38:
            return 2
        if progress < 0.75:
            return 3
        return 4

    def _daily_probability(self, current_date: date) -> float:
        phase = self._phase(current_date)
        return {1: 0.15, 2: 0.25, 3: 0.35, 4: 0.25}[phase]

    def modify_auth_events(self, user_id, events, current_date, rng):
        if not self.is_active(current_date) or user_id != self.target_user:
            return events
        if rng.random() > self._daily_probability(current_date):
            return events

        phase = self._phase(current_date)
        days_in = self._days_elapsed(current_date)

        if phase == 1:
            if rng.random() < 0.40:
                ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                    hours=float(rng.uniform(22, 23.5))
                )
                events.append({
                    "timestamp": ts.isoformat(),
                    "user_id": user_id,
                    "event_type": "login",
                    "source_ip": self.proxy_ip,
                    "auth_method": "vpn",
                    "success": True,
                    "geo_country": "US",
                    "off_hours": True,
                    "attack_id": self.id,
                    "label": "volt_initial_access",
                })

        elif phase >= 2:
            n_hops = min(1 + days_in // 50, 2)
            for _ in range(rng.integers(1, n_hops + 1)):
                seg_idx = min(phase - 1, len(_INTERNAL_TARGETS) - 1)
                avail = _INTERNAL_TARGETS[:seg_idx + 2]
                ip_tmpl, zone = avail[rng.integers(0, len(avail))]
                target_ip = ip_tmpl.format(n=rng.integers(10, 200))
                method = rng.choice(["rdp", "ntlm", "kerberos"])

                hour = float(rng.choice([
                    rng.uniform(1, 5),
                    rng.uniform(10, 16),
                    rng.uniform(21, 23.5),
                ]))
                ts = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=hour)

                src_host = 10 + (hash(user_id) % 3)
                events.append({
                    "timestamp": ts.isoformat(),
                    "user_id": user_id,
                    "event_type": "login",
                    "source_ip": f"10.0.5.{src_host}",
                    "destination_ip": target_ip,
                    "destination_zone": zone,
                    "auth_method": method,
                    "success": True,
                    "off_hours": hour < 7 or hour > 19,
                    "new_device": target_ip not in self._compromised_systems,
                    "attack_id": self.id,
                    "label": "volt_lateral_movement",
                })
                if target_ip not in self._compromised_systems:
                    self._compromised_systems.append(target_ip)

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
        endpoint_events = []
        file_events = []
        dns_events = []

        # LOTL tool execution (phases 2+)
        if phase >= 2:
            n_tools = rng.integers(1, 3 + phase)
            for _ in range(n_tools):
                tool_name, cmd_template = _LOTL_TOOLS[rng.integers(0, len(_LOTL_TOOLS))]
                target_ip = f"10.0.{rng.integers(1, 20)}.{rng.integers(10, 200)}"
                cmd = cmd_template.format(target=target_ip)
                hour = float(rng.choice([
                    rng.uniform(2, 5),
                    rng.uniform(11, 15),
                    rng.uniform(21, 23),
                ]))
                ts = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=hour)
                endpoint_events.append({
                    "timestamp": ts.isoformat(),
                    "device_id": self.target_device,
                    "user_id": self.target_user,
                    "event_type": "process_start",
                    "process_name": tool_name,
                    "command_line": cmd,
                    "parent_process": "cmd.exe",
                    "attack_id": self.id,
                    "label": "volt_lotl_execution",
                })

        # Internal lateral movement traffic (phases 3+)
        if phase >= 3:
            n_flows = rng.integers(2, 6 + (phase - 2) * 3)
            for _ in range(n_flows):
                seg_idx = min(phase, len(_INTERNAL_TARGETS) - 1)
                avail = _INTERNAL_TARGETS[:seg_idx + 1]
                ip_tmpl, _ = avail[rng.integers(0, len(avail))]
                dst_ip = ip_tmpl.format(n=rng.integers(10, 200))
                port = int(rng.choice([445, 3389, 5985, 22, 135, 139]))

                ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                    hours=float(rng.uniform(0, 24))
                )
                network_events.append({
                    "timestamp": ts.isoformat(),
                    "src_ip": f"10.0.5.{rng.integers(10, 50)}",
                    "dst_ip": dst_ip,
                    "dst_port": port,
                    "bytes_out": int(rng.integers(500, 15000)),
                    "bytes_in": int(rng.integers(200, 8000)),
                    "protocol": "tcp",
                    "device_id": self.target_device,
                    "attack_id": self.id,
                    "label": "volt_lateral_traffic",
                })

        # Minimal external proxy check-in (once every 3-5 days, phase 2+)
        if phase >= 2 and days_in % rng.integers(3, 6) == 0:
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(2, 5))
            )
            network_events.append({
                "timestamp": ts.isoformat(),
                "src_ip": f"10.0.5.{rng.integers(10, 50)}",
                "dst_ip": self.proxy_ip,
                "dst_port": 443,
                "bytes_out": int(rng.integers(100, 800)),
                "bytes_in": int(rng.integers(50, 400)),
                "protocol": "tcp",
                "device_id": self.target_device,
                "attack_id": self.id,
                "label": "volt_proxy_checkin",
            })

        # Infrastructure document access (phases 3+)
        if phase >= 3 and rng.random() < 0.35:
            progress = min(days_in / self.duration_days, 1.0)
            max_doc_idx = min(int(progress * len(_INFRA_DOCS)), len(_INFRA_DOCS) - 1)
            doc_path = _INFRA_DOCS[rng.integers(0, max_doc_idx + 1)]
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(10, 16))
            )
            classification = "restricted" if "scada" in doc_path or "credential" in doc_path else "confidential"
            file_events.append({
                "timestamp": ts.isoformat(),
                "user_id": self.target_user,
                "source_device_id": self.target_device,
                "operation": "read",
                "file_path": doc_path,
                "file_size_bytes": int(rng.integers(50_000, 2_000_000)),
                "data_classification": classification,
                "success": True,
                "attack_id": self.id,
                "label": "volt_infra_recon",
            })

        # Internal DNS recon (phase 2+)
        if phase >= 2 and rng.random() < 0.25:
            internal_domains = [
                "dc01.corp.local", "dc02.corp.local", "exchange.corp.local",
                "fileserver.corp.local", "backup.corp.local", "scada-hmi.corp.local",
                "vpn-gw.corp.local", "pki-ca.corp.local",
            ]
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(
                hours=float(rng.uniform(9, 17))
            )
            dns_events.append({
                "timestamp": ts.isoformat(),
                "device_id": self.target_device,
                "query_domain": rng.choice(internal_domains),
                "query_type": "A",
                "response": f"10.0.{rng.integers(1, 10)}.{rng.integers(1, 50)}",
                "attack_id": self.id,
                "label": "volt_internal_recon",
            })

        result = {}
        if network_events:
            result["network"] = network_events
        if endpoint_events:
            result["endpoint"] = endpoint_events
        if file_events:
            result["file"] = file_events
        if dns_events:
            result["dns"] = dns_events
        return result

    @property
    def mitre_techniques(self):
        return [
            "T1059.001",  # PowerShell
            "T1003",      # OS Credential Dumping
            "T1021",      # Remote Services (RDP, SMB, WMI)
            "T1078",      # Valid Accounts
            "T1090",      # Proxy
            "T1570",      # Lateral Tool Transfer
            "T1083",      # File and Directory Discovery
            "T1018",      # Remote System Discovery
        ]

    @property
    def involved_entities(self):
        return {
            "users": [self.target_user],
            "devices": [self.target_device],
            "ips": [self.proxy_ip],
        }
