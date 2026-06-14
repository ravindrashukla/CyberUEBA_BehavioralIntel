"""Embedding pipeline: embed behavioral signals into 1536-d vectors."""
from embeddings.embedder import Embedder
from embeddings.composer import compose, cosine_similarity, drift_magnitude, drift_vector
from embeddings.snapshot_builder import SnapshotBuilder

__all__ = [
    "Embedder",
    "compose",
    "cosine_similarity",
    "drift_magnitude",
    "drift_vector",
    "SnapshotBuilder",
]
