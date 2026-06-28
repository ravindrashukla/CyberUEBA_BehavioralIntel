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
MAX_BATCH_SIZE = 2000  # OpenAI supports large batches for short texts
RATE_LIMIT_PAUSE = 0.2  # seconds between batches


class Embedder:
    """Production embedder using OpenAI text-embedding-3-small with disk cache."""

    def __init__(self, api_key: str = None, cache_dir: Path = CACHE_DIR, preload: bool = True):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = None  # lazy init
        self._cache_hits = 0
        self._api_calls = 0
        self._mem_cache: dict[str, np.ndarray] = {}
        if preload:
            self._preload_cache()

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, timeout=60.0)
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
        import sys
        results = [None] * len(texts)
        uncached_indices = []

        for i, text in enumerate(texts):
            cached = self._get_cached(text)
            if cached is not None:
                results[i] = cached
                self._cache_hits += 1
            else:
                uncached_indices.append(i)

        n_batches = (len(uncached_indices) + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE if uncached_indices else 0
        if uncached_indices:
            print(f"    {len(texts)} total, {self._cache_hits} cached, "
                  f"{len(uncached_indices)} to embed in {n_batches} batches",
                  flush=True)

        for batch_num, batch_start in enumerate(range(0, len(uncached_indices), MAX_BATCH_SIZE)):
            batch_end = min(batch_start + MAX_BATCH_SIZE, len(uncached_indices))
            batch_indices = uncached_indices[batch_start:batch_end]
            batch_texts = [texts[i] for i in batch_indices]

            for attempt in range(3):
                try:
                    response = self.client.embeddings.create(
                        input=batch_texts,
                        model=EMBEDDING_MODEL,
                    )
                    break
                except Exception as e:
                    if attempt < 2:
                        wait = 2 ** (attempt + 1)
                        print(f"    Batch {batch_num+1} attempt {attempt+1} failed: {e}. Retrying in {wait}s...",
                              flush=True)
                        time.sleep(wait)
                    else:
                        raise

            self._api_calls += len(batch_texts)

            for j, embedding_obj in enumerate(response.data):
                idx = batch_indices[j]
                vector = np.array(embedding_obj.embedding, dtype=np.float32)
                results[idx] = vector
                self._set_cached(texts[idx], vector)

            if (batch_num + 1) % 5 == 0 or batch_num == n_batches - 1:
                done = batch_end
                print(f"    Batch {batch_num+1}/{n_batches}: {done}/{len(uncached_indices)} embedded",
                      flush=True)

            if batch_end < len(uncached_indices):
                time.sleep(RATE_LIMIT_PAUSE)

        return results

    def _cache_key(self, text: str) -> str:
        """SHA256 hash of text for cache filename."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _cache_path(self, text: str) -> Path:
        """Return sharded cache path: cache_dir/ab/abcdef...npy"""
        key = self._cache_key(text)
        shard = key[:2]
        return self.cache_dir / shard / f"{key}.npy"

    def _preload_cache(self):
        """Load all cached embeddings into memory at startup."""
        import pickle
        consolidated = self.cache_dir / "_consolidated.pkl"
        if consolidated.exists():
            with open(consolidated, "rb") as f:
                self._mem_cache = pickle.load(f)
            print(f"  Preloaded {len(self._mem_cache)} embeddings from consolidated cache "
                  f"({len(self._mem_cache) * EMBEDDING_DIM * 4 / 1024 / 1024:.0f} MB)")
            return
        count = 0
        for shard_dir in self.cache_dir.iterdir():
            if shard_dir.is_dir() and len(shard_dir.name) == 2:
                for npy_file in shard_dir.glob("*.npy"):
                    try:
                        arr = np.load(npy_file)
                        if arr.shape == (EMBEDDING_DIM,):
                            self._mem_cache[npy_file.stem] = arr
                            count += 1
                    except (ValueError, OSError):
                        pass
        if count > 0:
            print(f"  Preloaded {count} embeddings into memory "
                  f"({count * EMBEDDING_DIM * 4 / 1024 / 1024:.0f} MB)")

    def _get_cached(self, text: str) -> np.ndarray | None:
        """Check memory cache first, then disk."""
        key = self._cache_key(text)
        if key in self._mem_cache:
            return self._mem_cache[key]
        path = self._cache_path(text)
        if not path.exists():
            flat = self.cache_dir / f"{key}.npy"
            if flat.exists():
                path = flat
            else:
                return None
        try:
            arr = np.load(path)
            if arr.shape == (EMBEDDING_DIM,):
                self._mem_cache[key] = arr
                return arr
            path.unlink()
        except (ValueError, OSError):
            path.unlink(missing_ok=True)
        return None

    def _set_cached(self, text: str, vector: np.ndarray):
        """Save to memory and sharded disk cache."""
        key = self._cache_key(text)
        self._mem_cache[key] = vector
        path = self._cache_path(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, vector)

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
