"""Simulation configuration for Cyber UEBA synthetic data generation."""
from datetime import date, timedelta

SIM_START = date(2025, 1, 1)
SIM_END = date(2026, 5, 1)
CURRENT_DATE = date(2026, 5, 1)
SIM_DAYS = (SIM_END - SIM_START).days

N_USERS = 250
N_DEVICES = 400
N_SEGMENTS = 25
N_APPLICATIONS = 60
N_ROLES = 30

USER_TYPE_DIST = {"employee": 0.80, "contractor": 0.15, "service_account": 0.05}
DEVICE_TYPE_DIST = {"endpoint": 0.80, "server": 0.12, "network_appliance": 0.05, "iot": 0.03}
SEGMENT_ZONES = ["dmz", "internal", "restricted", "management", "guest"]

AUTH_EVENTS_PER_USER_DAY = 8
NETWORK_FLOWS_PER_DEVICE_DAY = 40
DNS_QUERIES_PER_DEVICE_DAY = 10
ENDPOINT_EVENTS_PER_DEVICE_DAY = 8
FILE_ACCESS_PER_USER_DAY = 10
APP_EVENTS_PER_USER_DAY = 5
PRIV_OPS_PER_DAY = 5

WORK_HOURS = (8, 18)
WORK_DAYS = [0, 1, 2, 3, 4]

DEPARTMENTS = [
    "Engineering", "Finance", "HR", "Legal", "IT Operations",
    "Security", "Sales", "Marketing", "Executive", "Research",
    "Supply Chain", "Customer Support", "Data Science", "DevOps", "QA",
]

ROLES = [
    "Software Engineer", "Senior Engineer", "Staff Engineer",
    "Financial Analyst", "Accountant", "CFO",
    "HR Specialist", "HR Manager", "Recruiter",
    "IT Admin", "Network Engineer", "SysAdmin", "DBA",
    "Security Analyst", "SOC Operator", "CISO",
    "Sales Rep", "Account Manager", "VP Sales",
    "Data Scientist", "ML Engineer", "Analyst",
    "DevOps Engineer", "SRE", "Cloud Architect",
    "QA Engineer", "Test Lead",
    "CEO", "CTO", "COO", "General Counsel",
]

CLEARANCE_LEVELS = ["public", "internal", "confidential", "restricted", "top_secret"]

OS_TYPES = {
    "endpoint": [("Windows 11", 0.6), ("macOS 14", 0.3), ("Ubuntu 22.04", 0.1)],
    "server": [("Ubuntu 22.04", 0.4), ("RHEL 9", 0.3), ("Windows Server 2022", 0.3)],
    "network_appliance": [("Cisco IOS-XE", 0.5), ("Junos OS", 0.3), ("PAN-OS", 0.2)],
    "iot": [("Embedded Linux", 0.7), ("RTOS", 0.3)],
}

DATA_CLASSIFICATIONS = ["public", "internal", "confidential", "restricted"]

APP_TYPES = ["service", "database", "cloud_resource", "web_app", "api"]

ATTACK_SCENARIOS = [
    {
        "id": "ATK-001",
        "type": "brute_force",
        "start": date(2026, 3, 15),
        "duration_hours": 4,
        "target_users": 50,
        "description": "Credential stuffing from external botnet",
    },
    {
        "id": "ATK-002",
        "type": "credential_theft_lateral",
        "start": date(2026, 2, 1),
        "duration_days": 5,
        "compromised_user": "USR-087",
        "description": "Phishing → credential theft → lateral movement",
    },
    {
        "id": "ATK-003",
        "type": "apt_slow",
        "start": date(2025, 3, 10),
        "duration_days": 65,
        "c2_interval_minutes": 360,
        "target_user": "USR-234",
        "description": "Slow APT with periodic C2 beacon and gradual data staging",
    },
    {
        "id": "ATK-004",
        "type": "insider_threat",
        "start": date(2025, 3, 10),
        "escalation_months": 2,
        "user": "USR-156",
        "description": "Disgruntled employee gradually escalating access and exfiltrating data",
    },
    {
        "id": "ATK-005",
        "type": "ransomware",
        "start": date(2026, 4, 10),
        "duration_hours": 6,
        "initial_device": "DEV-342",
        "description": "Ransomware deployment via compromised RDP",
    },
    {
        "id": "ATK-006",
        "type": "supply_chain",
        "start": date(2025, 10, 1),
        "compromised_app": "APP-017",
        "dormant_days": 90,
        "description": "Legitimate app update contains backdoor, activates after dormancy",
    },
    {
        "id": "ATK-007",
        "type": "volt_typhoon",
        "start": date(2025, 3, 15),
        "duration_days": 60,
        "target_user": "USR-042",
        "proxy_ip": "203.0.113.88",
        "description": "Volt Typhoon: LOTL credential harvest + lateral movement + infrastructure pre-positioning",
    },
    {
        "id": "ATK-008",
        "type": "salt_typhoon",
        "start": date(2025, 3, 15),
        "duration_days": 60,
        "target_user": "USR-118",
        "c2_domain": "cdn-check.microsoftupdate-service.com",
        "exfil_ip": "198.18.0.77",
        "description": "Salt Typhoon: Telecom infrastructure interception via edge device compromise + CDR exfil",
    },
]

MITRE_TACTICS_ORDER = [
    "Reconnaissance", "Resource Development", "Initial Access",
    "Execution", "Persistence", "Privilege Escalation",
    "Defense Evasion", "Credential Access", "Discovery",
    "Lateral Movement", "Collection", "Command and Control",
    "Exfiltration", "Impact",
]
