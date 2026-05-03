"""Privileged operations log generator for UEBA synthetic data."""

import datetime
import numpy as np

from simulator.config import PRIV_OPS_PER_DAY, WORK_HOURS


OPERATION_WEIGHTS = {
    "role_grant": 0.20,
    "role_revoke": 0.10,
    "access_elevation": 0.25,
    "sudo_use": 0.20,
    "policy_change": 0.10,
    "account_create": 0.05,
    "account_disable": 0.05,
    "mfa_bypass": 0.05,
}

OPERATIONS = list(OPERATION_WEIGHTS.keys())
OPERATION_PROBS = list(OPERATION_WEIGHTS.values())

ACTOR_ROLES = ["IT Admin", "Security Analyst", "HR Manager", "SysAdmin", "DBA", "SOC Operator"]

RESOURCES = {
    "role_grant": ["admin_role", "read_only_role", "developer_role", "auditor_role", "db_write_role"],
    "role_revoke": ["admin_role", "elevated_role", "temp_access_role", "contractor_role"],
    "access_elevation": ["prod_database", "secrets_vault", "cloud_console", "network_infra", "security_tools"],
    "sudo_use": ["server_root", "db_superuser", "container_host", "network_device", "build_server"],
    "policy_change": ["password_policy", "mfa_policy", "network_acl", "firewall_rule", "retention_policy"],
    "account_create": ["standard_user", "service_account", "contractor_account", "admin_account"],
    "account_disable": ["terminated_user", "inactive_account", "compromised_account", "expired_contractor"],
    "mfa_bypass": ["lost_device", "hardware_failure", "travel_exception", "exec_request"],
}

JUSTIFICATIONS = {
    "role_grant": ["new_hire_onboarding", "project_assignment", "role_change", "cross_team_collaboration"],
    "role_revoke": ["project_completion", "role_change", "security_incident", "policy_violation"],
    "access_elevation": ["incident_response", "production_fix", "audit_requirement", "scheduled_maintenance"],
    "sudo_use": ["system_update", "service_restart", "log_rotation", "config_deployment", "troubleshooting"],
    "policy_change": ["compliance_update", "security_hardening", "audit_finding", "executive_directive"],
    "account_create": ["new_hire", "new_contractor", "automation_pipeline", "service_integration"],
    "account_disable": ["termination", "security_lockout", "contract_end", "inactivity_policy"],
    "mfa_bypass": ["device_replacement", "travel_emergency", "hardware_malfunction", "executive_override"],
}


def _work_hour_timestamp(current_date, rng):
    """Generate timestamp biased toward work hours (85/15 split)."""
    work_start, work_end = WORK_HOURS
    if rng.random() < 0.85:
        hour = rng.integers(work_start, work_end)
    else:
        hour = rng.choice(list(range(0, work_start)) + list(range(work_end, 24)))
    minute = rng.integers(0, 60)
    second = rng.integers(0, 60)
    return datetime.datetime.combine(current_date, datetime.time(int(hour), int(minute), int(second)))


def generate_privilege_ops(users_df, current_date, rng) -> list[dict]:
    """Generate privileged operation events for a given date.

    This is a LOW volume stream (~20 events/day total across all users).

    Args:
        users_df: DataFrame with columns [user_id, role, ...]
        current_date: date object for event generation
        rng: numpy random Generator for reproducibility

    Returns:
        List of event dicts.
    """
    events = []

    # Filter potential actors (privileged roles)
    actor_mask = users_df["role"].isin(ACTOR_ROLES)
    actor_df = users_df[actor_mask]

    if actor_df.empty:
        return events

    all_user_ids = users_df["user_id"].values
    actor_user_ids = actor_df["user_id"].values

    # Total events per day is low-volume (Poisson around config mean)
    n_events = rng.poisson(PRIV_OPS_PER_DAY)

    for _ in range(n_events):
        ts = _work_hour_timestamp(current_date, rng)
        operation = rng.choice(OPERATIONS, p=OPERATION_PROBS)

        # Actor is always a privileged role user
        actor_user_id = rng.choice(actor_user_ids)

        # Target can be any user (but not self for most ops)
        target_user_id = rng.choice(all_user_ids)
        if operation != "sudo_use" and target_user_id == actor_user_id:
            target_user_id = rng.choice(all_user_ids)

        resource = rng.choice(RESOURCES[operation])
        justification = rng.choice(JUSTIFICATIONS[operation])

        # 85% approved, 15% denied
        approved = bool(rng.random() < 0.85)

        # Approver is a different privileged user (None if denied with no approver)
        approver_id = None
        if approved:
            approver_candidates = actor_user_ids[actor_user_ids != actor_user_id]
            if len(approver_candidates) > 0:
                approver_id = str(rng.choice(approver_candidates))

        events.append({
            "timestamp": ts,
            "actor_user_id": str(actor_user_id),
            "target_user_id": str(target_user_id),
            "operation": operation,
            "resource": resource,
            "justification": justification,
            "approved": approved,
            "approver_id": approver_id,
        })

    events.sort(key=lambda e: e["timestamp"])
    return events
