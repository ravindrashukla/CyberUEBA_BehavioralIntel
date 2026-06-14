# V-Intelligence UEBA Complete Anomalous Scenario Inventory

8 attack scenarios spanning the full MITRE ATT&CK kill chain, injected across 82M+ events, 250 users, 300 devices, 30 roles, 15 departments, and 7 telemetry log types.

---

## ATK-001: Brute Force Credential Stuffing

| Field | Detail |
|---|---|
| **Duration** | 4 hours (single day -- 2026-03-15) |
| **Scale** | 50 targeted users, 20-50 failed attempts each |
| **Infrastructure** | 10 botnet IPs across Russia, China, Brazil |
| **Outcome** | 3 users compromised (USR-302, USR-317, USR-341) |
| **Post-compromise** | Lateral access to /admin/config, /hr/payroll, /finance/reports |
| **Log types injected** | auth, network |
| **MITRE techniques** | T1110 (Brute Force), T1078 (Valid Accounts) |
| **Detection challenge** | High-volume auth failures followed by anomalous access patterns |

---

## ATK-002: Phishing > Credential Theft > Lateral Movement

| Field | Detail |
|---|---|
| **Duration** | 5 days (2026-02-01 to 2026-02-05) |
| **Target** | USR-087, DEV-087 |
| **Attacker IPs** | 3 IPs in Romania / Netherlands |
| **Log types injected** | auth, network, file, endpoint |
| **MITRE techniques** | T1566, T1078, T1003, T1021, T1074, T1048 |

**Day-by-day progression:**

| Day | Activity |
|---|---|
| **Day 1** | Phishing click: outlook.exe spawns powershell.exe. Credential exfil to attacker IP. Stolen credential reuse from Romania. |
| **Day 2** | Off-hours access. Credential store reads (/etc/shadow, SAM, vault). mimikatz / procdump execution. |
| **Days 3-4** | Lateral movement to 7 devices across internal / restricted / management segments via NTLM, Kerberos, SSH. |
| **Day 5** | Staging 5-12 sensitive files (employee_roster, budget, api_keys, source_code). Exfiltration (1-50 MB flows). |

---

## ATK-003: Slow APT with C2 Beacon

| Field | Detail |
|---|---|
| **Duration** | 180 days (2025-08-01 to 2026-01-28) |
| **Target** | USR-234, DEV-234 |
| **C2 IP** | 198.51.100.47 |
| **Log types injected** | network, dns, file, auth |
| **MITRE techniques** | T1071, T1573, T1074, T1048 |
| **Detection challenge** | Per-day deviation is intentionally tiny; requires CUSUM / behavioral drift over weeks |

**Daily activity:**

- ~32 C2 beacons per day (every 45 min +/- 10 min jitter), tiny packets (100-500 bytes)
- 1-3 DGA DNS queries per day (random consonant/vowel domains)
- Data staging every 17 days -- progressively accessing 10 sensitivity tiers:
  `/shared/docs/general` > `/engineering/repos` > `/finance/budgets` > `/security/audit-logs` > `/executive/strategy`
- Privilege escalation every 30 days (days 30, 60, 90, 120, 150)

---

## ATK-004: Insider Threat (Disgruntled Employee)

| Field | Detail |
|---|---|
| **Duration** | 8 months (2025-06-01 to 2026-01-28) |
| **Target** | USR-156, DEV-156 |
| **Log types injected** | auth, file, dns, network, endpoint |
| **MITRE techniques** | T1078, T1083, T1005, T1039, T1052, T1048, T1567 |
| **Detection challenge** | No single day is malicious. Detection requires viewing directional trend over months. **The KEY test case for CUSUM / trajectory detection.** |

**4-phase escalation:**

| Phase | Months | Activity |
|---|---|---|
| **Phase 1: Mood shift** | Months 1-2 | Off-hours logins (25% daily). Job site browsing (LinkedIn, Indeed, Glassdoor) -- 1-2 DNS queries/day. |
| **Phase 2: Curiosity** | Months 3-4 | File scope creep -- accessing /hr/org-charts, /finance/budgets, /legal/contracts (40% of days, 1-3 files). |
| **Phase 3: Reconnaissance** | Months 5-6 | SMB enumeration of cross-dept shares (//fs01/finance$, //fs01/hr$). Reading restricted docs (/security/network-maps, /executive/strategy). Privilege elevation requests. |
| **Phase 4: Exfiltration** | Months 7-8 | USB device connections (SanDisk/Kingston, 20% of days). Email to personal accounts (gmail, protonmail -- 25%). Cloud storage uploads (Dropbox, Google Drive, Mega.nz -- 25-45%). Archive tool usage (7z, WinRAR -- 15%). Bulk data transfer (100-500 MB at night, final 2 weeks). |

---

## ATK-005: Ransomware Deployment

| Field | Detail |
|---|---|
| **Duration** | 6 hours (2026-04-10) |
| **Initial device** | DEV-342 (10.0.6.42) |
| **Attacker IP** | 45.155.205.99 (Russia) |
| **Spread targets** | 10 devices (DEV-101, DEV-204, DEV-310, SRV-017, SRV-042, SRV-055, etc.) |
| **Log types injected** | auth, network, file, endpoint |
| **MITRE techniques** | T1021.001, T1046, T1570, T1486, T1490 |
| **Detection challenge** | Fast and loud; tests multi-device burst detection |

**Hour-by-hour:**

| Hour | Activity |
|---|---|
| **Hour 1** | 3-8 RDP auth failures then success as Administrator |
| **Hour 2** | 50-150 port scans (445, 135, 3389, 5985, 22). Recon tools: netscan, nbtscan, net.exe, nltest. |
| **Hour 3** | Lateral spread to 6-10 devices via NTLM/WMI/PsExec. Ransomware binary deployment via SMB. |
| **Hours 4-5** | Mass encryption: 50-200 file_write events per device (encrypt.exe, locker.exe, crypt32svc.exe). Shadow copy deletion (vssadmin delete shadows). |
| **Hour 6** | Ransom note deployment (README_DECRYPT.txt, HOW_TO_RECOVER.html) -- 5-15 notes per device. |

---

## ATK-006: Supply Chain Compromise

| Field | Detail |
|---|---|
| **Duration** | 90 days dormant + indefinite active (2025-10-01 onward) |
| **Compromised app** | APP-017 across 15 devices |
| **C2 IPs** | 3 IPs on Azure, AWS CloudFront, Cloudflare (legitimate cloud providers) |
| **Log types injected** | dns, network, app |
| **MITRE techniques** | T1195.002, T1071, T1568, T1005, T1041 |
| **Detection challenge** | Extremely subtle; each event looks benign; requires accumulation analysis |

**Dormant phase (days 1-90):**

- 1-3 devices per day make 1 DGA DNS query each (looks like failed update check)
- 20% chance per device per day of 5-15% traffic increase (within normal variance)

**Active phase (post-day 90):**

- C2 callbacks: 3-6 per day per device, every 4-8 hours, small HTTPS packets
- Data collection every 2-3 days: SQL queries against user_directory, device_inventory, api_keys, config_secrets
- Exfiltration starts day 120+: 50 KB - 500 KB per day from one device

---

## ATK-007: Volt Typhoon — Living Off The Land (LOTL)

| Field | Detail |
|---|---|
| **Duration** | 115 days (2025-01-15 to 2025-05-10) |
| **Target** | USR-042, DEV-042 |
| **Proxy IP** | 203.0.113.88 |
| **Log types injected** | auth, network, dns, endpoint, file |
| **MITRE techniques** | T1078, T1003, T1021, T1059, T1036, T1057, T1083 |
| **Detection challenge** | Uses only legitimate admin tools (PowerShell, WMI, PsExec); no malware binaries to signature-match |

**Key behavioral signals:**
- Credential harvesting using built-in tools (mimikatz, procdump, comsvcs.dll)
- Lateral movement via legitimate protocols (RDP, WMI, PsExec) across internal segments
- Infrastructure pre-positioning: accessing network configs, firewall rules, SCADA/ICS documentation
- Proxy-based C2 through SOHO routers (blends with normal admin traffic)
- Gradual privilege escalation through valid credential reuse

---

## ATK-008: Salt Typhoon — Telecom Infrastructure Interception

| Field | Detail |
|---|---|
| **Duration** | 100 days (2025-01-20 to 2025-04-30) |
| **Target** | USR-118, DEV-001 (edge network device) |
| **C2 domain** | cdn-check.microsoftupdate-service.com |
| **Exfil IP** | 198.18.0.77 |
| **Log types injected** | auth, network, dns, file, endpoint |
| **MITRE techniques** | T1071, T1568, T1005, T1041, T1556, T1557 |
| **Detection challenge** | Targets network infrastructure itself; kernel-level persistence on network appliances |

**4-phase progression:**

| Phase | Days | Activity |
|---|---|---|
| **Phase 1: Edge compromise** | 1-10 | Exploit edge network device, establish kernel-level persistence |
| **Phase 2: Infrastructure mapping** | 11-40 | Network config access, routing table collection, ACL enumeration |
| **Phase 3: CDR collection** | 41-75 | Access call detail records, SMS metadata, lawful intercept systems |
| **Phase 4: Exfiltration** | 76-100 | DNS tunneling for C2, staged data exfil via HTTPS to external IP |

---

## Detection Target Library: 12 Reference Concepts

| # | Concept | Category | Severity | MITRE Techniques |
|---|---|---|---|---|
| 1 | compromised_endpoint | Threat | Critical | T1059, T1547, T1562, T1071 |
| 2 | data_exfiltration | Threat | Critical | T1005, T1074, T1048, T1567 |
| 3 | insider_threat_fast | Threat | Critical | T1005, T1052, T1048, T1567 |
| 4 | c2_beacon | Threat | Critical | T1071, T1573, T1568, T1102 |
| 5 | supply_chain_compromise | Threat | Critical | T1195, T1059, T1071 |
| 6 | privilege_escalation | Threat | High | T1078, T1068, T1134, T1548 |
| 7 | lateral_movement | Threat | High | T1021, T1570, T1550, T1072 |
| 8 | insider_threat_slow | Threat | High | T1078, T1083, T1005, T1052 |
| 9 | credential_stuffing | Threat | High | T1110, T1078 |
| 10 | reconnaissance | Threat | Medium | T1046, T1018, T1087, T1135 |
| 11 | normal_role_change | Benign | Low | -- |
| 12 | seasonal_variation | Benign | Low | -- |

---

## Key Differentiator

ATK-003 (slow APT), ATK-004 (insider threat), ATK-007 (Volt Typhoon), and ATK-008 (Salt Typhoon) are specifically designed to be **undetectable by traditional SIEM rules** -- no single event crosses any threshold. Cumulative behavioral analysis is required to catch them.

The system detects anomalies by tracking 5 independent behavioral signals per entity via high-dimensional embeddings, complemented by direct known-bad behavioral profiles. The clean 4/4-at-0-false-positives result comes from the multi-front threat-profile detector (`threat_profile_detector.py`) — measurable profiles such as C2-beacon, DGA-DNS, LOTL-process, cohort-rare access, recon-fanout, and insider-collection, scored cohort-relative + raw-event, label-free.

CUSUM change-point detection contributes, but its value is **attack-dependent**, not universal: embedding CUSUM surfaces the insider (USR-156) and LOTL (USR-042) campaigns roughly 30 weeks earlier than threshold methods, fires LATER for the volume-driven Salt Typhoon (USR-118), and never separates the slow-APT (USR-234). It is one signal among several, not a stand-alone win.

**Current data coverage:** 250 users, 300 devices, the full 485-day generation window (2025-01-01 to 2026-04-30). Slow-burn attacks ATK-003, ATK-004, ATK-007, ATK-008 are embedded across this window; the fast/loud scenarios ATK-001, ATK-002, ATK-005, ATK-006 are also injected on their respective dates within the 485-day span.

**Attack spectrum coverage:**
- **Fast/loud**: Brute force (4 hours), Ransomware (6 hours)
- **Medium pace**: Credential theft (5 days)
- **Slow/stealthy**: Supply chain (90-day dormancy), APT C2 (180 days), Insider threat (8 months)
