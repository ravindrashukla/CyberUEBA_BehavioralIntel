"""Annotate qualitative features with novelty and role-appropriateness flags.

Enriches the raw qualitative strings (qual_file_dirs, qual_net_ext_ips,
qual_dns_domains) with semantic annotations that help embedding models
distinguish benign variation from suspicious behavioral shifts.
"""
import math
import re
from collections import defaultdict

import pandas as pd

BASELINE_WEEKS = 10

ROLE_EXPECTED_DIRS = {
    "developer": {"/engineering", "/shared", "/docs", "Documents/Project",
                  "Documents/Code", "Documents/Product", "Documents/Tech"},
    "admin": {"/infrastructure", "/it-ops", "/shared", "/engineering",
              "Documents/Network", "Documents/Infrastructure"},
    "security": {"/security", "/siem", "/shared", "/incident",
                 "Documents/Security", "Documents/Incident"},
    "business": {"/finance", "/hr", "/sales", "/shared", "/legal",
                 "Documents/Budget", "Documents/RFP", "Documents/Vendor",
                 "Documents/Customer", "Documents/Q4", "Documents/Compliance",
                 "Documents/Merger", "Documents/Patent"},
    "executive": {"/executive", "/finance", "/strategy", "/shared",
                  "Documents/Board", "Documents/Strategy"},
}

SENSITIVE_DIRS = {
    "/executive": {"executive"},
    "/finance": {"business", "executive"},
    "/hr": {"business", "executive"},
    "/security/audit": {"security"},
    "/security/policies": {"security", "admin"},
    "/legal": {"business", "executive"},
}


def _domain_entropy(domain: str) -> float:
    """Shannon entropy of the domain name (higher = more random/DGA-like)."""
    name = domain.split(".")[0] if "." in domain else domain
    if not name:
        return 0.0
    freq = {}
    for c in name.lower():
        freq[c] = freq.get(c, 0) + 1
    length = len(name)
    entropy = -sum((count / length) * math.log2(count / length)
                   for count in freq.values())
    return entropy


def _is_internal_domain(domain: str) -> bool:
    """Check if domain is internal (corp, internal, etc.)."""
    parts = domain.lower().strip().split(".")
    return parts[-1] in {"corp", "internal", "local", "lan", "intranet"}


def _dir_is_role_appropriate(dir_path: str, role_group: str) -> bool:
    """Check if a directory is expected for the given role group."""
    path_lower = dir_path.lower().replace("\\", "/")
    expected = ROLE_EXPECTED_DIRS.get(role_group, set())
    return any(exp.lower() in path_lower for exp in expected)


def _dir_is_sensitive_for_role(dir_path: str, role_group: str) -> str | None:
    """Return sensitivity label if directory is unusual for this role."""
    path_lower = dir_path.lower().replace("\\", "/")
    for sensitive_pattern, allowed_groups in SENSITIVE_DIRS.items():
        if sensitive_pattern.lower() in path_lower:
            if role_group not in allowed_groups:
                return sensitive_pattern
    return None


def annotate_qualitative_features(
    features_df: pd.DataFrame,
    role_group_map: dict[str, str],
) -> pd.DataFrame:
    """Enrich qualitative features with novelty and role-appropriateness annotations.

    For each user:
    - Baseline (first BASELINE_WEEKS weeks): collect all observed dirs, IPs, domains
    - Subsequent weeks: flag NOVEL items + ROLE-ATYPICAL directories + HIGH-ENTROPY domains
    """
    df = features_df.copy()

    if "qual_file_dirs" not in df.columns:
        return df

    user_baselines = defaultdict(lambda: {"dirs": set(), "ips": set(), "domains": set()})

    for uid in df["user_id"].unique():
        user_mask = df["user_id"] == uid
        user_rows = df[user_mask].sort_values("week_idx")
        baseline_rows = user_rows[user_rows["week_idx"] < BASELINE_WEEKS]

        bl = user_baselines[uid]
        for _, row in baseline_rows.iterrows():
            dirs_str = str(row.get("qual_file_dirs", ""))
            if dirs_str:
                bl["dirs"].update(d.strip() for d in dirs_str.split(";") if d.strip())
            ips_str = str(row.get("qual_net_ext_ips", ""))
            if ips_str:
                bl["ips"].update(ip.strip() for ip in ips_str.split(";") if ip.strip())
            doms_str = str(row.get("qual_dns_domains", ""))
            if doms_str:
                bl["domains"].update(d.strip() for d in doms_str.split(";") if d.strip())

    for idx, row in df.iterrows():
        uid = row["user_id"]
        week = row["week_idx"]
        role_group = role_group_map.get(uid, "unknown")
        bl = user_baselines[uid]

        # Annotate file directories
        dirs_str = str(row.get("qual_file_dirs", ""))
        if dirs_str and week >= BASELINE_WEEKS:
            dirs = [d.strip() for d in dirs_str.split(";") if d.strip()]
            annotated = []
            for d in dirs:
                tags = []
                if d not in bl["dirs"]:
                    tags.append("NOVEL")
                sens = _dir_is_sensitive_for_role(d, role_group)
                if sens:
                    tags.append(f"ATYPICAL-{role_group.upper()}")
                if tags:
                    annotated.append(f"{d} [{', '.join(tags)}]")
                else:
                    annotated.append(d)
            df.at[idx, "qual_file_dirs"] = "; ".join(annotated)

        # Annotate external IPs
        ips_str = str(row.get("qual_net_ext_ips", ""))
        if ips_str and week >= BASELINE_WEEKS:
            ips = [ip.strip() for ip in ips_str.split(";") if ip.strip()]
            annotated = []
            for ip in ips:
                if ip not in bl["ips"]:
                    annotated.append(f"{ip} [NOVEL]")
                else:
                    annotated.append(ip)
            df.at[idx, "qual_net_ext_ips"] = "; ".join(annotated)

        # Annotate DNS domains
        doms_str = str(row.get("qual_dns_domains", ""))
        if doms_str and week >= BASELINE_WEEKS:
            doms = [d.strip() for d in doms_str.split(";") if d.strip()]
            annotated = []
            for d in doms:
                tags = []
                if d not in bl["domains"] and not _is_internal_domain(d):
                    tags.append("NOVEL")
                ent = _domain_entropy(d)
                if ent > 3.5 and not _is_internal_domain(d):
                    tags.append(f"HIGH-ENTROPY={ent:.1f}")
                if tags:
                    annotated.append(f"{d} [{', '.join(tags)}]")
                else:
                    annotated.append(d)
            df.at[idx, "qual_dns_domains"] = "; ".join(annotated)

    return df


def compute_novelty_metrics(features_df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-user novelty persistence metrics from qualitative features.

    Returns a DataFrame with one row per user:
    - persistent_novel_ips: count of novel IPs appearing in 5+ post-baseline weeks
    - novel_ip_persistence: max consecutive weeks any novel IP appears
    - novel_ip_weeks_frac: fraction of post-baseline weeks with novel IPs
    """
    records = []

    for uid in features_df["user_id"].unique():
        user_rows = features_df[features_df["user_id"] == uid].sort_values("week_idx")
        baseline_rows = user_rows[user_rows["week_idx"] < BASELINE_WEEKS]
        post_rows = user_rows[user_rows["week_idx"] >= BASELINE_WEEKS]

        baseline_ips = set()
        for _, row in baseline_rows.iterrows():
            ips_str = str(row.get("qual_net_ext_ips", ""))
            if ips_str:
                for ip in ips_str.split(";"):
                    ip = ip.strip().split("[")[0].strip()
                    if ip:
                        baseline_ips.add(ip)

        novel_ip_weeks: dict[str, int] = {}
        n_post_weeks = len(post_rows)
        weeks_with_novel = 0

        for _, row in post_rows.iterrows():
            ips_str = str(row.get("qual_net_ext_ips", ""))
            if not ips_str:
                continue
            has_novel = False
            for ip in ips_str.split(";"):
                ip_clean = ip.strip().split("[")[0].strip()
                if ip_clean and ip_clean not in baseline_ips:
                    novel_ip_weeks[ip_clean] = novel_ip_weeks.get(ip_clean, 0) + 1
                    has_novel = True
            if has_novel:
                weeks_with_novel += 1

        persistent_novel = sum(1 for cnt in novel_ip_weeks.values() if cnt >= 5)
        max_persistence = max(novel_ip_weeks.values(), default=0)
        novel_frac = weeks_with_novel / max(n_post_weeks, 1)

        records.append({
            "uid": uid,
            "persistent_novel_ips": persistent_novel,
            "novel_ip_max_persistence": max_persistence,
            "novel_ip_weeks_frac": novel_frac,
        })

    return pd.DataFrame(records)
