"""Detection engine for behavioral drift analysis."""
from detection.cusum import CUSUMResult, cusum_detect, cusum_scan_entity, batch_cusum_scan
from detection.reference_concepts import (
    ReferenceConcept,
    THREAT_CONCEPTS,
    BENIGN_CONCEPTS,
    ALL_CONCEPTS,
    ConceptLibrary,
)
from detection.drift_direction import (
    ConceptAlignment,
    DriftAnalysis,
    compute_drift_vector,
    concept_alignment,
    analyze_entity_drift,
    batch_drift_analysis,
)
from detection.alert_generator import AlertSeverity, AlertStatus, Alert, AlertGenerator
from detection.kill_chain import KillChainEvent, KillChain, KillChainReconstructor
from detection.cohort_analysis import Cohort, CohortMember, detect_cohorts, detect_cohorts_from_db
from detection.mitre_mapper import (
    TechniqueInfo,
    TECHNIQUE_DB,
    technique_to_tactic,
    techniques_to_tactics,
    get_technique_info,
    concept_to_techniques,
    build_attack_narrative,
)

__all__ = [
    # cusum
    "CUSUMResult",
    "cusum_detect",
    "cusum_scan_entity",
    "batch_cusum_scan",
    # reference_concepts
    "ReferenceConcept",
    "THREAT_CONCEPTS",
    "BENIGN_CONCEPTS",
    "ALL_CONCEPTS",
    "ConceptLibrary",
    # drift_direction
    "ConceptAlignment",
    "DriftAnalysis",
    "compute_drift_vector",
    "concept_alignment",
    "analyze_entity_drift",
    "batch_drift_analysis",
    # alert_generator
    "AlertSeverity",
    "AlertStatus",
    "Alert",
    "AlertGenerator",
    # kill_chain
    "KillChainEvent",
    "KillChain",
    "KillChainReconstructor",
    # cohort_analysis
    "Cohort",
    "CohortMember",
    "detect_cohorts",
    "detect_cohorts_from_db",
    # mitre_mapper
    "TechniqueInfo",
    "TECHNIQUE_DB",
    "technique_to_tactic",
    "techniques_to_tactics",
    "get_technique_info",
    "concept_to_techniques",
    "build_attack_narrative",
]
