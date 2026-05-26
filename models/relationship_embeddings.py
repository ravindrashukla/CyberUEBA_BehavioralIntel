"""Relationship embeddings via Hadamard product.

Entity-pair interactions become first-class vectors in the same 1536-d space.
Drift in a relationship embedding means the interaction pattern is changing,
even if neither entity individually drifts.

Ported from DLA MVP's relationship_embeddings.py (Hadamard composition).
"""
import numpy as np


def hadamard(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Element-wise product, L2-normalized."""
    product = a.astype(np.float64) * b.astype(np.float64)
    norm = np.linalg.norm(product)
    if norm < 1e-8:
        return np.zeros_like(product, dtype=np.float32)
    return (product / norm).astype(np.float32)


def compute_user_device_vector(user_emb: np.ndarray, device_emb: np.ndarray) -> np.ndarray:
    """UserDevice(User, Device) = user_emb ⊙ device_emb."""
    return hadamard(user_emb, device_emb)


def compute_user_app_vector(user_emb: np.ndarray, app_emb: np.ndarray) -> np.ndarray:
    """UserApp(User, App) = user_emb ⊙ app_emb."""
    return hadamard(user_emb, app_emb)


def compute_device_segment_vector(device_emb: np.ndarray, segment_emb: np.ndarray) -> np.ndarray:
    """DeviceSegment(Device, Segment) = device_emb ⊙ segment_emb."""
    return hadamard(device_emb, segment_emb)


def relationship_drift(rel_old: np.ndarray, rel_new: np.ndarray) -> float:
    """Cosine distance between two relationship snapshots. Range [0, 2]."""
    dot = np.dot(rel_old, rel_new)
    na = np.linalg.norm(rel_old)
    nb = np.linalg.norm(rel_new)
    if na < 1e-8 or nb < 1e-8:
        return 0.0
    return float(1.0 - dot / (na * nb))
