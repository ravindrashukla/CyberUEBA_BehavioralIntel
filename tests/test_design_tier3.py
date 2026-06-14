"""Design-spec verification for ACECARD Tier 3 Digital Entity detection.

Verifies every commitment in the Tier 3 design specification:
 - 5 hierarchical zone embeddings with correct features
 - Context-adaptive softmax attention (4 contexts)
 - Velocity vectors + 6 trajectory features + regime detection
 - Hadamard product relationship embeddings
 - DB zone/context divergence for attack users USR-156 and USR-234
 - CyberEntity / PhaseState / Tier3Config dataclass contracts
"""

import os
import sys
import json
import math
from dataclasses import fields as dataclass_fields

import numpy as np
import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5437")
os.environ.setdefault("DB_NAME", "cyber_ueba")
os.environ.setdefault("DB_USER", "cyber_ueba")
os.environ.setdefault("DB_PASSWORD", "password")

from embeddings.composer import cosine_similarity, compose_with_attention, hadamard_compose
from models.hierarchical_zones import (
    CYBER_ZONES, CONTEXT_WEIGHTS, ALL_CONTEXTS, USER_ZONE_ORDER,
    serialize_zone, build_zone_embeddings, compose_zones,
)
from models.temporal_trajectory import (
    compute_velocity_vector, compute_trajectory_features, detect_regime,
)
from models.relationship_embeddings import hadamard
from models.cyber_entity import CyberEntity, PhaseState, Tier3Config, EMBED_DIM

ATTACK_USERS = ["USR-156", "USR-234", "USR-042", "USR-118"]


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def real_embedder():
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("requires OPENAI_API_KEY — real OpenAI embeddings (mock removed)")
    from embeddings.embedder import Embedder
    return Embedder(preload=False)


@pytest.fixture(scope="module")
def sample_profile():
    return {
        "user_id": "USR-TEST",
        "role": "analyst",
        "department": "finance",
        "clearance": "secret",
        "tenure_days": 365,
        "user_type": "employee",
    }


@pytest.fixture(scope="module")
def sample_features():
    return {
        "auth_total": 150,
        "auth_fail_rate": 0.05,
        "auth_off_hours_ratio": 0.12,
        "auth_unique_sources": 3,
        "auth_unique_dests": 10,
        "auth_methods_used": 2,
        "file_total": 200,
        "file_restricted_ratio": 0.02,
        "file_confidential_ratio": 0.01,
        "file_write_ratio": 0.30,
        "file_unique_paths": 45,
        "file_total_bytes": 500000,
        "net_bytes_out": 1200000,
        "net_unique_dsts": 15,
        "net_external_ratio": 0.25,
        "dns_unique_domains": 80,
        "dns_nxdomain_ratio": 0.005,
        "endpoint_suspicious_ratio": 0.001,
        "endpoint_max_risk": 0.4,
        "endpoint_mean_risk": 0.15,
        "endpoint_unique_processes": 120,
        "endpoint_total": 500,
    }


@pytest.fixture(scope="module")
def zone_embeddings(real_embedder, sample_profile, sample_features):
    return build_zone_embeddings("user", "USR-TEST", sample_profile, sample_features, real_embedder)


def _random_unit_vector(dim=EMBED_DIM, seed=None):
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture(scope="module")
def db_conn():
    from pipeline.db_connect import get_connection
    conn = get_connection()
    conn.autocommit = True
    yield conn
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1: ZONE_FEATURES dict — 5 zones with correct feature lists
# ═══════════════════════════════════════════════════════════════════════════════

class TestZoneFeatures:
    """Verify CYBER_ZONES defines exactly 5 user zones with the specified features."""

    EXPECTED_ZONES = {
        "identity": ["role", "department", "clearance", "tenure_days", "user_type"],
        "access_pattern": [
            "auth_total", "auth_fail_rate", "auth_off_hours_ratio",
            "auth_unique_sources", "auth_unique_dests", "auth_methods_used",
        ],
        "data_behavior": [
            "file_total", "file_restricted_ratio", "file_confidential_ratio",
            "file_write_ratio", "file_unique_paths", "file_total_bytes",
        ],
        "network_footprint": [
            "net_bytes_out", "net_unique_dsts", "net_external_ratio",
            "dns_unique_domains", "dns_nxdomain_ratio",
        ],
        "risk_posture": [
            "endpoint_suspicious_ratio", "endpoint_max_risk",
            "endpoint_mean_risk", "endpoint_unique_processes", "endpoint_total",
        ],
    }

    def test_five_user_zones_exist(self):
        user_zones = CYBER_ZONES["user"]
        assert len(user_zones) == 5, f"Expected 5 zones, got {len(user_zones)}: {list(user_zones)}"

    def test_zone_names_match_spec(self):
        user_zones = CYBER_ZONES["user"]
        assert set(user_zones.keys()) == set(self.EXPECTED_ZONES.keys())

    @pytest.mark.parametrize("zone_name", [
        "identity", "access_pattern", "data_behavior", "network_footprint", "risk_posture",
    ])
    def test_zone_feature_list(self, zone_name):
        actual = CYBER_ZONES["user"][zone_name]["fields"]
        expected = self.EXPECTED_ZONES[zone_name]
        assert actual == expected, (
            f"Zone '{zone_name}' features mismatch.\n"
            f"  Expected: {expected}\n"
            f"  Actual:   {actual}"
        )

    def test_user_zone_order(self):
        assert USER_ZONE_ORDER == list(self.EXPECTED_ZONES.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2: CONTEXT_WEIGHTS — exact weight values for all 4 contexts
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextWeights:
    """Verify context-adaptive attention weights match the specification."""

    EXPECTED = {
        "normal_ops": {
            "identity": 0.20, "access_pattern": 0.20, "data_behavior": 0.20,
            "network_footprint": 0.20, "risk_posture": 0.20,
        },
        "insider_investigation": {
            "identity": 0.10, "access_pattern": 0.15, "data_behavior": 0.40,
            "network_footprint": 0.15, "risk_posture": 0.20,
        },
        "apt_hunt": {
            "identity": 0.05, "access_pattern": 0.15, "data_behavior": 0.10,
            "network_footprint": 0.40, "risk_posture": 0.30,
        },
        "privilege_audit": {
            "identity": 0.10, "access_pattern": 0.25, "data_behavior": 0.10,
            "network_footprint": 0.15, "risk_posture": 0.40,
        },
    }

    def test_four_contexts_exist(self):
        user_ctx = CONTEXT_WEIGHTS["user"]
        assert set(user_ctx.keys()) == set(self.EXPECTED.keys())

    @pytest.mark.parametrize("context", [
        "normal_ops", "insider_investigation", "apt_hunt", "privilege_audit",
    ])
    def test_context_weight_values(self, context):
        actual = CONTEXT_WEIGHTS["user"][context]
        expected = self.EXPECTED[context]
        for zone, exp_w in expected.items():
            assert abs(actual[zone] - exp_w) < 1e-6, (
                f"Context '{context}', zone '{zone}': expected {exp_w}, got {actual[zone]}"
            )

    @pytest.mark.parametrize("context", [
        "normal_ops", "insider_investigation", "apt_hunt", "privilege_audit",
    ])
    def test_context_weights_sum_to_one(self, context):
        """Test 19: attention weights for each context sum to 1.0."""
        weights = CONTEXT_WEIGHTS["user"][context]
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-6, (
            f"Context '{context}' weights sum to {total}, expected 1.0"
        )

    def test_all_contexts_constant(self):
        assert set(ALL_CONTEXTS) == set(self.EXPECTED.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3: serialize_zone() — non-empty string output with feature values
# ═══════════════════════════════════════════════════════════════════════════════

class TestSerializeZone:
    """Verify serialize_zone produces meaningful text for each zone."""

    ZONES = ["identity", "access_pattern", "data_behavior", "network_footprint", "risk_posture"]

    @pytest.mark.parametrize("zone_name", ZONES)
    def test_serialize_returns_nonempty_string(self, zone_name, sample_profile, sample_features):
        text = serialize_zone("user", zone_name, sample_profile, sample_features)
        assert isinstance(text, str)
        assert len(text) > 10, f"Zone '{zone_name}' text too short: {text!r}"

    def test_identity_contains_profile_values(self, sample_profile, sample_features):
        text = serialize_zone("user", "identity", sample_profile, sample_features)
        assert "analyst" in text
        assert "finance" in text
        assert "secret" in text

    def test_access_pattern_contains_feature_values(self, sample_profile, sample_features):
        text = serialize_zone("user", "access_pattern", sample_profile, sample_features)
        assert "150" in text  # auth_total
        assert "0.05" in text or "0.0500" in text  # auth_fail_rate

    def test_data_behavior_contains_feature_values(self, sample_profile, sample_features):
        text = serialize_zone("user", "data_behavior", sample_profile, sample_features)
        assert "200" in text  # file_total
        assert "500000" in text  # file_total_bytes

    def test_network_contains_feature_values(self, sample_profile, sample_features):
        text = serialize_zone("user", "network_footprint", sample_profile, sample_features)
        assert "1200000" in text  # net_bytes_out

    def test_risk_contains_feature_values(self, sample_profile, sample_features):
        text = serialize_zone("user", "risk_posture", sample_profile, sample_features)
        assert "500" in text  # endpoint_total


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4: build_zone_embeddings() — 5 zone keys, each 1536-d
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildZoneEmbeddings:
    """Verify zone embedding construction with MockEmbedder."""

    def test_returns_five_zones(self, zone_embeddings):
        assert len(zone_embeddings) == 5
        assert set(zone_embeddings.keys()) == {
            "identity", "access_pattern", "data_behavior",
            "network_footprint", "risk_posture",
        }

    @pytest.mark.parametrize("zone_name", [
        "identity", "access_pattern", "data_behavior", "network_footprint", "risk_posture",
    ])
    def test_each_zone_is_1536d(self, zone_name, zone_embeddings):
        vec = zone_embeddings[zone_name]
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (EMBED_DIM,), f"Zone '{zone_name}' shape {vec.shape}, expected ({EMBED_DIM},)"

    @pytest.mark.parametrize("zone_name", [
        "identity", "access_pattern", "data_behavior", "network_footprint", "risk_posture",
    ])
    def test_each_zone_is_unit_normalized(self, zone_name, zone_embeddings):
        vec = zone_embeddings[zone_name]
        norm = float(np.linalg.norm(vec))
        assert abs(norm - 1.0) < 0.01, f"Zone '{zone_name}' norm {norm}, expected ~1.0"

    def test_zones_are_distinct(self, zone_embeddings):
        """Different zones should produce different embeddings."""
        names = list(zone_embeddings.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                sim = cosine_similarity(zone_embeddings[names[i]], zone_embeddings[names[j]])
                assert sim < 0.99, (
                    f"Zones '{names[i]}' and '{names[j]}' too similar: {sim:.4f}"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5: compose_zones() — 1536-d under all 4 contexts, contexts differ
# ═══════════════════════════════════════════════════════════════════════════════

class TestComposeZones:
    """Verify attention-weighted zone composition across contexts."""

    @pytest.mark.parametrize("context", ALL_CONTEXTS)
    def test_compose_returns_1536d(self, context, zone_embeddings):
        composite = compose_zones(zone_embeddings, context=context)
        assert composite.shape == (EMBED_DIM,)

    @pytest.mark.parametrize("context", ALL_CONTEXTS)
    def test_compose_is_normalized(self, context, zone_embeddings):
        composite = compose_zones(zone_embeddings, context=context)
        norm = float(np.linalg.norm(composite))
        assert abs(norm - 1.0) < 0.01, f"Context '{context}' composite norm {norm}"

    def test_different_contexts_different_vectors(self, zone_embeddings):
        composites = {}
        for ctx in ALL_CONTEXTS:
            composites[ctx] = compose_zones(zone_embeddings, context=ctx)

        # At least some context pairs must differ
        pairs_differ = 0
        for i, c1 in enumerate(ALL_CONTEXTS):
            for c2 in ALL_CONTEXTS[i + 1:]:
                sim = cosine_similarity(composites[c1], composites[c2])
                if sim < 0.999:
                    pairs_differ += 1

        assert pairs_differ > 0, "All contexts produced identical composites"

    def test_insider_vs_normal_differ(self, zone_embeddings):
        normal = compose_zones(zone_embeddings, context="normal_ops")
        insider = compose_zones(zone_embeddings, context="insider_investigation")
        sim = cosine_similarity(normal, insider)
        assert sim < 0.9999, f"insider_investigation and normal_ops too similar: {sim}"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 6: compute_velocity_vector() — 1536-d normalized
# ═══════════════════════════════════════════════════════════════════════════════

class TestVelocityVector:
    """Verify velocity vector computation from embedding series."""

    def test_returns_1536d(self):
        snapshots = [_random_unit_vector(seed=i) for i in range(5)]
        vel = compute_velocity_vector(snapshots)
        assert vel.shape == (EMBED_DIM,)

    def test_is_normalized(self):
        snapshots = [_random_unit_vector(seed=i) for i in range(5)]
        vel = compute_velocity_vector(snapshots)
        norm = float(np.linalg.norm(vel))
        assert abs(norm - 1.0) < 0.01 or norm < 1e-6, f"Velocity norm {norm}"

    def test_single_snapshot_returns_zero(self):
        snapshots = [_random_unit_vector(seed=0)]
        vel = compute_velocity_vector(snapshots)
        assert np.allclose(vel, 0.0)

    def test_identical_snapshots_return_zero(self):
        v = _random_unit_vector(seed=42)
        snapshots = [v.copy(), v.copy(), v.copy()]
        vel = compute_velocity_vector(snapshots)
        assert np.allclose(vel, 0.0, atol=1e-6)

    def test_direction_is_last_minus_first(self):
        v1 = _random_unit_vector(seed=10)
        v2 = _random_unit_vector(seed=20)
        vel = compute_velocity_vector([v1, v2])
        raw_diff = (v2 - v1).astype(np.float64)
        raw_diff /= np.linalg.norm(raw_diff)
        dot = float(np.dot(vel.astype(np.float64), raw_diff))
        assert dot > 0.99, f"Velocity direction mismatch: dot={dot}"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 7: compute_trajectory_features() — 6 keys, correct ranges
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrajectoryFeatures:
    """Verify all 6 trajectory features with correct semantics."""

    EXPECTED_KEYS = [
        "velocity_magnitude", "acceleration", "stability",
        "regime_shifts", "trend_consistency", "total_drift",
    ]

    def test_returns_all_six_keys(self):
        snapshots = [_random_unit_vector(seed=i) for i in range(10)]
        feats = compute_trajectory_features(snapshots)
        for key in self.EXPECTED_KEYS:
            assert key in feats, f"Missing trajectory feature: {key}"

    def test_velocity_magnitude_non_negative(self):
        snapshots = [_random_unit_vector(seed=i) for i in range(10)]
        feats = compute_trajectory_features(snapshots)
        assert feats["velocity_magnitude"] >= 0

    def test_stability_in_unit_range(self):
        # Use closely-related vectors for high stability
        base = _random_unit_vector(seed=0)
        snapshots = [base + 0.01 * _random_unit_vector(seed=i) for i in range(10)]
        for i in range(len(snapshots)):
            snapshots[i] = snapshots[i] / np.linalg.norm(snapshots[i])
        feats = compute_trajectory_features(snapshots)
        assert 0.0 <= feats["stability"] <= 1.0, f"Stability={feats['stability']}"

    def test_regime_shifts_fraction(self):
        snapshots = [_random_unit_vector(seed=i) for i in range(10)]
        feats = compute_trajectory_features(snapshots)
        assert 0.0 <= feats["regime_shifts"] <= 1.0

    def test_total_drift_non_negative(self):
        snapshots = [_random_unit_vector(seed=i) for i in range(10)]
        feats = compute_trajectory_features(snapshots)
        assert feats["total_drift"] >= 0.0

    def test_identical_snapshots_zero_drift(self):
        v = _random_unit_vector(seed=42)
        snapshots = [v.copy() for _ in range(5)]
        feats = compute_trajectory_features(snapshots)
        assert abs(feats["total_drift"]) < 1e-6
        assert abs(feats["velocity_magnitude"]) < 1e-6
        assert feats["stability"] > 0.999

    def test_single_snapshot_defaults(self):
        feats = compute_trajectory_features([_random_unit_vector(seed=0)])
        assert feats["velocity_magnitude"] == 0.0
        assert feats["stability"] == 1.0
        assert feats["total_drift"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 8: detect_regime() — 4 regime types
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectRegime:
    """Test regime classification logic for all 4 possible outcomes."""

    def test_stable_regime(self):
        feats = {
            "velocity_magnitude": 0.001,
            "acceleration": 0.001,
            "stability": 0.99,
            "regime_shifts": 0.0,
            "trend_consistency": 0.0,
            "total_drift": 0.001,
        }
        assert detect_regime(feats) == "stable"

    def test_drifting_regime(self):
        feats = {
            "velocity_magnitude": 0.05,
            "acceleration": 0.005,
            "stability": 0.85,
            "regime_shifts": 0.0,
            "trend_consistency": 0.1,
            "total_drift": 0.10,
        }
        assert detect_regime(feats) == "drifting"

    def test_regime_shift(self):
        feats = {
            "velocity_magnitude": 0.2,
            "acceleration": 0.05,
            "stability": 0.3,
            "regime_shifts": 0.5,
            "trend_consistency": 0.1,
            "total_drift": 0.5,
        }
        assert detect_regime(feats) == "regime_shift"

    def test_accelerating_regime(self):
        feats = {
            "velocity_magnitude": 0.1,
            "acceleration": 0.05,
            "stability": 0.6,
            "regime_shifts": 0.0,
            "trend_consistency": 0.5,
            "total_drift": 0.02,
        }
        assert detect_regime(feats) == "accelerating"

    def test_all_four_regimes_reachable(self):
        """Confirm the detect_regime function can produce all 4 states."""
        regimes = set()
        test_cases = [
            {"regime_shifts": 0.5, "acceleration": 0.0, "trend_consistency": 0.0,
             "total_drift": 0.0, "stability": 1.0, "velocity_magnitude": 0.0},
            {"regime_shifts": 0.0, "acceleration": 0.05, "trend_consistency": 0.5,
             "total_drift": 0.02, "stability": 0.6, "velocity_magnitude": 0.1},
            {"regime_shifts": 0.0, "acceleration": 0.005, "trend_consistency": 0.1,
             "total_drift": 0.10, "stability": 0.85, "velocity_magnitude": 0.05},
            {"regime_shifts": 0.0, "acceleration": 0.001, "trend_consistency": 0.0,
             "total_drift": 0.001, "stability": 0.99, "velocity_magnitude": 0.001},
        ]
        for feats in test_cases:
            regimes.add(detect_regime(feats))
        assert regimes == {"stable", "drifting", "regime_shift", "accelerating"}


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 9: hadamard() — element-wise multiply + L2 normalize
# ═══════════════════════════════════════════════════════════════════════════════

class TestHadamard:
    """Verify Hadamard product relationship embeddings."""

    def test_output_shape(self):
        a = _random_unit_vector(seed=1)
        b = _random_unit_vector(seed=2)
        result = hadamard(a, b)
        assert result.shape == (EMBED_DIM,)

    def test_output_is_normalized(self):
        a = _random_unit_vector(seed=1)
        b = _random_unit_vector(seed=2)
        result = hadamard(a, b)
        norm = float(np.linalg.norm(result))
        assert abs(norm - 1.0) < 0.01, f"Hadamard norm {norm}"

    def test_element_wise_product_direction(self):
        """Result should be in the direction of a*b (element-wise)."""
        a = _random_unit_vector(seed=10)
        b = _random_unit_vector(seed=20)
        result = hadamard(a, b)
        raw = (a.astype(np.float64) * b.astype(np.float64))
        raw_norm = np.linalg.norm(raw)
        if raw_norm > 1e-8:
            raw_unit = raw / raw_norm
            dot = float(np.dot(result.astype(np.float64), raw_unit))
            assert dot > 0.99, f"Hadamard direction mismatch: dot={dot}"

    def test_zero_vector_returns_zero(self):
        a = np.zeros(EMBED_DIM, dtype=np.float32)
        b = _random_unit_vector(seed=1)
        result = hadamard(a, b)
        assert np.allclose(result, 0.0)

    def test_symmetry(self):
        a = _random_unit_vector(seed=3)
        b = _random_unit_vector(seed=4)
        assert np.allclose(hadamard(a, b), hadamard(b, a), atol=1e-6)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 10: CyberEntity dataclass — all fields exist with correct types
# ═══════════════════════════════════════════════════════════════════════════════

class TestCyberEntityDataclass:
    """Verify CyberEntity dataclass contract."""

    REQUIRED_FIELDS = {
        "entity_type": str,
        "entity_id": str,
        "profile": dict,
        "zone_embeddings": dict,
        "composite_embedding": (np.ndarray, type(None)),
        "phase_state": PhaseState,
        "relationships": dict,
        "risk_scores": dict,
        "computed_at": str,
        "data_gaps": list,
        "context": str,
    }

    def test_all_fields_exist(self):
        field_names = {f.name for f in dataclass_fields(CyberEntity)}
        for name in self.REQUIRED_FIELDS:
            assert name in field_names, f"CyberEntity missing field: {name}"

    def test_has_at_least_11_fields(self):
        field_names = {f.name for f in dataclass_fields(CyberEntity)}
        assert len(field_names) >= 11, f"CyberEntity has {len(field_names)} fields, expected >= 11"

    def test_default_construction(self):
        entity = CyberEntity(entity_type="user", entity_id="test-001")
        assert entity.entity_type == "user"
        assert entity.entity_id == "test-001"
        assert isinstance(entity.profile, dict)
        assert isinstance(entity.zone_embeddings, dict)
        assert entity.composite_embedding is None
        assert isinstance(entity.phase_state, PhaseState)
        assert isinstance(entity.relationships, dict)
        assert isinstance(entity.risk_scores, dict)
        assert entity.computed_at == ""
        assert isinstance(entity.data_gaps, list)
        assert entity.context == "normal_ops"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 11: PhaseState dataclass — all 8 fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestPhaseStateDataclass:
    """Verify PhaseState dataclass contract."""

    REQUIRED_FIELDS = [
        "velocity_vector", "velocity_magnitude", "acceleration",
        "stability", "regime_shifts", "trend_consistency",
        "total_drift", "current_regime",
    ]

    def test_all_eight_fields_exist(self):
        field_names = {f.name for f in dataclass_fields(PhaseState)}
        assert len(field_names) == 8, f"PhaseState has {len(field_names)} fields, expected 8"
        for name in self.REQUIRED_FIELDS:
            assert name in field_names, f"PhaseState missing field: {name}"

    def test_defaults(self):
        ps = PhaseState()
        assert ps.velocity_magnitude == 0.0
        assert ps.acceleration == 0.0
        assert ps.stability == 1.0
        assert ps.regime_shifts == 0.0
        assert ps.trend_consistency == 1.0
        assert ps.total_drift == 0.0
        assert ps.current_regime == "stable"
        assert isinstance(ps.velocity_vector, np.ndarray)
        assert ps.velocity_vector.shape == (EMBED_DIM,)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 12: Tier3Config dataclass — threshold fields with correct defaults
# ═══════════════════════════════════════════════════════════════════════════════

class TestTier3ConfigDataclass:
    """Verify Tier3Config dataclass threshold fields."""

    EXPECTED_DEFAULTS = {
        "acceleration_threshold": 0.01,
        "trend_consistency_min": 0.5,
        "regime_shift_threshold": 0.7,
        "zone_stable_threshold": 0.02,
        "zone_drifting_threshold": 0.05,
        "relationship_drift_threshold": 0.05,
        "contextual_threat_threshold": 0.30,
        "cohort_similarity": 0.5,
        "cohort_min_size": 3,
        "threat_consistency_threshold": 0.40,
    }

    def test_has_threshold_fields(self):
        field_names = {f.name for f in dataclass_fields(Tier3Config)}
        for name in self.EXPECTED_DEFAULTS:
            assert name in field_names, f"Tier3Config missing field: {name}"

    def test_field_count(self):
        field_names = {f.name for f in dataclass_fields(Tier3Config)}
        assert len(field_names) >= 9, f"Tier3Config has {len(field_names)} fields, expected >= 9"

    def test_default_values(self):
        cfg = Tier3Config()
        for name, expected_val in self.EXPECTED_DEFAULTS.items():
            actual_val = getattr(cfg, name)
            assert actual_val == expected_val, (
                f"Tier3Config.{name}: expected {expected_val}, got {actual_val}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 13: cosine_similarity() — mathematical correctness
# ═══════════════════════════════════════════════════════════════════════════════

class TestCosineSimilarity:
    """Verify cosine_similarity from embeddings.composer."""

    def test_identical_vectors_return_one(self):
        v = _random_unit_vector(seed=0)
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors_return_zero(self):
        v1 = np.zeros(EMBED_DIM, dtype=np.float32)
        v2 = np.zeros(EMBED_DIM, dtype=np.float32)
        v1[0] = 1.0
        v2[1] = 1.0
        assert abs(cosine_similarity(v1, v2)) < 1e-6

    def test_opposite_vectors_return_negative_one(self):
        v = _random_unit_vector(seed=5)
        assert abs(cosine_similarity(v, -v) + 1.0) < 1e-5

    def test_zero_vector_returns_zero(self):
        v = _random_unit_vector(seed=0)
        z = np.zeros(EMBED_DIM, dtype=np.float32)
        assert cosine_similarity(v, z) == 0.0

    def test_known_value(self):
        a = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        b = np.array([4.0, 5.0, 6.0], dtype=np.float32)
        expected = float(np.dot(a, b)) / (np.linalg.norm(a) * np.linalg.norm(b))
        assert abs(cosine_similarity(a, b) - expected) < 1e-5

    def test_symmetry(self):
        a = _random_unit_vector(seed=10)
        b = _random_unit_vector(seed=20)
        assert abs(cosine_similarity(a, b) - cosine_similarity(b, a)) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 14-18: Database integration tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDBZoneDivergence:
    """Verify attack user detection signals in DB trajectory_snapshots."""

    def test_usr156_data_behavior_drift_positive(self, db_conn):
        """Test 14: USR-156 (insider) should have data_behavior zone drift > 0."""
        cur = db_conn.cursor()
        cur.execute("""
            SELECT zone_drifts FROM trajectory_snapshots
            WHERE entity_type = 'user' AND entity_id = 'USR-156'
            ORDER BY cutoff_date DESC LIMIT 1
        """)
        row = cur.fetchone()
        assert row is not None, "No trajectory_snapshots for USR-156"
        zd = row[0]
        if isinstance(zd, str):
            zd = json.loads(zd)
        assert zd["data_behavior"] > 0, (
            f"USR-156 data_behavior drift should be > 0, got {zd['data_behavior']}"
        )

    def test_usr234_network_footprint_drift_positive(self, db_conn):
        """Test 15: USR-234 (APT) should have network_footprint zone drift > 0."""
        cur = db_conn.cursor()
        cur.execute("""
            SELECT zone_drifts FROM trajectory_snapshots
            WHERE entity_type = 'user' AND entity_id = 'USR-234'
            ORDER BY cutoff_date DESC LIMIT 1
        """)
        row = cur.fetchone()
        assert row is not None, "No trajectory_snapshots for USR-234"
        zd = row[0]
        if isinstance(zd, str):
            zd = json.loads(zd)
        assert zd["network_footprint"] > 0, (
            f"USR-234 network_footprint drift should be > 0, got {zd['network_footprint']}"
        )

    def test_usr156_insider_context_ge_normal(self, db_conn):
        """Test 16: USR-156 insider_investigation drift >= normal_ops drift."""
        cur = db_conn.cursor()
        cur.execute("""
            SELECT context_drifts FROM trajectory_snapshots
            WHERE entity_type = 'user' AND entity_id = 'USR-156'
              AND context_drifts IS NOT NULL
            ORDER BY cutoff_date DESC LIMIT 1
        """)
        row = cur.fetchone()
        assert row is not None, "No context_drifts for USR-156"
        cd = row[0]
        if isinstance(cd, str):
            cd = json.loads(cd)
        insider = cd.get("insider_investigation", 0)
        normal = cd.get("normal_ops", 0)
        assert insider >= normal, (
            f"USR-156: insider_investigation ({insider}) should be >= normal_ops ({normal})"
        )

    def test_usr234_apt_context_ge_normal(self, db_conn):
        """Test 17: USR-234 apt_hunt drift >= normal_ops drift."""
        cur = db_conn.cursor()
        cur.execute("""
            SELECT context_drifts FROM trajectory_snapshots
            WHERE entity_type = 'user' AND entity_id = 'USR-234'
              AND context_drifts IS NOT NULL
            ORDER BY cutoff_date DESC LIMIT 1
        """)
        row = cur.fetchone()
        assert row is not None, "No context_drifts for USR-234"
        cd = row[0]
        if isinstance(cd, str):
            cd = json.loads(cd)
        apt = cd.get("apt_hunt", 0)
        normal = cd.get("normal_ops", 0)
        assert apt >= normal, (
            f"USR-234: apt_hunt ({apt}) should be >= normal_ops ({normal})"
        )


class TestDBAttackUsersTrajectory:
    """Test 18: All 4 attack users have trajectory events in the DB."""

    @pytest.mark.parametrize("user_id", ATTACK_USERS)
    def test_attack_user_has_trajectory_events(self, user_id, db_conn):
        cur = db_conn.cursor()
        cur.execute("""
            SELECT count(*) FROM trajectory_events
            WHERE entity_id = %s
        """, (user_id,))
        count = cur.fetchone()[0]
        assert count > 0, f"{user_id} has 0 trajectory events, expected > 0"
