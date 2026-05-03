"""Compose multiple signal embeddings into a single composite vector."""
import numpy as np

SIGNAL_WEIGHTS = {
    "user": {
        "auth": 0.25,
        "privilege": 0.20,
        "data_access": 0.20,
        "network": 0.20,
        "communication": 0.15,
    },
    "device": {
        "process": 0.25,
        "traffic": 0.25,
        "resource": 0.20,
        "auth": 0.15,
        "config": 0.15,
    },
    "segment": {
        "volume": 0.20,
        "connections": 0.25,
        "protocols": 0.20,
        "threats": 0.20,
        "exposure": 0.15,
    },
    "app": {
        "access": 0.25,
        "queries": 0.20,
        "errors": 0.20,
        "performance": 0.15,
        "config": 0.20,
    },
    "session": {
        "activity": 0.20,
        "risk_accum": 0.25,
        "data_movement": 0.20,
        "lateral": 0.20,
        "temporal": 0.15,
    },
}


def compose(signal_vectors: dict[str, np.ndarray], entity_type: str) -> np.ndarray:
    """Weighted average composition of signal vectors into composite.

    Args:
        signal_vectors: dict mapping signal_name -> 1536-d numpy array
        entity_type: one of "user", "device", "segment", "app", "session"

    Returns:
        1536-d normalized composite vector

    Raises:
        ValueError: if entity_type is unknown or no valid signals provided
    """
    if entity_type not in SIGNAL_WEIGHTS:
        raise ValueError(
            f"Unknown entity_type '{entity_type}'. "
            f"Must be one of: {list(SIGNAL_WEIGHTS.keys())}"
        )

    weights = SIGNAL_WEIGHTS[entity_type]
    composite = np.zeros(signal_vectors[next(iter(signal_vectors))].shape, dtype=np.float64)
    total_weight = 0.0

    for signal_name, vector in signal_vectors.items():
        w = weights.get(signal_name, 0.0)
        if w > 0:
            composite += w * vector.astype(np.float64)
            total_weight += w

    if total_weight == 0.0:
        raise ValueError(
            f"No matching signal weights for entity_type '{entity_type}'. "
            f"Provided signals: {list(signal_vectors.keys())}, "
            f"expected: {list(weights.keys())}"
        )

    # Normalize by actual weight sum (handles missing signals gracefully)
    composite = composite / total_weight

    # L2-normalize to unit vector
    norm = np.linalg.norm(composite)
    if norm > 0:
        composite = composite / norm

    return composite.astype(np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def drift_vector(v_old: np.ndarray, v_new: np.ndarray) -> np.ndarray:
    """Compute drift direction vector (v_new - v_old), normalized.

    Returns a unit vector pointing in the direction of behavioral change.
    If the vectors are identical, returns a zero vector.
    """
    diff = v_new.astype(np.float64) - v_old.astype(np.float64)
    norm = np.linalg.norm(diff)
    if norm < 1e-10:
        return np.zeros_like(diff, dtype=np.float32)
    return (diff / norm).astype(np.float32)


def drift_magnitude(v_old: np.ndarray, v_new: np.ndarray) -> float:
    """Cosine distance between two temporal snapshots.

    Returns value in [0, 2]: 0 = identical, 1 = orthogonal, 2 = opposite.
    """
    return 1.0 - cosine_similarity(v_old, v_new)
