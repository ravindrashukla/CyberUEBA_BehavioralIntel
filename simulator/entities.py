"""Synthetic entity generator for Cyber UEBA simulation."""
import numpy as np
import pandas as pd

from simulator.config import (
    N_USERS, N_DEVICES, N_SEGMENTS, N_APPLICATIONS,
    USER_TYPE_DIST, DEVICE_TYPE_DIST, SEGMENT_ZONES,
    DEPARTMENTS, ROLES, CLEARANCE_LEVELS, OS_TYPES,
    DATA_CLASSIFICATIONS, APP_TYPES,
)

SEED = 42


def _rng():
    return np.random.default_rng(SEED)


def generate_users() -> pd.DataFrame:
    rng = _rng()
    n = N_USERS

    user_ids = [f"USR-{i+1:03d}" for i in range(n)]

    types = rng.choice(
        list(USER_TYPE_DIST.keys()),
        size=n,
        p=list(USER_TYPE_DIST.values()),
    )

    departments = rng.choice(DEPARTMENTS, size=n)
    roles = rng.choice(ROLES, size=n)

    clearance_weights = np.array([0.30, 0.30, 0.20, 0.15, 0.05])
    clearances = rng.choice(CLEARANCE_LEVELS, size=n, p=clearance_weights)

    # Service accounts don't have managers; others get a random employee as manager
    employee_mask = types == "employee"
    employee_indices = np.where(employee_mask)[0]
    managers = []
    for i in range(n):
        if types[i] == "service_account":
            managers.append(None)
        elif len(employee_indices) > 0:
            mgr_idx = rng.choice(employee_indices)
            managers.append(user_ids[mgr_idx])
        else:
            managers.append(None)

    usernames = []
    for i in range(n):
        if types[i] == "service_account":
            usernames.append(f"svc_{departments[i].lower().replace(' ', '_')}_{i:03d}")
        else:
            first = rng.choice(["james", "maria", "chen", "anna", "raj", "sarah",
                                "david", "priya", "alex", "fatima", "john", "li",
                                "omar", "elena", "yuki", "carlos", "aisha", "erik",
                                "mei", "noah"])
            last = rng.choice(["smith", "johnson", "williams", "patel", "kim",
                               "chen", "garcia", "mueller", "tanaka", "okonkwo",
                               "santos", "larsson", "khan", "dubois", "silva",
                               "wang", "volkov", "ross", "nair", "berg"])
            usernames.append(f"{first}.{last}{i:03d}")

    hire_days_ago = rng.integers(30, 2000, size=n)

    return pd.DataFrame({
        "user_id": user_ids,
        "username": usernames,
        "user_type": types,
        "department": departments,
        "role": roles,
        "clearance": clearances,
        "manager_id": managers,
        "tenure_days": hire_days_ago,
    })


def generate_network_segments() -> pd.DataFrame:
    rng = _rng()
    n = N_SEGMENTS

    seg_ids = [f"SEG-{i+1:02d}" for i in range(n)]

    zones = rng.choice(SEGMENT_ZONES, size=n)
    vlans = list(range(10, 10 + n))

    trust_levels = {
        "dmz": 1, "guest": 1, "internal": 3, "management": 4, "restricted": 5,
    }
    trust = [trust_levels[z] for z in zones]

    # Generate /24 CIDRs from 10.x.y.0
    cidrs = [f"10.{(i // 8) + 1}.{(i % 8) * 32}.0/24" for i in range(n)]

    # Adjacency: each segment connects to 2-4 others
    adjacency = []
    for i in range(n):
        n_adj = rng.integers(2, 5)
        candidates = [j for j in range(n) if j != i]
        adj_indices = rng.choice(candidates, size=min(n_adj, len(candidates)), replace=False)
        adjacency.append([seg_ids[j] for j in adj_indices])

    return pd.DataFrame({
        "segment_id": seg_ids,
        "cidr": cidrs,
        "vlan": vlans,
        "zone": zones,
        "trust_level": trust,
        "adjacent_segments": adjacency,
    })


def generate_devices(users_df: pd.DataFrame, segments_df: pd.DataFrame) -> pd.DataFrame:
    rng = _rng()
    n = N_DEVICES

    dev_ids = [f"DEV-{i+1:03d}" for i in range(n)]

    types = rng.choice(
        list(DEVICE_TYPE_DIST.keys()),
        size=n,
        p=list(DEVICE_TYPE_DIST.values()),
    )

    # Assign OS based on device type
    os_list = []
    for dtype in types:
        options = OS_TYPES[dtype]
        names, probs = zip(*options)
        os_list.append(rng.choice(names, p=probs))

    # Assign to segments
    segment_ids = segments_df["segment_id"].values
    seg_assignments = rng.choice(segment_ids, size=n)

    # Build IP from segment CIDR
    cidr_map = dict(zip(segments_df["segment_id"], segments_df["cidr"]))
    host_counters = {}
    ips = []
    for seg in seg_assignments:
        base = cidr_map[seg].replace(".0/24", "")
        host_counters[seg] = host_counters.get(seg, 0) + 1
        host = host_counters[seg]
        ips.append(f"{base}.{host}")

    # Assign owner (endpoints → users, servers/appliances/iot → None or IT)
    owners = []
    human_users = users_df[users_df["user_type"] != "service_account"]["user_id"].values
    for dtype in types:
        if dtype == "endpoint" and len(human_users) > 0:
            owners.append(rng.choice(human_users))
        else:
            owners.append(None)

    hostnames = []
    for i, dtype in enumerate(types):
        prefix = {"endpoint": "WS", "server": "SRV", "network_appliance": "NET", "iot": "IOT"}[dtype]
        hostnames.append(f"{prefix}-{i+1:04d}")

    return pd.DataFrame({
        "device_id": dev_ids,
        "hostname": hostnames,
        "device_type": types,
        "os": os_list,
        "ip_address": ips,
        "segment_id": seg_assignments,
        "owner_user_id": owners,
    })


def generate_applications(segments_df: pd.DataFrame) -> pd.DataFrame:
    rng = _rng()
    n = N_APPLICATIONS

    app_ids = [f"APP-{i+1:03d}" for i in range(n)]

    app_types = rng.choice(APP_TYPES, size=n)
    classifications = rng.choice(DATA_CLASSIFICATIONS, size=n)

    segment_ids = segments_df["segment_id"].values
    hosting_segments = rng.choice(segment_ids, size=n)

    criticality_levels = ["low", "medium", "high", "critical"]
    criticality_weights = [0.20, 0.40, 0.30, 0.10]
    criticalities = rng.choice(criticality_levels, size=n, p=criticality_weights)

    app_names = [
        "ActiveDirectory", "Exchange", "SharePoint", "SAP_ERP", "Salesforce",
        "Jira", "Confluence", "GitHub_Enterprise", "Jenkins", "SonarQube",
        "Splunk", "CrowdStrike", "Zscaler", "Okta", "AWS_Console",
        "Azure_Portal", "GCP_Console", "Snowflake", "Databricks", "Tableau",
        "ServiceNow", "Workday", "Slack", "Teams", "Zoom",
        "DocuSign", "PagerDuty", "Datadog", "Vault", "Terraform_Cloud",
        "Kubernetes_API", "Docker_Registry", "Artifactory", "Nexus", "Kafka",
        "Elasticsearch", "PostgreSQL_Prod", "MongoDB_Analytics", "Redis_Cache", "RabbitMQ",
        "NGINX_LB", "F5_BigIP", "Palo_Alto_FW", "CyberArk", "BeyondTrust",
        "Carbon_Black", "Symantec_DLP", "Varonis", "Netskope", "Proofpoint",
        "Custom_HRPortal", "Custom_FinanceApp", "Custom_SupplyChain",
        "Custom_ResearchDB", "Custom_DevTool", "Legacy_Mainframe",
        "IoT_Management", "SCADA_HMI", "Badge_System", "VPN_Concentrator",
    ]
    names = app_names[:n]

    return pd.DataFrame({
        "app_id": app_ids,
        "app_name": names,
        "app_type": app_types,
        "data_classification": classifications,
        "hosting_segment": hosting_segments,
        "criticality": criticalities,
    })


def generate_role_profiles() -> dict:
    """Maps each role to baseline behavioral parameters used by log generators."""
    profiles = {
        "Software Engineer": {
            "typical_login_hours": (8, 20),
            "typical_systems_accessed": 8,
            "data_sensitivity_access": "confidential",
            "network_activity_level": "medium",
            "privilege_level": "power_user",
        },
        "Senior Engineer": {
            "typical_login_hours": (8, 21),
            "typical_systems_accessed": 12,
            "data_sensitivity_access": "confidential",
            "network_activity_level": "medium",
            "privilege_level": "power_user",
        },
        "Staff Engineer": {
            "typical_login_hours": (7, 22),
            "typical_systems_accessed": 15,
            "data_sensitivity_access": "restricted",
            "network_activity_level": "high",
            "privilege_level": "admin",
        },
        "Financial Analyst": {
            "typical_login_hours": (8, 18),
            "typical_systems_accessed": 5,
            "data_sensitivity_access": "confidential",
            "network_activity_level": "low",
            "privilege_level": "user",
        },
        "Accountant": {
            "typical_login_hours": (8, 17),
            "typical_systems_accessed": 4,
            "data_sensitivity_access": "confidential",
            "network_activity_level": "low",
            "privilege_level": "user",
        },
        "CFO": {
            "typical_login_hours": (7, 20),
            "typical_systems_accessed": 8,
            "data_sensitivity_access": "restricted",
            "network_activity_level": "low",
            "privilege_level": "power_user",
        },
        "HR Specialist": {
            "typical_login_hours": (8, 17),
            "typical_systems_accessed": 4,
            "data_sensitivity_access": "confidential",
            "network_activity_level": "low",
            "privilege_level": "user",
        },
        "HR Manager": {
            "typical_login_hours": (8, 18),
            "typical_systems_accessed": 6,
            "data_sensitivity_access": "restricted",
            "network_activity_level": "low",
            "privilege_level": "power_user",
        },
        "Recruiter": {
            "typical_login_hours": (8, 18),
            "typical_systems_accessed": 3,
            "data_sensitivity_access": "internal",
            "network_activity_level": "low",
            "privilege_level": "user",
        },
        "IT Admin": {
            "typical_login_hours": (6, 22),
            "typical_systems_accessed": 20,
            "data_sensitivity_access": "restricted",
            "network_activity_level": "high",
            "privilege_level": "admin",
        },
        "Network Engineer": {
            "typical_login_hours": (7, 21),
            "typical_systems_accessed": 18,
            "data_sensitivity_access": "restricted",
            "network_activity_level": "high",
            "privilege_level": "admin",
        },
        "SysAdmin": {
            "typical_login_hours": (6, 22),
            "typical_systems_accessed": 22,
            "data_sensitivity_access": "restricted",
            "network_activity_level": "high",
            "privilege_level": "admin",
        },
        "DBA": {
            "typical_login_hours": (7, 20),
            "typical_systems_accessed": 10,
            "data_sensitivity_access": "restricted",
            "network_activity_level": "medium",
            "privilege_level": "admin",
        },
        "Security Analyst": {
            "typical_login_hours": (6, 22),
            "typical_systems_accessed": 15,
            "data_sensitivity_access": "restricted",
            "network_activity_level": "high",
            "privilege_level": "power_user",
        },
        "SOC Operator": {
            "typical_login_hours": (0, 24),
            "typical_systems_accessed": 12,
            "data_sensitivity_access": "restricted",
            "network_activity_level": "high",
            "privilege_level": "power_user",
        },
        "CISO": {
            "typical_login_hours": (7, 20),
            "typical_systems_accessed": 10,
            "data_sensitivity_access": "top_secret",
            "network_activity_level": "medium",
            "privilege_level": "admin",
        },
        "Sales Rep": {
            "typical_login_hours": (8, 19),
            "typical_systems_accessed": 4,
            "data_sensitivity_access": "internal",
            "network_activity_level": "low",
            "privilege_level": "user",
        },
        "Account Manager": {
            "typical_login_hours": (8, 19),
            "typical_systems_accessed": 5,
            "data_sensitivity_access": "internal",
            "network_activity_level": "low",
            "privilege_level": "user",
        },
        "VP Sales": {
            "typical_login_hours": (7, 20),
            "typical_systems_accessed": 7,
            "data_sensitivity_access": "confidential",
            "network_activity_level": "low",
            "privilege_level": "power_user",
        },
        "Data Scientist": {
            "typical_login_hours": (8, 21),
            "typical_systems_accessed": 10,
            "data_sensitivity_access": "confidential",
            "network_activity_level": "medium",
            "privilege_level": "power_user",
        },
        "ML Engineer": {
            "typical_login_hours": (8, 22),
            "typical_systems_accessed": 12,
            "data_sensitivity_access": "confidential",
            "network_activity_level": "high",
            "privilege_level": "power_user",
        },
        "Analyst": {
            "typical_login_hours": (8, 18),
            "typical_systems_accessed": 6,
            "data_sensitivity_access": "confidential",
            "network_activity_level": "low",
            "privilege_level": "user",
        },
        "DevOps Engineer": {
            "typical_login_hours": (7, 22),
            "typical_systems_accessed": 18,
            "data_sensitivity_access": "restricted",
            "network_activity_level": "high",
            "privilege_level": "admin",
        },
        "SRE": {
            "typical_login_hours": (0, 24),
            "typical_systems_accessed": 20,
            "data_sensitivity_access": "restricted",
            "network_activity_level": "high",
            "privilege_level": "admin",
        },
        "Cloud Architect": {
            "typical_login_hours": (8, 20),
            "typical_systems_accessed": 15,
            "data_sensitivity_access": "restricted",
            "network_activity_level": "high",
            "privilege_level": "admin",
        },
        "QA Engineer": {
            "typical_login_hours": (8, 18),
            "typical_systems_accessed": 8,
            "data_sensitivity_access": "internal",
            "network_activity_level": "medium",
            "privilege_level": "user",
        },
        "Test Lead": {
            "typical_login_hours": (8, 19),
            "typical_systems_accessed": 10,
            "data_sensitivity_access": "confidential",
            "network_activity_level": "medium",
            "privilege_level": "power_user",
        },
        "CEO": {
            "typical_login_hours": (6, 22),
            "typical_systems_accessed": 8,
            "data_sensitivity_access": "top_secret",
            "network_activity_level": "low",
            "privilege_level": "admin",
        },
        "CTO": {
            "typical_login_hours": (7, 22),
            "typical_systems_accessed": 12,
            "data_sensitivity_access": "top_secret",
            "network_activity_level": "medium",
            "privilege_level": "admin",
        },
        "COO": {
            "typical_login_hours": (7, 20),
            "typical_systems_accessed": 8,
            "data_sensitivity_access": "top_secret",
            "network_activity_level": "low",
            "privilege_level": "admin",
        },
        "General Counsel": {
            "typical_login_hours": (8, 19),
            "typical_systems_accessed": 6,
            "data_sensitivity_access": "restricted",
            "network_activity_level": "low",
            "privilege_level": "power_user",
        },
    }
    return profiles


def generate_all() -> dict[str, pd.DataFrame]:
    rng = _rng()
    segments_df = generate_network_segments()
    users_df = generate_users()
    devices_df = generate_devices(users_df, segments_df)
    applications_df = generate_applications(segments_df)

    # Enrich users with primary_device_id (first owned endpoint)
    owner_to_device = devices_df[devices_df["owner_user_id"].notna()].groupby("owner_user_id")["device_id"].first()
    users_df["primary_device_id"] = users_df["user_id"].map(owner_to_device).fillna(devices_df["device_id"].iloc[0])

    # Enrich users with subnet (from their primary device's segment)
    device_seg = devices_df.set_index("device_id")["segment_id"]
    seg_cidr = segments_df.set_index("segment_id")["cidr"]
    users_df["subnet"] = users_df["primary_device_id"].map(device_seg).map(seg_cidr).fillna("10.0.0.0/24").str.replace(".0/24", "", regex=False)

    # Enrich users with primary_location
    locations = ["HQ_floor1", "HQ_floor2", "HQ_floor3", "branch_east", "branch_west", "remote"]
    users_df["primary_location"] = rng.choice(locations, size=len(users_df))

    return {
        "users": users_df,
        "devices": devices_df,
        "segments": segments_df,
        "applications": applications_df,
    }
