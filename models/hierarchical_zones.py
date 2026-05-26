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
                       "dns_unique_domains", "dns_nxdomain_ratio"],
        },
        "risk_posture": {
            "fields": ["endpoint_suspicious_ratio", "endpoint_max_risk",
                       "endpoint_mean_risk", "endpoint_unique_processes", "endpoint_total"],
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
        return (
            f"User {uid} data: file_accesses={features.get('file_total', 0):.0f}, "
            f"restricted_ratio={features.get('file_restricted_ratio', 0):.4f}, "
            f"confidential_ratio={features.get('file_confidential_ratio', 0):.4f}, "
            f"write_ratio={features.get('file_write_ratio', 0):.4f}, "
            f"unique_paths={features.get('file_unique_paths', 0):.0f}, "
            f"bytes={features.get('file_total_bytes', 0):.0f}"
        )
    elif zone_name == "network_footprint":
        return (
            f"User {uid} network: bytes_out={features.get('net_bytes_out', 0):.0f}, "
            f"unique_dsts={features.get('net_unique_dsts', 0):.0f}, "
            f"external_ratio={features.get('net_external_ratio', 0):.4f}, "
            f"dns_domains={features.get('dns_unique_domains', 0):.0f}, "
            f"nxdomain_ratio={features.get('dns_nxdomain_ratio', 0):.4f}"
        )
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


# ── Embedding and composition ────────────────────────────────────────────────

def build_zone_embeddings(entity_type: str, entity_id: str,
                          entity_profile: dict[str, Any],
                          features: dict[str, float],
                          embedder) -> dict[str, np.ndarray]:
    """Build 5 zone embeddings independently.

    Each zone's features are serialized to text, then embedded to 1536-d.
    """
    zones = CYBER_ZONES.get(entity_type, CYBER_ZONES["user"])
    zone_embeddings = {}

    for zone_name in zones:
        text = serialize_zone(entity_type, zone_name, entity_profile, features)
        vec = embedder.embed_text(text)
        if isinstance(vec, list):
            vec = np.array(vec, dtype=np.float32)
        zone_embeddings[zone_name] = vec

    return zone_embeddings


def softmax_attention(zone_vecs: dict[str, np.ndarray],
                      context_weights: dict[str, float]) -> dict[str, float]:
    """Compute softmax attention weights biased by context.

    logit_i = ||zone_i|| * context_weight[zone_i]
    alpha_i = softmax(logits)
    """
    if not zone_vecs:
        return {}

    logits = {}
    for name, vec in zone_vecs.items():
        energy = float(np.linalg.norm(vec))
        bias = context_weights.get(name, 0.2)
        logits[name] = energy * bias

    max_logit = max(logits.values()) if logits else 0.0
    exp_logits = {k: math.exp(v - max_logit) for k, v in logits.items()}
    total = sum(exp_logits.values())

    if total == 0:
        uniform = 1.0 / len(zone_vecs)
        return {k: uniform for k in zone_vecs}

    return {k: v / total for k, v in exp_logits.items()}


def compose_zones(zone_embeddings: dict[str, np.ndarray],
                  context: str = "normal_ops",
                  entity_type: str = "user") -> np.ndarray:
    """Attention-weighted composition of zone embeddings into composite.

    Uses context-adaptive weights to bias attention toward zones relevant
    to the investigation scenario (APT hunt, insider investigation, etc.).
    """
    ctx_weights = CONTEXT_WEIGHTS.get(entity_type, CONTEXT_WEIGHTS["user"]).get(
        context, CONTEXT_WEIGHTS["user"]["normal_ops"]
    )

    alphas = softmax_attention(zone_embeddings, ctx_weights)

    composite = np.zeros(EMBED_DIM, dtype=np.float64)
    for name, vec in zone_embeddings.items():
        alpha = alphas.get(name, 0.0)
        composite += alpha * vec.astype(np.float64)

    norm = np.linalg.norm(composite)
    if norm > 1e-10:
        composite = composite / norm

    return composite.astype(np.float32)
