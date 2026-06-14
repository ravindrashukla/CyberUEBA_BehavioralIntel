import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import numpy as np
from detection.reference_concepts import ConceptLibrary
from detection.alert_generator import AlertGenerator
from detection.kill_chain import KillChainReconstructor


@pytest.fixture
def real_embedder():
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("requires OPENAI_API_KEY — real OpenAI embeddings (mock removed)")
    from embeddings.embedder import Embedder
    return Embedder(preload=False)


@pytest.fixture
def concept_library(real_embedder):
    lib = ConceptLibrary(embedder=real_embedder)
    lib.embed_concepts()
    return lib


@pytest.fixture
def alert_generator():
    return AlertGenerator(
        drift_threshold=0.15,
        cusum_threshold=0.05,
        alignment_threshold=0.2,
    )


@pytest.fixture
def kill_chain_reconstructor():
    return KillChainReconstructor(correlation_window_hours=72)


@pytest.fixture
def random_unit_vector():
    def _factory(dim=1536, seed=None):
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(dim).astype(np.float32)
        return v / np.linalg.norm(v)
    return _factory
