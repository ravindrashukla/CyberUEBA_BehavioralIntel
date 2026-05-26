"""Temporal trajectory analysis: velocity vectors, trajectory features, regime detection.

Computes full 1536-d velocity vectors (not just scalar drift magnitude) and
extracts 6 trajectory features that capture how an entity is moving through
embedding space: velocity, acceleration, stability, regime shifts, trend
consistency, and total drift.

Ported from DLA MVP's temporal_embeddings.py (_velocity_vector, _trajectory_features).
"""
import numpy as np
from embeddings.composer import cosine_similarity
from models.cyber_entity import PhaseState, EMBED_DIM


def compute_velocity_vector(snapshots: list[np.ndarray]) -> np.ndarray:
    """1536-d velocity = normalized(last - first).

    Returns the direction the entity is moving in embedding space.
    Zero vector if fewer than 2 snapshots or no meaningful change.
    """
    if len(snapshots) < 2:
        dim = len(snapshots[0]) if snapshots else EMBED_DIM
        return np.zeros(dim, dtype=np.float32)

    velocity = snapshots[-1].astype(np.float64) - snapshots[0].astype(np.float64)
    norm = np.linalg.norm(velocity)
    if norm < 1e-8:
        return np.zeros_like(velocity, dtype=np.float32)
    return (velocity / norm).astype(np.float32)


def compute_trajectory_features(snapshots: list[np.ndarray]) -> dict:
    """Extract 6 trajectory features from a sequence of embedding snapshots.

    Returns:
        velocity_magnitude: avg L2 norm of consecutive diffs
        acceleration: mean change in velocity magnitude over steps
        stability: mean cosine similarity of consecutive snapshots
        regime_shifts: fraction of consecutive pairs below 0.7 similarity
        trend_consistency: mean pairwise cosine of step direction vectors
        total_drift: 1 - cosine_similarity(first, last)
    """
    n = len(snapshots)
    if n < 2:
        return {
            "velocity_magnitude": 0.0,
            "acceleration": 0.0,
            "stability": 1.0,
            "regime_shifts": 0.0,
            "trend_consistency": 1.0,
            "total_drift": 0.0,
        }

    consecutive_sims = []
    for i in range(n - 1):
        sim = cosine_similarity(snapshots[i], snapshots[i + 1])
        consecutive_sims.append(sim)

    diffs = [snapshots[i + 1].astype(np.float64) - snapshots[i].astype(np.float64)
             for i in range(n - 1)]
    velocities = [float(np.linalg.norm(d)) for d in diffs]
    avg_velocity = float(np.mean(velocities))

    if len(velocities) >= 2:
        accel = [velocities[i + 1] - velocities[i] for i in range(len(velocities) - 1)]
        avg_accel = float(np.mean(accel))
    else:
        avg_accel = 0.0

    stability = float(np.mean(consecutive_sims))

    regime_threshold = 0.7
    regime_shift_count = sum(1 for s in consecutive_sims if s < regime_threshold)

    if len(diffs) >= 2:
        direction_sims = []
        for i in range(len(diffs) - 1):
            d1_norm = np.linalg.norm(diffs[i])
            d2_norm = np.linalg.norm(diffs[i + 1])
            if d1_norm > 1e-8 and d2_norm > 1e-8:
                direction_sims.append(cosine_similarity(
                    diffs[i].astype(np.float32), diffs[i + 1].astype(np.float32)
                ))
        trend_consistency = float(np.mean(direction_sims)) if direction_sims else 0.0
    else:
        trend_consistency = 0.0

    total_drift = float(1.0 - cosine_similarity(snapshots[0], snapshots[-1]))

    return {
        "velocity_magnitude": avg_velocity,
        "acceleration": avg_accel,
        "stability": stability,
        "regime_shifts": float(regime_shift_count) / max(n - 1, 1),
        "trend_consistency": trend_consistency,
        "total_drift": total_drift,
    }


def detect_regime(features: dict) -> str:
    """Classify behavioral regime from trajectory features."""
    if features["regime_shifts"] > 0:
        return "regime_shift"
    if features["acceleration"] > 0.01 and features["trend_consistency"] > 0.3:
        return "accelerating"
    if features["total_drift"] > 0.05 and features["stability"] > 0.7:
        return "drifting"
    return "stable"


def compute_zone_trajectories(
    zone_snapshot_series: dict[str, list[np.ndarray]],
) -> dict[str, dict]:
    """Per-zone trajectory features.

    Computes trajectory features independently per zone, enabling detection
    like "identity zone stable but network_footprint zone in regime_shift."
    """
    results = {}
    for zone_name, snapshots in zone_snapshot_series.items():
        feats = compute_trajectory_features(snapshots)
        feats["regime"] = detect_regime(feats)
        results[zone_name] = feats
    return results


def build_phase_state(
    composite_snapshots: list[np.ndarray],
    zone_snapshot_series: dict[str, list[np.ndarray]] = None,
) -> PhaseState:
    """Build full PhaseState from temporal snapshot series."""
    feats = compute_trajectory_features(composite_snapshots)
    vel = compute_velocity_vector(composite_snapshots)
    regime = detect_regime(feats)

    return PhaseState(
        velocity_vector=vel,
        velocity_magnitude=feats["velocity_magnitude"],
        acceleration=feats["acceleration"],
        stability=feats["stability"],
        regime_shifts=feats["regime_shifts"],
        trend_consistency=feats["trend_consistency"],
        total_drift=feats["total_drift"],
        current_regime=regime,
    )
