"""Drift direction analysis: what is this entity BECOMING?

Core idea: drift_vector = V_t2 - V_t1 (the direction of behavioral change)
Project this onto reference concept embeddings to determine WHAT the entity
is drifting toward. High alignment with a threat concept = alert.
"""
import numpy as np
from dataclasses import dataclass

from embeddings.composer import cosine_similarity, drift_magnitude, drift_vector
from detection.reference_concepts import ConceptLibrary, ReferenceConcept

__all__ = [
    "ConceptAlignment",
    "DriftAnalysis",
    "compute_drift_vector",
    "concept_alignment",
    "analyze_entity_drift",
    "batch_drift_analysis",
]


@dataclass
class ConceptAlignment:
    concept_name: str
    category: str  # "threat" or "benign"
    alignment_score: float  # cosine similarity of drift_vector with concept vector
    severity: str
    mitre_techniques: list[str]


@dataclass
class DriftAnalysis:
    entity_type: str
    entity_id: str
    drift_magnitude: float  # how much did it drift (cosine distance)
    top_alignments: list[ConceptAlignment]  # sorted by abs(alignment_score)
    primary_direction: str  # name of highest-alignment concept
    is_threat: bool  # primary direction is a threat concept above threshold
    confidence: float  # alignment_score of primary direction


def compute_drift_vector(v_old: np.ndarray, v_new: np.ndarray) -> np.ndarray:
    """Compute normalized drift direction between two snapshots.

    Returns a unit vector pointing in the direction of behavioral change.
    If the vectors are identical, returns a zero vector.
    """
    return drift_vector(v_old, v_new)


def concept_alignment(
    drift_vec: np.ndarray,
    concept_vectors: dict[str, np.ndarray],
    concept_library: ConceptLibrary,
) -> list[ConceptAlignment]:
    """Project drift vector onto all concept vectors.

    Computes cosine similarity between the drift direction and each reference
    concept embedding. High positive score means the entity is drifting TOWARD
    that concept; negative means drifting AWAY from it.

    Args:
        drift_vec: normalized drift direction vector
        concept_vectors: mapping of concept_name -> embedding vector
        concept_library: library instance for metadata lookup

    Returns:
        List of ConceptAlignment sorted by alignment_score descending.
    """
    # Zero drift vector means no movement — return empty alignments
    if np.linalg.norm(drift_vec) < 1e-10:
        return []

    alignments = []
    for name, vec in concept_vectors.items():
        score = cosine_similarity(drift_vec, vec)
        concept = concept_library.get_concept(name)
        alignments.append(ConceptAlignment(
            concept_name=name,
            category=concept.category,
            alignment_score=float(score),
            severity=concept.severity,
            mitre_techniques=concept.mitre_techniques,
        ))

    alignments.sort(key=lambda a: a.alignment_score, reverse=True)
    return alignments


def analyze_entity_drift(
    entity_type: str,
    entity_id: str,
    v_old: np.ndarray,
    v_new: np.ndarray,
    concept_library: ConceptLibrary,
    alignment_threshold: float = 0.3,
) -> DriftAnalysis:
    """Full drift analysis for an entity between two time periods.

    Computes drift direction, projects onto all concept vectors, and determines
    whether the primary drift direction constitutes a threat.

    Args:
        entity_type: type of entity (user, device, segment, etc.)
        entity_id: unique identifier
        v_old: earlier behavioral embedding
        v_new: later behavioral embedding
        concept_library: library with pre-computed concept embeddings
        alignment_threshold: minimum alignment score to classify as threat

    Returns:
        DriftAnalysis with concept alignments and threat determination.
    """
    mag = drift_magnitude(v_old, v_new)
    drift_vec = compute_drift_vector(v_old, v_new)

    # Combine all concept vectors for projection
    all_vectors = {**concept_library.all_threat_vectors(), **concept_library.all_benign_vectors()}
    alignments = concept_alignment(drift_vec, all_vectors, concept_library)

    # Determine primary direction
    if alignments:
        primary = alignments[0]
        is_threat = (
            primary.category == "threat"
            and primary.alignment_score >= alignment_threshold
        )
    else:
        primary = None
        is_threat = False

    return DriftAnalysis(
        entity_type=entity_type,
        entity_id=entity_id,
        drift_magnitude=float(mag),
        top_alignments=alignments[:5],  # top 5 for diagnostics
        primary_direction=primary.concept_name if primary else "none",
        is_threat=is_threat,
        confidence=primary.alignment_score if primary else 0.0,
    )


def batch_drift_analysis(
    entity_snapshots: dict[str, tuple[np.ndarray, np.ndarray]],
    entity_type: str,
    concept_library: ConceptLibrary,
    alignment_threshold: float = 0.3,
    min_drift_magnitude: float = 0.01,
) -> list[DriftAnalysis]:
    """Analyze drift for multiple entities. Return only those with significant drift.

    Args:
        entity_snapshots: mapping of entity_id -> (v_old, v_new) embedding pairs
        entity_type: type of all entities in this batch
        concept_library: library with pre-computed concept embeddings
        alignment_threshold: minimum alignment score for threat classification
        min_drift_magnitude: minimum drift magnitude to include in results

    Returns:
        List of DriftAnalysis for entities with drift above min_drift_magnitude,
        sorted by drift_magnitude descending.
    """
    results = []
    for entity_id, (v_old, v_new) in entity_snapshots.items():
        mag = drift_magnitude(v_old, v_new)
        if mag < min_drift_magnitude:
            continue

        analysis = analyze_entity_drift(
            entity_type=entity_type,
            entity_id=entity_id,
            v_old=v_old,
            v_new=v_new,
            concept_library=concept_library,
            alignment_threshold=alignment_threshold,
        )
        results.append(analysis)

    results.sort(key=lambda a: a.drift_magnitude, reverse=True)
    return results


# ── Tier 3 zone-specific drift analysis ──────────────────────────────────────


def analyze_zone_drift(
    entity_type: str,
    entity_id: str,
    zone_old: dict[str, np.ndarray],
    zone_new: dict[str, np.ndarray],
    concept_library: ConceptLibrary,
    alignment_threshold: float = 0.3,
) -> dict[str, DriftAnalysis]:
    """Per-zone drift analysis. Returns {zone_name: DriftAnalysis}.

    Computes drift analysis independently per zone, enabling detection of
    patterns like "identity stable but network_footprint drifting toward
    c2_beacon."
    """
    results = {}
    for zone_name in zone_old:
        if zone_name not in zone_new:
            continue
        v_old = zone_old[zone_name]
        v_new = zone_new[zone_name]
        analysis = analyze_entity_drift(
            entity_type=entity_type,
            entity_id=f"{entity_id}:{zone_name}",
            v_old=v_old,
            v_new=v_new,
            concept_library=concept_library,
            alignment_threshold=alignment_threshold,
        )
        results[zone_name] = analysis
    return results


def detect_zone_divergence(
    zone_drift_results: dict[str, DriftAnalysis],
    stable_threshold: float = 0.02,
    drift_threshold: float = 0.05,
) -> list[str]:
    """Find zones drifting while others are stable.

    Returns diagnostic strings like:
    "identity STABLE (0.003), network_footprint DRIFTING (0.082) toward c2_beacon"
    """
    stable_zones = []
    drifting_zones = []

    for zone_name, analysis in zone_drift_results.items():
        if analysis.drift_magnitude < stable_threshold:
            stable_zones.append((zone_name, analysis))
        elif analysis.drift_magnitude >= drift_threshold:
            drifting_zones.append((zone_name, analysis))

    if not stable_zones or not drifting_zones:
        return []

    diagnostics = []
    for sz_name, sz_analysis in stable_zones:
        for dz_name, dz_analysis in drifting_zones:
            direction = dz_analysis.primary_direction
            msg = (
                f"{sz_name} STABLE ({sz_analysis.drift_magnitude:.3f}), "
                f"{dz_name} DRIFTING ({dz_analysis.drift_magnitude:.3f}) "
                f"toward {direction}"
            )
            diagnostics.append(msg)

    return diagnostics
