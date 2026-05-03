"""OpenAI embedding client with disk cache and rate limiting."""
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
CACHE_DIR = Path("data/embedding_cache")
MAX_BATCH_SIZE = 100  # OpenAI limit
RATE_LIMIT_PAUSE = 0.1  # seconds between batches


class Embedder:
    """Production embedder using OpenAI text-embedding-3-small with disk cache."""

    def __init__(self, api_key: str = None, cache_dir: Path = CACHE_DIR):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = None  # lazy init
        self._cache_hits = 0
        self._api_calls = 0

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    def embed_text(self, text: str) -> np.ndarray:
        """Embed a single text string, using cache if available."""
        cached = self._get_cached(text)
        if cached is not None:
            self._cache_hits += 1
            return cached

        response = self.client.embeddings.create(
            input=[text],
            model=EMBEDDING_MODEL,
        )
        vector = np.array(response.data[0].embedding, dtype=np.float32)
        self._api_calls += 1
        self._set_cached(text, vector)
        return vector

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """Embed multiple texts in batches of MAX_BATCH_SIZE."""
        results = [None] * len(texts)
        uncached_indices = []

        # Check cache first
        for i, text in enumerate(texts):
            cached = self._get_cached(text)
            if cached is not None:
                results[i] = cached
                self._cache_hits += 1
            else:
                uncached_indices.append(i)

        # Batch API calls for uncached texts
        for batch_start in range(0, len(uncached_indices), MAX_BATCH_SIZE):
            batch_end = min(batch_start + MAX_BATCH_SIZE, len(uncached_indices))
            batch_indices = uncached_indices[batch_start:batch_end]
            batch_texts = [texts[i] for i in batch_indices]

            response = self.client.embeddings.create(
                input=batch_texts,
                model=EMBEDDING_MODEL,
            )
            self._api_calls += len(batch_texts)

            for j, embedding_obj in enumerate(response.data):
                idx = batch_indices[j]
                vector = np.array(embedding_obj.embedding, dtype=np.float32)
                results[idx] = vector
                self._set_cached(texts[idx], vector)

            # Rate limit between batches
            if batch_end < len(uncached_indices):
                time.sleep(RATE_LIMIT_PAUSE)

        return results

    def _cache_key(self, text: str) -> str:
        """SHA256 hash of text for cache filename."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _get_cached(self, text: str) -> np.ndarray | None:
        """Load from disk cache if exists."""
        cache_path = self.cache_dir / f"{self._cache_key(text)}.npy"
        if cache_path.exists():
            return np.load(cache_path)
        return None

    def _set_cached(self, text: str, vector: np.ndarray):
        """Save to disk cache."""
        cache_path = self.cache_dir / f"{self._cache_key(text)}.npy"
        np.save(cache_path, vector)

    def stats(self) -> dict:
        """Return cache hit/miss stats."""
        return {
            "cache_hits": self._cache_hits,
            "api_calls": self._api_calls,
            "hit_rate": (
                self._cache_hits / (self._cache_hits + self._api_calls)
                if (self._cache_hits + self._api_calls) > 0
                else 0.0
            ),
        }


class MockEmbedder:
    """Deterministic pseudo-random embedder for testing without an API key.

    Produces consistent 1536-d unit vectors for the same input text by seeding
    a numpy RNG with the SHA256 hash of the text.
    """

    def __init__(self):
        self._cache_hits = 0
        self._api_calls = 0

    def embed_text(self, text: str) -> np.ndarray:
        """Generate a deterministic 1536-d vector from text hash."""
        self._api_calls += 1
        return self._hash_to_vector(text)

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """Generate deterministic vectors for a batch of texts."""
        self._api_calls += len(texts)
        return [self._hash_to_vector(t) for t in texts]

    def _hash_to_vector(self, text: str) -> np.ndarray:
        """Convert text to a deterministic unit vector via seeded RNG."""
        hash_bytes = hashlib.sha256(text.encode("utf-8")).digest()
        # Use first 8 bytes as uint64 seed
        seed = int.from_bytes(hash_bytes[:8], byteorder="little")
        rng = np.random.default_rng(seed)
        vector = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        # Normalize to unit length
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
        return vector

    def stats(self) -> dict:
        """Return stats (mock always shows 0 cache hits)."""
        return {
            "cache_hits": self._cache_hits,
            "api_calls": self._api_calls,
            "hit_rate": 0.0,
        }
