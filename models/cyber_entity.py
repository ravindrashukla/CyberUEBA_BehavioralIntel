"""Digital Entity model for Tier 3 detection.

Unified dataclass capturing an entity's full behavioral profile:
zone embeddings, phase state (velocity/regime), relationship embeddings,
and risk scores. Ported from DLA MVP's DigitalEntity pattern.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Any, Optional


EMBED_DIM = 1536


@dataclass
class PhaseState:
    velocity_vector: np.ndarray = field(default_factory=lambda: np.zeros(EMBED_DIM, dtype=np.float32))
    velocity_magnitude: float = 0.0
    acceleration: float = 0.0
    stability: float = 1.0
    regime_shifts: float = 0.0
    trend_consistency: float = 1.0
    total_drift: float = 0.0
    current_regime: str = "stable"


@dataclass
class CyberEntity:
    entity_type: str
    entity_id: str
    profile: dict[str, Any] = field(default_factory=dict)
    zone_embeddings: dict[str, np.ndarray] = field(default_factory=dict)
    composite_embedding: Optional[np.ndarray] = None
    phase_state: PhaseState = field(default_factory=PhaseState)
    relationships: dict[str, np.ndarray] = field(default_factory=dict)
    risk_scores: dict[str, float] = field(default_factory=dict)
    computed_at: str = ""
    data_gaps: list[str] = field(default_factory=list)
    context: str = "normal_ops"

    # Temporal series stored during pipeline run (not persisted)
    zone_snapshot_series: dict[str, list[np.ndarray]] = field(default_factory=dict)
    composite_snapshots: list[np.ndarray] = field(default_factory=list)
    relationship_snapshots: dict[str, list[np.ndarray]] = field(default_factory=dict)


@dataclass
class Tier3Config:
    acceleration_threshold: float = 0.01
    trend_consistency_min: float = 0.5
    regime_shift_threshold: float = 0.7
    zone_stable_threshold: float = 0.02
    zone_drifting_threshold: float = 0.05
    relationship_drift_threshold: float = 0.05
    contextual_threat_threshold: float = 0.30
    cohort_similarity: float = 0.5
    cohort_min_size: int = 3
    threat_consistency_threshold: float = 0.40
