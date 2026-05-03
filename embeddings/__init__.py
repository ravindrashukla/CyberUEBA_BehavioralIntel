"""Embedding pipeline: embed behavioral signals into 1536-d vectors."""
from embeddings.embedder import Embedder, MockEmbedder
from embeddings.composer import compose, cosine_similarity, drift_magnitude, drift_vector
from embeddings.snapshot_builder import SnapshotBuilder

__all__ = [
    "Embedder",
    "MockEmbedder",
    "compose",
    "cosine_similarity",
    "drift_magnitude",
    "drift_vector",
    "SnapshotBuilder",
]
