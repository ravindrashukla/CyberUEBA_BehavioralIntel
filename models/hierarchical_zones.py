"""Hierarchical zone embeddings for Tier 3 Digital Entity detection.

Instead of one composite 1536-d embedding per entity (Tier 2), Tier 3 builds
5 independent zone embeddings per entity, then composes via context-adaptive
softmax attention. Enables zone-specific drift detection: "identity stable
but network_footprint drifting" = C2 pattern.

Ported from DLA MVP's hierarchical_embedding.py (zone definitions, softmax
attention, context-adaptive weights).
"""
import math
import numpy as np
from dataclasses import dataclass, field
from typing import Any

EMBED_DIM = 1536

# ── Zone definitions per entity type ─────────────────────────────────────────

CYBER_ZONES = {
    "user": {
        "identity": {
            "fields": ["role", "department", "clearance", "tenure_days", "user_type"],
        },
        "access_pattern": {
            "fields": ["auth_total", "auth_fail_rate", "auth_off_hours_ratio",
                       "auth_unique_sources", "auth_unique_dests", "auth_methods_used"],
        },
        "data_behavior": {
            "fields": ["file_total", "file_restricted_ratio", "file_confidential_ratio",
                       "file_write_ratio", "file_unique_paths", "file_total_bytes"],
        },
        "network_footprint": {
            "fields": ["net_bytes_out", "net_unique_dsts", "net_external_ratio",
                       "dns_unique_domains"],
        },
        "risk_posture": {
            "fields": ["endpoint_suspicious_ratio", "endpoint_max_risk",
                       "endpoint_mean_risk", "endpoint_unique_processes",
                       "endpoint_total", "dns_nxdomain_ratio"],
        },
    },
    "device": {
        "identity": {
            "fields": ["device_type", "os", "segment_id"],
        },
        "process_behavior": {
            "fields": ["endpoint_total", "endpoint_suspicious_ratio",
                       "endpoint_unique_processes"],
        },
        "traffic_pattern": {
            "fields": ["net_bytes_out", "net_unique_dsts", "net_external_ratio"],
        },
        "resource_usage": {
            "fields": ["endpoint_max_risk", "endpoint_mean_risk"],
        },
        "auth_profile": {
            "fields": ["auth_total", "auth_fail_rate", "auth_off_hours_ratio"],
        },
    },
}

USER_ZONE_ORDER = ["identity", "access_pattern", "data_behavior",
                   "network_footprint", "risk_posture"]

# ── Context-adaptive weights ─────────────────────────────────────────────────

CONTEXT_WEIGHTS = {
    "user": {
        "normal_ops": {
            "identity": 0.20, "access_pattern": 0.20, "data_behavior": 0.20,
            "network_footprint": 0.20, "risk_posture": 0.20,
        },
        "insider_investigation": {
            "identity": 0.10, "access_pattern": 0.15, "data_behavior": 0.40,
            "network_footprint": 0.15, "risk_posture": 0.20,
        },
        "apt_hunt": {
            "identity": 0.05, "access_pattern": 0.15, "data_behavior": 0.10,
            "network_footprint": 0.40, "risk_posture": 0.30,
        },
        "privilege_audit": {
            "identity": 0.10, "access_pattern": 0.25, "data_behavior": 0.10,
            "network_footprint": 0.15, "risk_posture": 0.40,
        },
    },
}

ALL_CONTEXTS = ["normal_ops", "insider_investigation", "apt_hunt", "privilege_audit"]


# ── Behavioral context for interpretive serialization ───────────────────────

@dataclass
class BehavioralContext:
    """Population stats and per-user baseline for interpretive serialization."""
    pop_mean: dict[str, float] = field(default_factory=dict)
    pop_std: dict[str, float] = field(default_factory=dict)
    user_baseline: dict[str, float] = field(default_factory=dict)
    week_idx: int = 0
    recent_history: list[dict[str, float]] = field(default_factory=list)


def _human_bytes(n: float) -> str:
    """Human-readable byte size (e.g. 469838822 -> '448 MB')."""
    n = float(n)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _percentile_label(z: float) -> str:
    if z > 3.0:
        return "extreme"
    if z > 2.0:
        return "very high"
    if z > 1.0:
        return "elevated"
    if z > 0.5:
        return "above average"
    if z > -0.5:
        return "normal"
    if z > -1.0:
        return "below average"
    if z > -2.0:
        return "low"
    return "very low"


def _trend_label(values: list[float]) -> str:
    if len(values) < 3:
        return "insufficient data"
    recent = values[-3:]
    if all(recent[i] < recent[i + 1] for i in range(len(recent) - 1)):
        return "increasing"
    if all(recent[i] > recent[i + 1] for i in range(len(recent) - 1)):
        return "decreasing"
    return "fluctuating"


def _baseline_ratio(val: float, baseline: float) -> str:
    if baseline < 1e-6:
        return "no baseline" if val < 1e-6 else "new activity"
    ratio = val / baseline
    if ratio > 3.0:
        return f"{ratio:.1f}x baseline (major escalation)"
    if ratio > 1.5:
        return f"{ratio:.1f}x baseline (elevated)"
    if ratio > 1.1:
        return f"{ratio:.1f}x baseline (slightly above)"
    if ratio > 0.9:
        return "at baseline"
    if ratio > 0.5:
        return f"{ratio:.1f}x baseline (reduced)"
    return f"{ratio:.1f}x baseline (significantly reduced)"


def _zscore(val: float, mean: float, std: float) -> float:
    if std < 1e-10:
        return 0.0
    return (val - mean) / std


# ── Zone text serialization ──────────────────────────────────────────────────

def serialize_zone(entity_type: str, zone_name: str,
                   entity_profile: dict[str, Any],
                   features: dict[str, float]) -> str:
    """Generate natural-language text for a single zone.

    Combines static profile data (role, department) with dynamic weekly
    features (auth_total, file_restricted_ratio, etc.) into a prose
    description that captures the zone's behavioral state.
    """
    entity_id = entity_profile.get("user_id", entity_profile.get("entity_id", "unknown"))

    if entity_type == "user":
        return _serialize_user_zone(zone_name, entity_id, entity_profile, features)
    return _serialize_generic_zone(entity_type, zone_name, entity_id, entity_profile, features)


def _serialize_user_zone(zone_name: str, uid: str,
                         profile: dict, features: dict) -> str:
    if zone_name == "identity":
        return (
            f"User {uid} identity: role={profile.get('role', 'unknown')}, "
            f"department={profile.get('department', 'unknown')}, "
            f"clearance={profile.get('clearance', 'unknown')}, "
            f"tenure_days={profile.get('tenure_days', 0)}, "
            f"type={profile.get('user_type', 'employee')}"
        )
    elif zone_name == "access_pattern":
        return (
            f"User {uid} access: auth_events={features.get('auth_total', 0):.0f}, "
            f"fail_rate={features.get('auth_fail_rate', 0):.4f}, "
            f"off_hours={features.get('auth_off_hours_ratio', 0):.4f}, "
            f"unique_sources={features.get('auth_unique_sources', 0):.0f}, "
            f"unique_dests={features.get('auth_unique_dests', 0):.0f}, "
            f"methods={features.get('auth_methods_used', 0):.0f}"
        )
    elif zone_name == "data_behavior":
        base = (
            f"User {uid} data: file_accesses={features.get('file_total', 0):.0f}, "
            f"restricted_ratio={features.get('file_restricted_ratio', 0):.4f}, "
            f"confidential_ratio={features.get('file_confidential_ratio', 0):.4f}, "
            f"write_ratio={features.get('file_write_ratio', 0):.4f}, "
            f"unique_paths={features.get('file_unique_paths', 0):.0f}, "
            f"bytes={features.get('file_total_bytes', 0):.0f}"
        )
        dirs = features.get("qual_file_dirs", "")
        if dirs:
            base += f". Directories accessed: {dirs}"
        return base
    elif zone_name == "network_footprint":
        base = (
            f"User {uid} network: bytes_out={features.get('net_bytes_out', 0):.0f}, "
            f"unique_dsts={features.get('net_unique_dsts', 0):.0f}, "
            f"external_ratio={features.get('net_external_ratio', 0):.4f}, "
            f"dns_domains={features.get('dns_unique_domains', 0):.0f}, "
            f"nxdomain_ratio={features.get('dns_nxdomain_ratio', 0):.4f}"
        )
        ext_ips = features.get("qual_net_ext_ips", "")
        if ext_ips:
            base += f". External destinations: {ext_ips}"
        dns_doms = features.get("qual_dns_domains", "")
        if dns_doms:
            base += f". DNS domains queried: {dns_doms}"
        return base
    elif zone_name == "risk_posture":
        return (
            f"User {uid} risk: endpoint_events={features.get('endpoint_total', 0):.0f}, "
            f"suspicious_ratio={features.get('endpoint_suspicious_ratio', 0):.4f}, "
            f"max_risk={features.get('endpoint_max_risk', 0):.4f}, "
            f"mean_risk={features.get('endpoint_mean_risk', 0):.4f}, "
            f"unique_processes={features.get('endpoint_unique_processes', 0):.0f}"
        )
    return f"User {uid} {zone_name}: {features}"


def _serialize_generic_zone(entity_type: str, zone_name: str, eid: str,
                            profile: dict, features: dict) -> str:
    zone_def = CYBER_ZONES.get(entity_type, {}).get(zone_name, {})
    fields = zone_def.get("fields", [])
    parts = [f"{entity_type.title()} {eid} {zone_name}:"]
    for f in fields:
        val = features.get(f, profile.get(f, "N/A"))
        if isinstance(val, float):
            parts.append(f"{f}={val:.4f}")
        else:
            parts.append(f"{f}={val}")
    return " ".join(parts)


# ── Interpretive zone serialization ─────────────────────────────────────────

def serialize_zone_interpretive(
    entity_type: str, zone_name: str,
    entity_profile: dict[str, Any],
    features: dict[str, float],
    ctx: BehavioralContext,
) -> str:
    """Semantically rich text encoding behavioral state relative to population and baseline."""
    uid = entity_profile.get("user_id", entity_profile.get("entity_id", "unknown"))
    if entity_type != "user":
        return _serialize_generic_zone(entity_type, zone_name, uid, entity_profile, features)

    role = entity_profile.get("role", "unknown")
    dept = entity_profile.get("department", "unknown")

    if zone_name == "identity":
        return (
            f"Employee {uid} is a {role} in {dept} with "
            f"{entity_profile.get('clearance', 'standard')} clearance, "
            f"tenure {entity_profile.get('tenure_days', 0)} days, "
            f"type {entity_profile.get('user_type', 'employee')}."
        )

    if zone_name == "access_pattern":
        return _serialize_access_interpretive(uid, role, dept, features, ctx)
    if zone_name == "data_behavior":
        return _serialize_data_interpretive(uid, role, dept, features, ctx)
    if zone_name == "network_footprint":
        return _serialize_network_interpretive(uid, role, dept, features, ctx)
    if zone_name == "risk_posture":
        return _serialize_risk_interpretive(uid, role, dept, features, ctx)

    return serialize_zone(entity_type, zone_name, entity_profile, features)


def _max_z(features: dict, keys: list[str], ctx: BehavioralContext) -> float:
    """Return the highest absolute z-score among the given feature keys."""
    return max(
        (abs(_zscore(features.get(k, 0), ctx.pop_mean.get(k, 0), ctx.pop_std.get(k, 1)))
         for k in keys),
        default=0.0,
    )


def _feat_assessment(key: str, val: float, ctx: BehavioralContext) -> str:
    z = _zscore(val, ctx.pop_mean.get(key, 0), ctx.pop_std.get(key, 1))
    label = _percentile_label(z)
    baseline_val = ctx.user_baseline.get(key, 0)
    bline = _baseline_ratio(val, baseline_val)
    history = [h.get(key, 0) for h in ctx.recent_history]
    trend = _trend_label(history + [val]) if history else "no trend data"
    return f"{label} ({bline}, trend: {trend})"


def _serialize_access_interpretive(uid, role, dept, features, ctx):
    fail_rate = features.get("auth_fail_rate", 0)
    off_hours = features.get("auth_off_hours_ratio", 0)

    fail_z = _zscore(fail_rate, ctx.pop_mean.get("auth_fail_rate", 0), ctx.pop_std.get("auth_fail_rate", 1))
    off_z = _zscore(off_hours, ctx.pop_mean.get("auth_off_hours_ratio", 0), ctx.pop_std.get("auth_off_hours_ratio", 1))
    peak_z = max(abs(fail_z), abs(off_z))

    if peak_z > 2.5:
        parts = [f"CRITICAL ANOMALY in authentication for {role} {uid} in {dept}."]
        if abs(fail_z) > 2.5:
            parts.append(
                f"Authentication failure rate at EXTREME level: {fail_rate:.3f} "
                f"({abs(fail_z):.1f} standard deviations above population mean, "
                f"{_baseline_ratio(fail_rate, ctx.user_baseline.get('auth_fail_rate', 0))}). "
                f"This pattern is strongly consistent with credential stuffing, brute force attack, "
                f"or compromised credential reuse. Immediate investigation recommended."
            )
        if abs(off_z) > 2.5:
            parts.append(
                f"Off-hours access at EXTREME level: {off_hours:.3f} "
                f"({abs(off_z):.1f} standard deviations, "
                f"{_baseline_ratio(off_hours, ctx.user_baseline.get('auth_off_hours_ratio', 0))}). "
                f"Unauthorized after-hours activity pattern consistent with compromised account "
                f"being used during low-monitoring periods."
            )
        return " ".join(parts)

    if peak_z < 1.5:
        return (
            f"{role} {uid} in {dept}: authentication activity within normal parameters. "
            f"Failure rate {fail_rate:.3f}, off-hours ratio {off_hours:.3f}, both unremarkable."
        )

    parts = [f"{role} {uid} in {dept} authentication behavior:"]
    if fail_z > 1.0:
        parts.append(f"Failure rate {_percentile_label(fail_z)} at {fail_rate:.3f}, possible credential issues.")
    if off_z > 1.0:
        parts.append(f"Off-hours ratio {_percentile_label(off_z)} at {off_hours:.3f}.")
    parts.append(f"Using {features.get('auth_unique_sources', 0):.0f} sources, {features.get('auth_unique_dests', 0):.0f} destinations.")
    return " ".join(parts)


def _serialize_data_interpretive(uid, role, dept, features, ctx):
    restricted = features.get("file_restricted_ratio", 0)
    confidential = features.get("file_confidential_ratio", 0)
    write_ratio = features.get("file_write_ratio", 0)
    total_bytes = features.get("file_total_bytes", 0)
    file_total = features.get("file_total", 0)

    restr_z = _zscore(restricted, ctx.pop_mean.get("file_restricted_ratio", 0), ctx.pop_std.get("file_restricted_ratio", 1))
    conf_z = _zscore(confidential, ctx.pop_mean.get("file_confidential_ratio", 0), ctx.pop_std.get("file_confidential_ratio", 1))
    write_z = _zscore(write_ratio, ctx.pop_mean.get("file_write_ratio", 0), ctx.pop_std.get("file_write_ratio", 1))
    peak_z = max(abs(restr_z), abs(conf_z), abs(write_z))

    if peak_z > 2.5:
        parts = [f"CRITICAL ANOMALY in data access for {role} {uid} in {dept}."]
        if abs(restr_z) > 2.5:
            parts.append(
                f"Restricted file access at EXTREME level: ratio {restricted:.4f} "
                f"({abs(restr_z):.1f} standard deviations above population, "
                f"{_baseline_ratio(restricted, ctx.user_baseline.get('file_restricted_ratio', 0))}). "
                f"This user is accessing classified and restricted materials at a rate far exceeding "
                f"normal organizational patterns. Pattern strongly consistent with active data exfiltration, "
                f"insider threat data staging, or unauthorized access to sensitive intellectual property."
            )
        if abs(conf_z) > 2.5:
            parts.append(
                f"Confidential file access at EXTREME level: ratio {confidential:.4f} "
                f"({abs(conf_z):.1f} standard deviations, "
                f"{_baseline_ratio(confidential, ctx.user_baseline.get('file_confidential_ratio', 0))}). "
                f"Bulk access to confidential materials indicates potential data collection campaign "
                f"or preparation for large-scale information theft."
            )
        if abs(write_z) > 2.5:
            parts.append(
                f"Write operation ratio at EXTREME level: {write_ratio:.4f} "
                f"({abs(write_z):.1f} standard deviations). "
                f"Excessive write operations may indicate data staging, copying sensitive files "
                f"to removable media, or preparation for exfiltration."
            )
        parts.append(f"Total volume: {total_bytes:.0f} bytes across {features.get('file_unique_paths', 0):.0f} paths.")
        dirs = features.get("qual_file_dirs", "")
        if dirs:
            parts.append(f"Directories accessed: {dirs}.")
        return " ".join(parts)

    if peak_z < 1.5:
        base = (
            f"{role} {uid} in {dept}: data access activity within normal parameters. "
            f"File operations {file_total:.0f}, restricted ratio {restricted:.4f}, "
            f"confidential ratio {confidential:.4f}, all unremarkable."
        )
        dirs = features.get("qual_file_dirs", "")
        if dirs:
            base += f" Directories: {dirs}."
        return base

    parts = [f"{role} {uid} in {dept} data access behavior:"]
    if restr_z > 1.0:
        parts.append(f"Restricted access {_percentile_label(restr_z)} at {restricted:.4f}, elevated sensitivity.")
    if conf_z > 1.0:
        parts.append(f"Confidential access {_percentile_label(conf_z)} at {confidential:.4f}.")
    if write_z > 1.0:
        parts.append(f"Write ratio {_percentile_label(write_z)} at {write_ratio:.4f}.")
    parts.append(f"Volume: {total_bytes:.0f} bytes across {features.get('file_unique_paths', 0):.0f} paths.")
    dirs = features.get("qual_file_dirs", "")
    if dirs:
        parts.append(f"Directories accessed: {dirs}.")
    return " ".join(parts)


def _serialize_network_interpretive(uid, role, dept, features, ctx):
    bytes_out = features.get("net_bytes_out", 0)
    ext_ratio = features.get("net_external_ratio", 0)
    dns_domains = features.get("dns_unique_domains", 0)
    nxdomain = features.get("dns_nxdomain_ratio", 0)
    unique_dsts = features.get("net_unique_dsts", 0)

    ext_z = _zscore(ext_ratio, ctx.pop_mean.get("net_external_ratio", 0), ctx.pop_std.get("net_external_ratio", 1))
    bytes_z = _zscore(bytes_out, ctx.pop_mean.get("net_bytes_out", 0), ctx.pop_std.get("net_bytes_out", 1))
    nxd_z = _zscore(nxdomain, ctx.pop_mean.get("dns_nxdomain_ratio", 0), ctx.pop_std.get("dns_nxdomain_ratio", 1))
    peak_z = max(abs(ext_z), abs(bytes_z), abs(nxd_z))

    if peak_z > 2.5:
        parts = [f"CRITICAL ANOMALY in network behavior for {role} {uid} in {dept}."]
        if abs(ext_z) > 2.5:
            parts.append(
                f"External connection ratio at EXTREME level: {ext_ratio:.4f} "
                f"({abs(ext_z):.1f} standard deviations above population, "
                f"{_baseline_ratio(ext_ratio, ctx.user_baseline.get('net_external_ratio', 0))}). "
                f"Abnormal volume of connections to external infrastructure. Pattern strongly consistent "
                f"with command and control beacon activity, data exfiltration to external servers, "
                f"or active lateral movement using external relay points."
            )
        if abs(bytes_z) > 2.5:
            parts.append(
                f"Outbound data transfer at EXTREME level: {bytes_out:.0f} bytes "
                f"({abs(bytes_z):.1f} standard deviations, "
                f"{_baseline_ratio(bytes_out, ctx.user_baseline.get('net_bytes_out', 0))}). "
                f"Massive data transfer consistent with bulk data exfiltration or "
                f"large-scale unauthorized data movement to external destinations."
            )
        if abs(nxd_z) > 2.5:
            parts.append(
                f"NXDOMAIN ratio at EXTREME level: {nxdomain:.4f} "
                f"({abs(nxd_z):.1f} standard deviations). "
                f"High rate of failed DNS lookups strongly indicates domain generation algorithm (DGA) "
                f"activity, characteristic of advanced malware C2 communication."
            )
        ext_ips = features.get("qual_net_ext_ips", "")
        if ext_ips:
            parts.append(f"External destinations: {ext_ips}.")
        dns_doms = features.get("qual_dns_domains", "")
        if dns_doms:
            parts.append(f"DNS domains queried: {dns_doms}.")
        return " ".join(parts)

    if peak_z < 1.5:
        base = (
            f"{role} {uid} in {dept}: network activity within normal parameters. "
            f"Outbound {bytes_out:.0f} bytes, external ratio {ext_ratio:.4f}, "
            f"{dns_domains:.0f} DNS domains, all unremarkable."
        )
        ext_ips = features.get("qual_net_ext_ips", "")
        if ext_ips:
            base += f" External destinations: {ext_ips}."
        dns_doms = features.get("qual_dns_domains", "")
        if dns_doms:
            base += f" DNS: {dns_doms}."
        return base

    parts = [f"{role} {uid} in {dept} network behavior:"]
    if ext_z > 1.0:
        parts.append(f"External ratio {_percentile_label(ext_z)} at {ext_ratio:.4f}.")
    if bytes_z > 1.0:
        parts.append(f"Outbound traffic {_percentile_label(bytes_z)}: {_human_bytes(bytes_out)}.")
    if nxd_z > 1.0:
        parts.append(f"NXDOMAIN ratio {_percentile_label(nxd_z)} at {nxdomain:.4f}.")
    parts.append(f"Connecting to {unique_dsts:.0f} destinations, {dns_domains:.0f} DNS domains.")
    ext_ips = features.get("qual_net_ext_ips", "")
    if ext_ips:
        parts.append(f"External destinations: {ext_ips}.")
    dns_doms = features.get("qual_dns_domains", "")
    if dns_doms:
        parts.append(f"DNS: {dns_doms}.")
    return " ".join(parts)


def _serialize_risk_interpretive(uid, role, dept, features, ctx):
    max_risk = features.get("endpoint_max_risk", 0)
    mean_risk = features.get("endpoint_mean_risk", 0)
    susp_ratio = features.get("endpoint_suspicious_ratio", 0)
    ep_total = features.get("endpoint_total", 0)
    unique_procs = features.get("endpoint_unique_processes", 0)

    max_z = _zscore(max_risk, ctx.pop_mean.get("endpoint_max_risk", 0), ctx.pop_std.get("endpoint_max_risk", 1))
    mean_z = _zscore(mean_risk, ctx.pop_mean.get("endpoint_mean_risk", 0), ctx.pop_std.get("endpoint_mean_risk", 1))
    peak_z = max(abs(max_z), abs(mean_z))

    if peak_z > 2.5:
        parts = [f"CRITICAL ANOMALY in endpoint risk for {role} {uid} in {dept}."]
        if abs(max_z) > 2.5:
            parts.append(
                f"Peak risk score at EXTREME level: {max_risk:.4f} "
                f"({abs(max_z):.1f} standard deviations above population, "
                f"{_baseline_ratio(max_risk, ctx.user_baseline.get('endpoint_max_risk', 0))}). "
                f"Endpoint exhibiting behavior strongly consistent with active malware execution, "
                f"privilege escalation exploit, or ransomware deployment. "
                f"Immediate containment investigation recommended."
            )
        if abs(mean_z) > 2.5:
            parts.append(
                f"Sustained average risk at EXTREME level: {mean_risk:.4f} "
                f"({abs(mean_z):.1f} standard deviations). "
                f"Persistently elevated risk indicates ongoing compromise, "
                f"not a transient event."
            )
        if susp_ratio > 0.01:
            parts.append(f"Suspicious process ratio {susp_ratio:.4f} reinforces compromise indicators.")
        return " ".join(parts)

    if peak_z < 1.5:
        return (
            f"{role} {uid} in {dept}: endpoint risk within normal parameters. "
            f"Peak risk {max_risk:.4f}, mean risk {mean_risk:.4f}, both unremarkable."
        )

    parts = [f"{role} {uid} in {dept} endpoint risk posture:"]
    if max_z > 1.0:
        parts.append(f"Peak risk {_percentile_label(max_z)} at {max_risk:.4f}.")
    if mean_z > 1.0:
        parts.append(f"Mean risk {_percentile_label(mean_z)} at {mean_risk:.4f}.")
    if susp_ratio > 0.001:
        parts.append(f"Suspicious process ratio {susp_ratio:.4f}.")
    parts.append(f"Running {unique_procs:.0f} unique processes.")
    return " ".join(parts)


# ── Embedding and composition ────────────────────────────────────────────────

def build_zone_embeddings(entity_type: str, entity_id: str,
                          entity_profile: dict[str, Any],
                          features: dict[str, float],
                          embedder,
                          behavioral_ctx: BehavioralContext | None = None,
                          ) -> dict[str, np.ndarray]:
    """Build 5 zone embeddings independently.

    Each zone's features are serialized to text, then embedded to 1536-d.
    When behavioral_ctx is provided, uses interpretive serialization that
    encodes population percentiles, user baselines, and trend labels —
    producing semantically distinct embeddings for anomalous behavior.
    """
    zones = CYBER_ZONES.get(entity_type, CYBER_ZONES["user"])
    zone_embeddings = {}

    for zone_name in zones:
        if behavioral_ctx is not None:
            text = serialize_zone_interpretive(
                entity_type, zone_name, entity_profile, features, behavioral_ctx
            )
        else:
            text = serialize_zone(entity_type, zone_name, entity_profile, features)
        vec = embedder.embed_text(text)
        if isinstance(vec, list):
            vec = np.array(vec, dtype=np.float32)
        zone_embeddings[zone_name] = vec

    return zone_embeddings


def softmax_attention(zone_vecs: dict[str, np.ndarray],
                      context_weights: dict[str, float]) -> dict[str, float]:
    """Compute linear-normalized attention weights biased by context.

    Uses direct linear normalization instead of softmax to preserve
    the intended weight differentiation across investigation contexts.
    Softmax compresses weights (e.g., intended 0.40 → ~0.23); linear
    normalization preserves them (0.40 stays ~0.40).

    alpha_i = (||zone_i|| * context_weight[zone_i]) / sum(...)
    """
    if not zone_vecs:
        return {}

    raw = {}
    for name, vec in zone_vecs.items():
        energy = float(np.linalg.norm(vec))
        bias = context_weights.get(name, 0.2)
        raw[name] = energy * bias

    total = sum(raw.values())

    if total == 0:
        uniform = 1.0 / len(zone_vecs)
        return {k: uniform for k in zone_vecs}

    return {k: v / total for k, v in raw.items()}


def compose_zones(zone_embeddings: dict[str, np.ndarray],
                  context: str = "normal_ops",
                  entity_type: str = "user",
                  exclude_static: bool = True) -> np.ndarray:
    """Attention-weighted composition of zone embeddings into composite.

    Uses context-adaptive weights to bias attention toward zones relevant
    to the investigation scenario (APT hunt, insider investigation, etc.).

    Static zones (identity) are excluded from composition by default
    because they never drift and dilute the behavioral signal.
    Identity zone is still used separately as a stability reference
    in zone divergence detection.
    """
    STATIC_ZONES = {"identity"}
    if exclude_static:
        active_zones = {k: v for k, v in zone_embeddings.items()
                        if k not in STATIC_ZONES}
    else:
        active_zones = zone_embeddings

    if not active_zones:
        active_zones = zone_embeddings

    ctx_weights = CONTEXT_WEIGHTS.get(entity_type, CONTEXT_WEIGHTS["user"]).get(
        context, CONTEXT_WEIGHTS["user"]["normal_ops"]
    )

    alphas = softmax_attention(active_zones, ctx_weights)

    composite = np.zeros(EMBED_DIM, dtype=np.float64)
    for name, vec in active_zones.items():
        alpha = alphas.get(name, 0.0)
        composite += alpha * vec.astype(np.float64)

    norm = np.linalg.norm(composite)
    if norm > 1e-10:
        composite = composite / norm

    return composite.astype(np.float32)
