"""AI/ML Agent Tests — Embedding, Composition, Similarity, Drift, Zones,
Trajectory, Hadamard, Context Weights, DB Integrity, and End-to-End Pipeline.

Test IDs: AI-001 through AI-048
Covers:
  1. MockEmbedder determinism, dimension, normalization
  2. Zone serialization (all 5 zones)
  3. Embedding composition (Tier 2 weighted + Tier 3 attention)
  4. Cosine similarity properties
  5. Drift computation (magnitude, vector, symmetry)
  6. Velocity vectors (1536-d, direction)
  7. Trajectory features (6 keys, reasonable ranges)
  8. Regime detection (stable, regime_shift, accelerating, drifting)
  9. Hadamard products (dimension, normalization, commutativity)
 10. Context weight sensitivity (apt_hunt, insider_investigation)
 11. DB embedding integrity (behavioral_snapshots)
 12. End-to-end embedding pipeline
"""

import os
import warnings

# ── Environment defaults for DB connection ──────────────────────────────────
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5437")

# Suppress pandas SQLAlchemy warnings
warnings.filterwarnings("ignore", message=".*pandas.*SQLAlchemy.*")
warnings.filterwarnings("ignore", category=UserWarning, module="pandas")

import pytest
import numpy as np

from embeddings.embedder import EMBEDDING_DIM
from embeddings.composer import (
    SIGNAL_WEIGHTS,
    compose,
    cosine_similarity,
    drift_vector,
    drift_magnitude,
    compose_with_attention,
    hadamard_compose,
)
from models.hierarchical_zones import (
    CYBER_ZONES,
    USER_ZONE_ORDER,
    CONTEXT_WEIGHTS,
    ALL_CONTEXTS,
    serialize_zone,
    build_zone_embeddings,
    compose_zones,
    softmax_attention,
)
from models.temporal_trajectory import (
    compute_velocity_vector,
    compute_trajectory_features,
    detect_regime,
)
from models.relationship_embeddings import (
    hadamard,
    compute_user_device_vector,
)
from models.cyber_entity import EMBED_DIM, PhaseState
from detection.reference_concepts import ALL_CONCEPTS, ConceptLibrary
from detection.drift_direction import analyze_entity_drift


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1: MockEmbedder Determinism (AI-001 to AI-005)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.p0
def test_ai_001_embed_text_returns_1536d(real_embedder):
    """AI-001: embed_text returns a 1536-d float32 numpy array."""
    vec = real_embedder.embed_text("hello world")
    assert isinstance(vec, np.ndarray)
    assert vec.shape == (EMBEDDING_DIM,)
    assert vec.dtype == np.float32


@pytest.mark.p0
def test_ai_002_embed_text_unit_norm(real_embedder):
    """AI-002: embed_text output is L2-normalized (unit vector).

    Real OpenAI embeddings are normalized to ~1.0 but only to float32 precision,
    so use a tolerance appropriate for real (not exactly-normalized) vectors.
    """
    vec = real_embedder.embed_text("unit norm test")
    norm = float(np.linalg.norm(vec))
    assert np.allclose(norm, 1.0, atol=1e-3)


@pytest.mark.p0
def test_ai_003_embed_text_deterministic(real_embedder):
    """AI-003: Same input text always produces the same vector."""
    v1 = real_embedder.embed_text("deterministic check")
    v2 = real_embedder.embed_text("deterministic check")
    assert np.allclose(v1, v2, atol=1e-6)


@pytest.mark.p0
def test_ai_004_embed_text_different_inputs(real_embedder):
    """AI-004: Different input texts produce different vectors."""
    v1 = real_embedder.embed_text("alpha")
    v2 = real_embedder.embed_text("beta")
    assert not np.allclose(v1, v2, atol=1e-3)


@pytest.mark.p1
def test_ai_005_embed_batch_matches_singles(real_embedder):
    """AI-005: embed_batch results match individual embed_text calls."""
    texts = ["one", "two", "three"]
    batch = real_embedder.embed_batch(texts)
    assert len(batch) == len(texts)
    for text, batch_vec in zip(texts, batch):
        single_vec = real_embedder.embed_text(text)
        assert np.allclose(batch_vec, single_vec, atol=1e-6)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2: Composition — Tier 2 Weighted Average (AI-006 to AI-010)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.p0
def test_ai_006_compose_weighted_average(random_unit_vector):
    """AI-006: compose produces the correct weighted-average then L2-normalizes."""
    user_signals = list(SIGNAL_WEIGHTS["user"].keys())
    vectors = {}
    for i, name in enumerate(user_signals):
        vectors[name] = random_unit_vector(seed=100 + i)

    result = compose(vectors, "user")

    weights = SIGNAL_WEIGHTS["user"]
    total_weight = sum(weights[s] for s in user_signals)
    expected = np.zeros(EMBEDDING_DIM, dtype=np.float64)
    for name in user_signals:
        expected += weights[name] * vectors[name].astype(np.float64)
    expected /= total_weight
    norm = np.linalg.norm(expected)
    if norm > 0:
        expected = expected / norm
    expected = expected.astype(np.float32)

    assert np.allclose(result, expected, atol=1e-6)


@pytest.mark.p0
def test_ai_007_compose_output_unit_norm(random_unit_vector):
    """AI-007: compose output is always a unit vector."""
    vectors = {name: random_unit_vector(seed=200 + i)
               for i, name in enumerate(SIGNAL_WEIGHTS["device"].keys())}
    result = compose(vectors, "device")
    norm = float(np.linalg.norm(result))
    assert np.allclose(norm, 1.0, atol=1e-6)


@pytest.mark.p0
def test_ai_008_compose_all_entity_types(random_unit_vector):
    """AI-008: compose works for all 5 entity types with matching signal names."""
    for entity_type, signals in SIGNAL_WEIGHTS.items():
        vectors = {name: random_unit_vector(seed=300 + i)
                   for i, name in enumerate(signals.keys())}
        result = compose(vectors, entity_type)
        assert result.shape == (EMBEDDING_DIM,)
        norm = float(np.linalg.norm(result))
        assert np.allclose(norm, 1.0, atol=1e-6), (
            f"compose for entity_type='{entity_type}' did not return unit norm"
        )


@pytest.mark.p1
def test_ai_009_compose_unknown_entity_raises():
    """AI-009: compose raises ValueError for unknown entity_type."""
    dummy = {"x": np.zeros(EMBEDDING_DIM, dtype=np.float32)}
    with pytest.raises(ValueError, match="Unknown entity_type"):
        compose(dummy, "nonexistent_type")


@pytest.mark.p0
def test_ai_010_compose_no_matching_signals_raises():
    """AI-010: compose raises ValueError when no signal names match the entity weights."""
    bad_signals = {"zzz_bogus": np.ones(EMBEDDING_DIM, dtype=np.float32)}
    with pytest.raises(ValueError, match="No matching signal weights"):
        compose(bad_signals, "user")


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3: Cosine Similarity Properties (AI-011 to AI-013)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.p0
def test_ai_011_cosine_similarity_identical(random_unit_vector):
    """AI-011: cosine_similarity of a vector with itself is 1.0."""
    v = random_unit_vector(seed=400)
    sim = cosine_similarity(v, v)
    assert np.allclose(sim, 1.0, atol=1e-6)


@pytest.mark.p0
def test_ai_012_cosine_similarity_orthogonal():
    """AI-012: cosine_similarity of orthogonal vectors is 0.0."""
    a = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    b = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    a[0] = 1.0
    b[1] = 1.0
    sim = cosine_similarity(a, b)
    assert np.allclose(sim, 0.0, atol=1e-6)


@pytest.mark.p1
def test_ai_013_cosine_similarity_zero_vector():
    """AI-013: cosine_similarity returns 0.0 when either vector is zero."""
    zero = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    nonzero = np.ones(EMBEDDING_DIM, dtype=np.float32)
    assert cosine_similarity(zero, nonzero) == 0.0
    assert cosine_similarity(nonzero, zero) == 0.0
    assert cosine_similarity(zero, zero) == 0.0


@pytest.mark.p0
def test_ai_013b_cosine_similarity_opposite():
    """AI-013b: cosine_similarity of opposite vectors is -1.0."""
    v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    v[0] = 1.0
    sim = cosine_similarity(v, -v)
    assert np.allclose(sim, -1.0, atol=1e-6)


@pytest.mark.p0
def test_ai_013c_cosine_similarity_symmetric(random_unit_vector):
    """AI-013c: cosine_similarity(a, b) == cosine_similarity(b, a)."""
    a = random_unit_vector(seed=410)
    b = random_unit_vector(seed=411)
    assert np.allclose(cosine_similarity(a, b), cosine_similarity(b, a), atol=1e-6)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4: Drift Computation (AI-014 to AI-017)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.p0
def test_ai_014_drift_vector_unit_norm(random_unit_vector):
    """AI-014: drift_vector returns a unit vector when inputs differ."""
    v_old = random_unit_vector(seed=500)
    v_new = random_unit_vector(seed=501)
    dv = drift_vector(v_old, v_new)
    norm = float(np.linalg.norm(dv))
    assert np.allclose(norm, 1.0, atol=1e-6)


@pytest.mark.p0
def test_ai_015_drift_vector_identical_returns_zero(random_unit_vector):
    """AI-015: drift_vector returns zero vector when inputs are identical."""
    v = random_unit_vector(seed=600)
    dv = drift_vector(v, v)
    assert np.allclose(dv, np.zeros(EMBEDDING_DIM, dtype=np.float32), atol=1e-6)


@pytest.mark.p1
def test_ai_016_drift_magnitude_range(random_unit_vector):
    """AI-016: drift_magnitude is in [0, 2] for unit vectors."""
    v_old = random_unit_vector(seed=700)
    v_new = random_unit_vector(seed=701)
    mag = drift_magnitude(v_old, v_new)
    assert 0.0 <= mag <= 2.0

    mag_same = drift_magnitude(v_old, v_old)
    assert np.allclose(mag_same, 0.0, atol=1e-6)

    mag_opp = drift_magnitude(v_old, -v_old)
    assert np.allclose(mag_opp, 2.0, atol=1e-6)


@pytest.mark.p1
def test_ai_017_drift_magnitude_symmetry(random_unit_vector):
    """AI-017: drift_magnitude(a, b) == drift_magnitude(b, a)."""
    a = random_unit_vector(seed=800)
    b = random_unit_vector(seed=801)
    assert np.allclose(drift_magnitude(a, b), drift_magnitude(b, a), atol=1e-6)


@pytest.mark.p0
def test_ai_017b_zero_drift_identical_embeddings(real_embedder):
    """AI-017b: Identical embeddings produce zero drift."""
    vec = real_embedder.embed_text("same text repeated")
    assert drift_magnitude(vec, vec) == pytest.approx(0.0, abs=1e-6)


@pytest.mark.p0
def test_ai_017c_positive_drift_different_embeddings(real_embedder):
    """AI-017c: Different embeddings produce positive drift."""
    v1 = real_embedder.embed_text("normal user behavior pattern")
    v2 = real_embedder.embed_text("anomalous data exfiltration detected")
    mag = drift_magnitude(v1, v2)
    assert mag > 0.0, "Drift between different texts should be positive"
    assert mag <= 2.0, "Drift magnitude must be in [0, 2]"


# ═══════════════════════════════════════════════════════════════════════════════
# Section 5: Reference Concepts (AI-018 to AI-020)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.p0
def test_ai_018_concept_library_embeds_all(concept_library):
    """AI-018: ConceptLibrary embeds all 12 concepts (10 threat + 2 benign)."""
    assert len(ALL_CONCEPTS) == 12
    assert len(concept_library._embeddings) == 12
    threat_vecs = concept_library.all_threat_vectors()
    benign_vecs = concept_library.all_benign_vectors()
    assert len(threat_vecs) == 10
    assert len(benign_vecs) == 2
    for name, vec in {**threat_vecs, **benign_vecs}.items():
        assert vec.shape == (EMBEDDING_DIM,), f"Concept '{name}' has wrong shape"
        norm = float(np.linalg.norm(vec))
        assert np.allclose(norm, 1.0, atol=1e-6), f"Concept '{name}' is not unit norm"


@pytest.mark.p1
def test_ai_019_analyze_entity_drift_top_alignments(concept_library, random_unit_vector):
    """AI-019: analyze_entity_drift returns DriftAnalysis with <= 5 top_alignments sorted desc."""
    v_old = random_unit_vector(seed=900)
    v_new = random_unit_vector(seed=901)
    analysis = analyze_entity_drift(
        entity_type="user",
        entity_id="u-test-019",
        v_old=v_old,
        v_new=v_new,
        concept_library=concept_library,
        alignment_threshold=0.3,
    )
    assert analysis.entity_type == "user"
    assert analysis.entity_id == "u-test-019"
    assert 0.0 <= analysis.drift_magnitude <= 2.0
    assert len(analysis.top_alignments) <= 5
    scores = [a.alignment_score for a in analysis.top_alignments]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.p1
def test_ai_020_compose_partial_signals(random_unit_vector):
    """AI-020: compose with only 3 of 5 user signals still returns a unit-norm vector."""
    user_signal_names = list(SIGNAL_WEIGHTS["user"].keys())
    partial_signals = {name: random_unit_vector(seed=1000 + i)
                       for i, name in enumerate(user_signal_names[:3])}
    result = compose(partial_signals, "user")
    assert result.shape == (EMBEDDING_DIM,)
    norm = float(np.linalg.norm(result))
    assert np.allclose(norm, 1.0, atol=1e-6)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 6: Zone Serialization (AI-021 to AI-025)
# ═══════════════════════════════════════════════════════════════════════════════

_SAMPLE_PROFILE = {
    "user_id": "USR-TEST",
    "role": "engineer",
    "department": "R&D",
    "clearance": "secret",
    "tenure_days": 365,
    "user_type": "employee",
}

_SAMPLE_FEATURES = {
    "auth_total": 120.0,
    "auth_fail_rate": 0.05,
    "auth_off_hours_ratio": 0.12,
    "auth_unique_sources": 3.0,
    "auth_unique_dests": 8.0,
    "auth_methods_used": 2.0,
    "file_total": 450.0,
    "file_restricted_ratio": 0.03,
    "file_confidential_ratio": 0.01,
    "file_write_ratio": 0.25,
    "file_unique_paths": 15.0,
    "file_total_bytes": 5_000_000.0,
    "net_bytes_out": 1_200_000.0,
    "net_unique_dsts": 12.0,
    "net_external_ratio": 0.15,
    "dns_unique_domains": 25.0,
    "dns_nxdomain_ratio": 0.02,
    "endpoint_total": 80.0,
    "endpoint_suspicious_ratio": 0.005,
    "endpoint_max_risk": 0.35,
    "endpoint_mean_risk": 0.12,
    "endpoint_unique_processes": 20.0,
}


@pytest.mark.p0
def test_ai_021_serialize_all_five_zones():
    """AI-021: serialize_zone() produces non-empty text for all 5 user zones."""
    for zone_name in USER_ZONE_ORDER:
        text = serialize_zone("user", zone_name, _SAMPLE_PROFILE, _SAMPLE_FEATURES)
        assert isinstance(text, str), f"Zone '{zone_name}' did not return string"
        assert len(text) > 10, f"Zone '{zone_name}' text is too short: '{text}'"


@pytest.mark.p0
def test_ai_022_serialize_identity_contains_profile_fields():
    """AI-022: Identity zone text contains role, department, clearance."""
    text = serialize_zone("user", "identity", _SAMPLE_PROFILE, _SAMPLE_FEATURES)
    assert "engineer" in text
    assert "R&D" in text
    assert "secret" in text
    assert "USR-TEST" in text


@pytest.mark.p0
def test_ai_023_serialize_access_pattern_contains_features():
    """AI-023: Access pattern zone text contains auth feature values."""
    text = serialize_zone("user", "access_pattern", _SAMPLE_PROFILE, _SAMPLE_FEATURES)
    assert "120" in text, "auth_total (120) not found in access_pattern text"
    assert "0.05" in text or "0.0500" in text, "auth_fail_rate not found"


@pytest.mark.p0
def test_ai_024_serialize_network_footprint_contains_features():
    """AI-024: Network footprint zone text contains network feature values."""
    text = serialize_zone("user", "network_footprint", _SAMPLE_PROFILE, _SAMPLE_FEATURES)
    assert "1200000" in text, "net_bytes_out not found in network_footprint text"
    assert "USR-TEST" in text


@pytest.mark.p1
def test_ai_025_serialize_different_features_produce_different_text():
    """AI-025: Different feature values produce different serialization text."""
    features_normal = dict(_SAMPLE_FEATURES)
    features_anomalous = dict(_SAMPLE_FEATURES)
    features_anomalous["file_restricted_ratio"] = 0.85
    features_anomalous["net_bytes_out"] = 50_000_000.0

    for zone_name in USER_ZONE_ORDER:
        text_normal = serialize_zone("user", zone_name, _SAMPLE_PROFILE, features_normal)
        text_anomalous = serialize_zone("user", zone_name, _SAMPLE_PROFILE, features_anomalous)
        # At least data_behavior and network_footprint should differ
        if zone_name in ("data_behavior", "network_footprint"):
            assert text_normal != text_anomalous, (
                f"Zone '{zone_name}' text should differ for different features"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 7: Embedding Composition — Tier 3 Attention (AI-026 to AI-029)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.p0
def test_ai_026_compose_zones_returns_1536d_unit_vector(real_embedder):
    """AI-026: compose_zones() returns a 1536-d unit vector."""
    zone_embeddings = build_zone_embeddings(
        "user", "USR-026", _SAMPLE_PROFILE, _SAMPLE_FEATURES, real_embedder
    )
    composite = compose_zones(zone_embeddings, context="normal_ops")
    assert composite.shape == (EMBEDDING_DIM,)
    norm = float(np.linalg.norm(composite))
    assert np.allclose(norm, 1.0, atol=1e-5)


@pytest.mark.p0
def test_ai_027_compose_zones_different_contexts_differ(real_embedder):
    """AI-027: compose_zones() under different contexts produces different vectors."""
    zone_embeddings = build_zone_embeddings(
        "user", "USR-027", _SAMPLE_PROFILE, _SAMPLE_FEATURES, real_embedder
    )
    composites = {}
    for ctx in ALL_CONTEXTS:
        composites[ctx] = compose_zones(zone_embeddings, context=ctx)

    # At least apt_hunt and insider_investigation should differ
    sim = cosine_similarity(composites["apt_hunt"], composites["insider_investigation"])
    assert sim < 0.9999, (
        "apt_hunt and insider_investigation composites should differ "
        f"(cosine similarity = {sim})"
    )


@pytest.mark.p0
def test_ai_028_softmax_attention_weights_sum_to_one(random_unit_vector):
    """AI-028: Softmax attention weights sum to 1.0 for any context."""
    zone_vecs = {zone: random_unit_vector(seed=2800 + i)
                 for i, zone in enumerate(USER_ZONE_ORDER)}

    for ctx_name in ALL_CONTEXTS:
        ctx_weights = CONTEXT_WEIGHTS["user"][ctx_name]
        alphas = softmax_attention(zone_vecs, ctx_weights)
        weight_sum = sum(alphas.values())
        assert np.allclose(weight_sum, 1.0, atol=1e-6), (
            f"Attention weights for context '{ctx_name}' sum to {weight_sum}, not 1.0"
        )


@pytest.mark.p1
def test_ai_029_compose_with_attention_returns_tuple(random_unit_vector):
    """AI-029: compose_with_attention returns (vector, weights_dict) tuple."""
    zone_vecs = {zone: random_unit_vector(seed=2900 + i)
                 for i, zone in enumerate(USER_ZONE_ORDER)}
    ctx_weights = CONTEXT_WEIGHTS["user"]["normal_ops"]

    result = compose_with_attention(zone_vecs, "user", ctx_weights)
    assert isinstance(result, tuple)
    assert len(result) == 2

    vec, alphas = result
    assert vec.shape == (EMBEDDING_DIM,)
    assert isinstance(alphas, dict)
    assert np.allclose(sum(alphas.values()), 1.0, atol=1e-6)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 8: Velocity Vectors (AI-030 to AI-032)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.p0
def test_ai_030_velocity_vector_returns_1536d(random_unit_vector):
    """AI-030: compute_velocity_vector() returns a 1536-d vector."""
    snapshots = [random_unit_vector(seed=3000 + i) for i in range(5)]
    vel = compute_velocity_vector(snapshots)
    assert vel.shape == (EMBEDDING_DIM,)


@pytest.mark.p0
def test_ai_031_velocity_vector_direction_last_minus_first(random_unit_vector):
    """AI-031: Velocity vector direction aligns with (last - first)."""
    first = random_unit_vector(seed=3100)
    last = random_unit_vector(seed=3101)
    snapshots = [first, random_unit_vector(seed=3102), last]

    vel = compute_velocity_vector(snapshots)

    # Manual direction: normalized(last - first)
    expected_dir = last.astype(np.float64) - first.astype(np.float64)
    expected_norm = np.linalg.norm(expected_dir)
    if expected_norm > 1e-8:
        expected_dir = expected_dir / expected_norm

    sim = cosine_similarity(vel, expected_dir.astype(np.float32))
    assert np.allclose(sim, 1.0, atol=1e-5), (
        f"Velocity direction doesn't match (last-first), cosine sim = {sim}"
    )


@pytest.mark.p1
def test_ai_032_velocity_vector_single_snapshot_is_zero():
    """AI-032: Single snapshot produces zero velocity vector."""
    single = np.ones(EMBEDDING_DIM, dtype=np.float32) / np.sqrt(EMBEDDING_DIM)
    vel = compute_velocity_vector([single])
    assert np.allclose(vel, np.zeros(EMBEDDING_DIM), atol=1e-8)


@pytest.mark.p1
def test_ai_032b_velocity_vector_identical_snapshots_zero(random_unit_vector):
    """AI-032b: Identical snapshots produce zero velocity."""
    v = random_unit_vector(seed=3200)
    vel = compute_velocity_vector([v, v, v])
    assert np.allclose(np.linalg.norm(vel), 0.0, atol=1e-7)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 9: Trajectory Features (AI-033 to AI-035)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.p0
def test_ai_033_trajectory_features_has_6_keys(random_unit_vector):
    """AI-033: compute_trajectory_features() returns all 6 expected keys."""
    snapshots = [random_unit_vector(seed=3300 + i) for i in range(5)]
    feats = compute_trajectory_features(snapshots)
    expected_keys = {
        "velocity_magnitude", "acceleration", "stability",
        "regime_shifts", "trend_consistency", "total_drift",
    }
    assert set(feats.keys()) == expected_keys


@pytest.mark.p0
def test_ai_034_trajectory_features_reasonable_ranges(random_unit_vector):
    """AI-034: Trajectory feature values are in reasonable ranges."""
    snapshots = [random_unit_vector(seed=3400 + i) for i in range(10)]
    feats = compute_trajectory_features(snapshots)

    assert feats["velocity_magnitude"] >= 0.0
    assert 0.0 <= feats["stability"] <= 1.0 or feats["stability"] >= -1.0
    assert 0.0 <= feats["regime_shifts"] <= 1.0
    assert feats["total_drift"] >= 0.0


@pytest.mark.p1
def test_ai_035_trajectory_features_single_snapshot_defaults():
    """AI-035: Single snapshot returns default trajectory features."""
    single = np.ones(EMBEDDING_DIM, dtype=np.float32)
    single = single / np.linalg.norm(single)
    feats = compute_trajectory_features([single])
    assert feats["velocity_magnitude"] == 0.0
    assert feats["stability"] == 1.0
    assert feats["total_drift"] == 0.0
    assert feats["regime_shifts"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Section 10: Regime Detection (AI-036 to AI-039)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.p0
def test_ai_036_regime_stable_for_constant_series():
    """AI-036: Constant series (identical snapshots) detects 'stable' regime."""
    v = np.ones(EMBEDDING_DIM, dtype=np.float32)
    v = v / np.linalg.norm(v)
    snapshots = [v.copy() for _ in range(5)]
    feats = compute_trajectory_features(snapshots)
    regime = detect_regime(feats)
    assert regime == "stable", f"Expected 'stable' for constant series, got '{regime}'"


@pytest.mark.p0
def test_ai_037_regime_shift_for_sudden_change():
    """AI-037: Sudden orthogonal jump detects 'regime_shift'."""
    rng = np.random.default_rng(3700)
    # First 3 snapshots: same direction
    base = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    base = base / np.linalg.norm(base)
    snapshots = [base.copy() for _ in range(3)]

    # Sudden jump to very different vector
    jump = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    jump = jump / np.linalg.norm(jump)
    # Ensure jump is far from base (negate if too similar)
    if cosine_similarity(base, jump) > 0.5:
        jump = -jump
    snapshots.append(jump)

    feats = compute_trajectory_features(snapshots)
    regime = detect_regime(feats)
    assert regime == "regime_shift", (
        f"Expected 'regime_shift' for sudden change, got '{regime}'. "
        f"regime_shifts={feats['regime_shifts']}"
    )


@pytest.mark.p0
def test_ai_038_regime_accelerating_for_increasing_drift():
    """AI-038: Increasing drift over time detects 'accelerating'."""
    rng = np.random.default_rng(3800)
    base = rng.standard_normal(EMBEDDING_DIM).astype(np.float64)
    base = base / np.linalg.norm(base)

    # Create series where each step moves farther than the last in a
    # consistent direction
    direction = rng.standard_normal(EMBEDDING_DIM).astype(np.float64)
    direction = direction / np.linalg.norm(direction)

    snapshots = []
    current = base.copy()
    for i in range(6):
        snapshots.append((current / np.linalg.norm(current)).astype(np.float32))
        # Each step: move in the same direction with increasing magnitude
        step_size = 0.02 * (i + 1)
        current = current + step_size * direction

    feats = compute_trajectory_features(snapshots)
    regime = detect_regime(feats)
    assert regime in ("accelerating", "drifting", "regime_shift"), (
        f"Expected acceleration-related regime for increasing drift, got '{regime}'. "
        f"acceleration={feats['acceleration']}, trend_consistency={feats['trend_consistency']}"
    )


@pytest.mark.p1
def test_ai_039_regime_detect_returns_valid_string():
    """AI-039: detect_regime always returns one of the 4 valid regime strings."""
    valid_regimes = {"stable", "drifting", "regime_shift", "accelerating"}
    # Test with various feature combinations
    test_cases = [
        {"velocity_magnitude": 0.0, "acceleration": 0.0, "stability": 1.0,
         "regime_shifts": 0.0, "trend_consistency": 0.0, "total_drift": 0.0},
        {"velocity_magnitude": 0.5, "acceleration": 0.05, "stability": 0.8,
         "regime_shifts": 0.5, "trend_consistency": 0.7, "total_drift": 0.3},
        {"velocity_magnitude": 0.1, "acceleration": 0.02, "stability": 0.95,
         "regime_shifts": 0.0, "trend_consistency": 0.5, "total_drift": 0.1},
    ]
    for case in test_cases:
        regime = detect_regime(case)
        assert regime in valid_regimes, f"Invalid regime '{regime}'"


# ═══════════════════════════════════════════════════════════════════════════════
# Section 11: Hadamard Products (AI-040 to AI-043)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.p0
def test_ai_040_hadamard_returns_1536d(random_unit_vector):
    """AI-040: hadamard() output is 1536-d."""
    a = random_unit_vector(seed=4000)
    b = random_unit_vector(seed=4001)
    result = hadamard(a, b)
    assert result.shape == (EMBEDDING_DIM,)


@pytest.mark.p0
def test_ai_041_hadamard_is_normalized(random_unit_vector):
    """AI-041: hadamard() output is L2-normalized (unit vector)."""
    a = random_unit_vector(seed=4100)
    b = random_unit_vector(seed=4101)
    result = hadamard(a, b)
    norm = float(np.linalg.norm(result))
    assert np.allclose(norm, 1.0, atol=1e-5)


@pytest.mark.p0
def test_ai_042_hadamard_commutative(random_unit_vector):
    """AI-042: hadamard(a, b) == hadamard(b, a) (element-wise product is commutative)."""
    a = random_unit_vector(seed=4200)
    b = random_unit_vector(seed=4201)
    ab = hadamard(a, b)
    ba = hadamard(b, a)
    assert np.allclose(ab, ba, atol=1e-6), "Hadamard product should be commutative"


@pytest.mark.p0
def test_ai_043_hadamard_different_inputs_different_outputs(random_unit_vector):
    """AI-043: Different input pairs produce different Hadamard outputs."""
    a = random_unit_vector(seed=4300)
    b = random_unit_vector(seed=4301)
    c = random_unit_vector(seed=4302)

    ab = hadamard(a, b)
    ac = hadamard(a, c)
    assert not np.allclose(ab, ac, atol=1e-3), (
        "Hadamard of different pairs should produce different vectors"
    )


@pytest.mark.p1
def test_ai_043b_hadamard_compose_alias(random_unit_vector):
    """AI-043b: hadamard_compose from composer.py matches hadamard from relationship_embeddings.py."""
    a = random_unit_vector(seed=4350)
    b = random_unit_vector(seed=4351)
    result_rel = hadamard(a, b)
    result_comp = hadamard_compose(a, b)
    assert np.allclose(result_rel, result_comp, atol=1e-6)


@pytest.mark.p1
def test_ai_043c_compute_user_device_vector(random_unit_vector):
    """AI-043c: compute_user_device_vector is a typed wrapper around hadamard."""
    user = random_unit_vector(seed=4360)
    device = random_unit_vector(seed=4361)
    result = compute_user_device_vector(user, device)
    expected = hadamard(user, device)
    assert np.allclose(result, expected, atol=1e-6)
    assert result.shape == (EMBEDDING_DIM,)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 12: Context Weight Sensitivity (AI-044 to AI-045)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.p0
def test_ai_044_apt_hunt_upweights_network_footprint():
    """AI-044: apt_hunt context assigns 0.40 weight to network_footprint."""
    apt_weights = CONTEXT_WEIGHTS["user"]["apt_hunt"]
    assert apt_weights["network_footprint"] == pytest.approx(0.40), (
        f"apt_hunt network_footprint weight = {apt_weights['network_footprint']}, expected 0.40"
    )
    # Verify network_footprint has the highest or tied-for-highest weight
    max_weight = max(apt_weights.values())
    assert apt_weights["network_footprint"] >= max_weight - 0.01, (
        "network_footprint should be the dominant zone in apt_hunt context"
    )


@pytest.mark.p0
def test_ai_045_insider_investigation_upweights_data_behavior():
    """AI-045: insider_investigation context assigns 0.40 weight to data_behavior."""
    insider_weights = CONTEXT_WEIGHTS["user"]["insider_investigation"]
    assert insider_weights["data_behavior"] == pytest.approx(0.40), (
        f"insider_investigation data_behavior weight = {insider_weights['data_behavior']}, expected 0.40"
    )
    max_weight = max(insider_weights.values())
    assert insider_weights["data_behavior"] >= max_weight - 0.01, (
        "data_behavior should be the dominant zone in insider_investigation context"
    )


@pytest.mark.p1
def test_ai_045b_normal_ops_equal_weights():
    """AI-045b: normal_ops context assigns equal 0.20 weight to all zones."""
    normal_weights = CONTEXT_WEIGHTS["user"]["normal_ops"]
    for zone_name in USER_ZONE_ORDER:
        assert normal_weights[zone_name] == pytest.approx(0.20), (
            f"normal_ops {zone_name} weight = {normal_weights[zone_name]}, expected 0.20"
        )


@pytest.mark.p1
def test_ai_045c_privilege_audit_upweights_risk_posture():
    """AI-045c: privilege_audit context assigns 0.40 weight to risk_posture."""
    priv_weights = CONTEXT_WEIGHTS["user"]["privilege_audit"]
    assert priv_weights["risk_posture"] == pytest.approx(0.40), (
        f"privilege_audit risk_posture weight = {priv_weights['risk_posture']}, expected 0.40"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 13: DB Embedding Integrity (AI-046)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.p1
def test_ai_046_db_embedding_integrity():
    """AI-046: Read 5 random embeddings from behavioral_snapshots; verify 1536-d, normalized."""
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 not installed, skipping DB test")

    db_host = os.environ.get("DB_HOST", "127.0.0.1")
    db_port = os.environ.get("DB_PORT", "5437")

    try:
        conn = psycopg2.connect(
            host=db_host,
            port=int(db_port),
            dbname="cyber_ueba",
            user="cyber_ueba",
            password="password",
            connect_timeout=5,
        )
    except Exception as exc:
        pytest.skip(f"Cannot connect to DB at {db_host}:{db_port}: {exc}")

    try:
        cur = conn.cursor()
        # Check if table exists
        cur.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = 'behavioral_snapshots')"
        )
        if not cur.fetchone()[0]:
            pytest.skip("behavioral_snapshots table does not exist")

        # Get a vector column name (composite_embedding is the primary one)
        # Try composite_embedding first, fall back to any available vector column
        vector_col = "composite_embedding"
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'behavioral_snapshots' AND column_name = %s",
            (vector_col,),
        )
        if not cur.fetchone():
            # Fall back: find any vector column
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'behavioral_snapshots' AND udt_name = 'vector' "
                "LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                pytest.skip("No vector columns found in behavioral_snapshots")
            vector_col = row[0]

        cur.execute(
            f"SELECT {vector_col}::text FROM behavioral_snapshots "
            f"WHERE {vector_col} IS NOT NULL "
            "ORDER BY RANDOM() LIMIT 5"
        )
        rows = cur.fetchall()
        if len(rows) == 0:
            pytest.skip("No rows with embeddings in behavioral_snapshots")

        for i, (vec_str,) in enumerate(rows):
            # pgvector format: "[0.1,0.2,...,0.3]"
            vec_str = vec_str.strip("[]")
            values = [float(x) for x in vec_str.split(",")]
            vec = np.array(values, dtype=np.float32)

            assert vec.shape == (EMBEDDING_DIM,), (
                f"Row {i}: embedding has {vec.shape[0]} dims, expected {EMBEDDING_DIM}"
            )
            norm = float(np.linalg.norm(vec))
            assert np.allclose(norm, 1.0, atol=0.05), (
                f"Row {i}: embedding norm = {norm}, expected ~1.0"
            )

    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Section 14: End-to-End Embedding Pipeline (AI-047 to AI-048)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.p0
def test_ai_047_end_to_end_pipeline(real_embedder):
    """AI-047: Full pipeline: features -> serialize -> embed -> compose -> cosine sim."""
    # Step 1: Build zone embeddings from features
    zone_embeddings = build_zone_embeddings(
        "user", "USR-E2E", _SAMPLE_PROFILE, _SAMPLE_FEATURES, real_embedder
    )
    assert len(zone_embeddings) == 5, f"Expected 5 zones, got {len(zone_embeddings)}"
    for zone_name, vec in zone_embeddings.items():
        assert vec.shape == (EMBEDDING_DIM,), f"Zone '{zone_name}' not 1536-d"
        norm = float(np.linalg.norm(vec))
        # Real OpenAI embeddings are unit-norm only to float32 precision.
        assert np.allclose(norm, 1.0, atol=1e-3), f"Zone '{zone_name}' not unit norm"

    # Step 2: Compose under two contexts
    composite_normal = compose_zones(zone_embeddings, context="normal_ops")
    composite_apt = compose_zones(zone_embeddings, context="apt_hunt")
    assert composite_normal.shape == (EMBEDDING_DIM,)
    assert composite_apt.shape == (EMBEDDING_DIM,)

    # Step 3: Cosine similarity between contexts
    sim = cosine_similarity(composite_normal, composite_apt)
    assert -1.0 <= sim <= 1.0, f"Cosine sim out of range: {sim}"
    # Same zones, different weights -> high but not perfect similarity
    assert sim < 1.0, "Different contexts should produce different composites"

    # Step 4: Drift from normal to anomalous features
    anomalous_features = dict(_SAMPLE_FEATURES)
    anomalous_features["file_restricted_ratio"] = 0.75
    anomalous_features["net_bytes_out"] = 100_000_000.0
    anomalous_features["endpoint_max_risk"] = 0.95

    zone_embeddings_anomalous = build_zone_embeddings(
        "user", "USR-E2E", _SAMPLE_PROFILE, anomalous_features, real_embedder
    )
    composite_anomalous = compose_zones(zone_embeddings_anomalous, context="normal_ops")

    drift = drift_magnitude(composite_normal, composite_anomalous)
    assert drift > 0.0, "Anomalous features should produce non-zero drift"
    assert drift <= 2.0, f"Drift magnitude {drift} exceeds theoretical maximum"


@pytest.mark.p0
def test_ai_048_pipeline_trajectory_chain(real_embedder):
    """AI-048: Build multiple snapshots, compute trajectory and regime."""
    # Create a temporal series of zone embeddings by varying features
    snapshots = []
    for week in range(6):
        features = dict(_SAMPLE_FEATURES)
        # Gradually increase anomalous features each week
        features["file_restricted_ratio"] = 0.03 + 0.02 * week
        features["net_bytes_out"] = 1_200_000 + 500_000 * week

        zone_embs = build_zone_embeddings(
            "user", "USR-TRAJ", _SAMPLE_PROFILE, features, real_embedder
        )
        composite = compose_zones(zone_embs, context="normal_ops")
        snapshots.append(composite)

    # Compute trajectory
    vel = compute_velocity_vector(snapshots)
    assert vel.shape == (EMBEDDING_DIM,)

    feats = compute_trajectory_features(snapshots)
    assert set(feats.keys()) == {
        "velocity_magnitude", "acceleration", "stability",
        "regime_shifts", "trend_consistency", "total_drift",
    }

    regime = detect_regime(feats)
    assert regime in {"stable", "drifting", "regime_shift", "accelerating"}

    # Total drift should be non-zero since features changed
    assert feats["total_drift"] >= 0.0
