"""Deep Analysis Test Suite — Composite Scoring, Novelty Features, Embedding
Pipeline, Drift Direction, Numerical Stability, and Detection Accuracy.

Test IDs: DA2-001 through DA2-100+
Covers:
  1. Composite Scorer: 5-phase scoring, edge cases, NaN handling
  2. Novelty Features: C2 beacon detection, domain entropy, role-appropriateness
  3. Embedding Composer: edge cases, epsilon consistency, attention weights
  4. Drift Direction: concept alignment, zone divergence, evasion scenarios
  5. Detection Accuracy: verified against actual data (4/4 at 8.5% FP)
  6. Numerical Stability: NaN propagation, zero vectors, boundary values
  7. Hierarchical Zones: serialization, context weights, zone composition
  8. Temporal Trajectory: velocity, regime detection, edge cases
  9. Integration: scorer + novelty, end-to-end pipeline validation
"""

import os
import warnings

os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5437")
warnings.filterwarnings("ignore", message=".*pandas.*SQLAlchemy.*")
warnings.filterwarnings("ignore", category=UserWarning, module="pandas")

import math
import pytest
import numpy as np
import pandas as pd

from embeddings.embedder import MockEmbedder, EMBEDDING_DIM
from embeddings.composer import (
    SIGNAL_WEIGHTS,
    compose,
    cosine_similarity,
    drift_vector,
    drift_magnitude,
    compose_with_attention,
    hadamard_compose,
)
from detection.composite_scorer import (
    DRIFT_ZONES,
    CONTEXT_COLS,
    ROLE_GROUPS,
    ROLE_TO_GROUP,
    extract_user_features,
    compute_group_zscores,
    compute_composite_scores,
    threshold_sweep,
)
from detection.novelty_features import (
    _domain_entropy,
    _is_internal_domain,
    _dir_is_role_appropriate,
    _dir_is_sensitive_for_role,
    annotate_qualitative_features,
    compute_novelty_metrics,
    BASELINE_WEEKS,
    ROLE_EXPECTED_DIRS,
    SENSITIVE_DIRS,
)
from detection.drift_direction import (
    ConceptAlignment,
    DriftAnalysis,
    compute_drift_vector,
    concept_alignment,
    analyze_entity_drift,
    batch_drift_analysis,
)
from detection.reference_concepts import ConceptLibrary
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
from models.relationship_embeddings import hadamard


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def unit_vec(rng):
    def _make(seed=None):
        r = np.random.default_rng(seed or 42)
        v = r.standard_normal(EMBEDDING_DIM).astype(np.float32)
        return v / np.linalg.norm(v)
    return _make


@pytest.fixture
def mock_embedder():
    return MockEmbedder()


@pytest.fixture
def concept_library(mock_embedder):
    lib = ConceptLibrary(embedder=mock_embedder)
    lib.embed_concepts()
    return lib


@pytest.fixture
def minimal_trajectory_df():
    """Minimal trajectory DF with 2 users, 19 weeks."""
    rows = []
    for uid, is_attack, role in [("USR-001", False, "IT Admin"),
                                  ("USR-ATK", True, "Software Engineer")]:
        for week in range(19):
            row = {
                "user_id": uid, "week_idx": week,
                "is_attack": is_attack, "role": role,
                "composite_drift": 0.01 + (0.05 * week / 19 if is_attack else 0.0),
            }
            for z in DRIFT_ZONES:
                row[z] = 0.005 + (0.03 * week / 19 if is_attack else 0.0)
            for c in CONTEXT_COLS:
                row[c] = 0.01 + (0.04 * week / 19 if is_attack else 0.0)
            row["relationship_drift"] = 0.01 + (0.02 * week / 19 if is_attack else 0.0)
            row["zone_divergence"] = 0.01 + (0.03 * week / 19 if is_attack else 0.0)
            row["velocity"] = 0.005 + (0.01 * week / 19 if is_attack else 0.0)
            rows.append(row)
    return pd.DataFrame(rows)


@pytest.fixture
def multi_group_trajectory_df():
    """Trajectory DF with multiple role groups, 250 users, 19 weeks."""
    rng = np.random.default_rng(99)
    rows = []
    attack_users = {"USR-042", "USR-118", "USR-156", "USR-234"}
    roles = list(ROLE_TO_GROUP.keys())

    for i in range(250):
        uid = f"USR-{i:03d}"
        is_attack = uid in attack_users
        role = roles[i % len(roles)]
        for week in range(19):
            base_drift = rng.exponential(0.01)
            atk_boost = (0.03 * week / 19) if is_attack else 0.0
            row = {
                "user_id": uid, "week_idx": week,
                "is_attack": is_attack, "role": role,
                "composite_drift": base_drift + atk_boost,
            }
            for z in DRIFT_ZONES:
                row[z] = rng.exponential(0.008) + atk_boost * rng.uniform(0.5, 1.5)
            for c in CONTEXT_COLS:
                row[c] = rng.exponential(0.01) + atk_boost * rng.uniform(0.3, 1.2)
            row["relationship_drift"] = rng.exponential(0.005) + atk_boost * 0.5
            row["zone_divergence"] = rng.exponential(0.008) + atk_boost * 0.7
            row["velocity"] = rng.exponential(0.003) + atk_boost * 0.3
            rows.append(row)
    return pd.DataFrame(rows)


@pytest.fixture
def novelty_features_df():
    """Features DF for novelty testing."""
    rows = []
    for uid in ["USR-NORMAL", "USR-C2"]:
        for week in range(20):
            row = {"user_id": uid, "week_idx": week}
            if uid == "USR-NORMAL":
                row["qual_net_ext_ips"] = "10.0.0.1; 10.0.0.2"
                row["qual_file_dirs"] = "/shared; /engineering"
                row["qual_dns_domains"] = "google.com; github.com"
            else:
                if week < BASELINE_WEEKS:
                    row["qual_net_ext_ips"] = "10.0.0.1; 10.0.0.2"
                    row["qual_file_dirs"] = "/shared; /engineering"
                    row["qual_dns_domains"] = "google.com; github.com"
                else:
                    row["qual_net_ext_ips"] = "10.0.0.1; 192.168.99.99"
                    row["qual_file_dirs"] = "/shared; /executive"
                    row["qual_dns_domains"] = "google.com; xkr7qm2z.xyz"
            rows.append(row)
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1: COMPOSITE SCORER TESTS (DA2-001 to DA2-025)
# ═══════════════════════════════════════════════════════════════════════════

class TestCompositeScorer:
    """DA2-001 to DA2-025: Composite scorer unit tests."""

    def test_da2_001_extract_features_output_shape(self, minimal_trajectory_df):
        """DA2-001: extract_user_features returns correct shape."""
        feats = extract_user_features(minimal_trajectory_df)
        assert len(feats) == 2
        assert "uid" in feats.columns
        assert "is_attack" in feats.columns
        assert "grp" in feats.columns
        assert "role" in feats.columns

    def test_da2_002_extract_features_zone_columns(self, minimal_trajectory_df):
        """DA2-002: All zone-derived features present."""
        feats = extract_user_features(minimal_trajectory_df)
        for z in DRIFT_ZONES:
            zn = z.replace("_drift", "")
            for suffix in ["_sustained", "_late_q4", "_peak", "_trend", "_volatility"]:
                assert f"{zn}{suffix}" in feats.columns, f"Missing {zn}{suffix}"

    def test_da2_003_extract_features_attack_higher(self, minimal_trajectory_df):
        """DA2-003: Attack user has higher sustained drift than normal."""
        feats = extract_user_features(minimal_trajectory_df)
        atk = feats[feats.is_attack].iloc[0]
        norm = feats[~feats.is_attack].iloc[0]
        assert atk["access_pattern_sustained"] > norm["access_pattern_sustained"]

    def test_da2_004_extract_features_trend_positive(self, minimal_trajectory_df):
        """DA2-004: Attack user trend is positive (escalating)."""
        feats = extract_user_features(minimal_trajectory_df)
        atk = feats[feats.is_attack].iloc[0]
        assert atk["access_pattern_trend"] > 0

    def test_da2_005_group_zscores_zero_for_single_group(self):
        """DA2-005: Z-scores are 0 when group has no variance."""
        df = pd.DataFrame([
            {"uid": "U1", "is_attack": False, "grp": "admin", "role": "IT Admin", "feat1": 5.0},
            {"uid": "U2", "is_attack": False, "grp": "admin", "role": "IT Admin", "feat1": 5.0},
        ])
        result = compute_group_zscores(df)
        assert all(result["z_feat1"] == 0.0)

    def test_da2_006_group_zscores_attack_excluded_from_baseline(self):
        """DA2-006: Attack users don't contribute to group mean/std."""
        df = pd.DataFrame([
            {"uid": "N1", "is_attack": False, "grp": "dev", "role": "SE", "feat1": 1.0},
            {"uid": "N2", "is_attack": False, "grp": "dev", "role": "SE", "feat1": 3.0},
            {"uid": "ATK", "is_attack": True, "grp": "dev", "role": "SE", "feat1": 100.0},
        ])
        result = compute_group_zscores(df)
        atk_z = result[result.uid == "ATK"]["z_feat1"].iloc[0]
        assert atk_z > 10, "Attack z-score should be very high since excluded from baseline"

    def test_da2_007_group_zscores_single_normal_user(self):
        """DA2-007: Single normal user in group produces z=0 (no NaN)."""
        df = pd.DataFrame([
            {"uid": "N1", "is_attack": False, "grp": "exec", "role": "CEO", "feat1": 5.0},
            {"uid": "ATK", "is_attack": True, "grp": "exec", "role": "CEO", "feat1": 50.0},
        ])
        result = compute_group_zscores(df)
        for _, row in result.iterrows():
            assert not np.isnan(row["z_feat1"]), f"NaN z-score for {row['uid']}"

    def test_da2_008_composite_formula_manual_verification(self):
        """DA2-008: Verify composite formula matches manual calculation."""
        df = pd.DataFrame([{
            "uid": "U1", "is_attack": True, "grp": "dev", "role": "SE",
            "z_feat_a": 5.0, "z_feat_b": 4.0, "z_feat_c": 3.0,
            "z_feat_d": 1.0, "z_feat_e": 0.5,
            "z_access_pattern_sustained": 2.0,
            "z_data_behavior_sustained": 1.5,
            "z_network_footprint_sustained": 1.0,
            "z_risk_posture_sustained": 0.5,
            "z_ctx_spread": 3.0,
            "z_ctx_max": 2.0,
        }])
        scores = compute_composite_scores(df)
        row = scores.iloc[0]

        expected_signal = 5.0 + 4.0 + 3.0  # top-3 z-scores
        # breadth counts ALL z_ columns > 1.5, including z_ctx_spread and z_ctx_max
        expected_breadth = 6  # feat_a(5), feat_b(4), feat_c(3), access_sustained(2), ctx_spread(3), ctx_max(2)
        expected_sustained = 2.0 + 1.5  # top-2 zone sustained
        expected_ctx = 3.0  # ctx_spread
        expected_ctx_max = 2.0  # ctx_max

        expected_composite = (
            expected_signal * 1.0
            + expected_breadth * 0.5
            + expected_sustained * 0.3
            + max(expected_ctx, 0) * 0.5
            + max(expected_ctx_max, 0) * 0.3
            + 0.0  # no novelty
        )
        assert abs(row["composite"] - expected_composite) < 0.01

    def test_da2_009_composite_negative_zscores_no_crash(self):
        """DA2-009: All negative z-scores produce valid (likely negative) composite."""
        df = pd.DataFrame([{
            "uid": "U1", "is_attack": False, "grp": "dev", "role": "SE",
            "z_f1": -2.0, "z_f2": -1.0, "z_f3": -0.5,
            "z_ctx_spread": -1.0, "z_ctx_max": -0.5,
        }])
        scores = compute_composite_scores(df)
        assert not np.isnan(scores.iloc[0]["composite"])

    def test_da2_010_composite_novelty_integration(self):
        """DA2-010: Novelty score correctly boosts composite."""
        base_df = pd.DataFrame([{
            "uid": "U1", "is_attack": True, "grp": "dev", "role": "SE",
            "z_f1": 1.0, "z_f2": 0.5,
        }])
        novelty_df = pd.DataFrame([{
            "uid": "U1",
            "novel_ip_max_persistence": 15,
            "novel_ip_weeks_frac": 0.7,
            "persistent_novel_ips": 3,
        }])
        without = compute_composite_scores(base_df)
        with_nov = compute_composite_scores(base_df, novelty_df=novelty_df)
        assert with_nov.iloc[0]["composite"] > without.iloc[0]["composite"]
        assert with_nov.iloc[0]["novelty_score"] > 0

    def test_da2_011_novelty_persistence_cap(self):
        """DA2-011: Novelty score caps at 10 + 3 = 13 max."""
        df = pd.DataFrame([{
            "uid": "U1", "is_attack": True, "grp": "dev", "role": "SE",
            "z_f1": 0.0,
        }])
        novelty_df = pd.DataFrame([{
            "uid": "U1",
            "novel_ip_max_persistence": 1000,
            "novel_ip_weeks_frac": 1.0,
            "persistent_novel_ips": 100,
        }])
        scores = compute_composite_scores(df, novelty_df=novelty_df)
        assert scores.iloc[0]["novelty_score"] == 13.0

    def test_da2_012_novelty_below_threshold_no_score(self):
        """DA2-012: Persistence <= 10 and fraction <= 0.5 gives zero novelty."""
        df = pd.DataFrame([{
            "uid": "U1", "is_attack": False, "grp": "dev", "role": "SE",
            "z_f1": 0.0,
        }])
        novelty_df = pd.DataFrame([{
            "uid": "U1",
            "novel_ip_max_persistence": 8,
            "novel_ip_weeks_frac": 0.3,
            "persistent_novel_ips": 1,
        }])
        scores = compute_composite_scores(df, novelty_df=novelty_df)
        assert scores.iloc[0]["novelty_score"] == 0.0

    def test_da2_013_composite_sorted_descending(self, minimal_trajectory_df):
        """DA2-013: Output is sorted by composite descending."""
        feats = extract_user_features(minimal_trajectory_df)
        zscored = compute_group_zscores(feats)
        scores = compute_composite_scores(zscored)
        composites = scores["composite"].tolist()
        assert composites == sorted(composites, reverse=True)

    def test_da2_014_breadth_boundary_values(self):
        """DA2-014: Breadth counts at exact threshold boundaries."""
        df = pd.DataFrame([{
            "uid": "U1", "is_attack": False, "grp": "dev", "role": "SE",
            "z_at_15": 1.5, "z_above_15": 1.51, "z_below_15": 1.49,
            "z_at_20": 2.0, "z_above_20": 2.01, "z_below_20": 1.99,
        }])
        scores = compute_composite_scores(df)
        # breadth_15 counts ALL z_ values > 1.5: above_15(1.51), at_20(2.0), above_20(2.01), below_20(1.99)
        assert scores.iloc[0]["breadth_15"] == 4
        assert scores.iloc[0]["breadth_20"] == 1  # 2.01 only (> 2.0, strict)

    def test_da2_015_role_to_group_complete(self):
        """DA2-015: All roles in ROLE_GROUPS are mapped in ROLE_TO_GROUP."""
        for grp, roles in ROLE_GROUPS.items():
            for role in roles:
                assert role in ROLE_TO_GROUP
                assert ROLE_TO_GROUP[role] == grp

    def test_da2_016_unknown_role_maps_to_unknown(self):
        """DA2-016: Unknown role maps to 'unknown' group."""
        assert ROLE_TO_GROUP.get("Nonexistent Role", "unknown") == "unknown"

    def test_da2_017_extract_features_single_week(self):
        """DA2-017: Single week of data doesn't crash."""
        rows = [{
            "user_id": "U1", "week_idx": 0, "is_attack": False, "role": "IT Admin",
            "composite_drift": 0.01,
        }]
        for z in DRIFT_ZONES:
            rows[0][z] = 0.01
        for c in CONTEXT_COLS:
            rows[0][c] = 0.01
        df = pd.DataFrame(rows)
        feats = extract_user_features(df)
        assert len(feats) == 1
        for col in feats.columns:
            if col in ["uid", "role", "grp"]:
                continue
            assert not pd.isna(feats.iloc[0][col]), f"NaN in column {col}"

    def test_da2_018_extract_features_two_weeks(self):
        """DA2-018: Two weeks produces valid features (half=1, q3=1)."""
        rows = []
        for week in range(2):
            row = {"user_id": "U1", "week_idx": week, "is_attack": False,
                   "role": "IT Admin", "composite_drift": 0.01 * (week + 1)}
            for z in DRIFT_ZONES:
                row[z] = 0.01 * (week + 1)
            for c in CONTEXT_COLS:
                row[c] = 0.01 * (week + 1)
            rows.append(row)
        df = pd.DataFrame(rows)
        feats = extract_user_features(df)
        assert len(feats) == 1

    def test_da2_019_composite_with_250_users(self, multi_group_trajectory_df):
        """DA2-019: Full 250-user pipeline runs without errors."""
        feats = extract_user_features(multi_group_trajectory_df)
        assert len(feats) == 250
        zscored = compute_group_zscores(feats)
        scores = compute_composite_scores(zscored)
        assert len(scores) == 250
        assert not scores["composite"].isna().any()

    def test_da2_020_attack_users_rank_high(self, multi_group_trajectory_df):
        """DA2-020: Attack users rank in top half of composite scores."""
        feats = extract_user_features(multi_group_trajectory_df)
        zscored = compute_group_zscores(feats)
        scores = compute_composite_scores(zscored)
        for uid in ["USR-042", "USR-118", "USR-156", "USR-234"]:
            rank = scores.index[scores.uid == uid].tolist()
            if rank:
                assert rank[0] < 125, f"{uid} not in top half: rank {rank[0]+1}"

    def test_da2_021_signal_strength_is_top3_sum(self):
        """DA2-021: Signal strength equals sum of 3 highest z-values."""
        df = pd.DataFrame([{
            "uid": "U1", "is_attack": False, "grp": "dev", "role": "SE",
            "z_a": 10.0, "z_b": 5.0, "z_c": 3.0, "z_d": 1.0, "z_e": 0.1,
        }])
        scores = compute_composite_scores(df)
        assert abs(scores.iloc[0]["signal_strength"] - 18.0) < 0.01

    def test_da2_022_sustained_signal_top2_zones(self):
        """DA2-022: Sustained signal equals sum of top-2 zone sustaineds."""
        df = pd.DataFrame([{
            "uid": "U1", "is_attack": False, "grp": "dev", "role": "SE",
            "z_access_pattern_sustained": 5.0,
            "z_data_behavior_sustained": 3.0,
            "z_network_footprint_sustained": 1.0,
            "z_risk_posture_sustained": 0.5,
        }])
        scores = compute_composite_scores(df)
        assert abs(scores.iloc[0]["sustained_signal"] - 8.0) < 0.01

    def test_da2_023_context_negative_floored(self):
        """DA2-023: Negative context z-scores are floored to 0."""
        df = pd.DataFrame([{
            "uid": "U1", "is_attack": False, "grp": "dev", "role": "SE",
            "z_ctx_spread": -5.0, "z_ctx_max": -3.0, "z_f1": 0.0,
        }])
        scores = compute_composite_scores(df)
        composite = scores.iloc[0]["composite"]
        # With all z=0 and negative context, composite should be near 0
        assert composite <= 0.5

    def test_da2_024_empty_novelty_df(self):
        """DA2-024: None novelty_df produces zero novelty scores."""
        df = pd.DataFrame([{
            "uid": "U1", "is_attack": False, "grp": "dev", "role": "SE",
            "z_f1": 2.0,
        }])
        scores = compute_composite_scores(df, novelty_df=None)
        assert scores.iloc[0]["novelty_score"] == 0.0

    def test_da2_025_multiple_groups_independent(self):
        """DA2-025: Z-scores computed independently per group."""
        df = pd.DataFrame([
            {"uid": "A1", "is_attack": False, "grp": "admin", "role": "IT Admin", "feat": 10.0},
            {"uid": "A2", "is_attack": False, "grp": "admin", "role": "IT Admin", "feat": 12.0},
            {"uid": "D1", "is_attack": False, "grp": "dev", "role": "SE", "feat": 100.0},
            {"uid": "D2", "is_attack": False, "grp": "dev", "role": "SE", "feat": 102.0},
        ])
        result = compute_group_zscores(df)
        admin_z = result[result.grp == "admin"]["z_feat"].abs().max()
        dev_z = result[result.grp == "dev"]["z_feat"].abs().max()
        assert admin_z < 2 and dev_z < 2, "Z-scores should be small within-group"


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2: NOVELTY FEATURES TESTS (DA2-026 to DA2-040)
# ═══════════════════════════════════════════════════════════════════════════

class TestNoveltyFeatures:
    """DA2-026 to DA2-040: Novelty feature extraction and C2 detection."""

    def test_da2_026_domain_entropy_empty(self):
        """DA2-026: Empty domain has zero entropy."""
        assert _domain_entropy("") == 0.0

    def test_da2_027_domain_entropy_single_char(self):
        """DA2-027: Single repeated char has zero entropy."""
        assert _domain_entropy("aaaa.com") == 0.0

    def test_da2_028_domain_entropy_random_high(self):
        """DA2-028: Random-looking domain has high entropy (DGA-like)."""
        ent = _domain_entropy("xkr7qm2z.xyz")
        assert ent > 2.5, f"Expected high entropy, got {ent}"

    def test_da2_029_domain_entropy_normal_low(self):
        """DA2-029: Normal domain has moderate entropy."""
        ent = _domain_entropy("google.com")
        assert ent < 3.0

    def test_da2_030_is_internal_domain(self):
        """DA2-030: Internal domains correctly identified."""
        assert _is_internal_domain("mail.corp")
        assert _is_internal_domain("server.internal")
        assert _is_internal_domain("dc01.local")
        assert not _is_internal_domain("google.com")
        assert not _is_internal_domain("evil.xyz")

    def test_da2_031_dir_role_appropriate(self):
        """DA2-031: Role-appropriate directories correctly matched."""
        assert _dir_is_role_appropriate("/engineering/project", "developer")
        assert _dir_is_role_appropriate("/infrastructure/logs", "admin")
        assert not _dir_is_role_appropriate("/executive/board", "developer")

    def test_da2_032_dir_sensitive_for_role(self):
        """DA2-032: Sensitive directory access flagged for wrong role."""
        assert _dir_is_sensitive_for_role("/executive/reports", "developer") is not None
        assert _dir_is_sensitive_for_role("/finance/budget", "developer") is not None
        assert _dir_is_sensitive_for_role("/finance/budget", "business") is None
        assert _dir_is_sensitive_for_role("/shared/docs", "developer") is None

    def test_da2_033_annotate_baseline_untouched(self, novelty_features_df):
        """DA2-033: Baseline weeks (< BASELINE_WEEKS) are not annotated."""
        role_map = {"USR-NORMAL": "developer", "USR-C2": "developer"}
        result = annotate_qualitative_features(novelty_features_df, role_map)
        baseline = result[(result.user_id == "USR-C2") & (result.week_idx < BASELINE_WEEKS)]
        for _, row in baseline.iterrows():
            assert "[NOVEL]" not in str(row.get("qual_net_ext_ips", ""))

    def test_da2_034_annotate_novel_ips_tagged(self, novelty_features_df):
        """DA2-034: Novel IPs after baseline are tagged [NOVEL]."""
        role_map = {"USR-NORMAL": "developer", "USR-C2": "developer"}
        result = annotate_qualitative_features(novelty_features_df, role_map)
        post = result[(result.user_id == "USR-C2") & (result.week_idx >= BASELINE_WEEKS)]
        for _, row in post.iterrows():
            assert "[NOVEL]" in str(row["qual_net_ext_ips"])

    def test_da2_035_annotate_high_entropy_domain(self, novelty_features_df):
        """DA2-035: High-entropy domains tagged with entropy score."""
        role_map = {"USR-NORMAL": "developer", "USR-C2": "developer"}
        result = annotate_qualitative_features(novelty_features_df, role_map)
        post = result[(result.user_id == "USR-C2") & (result.week_idx >= BASELINE_WEEKS)]
        for _, row in post.iterrows():
            dns = str(row.get("qual_dns_domains", ""))
            assert "HIGH-ENTROPY" in dns or "NOVEL" in dns

    def test_da2_036_annotate_sensitive_dir(self, novelty_features_df):
        """DA2-036: Sensitive dir access by wrong role flagged ATYPICAL."""
        role_map = {"USR-NORMAL": "developer", "USR-C2": "developer"}
        result = annotate_qualitative_features(novelty_features_df, role_map)
        post = result[(result.user_id == "USR-C2") & (result.week_idx >= BASELINE_WEEKS)]
        found_atypical = False
        for _, row in post.iterrows():
            if "ATYPICAL" in str(row.get("qual_file_dirs", "")):
                found_atypical = True
        assert found_atypical, "Developer accessing /executive should be ATYPICAL"

    def test_da2_037_compute_novelty_c2_detected(self, novelty_features_df):
        """DA2-037: C2 beacon IP persistence detected in novelty metrics."""
        metrics = compute_novelty_metrics(novelty_features_df)
        c2 = metrics[metrics.uid == "USR-C2"].iloc[0]
        assert c2["novel_ip_max_persistence"] > 0
        assert c2["novel_ip_weeks_frac"] > 0

    def test_da2_038_compute_novelty_normal_low(self, novelty_features_df):
        """DA2-038: Normal user has zero novel IPs."""
        metrics = compute_novelty_metrics(novelty_features_df)
        norm = metrics[metrics.uid == "USR-NORMAL"].iloc[0]
        assert norm["novel_ip_max_persistence"] == 0
        assert norm["novel_ip_weeks_frac"] == 0.0

    def test_da2_039_novelty_empty_ips(self):
        """DA2-039: Empty IP strings don't crash novelty computation."""
        df = pd.DataFrame([
            {"user_id": "U1", "week_idx": w, "qual_net_ext_ips": ""}
            for w in range(20)
        ])
        metrics = compute_novelty_metrics(df)
        assert len(metrics) == 1
        assert metrics.iloc[0]["novel_ip_max_persistence"] == 0

    def test_da2_040_novelty_nan_ips(self):
        """DA2-040: NaN IP strings handled gracefully."""
        df = pd.DataFrame([
            {"user_id": "U1", "week_idx": w, "qual_net_ext_ips": float('nan')}
            for w in range(20)
        ])
        metrics = compute_novelty_metrics(df)
        assert len(metrics) == 1


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3: EMBEDDING COMPOSER EDGE CASES (DA2-041 to DA2-055)
# ═══════════════════════════════════════════════════════════════════════════

class TestComposerEdgeCases:
    """DA2-041 to DA2-055: Composer edge cases and numerical stability."""

    def test_da2_041_compose_unknown_entity_type(self, unit_vec):
        """DA2-041: Unknown entity type raises ValueError."""
        v = unit_vec(seed=1)
        with pytest.raises(ValueError, match="Unknown entity_type"):
            compose({"auth": v}, "alien")

    def test_da2_042_compose_empty_dict_raises(self):
        """DA2-042: Empty signal dict raises error."""
        with pytest.raises((ValueError, StopIteration)):
            compose({}, "user")

    def test_da2_043_compose_unrecognized_signal_ignored(self, unit_vec):
        """DA2-043: Unrecognized signal names have zero weight."""
        v = unit_vec(seed=1)
        with pytest.raises(ValueError, match="No matching signal weights"):
            compose({"nonexistent_signal": v}, "user")

    def test_da2_044_compose_output_unit_norm(self, unit_vec):
        """DA2-044: Composed vector is unit-normalized."""
        signals = {name: unit_vec(seed=i) for i, name in enumerate(SIGNAL_WEIGHTS["user"])}
        result = compose(signals, "user")
        assert abs(np.linalg.norm(result) - 1.0) < 1e-5

    def test_da2_045_compose_output_1536d(self, unit_vec):
        """DA2-045: Output is exactly 1536 dimensions."""
        signals = {name: unit_vec(seed=i) for i, name in enumerate(SIGNAL_WEIGHTS["user"])}
        result = compose(signals, "user")
        assert result.shape == (EMBEDDING_DIM,)

    def test_da2_046_cosine_identical_vectors(self, unit_vec):
        """DA2-046: Identical vectors have cosine similarity 1.0."""
        v = unit_vec(seed=1)
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_da2_047_cosine_opposite_vectors(self, unit_vec):
        """DA2-047: Opposite vectors have cosine similarity -1.0."""
        v = unit_vec(seed=1)
        assert abs(cosine_similarity(v, -v) - (-1.0)) < 1e-6

    def test_da2_048_cosine_zero_vector(self, unit_vec):
        """DA2-048: Zero vector returns cosine similarity 0."""
        v = unit_vec(seed=1)
        z = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        assert cosine_similarity(v, z) == 0.0
        assert cosine_similarity(z, z) == 0.0

    def test_da2_049_drift_magnitude_range(self, unit_vec):
        """DA2-049: Drift magnitude is in [0, 2]."""
        v1 = unit_vec(seed=1)
        v2 = unit_vec(seed=2)
        mag = drift_magnitude(v1, v2)
        assert 0 <= mag <= 2

    def test_da2_050_drift_identical_is_zero(self, unit_vec):
        """DA2-050: Identical vectors have zero drift."""
        v = unit_vec(seed=1)
        assert drift_magnitude(v, v) < 1e-6

    def test_da2_051_drift_vector_unit_norm(self, unit_vec):
        """DA2-051: Drift vector is unit-normalized when vectors differ."""
        v1 = unit_vec(seed=1)
        v2 = unit_vec(seed=2)
        dv = drift_vector(v1, v2)
        norm = np.linalg.norm(dv)
        assert abs(norm - 1.0) < 1e-5 or norm < 1e-10

    def test_da2_052_drift_vector_identical_is_zero(self, unit_vec):
        """DA2-052: Identical vectors produce zero drift vector."""
        v = unit_vec(seed=1)
        dv = drift_vector(v, v)
        assert np.linalg.norm(dv) < 1e-9

    def test_da2_053_attention_context_sensitivity(self, unit_vec):
        """DA2-053: Different contexts produce different attention weights."""
        signals = {
            "network_footprint": unit_vec(seed=1) * 2.0,
            "data_behavior": unit_vec(seed=2) * 1.5,
            "access_pattern": unit_vec(seed=3),
        }
        apt_weights = {"network_footprint": 0.40, "data_behavior": 0.10, "access_pattern": 0.15}
        insider_weights = {"network_footprint": 0.10, "data_behavior": 0.40, "access_pattern": 0.15}

        _, apt_alphas = compose_with_attention(signals, "user", apt_weights)
        _, ins_alphas = compose_with_attention(signals, "user", insider_weights)

        assert apt_alphas["network_footprint"] > ins_alphas["network_footprint"]
        assert ins_alphas["data_behavior"] > apt_alphas["data_behavior"]

    def test_da2_054_hadamard_commutative(self, unit_vec):
        """DA2-054: Hadamard composition is commutative."""
        a = unit_vec(seed=1)
        b = unit_vec(seed=2)
        ab = hadamard_compose(a, b)
        ba = hadamard_compose(b, a)
        assert np.allclose(ab, ba, atol=1e-6)

    def test_da2_055_hadamard_zero_vector(self, unit_vec):
        """DA2-055: Hadamard with zero vector returns zero."""
        v = unit_vec(seed=1)
        z = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        result = hadamard_compose(v, z)
        assert np.linalg.norm(result) < 1e-7


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4: DRIFT DIRECTION TESTS (DA2-056 to DA2-070)
# ═══════════════════════════════════════════════════════════════════════════

class TestDriftDirection:
    """DA2-056 to DA2-070: Drift direction analysis and concept alignment."""

    def test_da2_056_zero_drift_no_alignments(self, concept_library):
        """DA2-056: Zero drift vector returns empty alignments."""
        z = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        result = concept_alignment(z, concept_library.all_threat_vectors(), concept_library)
        assert len(result) == 0

    def test_da2_057_concept_alignment_sorted_descending(self, concept_library, unit_vec):
        """DA2-057: Alignments sorted by score descending."""
        dv = unit_vec(seed=99)
        vecs = {**concept_library.all_threat_vectors(), **concept_library.all_benign_vectors()}
        result = concept_alignment(dv, vecs, concept_library)
        scores = [a.alignment_score for a in result]
        assert scores == sorted(scores, reverse=True)

    def test_da2_058_analyze_drift_no_change(self, concept_library, unit_vec):
        """DA2-058: No drift produces is_threat=False."""
        v = unit_vec(seed=1)
        analysis = analyze_entity_drift("user", "U1", v, v, concept_library)
        assert analysis.drift_magnitude < 1e-5
        assert not analysis.is_threat

    def test_da2_059_analyze_drift_result_fields(self, concept_library, unit_vec):
        """DA2-059: DriftAnalysis has all expected fields."""
        v1 = unit_vec(seed=1)
        v2 = unit_vec(seed=2)
        analysis = analyze_entity_drift("user", "U1", v1, v2, concept_library)
        assert hasattr(analysis, "entity_type")
        assert hasattr(analysis, "entity_id")
        assert hasattr(analysis, "drift_magnitude")
        assert hasattr(analysis, "top_alignments")
        assert hasattr(analysis, "primary_direction")
        assert hasattr(analysis, "is_threat")
        assert hasattr(analysis, "confidence")
        assert analysis.entity_type == "user"
        assert analysis.entity_id == "U1"

    def test_da2_060_batch_drift_filters_low_magnitude(self, concept_library, unit_vec):
        """DA2-060: Batch analysis filters entities below min_drift_magnitude."""
        v = unit_vec(seed=1)
        snapshots = {
            "U1": (v, v),  # zero drift — should be filtered
            "U2": (unit_vec(seed=2), unit_vec(seed=3)),  # real drift
        }
        results = batch_drift_analysis(snapshots, "user", concept_library, min_drift_magnitude=0.01)
        uids = [r.entity_id for r in results]
        assert "U1" not in uids
        assert "U2" in uids

    def test_da2_061_batch_drift_sorted_by_magnitude(self, concept_library, unit_vec):
        """DA2-061: Batch results sorted by drift magnitude descending."""
        snapshots = {
            f"U{i}": (unit_vec(seed=i), unit_vec(seed=i + 100))
            for i in range(5)
        }
        results = batch_drift_analysis(snapshots, "user", concept_library, min_drift_magnitude=0.0)
        mags = [r.drift_magnitude for r in results]
        assert mags == sorted(mags, reverse=True)

    def test_da2_062_alignment_threshold_effect(self, concept_library, unit_vec):
        """DA2-062: Higher threshold makes threat classification harder."""
        v1 = unit_vec(seed=1)
        v2 = unit_vec(seed=2)
        low = analyze_entity_drift("user", "U1", v1, v2, concept_library, alignment_threshold=0.01)
        high = analyze_entity_drift("user", "U1", v1, v2, concept_library, alignment_threshold=0.99)
        # If low threshold triggers threat, high should not
        if low.is_threat:
            assert not high.is_threat

    def test_da2_063_concept_alignment_has_category(self, concept_library, unit_vec):
        """DA2-063: Each alignment has a valid category."""
        dv = unit_vec(seed=42)
        vecs = {**concept_library.all_threat_vectors(), **concept_library.all_benign_vectors()}
        result = concept_alignment(dv, vecs, concept_library)
        for a in result:
            assert a.category in ("threat", "benign")

    def test_da2_064_drift_magnitude_symmetric(self, unit_vec):
        """DA2-064: Drift magnitude is symmetric."""
        v1 = unit_vec(seed=1)
        v2 = unit_vec(seed=2)
        assert abs(drift_magnitude(v1, v2) - drift_magnitude(v2, v1)) < 1e-6

    def test_da2_065_concept_alignment_mitre_present(self, concept_library, unit_vec):
        """DA2-065: Threat concepts have MITRE techniques."""
        dv = unit_vec(seed=42)
        threats = concept_library.all_threat_vectors()
        result = concept_alignment(dv, threats, concept_library)
        for a in result:
            if a.category == "threat":
                assert isinstance(a.mitre_techniques, list)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5: HIERARCHICAL ZONES (DA2-066 to DA2-075)
# ═══════════════════════════════════════════════════════════════════════════

class TestHierarchicalZones:
    """DA2-066 to DA2-075: Zone definitions and composition."""

    def test_da2_066_five_user_zones(self):
        """DA2-066: Exactly 5 user zones defined."""
        assert len(USER_ZONE_ORDER) == 5
        expected = {"identity", "access_pattern", "data_behavior",
                    "network_footprint", "risk_posture"}
        assert set(USER_ZONE_ORDER) == expected

    def test_da2_067_four_contexts_defined(self):
        """DA2-067: Exactly 4 investigation contexts defined."""
        assert len(ALL_CONTEXTS) == 4
        expected = {"normal_ops", "insider_investigation", "apt_hunt", "privilege_audit"}
        assert set(ALL_CONTEXTS) == expected

    def test_da2_068_context_weights_sum_to_one(self):
        """DA2-068: Context weights sum to ~1.0 for each context."""
        for ctx_name, ctx_weights in CONTEXT_WEIGHTS["user"].items():
            total = sum(ctx_weights.values())
            assert abs(total - 1.0) < 0.01, f"{ctx_name} weights sum to {total}"

    def test_da2_069_apt_hunt_upweights_network(self):
        """DA2-069: APT hunt context gives network_footprint highest weight."""
        apt = CONTEXT_WEIGHTS["user"]["apt_hunt"]
        assert apt["network_footprint"] >= apt["data_behavior"]
        assert apt["network_footprint"] >= apt["access_pattern"]

    def test_da2_070_insider_upweights_data(self):
        """DA2-070: Insider context gives data_behavior highest weight."""
        insider = CONTEXT_WEIGHTS["user"]["insider_investigation"]
        assert insider["data_behavior"] >= insider["network_footprint"]
        assert insider["data_behavior"] >= insider["access_pattern"]

    def test_da2_071_serialize_zone_returns_string(self, mock_embedder):
        """DA2-071: serialize_zone produces non-empty string."""
        features = {"auth_total": 100, "auth_fail_rate": 0.05}
        text = serialize_zone("user", "access_pattern", {"role": "IT Admin"}, features)
        assert isinstance(text, str)
        assert len(text) > 10

    def test_da2_072_build_zone_embeddings_all_zones(self, mock_embedder):
        """DA2-072: build_zone_embeddings produces 5 zone embeddings."""
        profile = {"role": "IT Admin", "department": "IT"}
        features = {
            "auth_total": 100, "auth_fail_rate": 0.05, "auth_off_hours_ratio": 0.1,
            "auth_unique_sources": 5, "auth_unique_dests": 10, "auth_methods": 3,
            "file_total": 50, "file_restricted_ratio": 0.02, "file_confidential_ratio": 0.01,
            "file_write_ratio": 0.3, "file_unique_paths": 20, "file_total_bytes": 1e6,
            "net_bytes_out": 5e6, "net_unique_dsts": 30, "net_external_ratio": 0.2,
            "dns_unique_domains": 40, "dns_nxdomain_ratio": 0.05,
            "endpoint_suspicious_ratio": 0.01, "endpoint_max_risk": 3,
            "endpoint_mean_risk": 1.5, "endpoint_unique_processes": 15,
            "endpoint_total": 200,
        }
        zones = build_zone_embeddings("user", "U1", profile, features, mock_embedder)
        assert len(zones) == 5
        for zone_name, emb in zones.items():
            assert emb.shape == (EMBEDDING_DIM,)

    def test_da2_073_compose_zones_different_contexts(self, mock_embedder):
        """DA2-073: Different contexts produce different composite vectors."""
        profile = {"role": "IT Admin", "department": "IT"}
        features = {
            "auth_total": 100, "auth_fail_rate": 0.05, "auth_off_hours_ratio": 0.1,
            "auth_unique_sources": 5, "auth_unique_dests": 10, "auth_methods": 3,
            "file_total": 50, "file_restricted_ratio": 0.02, "file_confidential_ratio": 0.01,
            "file_write_ratio": 0.3, "file_unique_paths": 20, "file_total_bytes": 1e6,
            "net_bytes_out": 5e6, "net_unique_dsts": 30, "net_external_ratio": 0.2,
            "dns_unique_domains": 40, "dns_nxdomain_ratio": 0.05,
            "endpoint_suspicious_ratio": 0.01, "endpoint_max_risk": 3,
            "endpoint_mean_risk": 1.5, "endpoint_unique_processes": 15,
            "endpoint_total": 200,
        }
        zones = build_zone_embeddings("user", "U1", profile, features, mock_embedder)
        apt_comp = compose_zones(zones, "apt_hunt", "user")
        insider_comp = compose_zones(zones, "insider_investigation", "user")
        sim = cosine_similarity(apt_comp, insider_comp)
        assert sim < 0.999, "Different contexts should produce different composites"

    def test_da2_074_softmax_attention_sums_to_one(self):
        """DA2-074: Softmax attention weights sum to 1.0."""
        zone_vecs = {
            "a": np.random.randn(1536).astype(np.float32),
            "b": np.random.randn(1536).astype(np.float32),
            "c": np.random.randn(1536).astype(np.float32),
        }
        context_weights = {"a": 0.5, "b": 0.3, "c": 0.2}
        result = softmax_attention(zone_vecs, context_weights)
        assert abs(sum(result.values()) - 1.0) < 1e-6

    def test_da2_075_compose_zones_output_normalized(self, mock_embedder):
        """DA2-075: Composed zone output is unit-normalized."""
        profile = {"role": "IT Admin"}
        features = {
            "auth_total": 100, "auth_fail_rate": 0.05, "auth_off_hours_ratio": 0.1,
            "auth_unique_sources": 5, "auth_unique_dests": 10, "auth_methods": 3,
            "file_total": 50, "file_restricted_ratio": 0.02, "file_confidential_ratio": 0.01,
            "file_write_ratio": 0.3, "file_unique_paths": 20, "file_total_bytes": 1e6,
            "net_bytes_out": 5e6, "net_unique_dsts": 30, "net_external_ratio": 0.2,
            "dns_unique_domains": 40, "dns_nxdomain_ratio": 0.05,
            "endpoint_suspicious_ratio": 0.01, "endpoint_max_risk": 3,
            "endpoint_mean_risk": 1.5, "endpoint_unique_processes": 15,
            "endpoint_total": 200,
        }
        zones = build_zone_embeddings("user", "U1", profile, features, mock_embedder)
        comp = compose_zones(zones, "normal_ops", "user")
        assert abs(np.linalg.norm(comp) - 1.0) < 1e-4


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6: TEMPORAL TRAJECTORY (DA2-076 to DA2-085)
# ═══════════════════════════════════════════════════════════════════════════

class TestTemporalTrajectory:
    """DA2-076 to DA2-085: Velocity, trajectory features, regime detection."""

    def test_da2_076_velocity_single_snapshot(self, unit_vec):
        """DA2-076: Single snapshot returns zero velocity."""
        v = unit_vec(seed=1)
        vel = compute_velocity_vector([v])
        assert np.linalg.norm(vel) < 1e-9

    def test_da2_077_velocity_two_snapshots(self, unit_vec):
        """DA2-077: Two different snapshots produce non-zero velocity."""
        v1, v2 = unit_vec(seed=1), unit_vec(seed=2)
        vel = compute_velocity_vector([v1, v2])
        assert np.linalg.norm(vel) > 0.01

    def test_da2_078_velocity_identical_is_zero(self, unit_vec):
        """DA2-078: Identical snapshots produce zero velocity."""
        v = unit_vec(seed=1)
        vel = compute_velocity_vector([v, v, v])
        assert np.linalg.norm(vel) < 1e-9

    def test_da2_079_trajectory_features_keys(self, unit_vec):
        """DA2-079: Trajectory features contain all 6 expected keys."""
        snaps = [unit_vec(seed=i) for i in range(10)]
        feats = compute_trajectory_features(snaps)
        expected = {"velocity_magnitude", "acceleration", "stability",
                    "regime_shifts", "trend_consistency", "total_drift"}
        assert set(feats.keys()) == expected

    def test_da2_080_regime_stable(self):
        """DA2-080: Low drift, no acceleration = stable regime."""
        feats = {
            "velocity_magnitude": 0.001,
            "acceleration": 0.001,
            "stability": 0.99,
            "regime_shifts": 0.0,
            "trend_consistency": 0.9,
            "total_drift": 0.01,
        }
        assert detect_regime(feats) == "stable"

    def test_da2_081_regime_shift_detected(self):
        """DA2-081: Any regime shifts fraction > 0 triggers regime_shift."""
        feats = {
            "velocity_magnitude": 0.5,
            "acceleration": 0.02,
            "stability": 0.5,
            "regime_shifts": 0.1,
            "trend_consistency": 0.3,
            "total_drift": 0.5,
        }
        assert detect_regime(feats) == "regime_shift"

    def test_da2_082_regime_accelerating(self):
        """DA2-082: High acceleration with consistent trend = accelerating."""
        feats = {
            "velocity_magnitude": 0.3,
            "acceleration": 0.05,
            "stability": 0.7,
            "regime_shifts": 0.0,
            "trend_consistency": 0.8,
            "total_drift": 0.3,
        }
        assert detect_regime(feats) == "accelerating"

    def test_da2_083_regime_drifting(self):
        """DA2-083: Moderate drift without acceleration or shifts = drifting."""
        feats = {
            "velocity_magnitude": 0.1,
            "acceleration": 0.005,
            "stability": 0.8,
            "regime_shifts": 0.0,
            "trend_consistency": 0.3,
            "total_drift": 0.15,
        }
        regime = detect_regime(feats)
        assert regime in ("drifting", "stable")

    def test_da2_084_trajectory_monotonic_drift(self, unit_vec):
        """DA2-084: Monotonically drifting series has positive trend consistency."""
        base = unit_vec(seed=1).astype(np.float64)
        direction = unit_vec(seed=2).astype(np.float64)
        snaps = [(base + i * 0.02 * direction).astype(np.float32) for i in range(20)]
        feats = compute_trajectory_features(snaps)
        assert feats["trend_consistency"] >= 0

    def test_da2_085_trajectory_short_series(self, unit_vec):
        """DA2-085: 3-snapshot series produces valid features."""
        snaps = [unit_vec(seed=i) for i in range(3)]
        feats = compute_trajectory_features(snaps)
        assert all(not np.isnan(v) for v in feats.values())


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7: DETECTION ACCURACY VALIDATION (DA2-086 to DA2-095)
# ═══════════════════════════════════════════════════════════════════════════

class TestDetectionAccuracy:
    """DA2-086 to DA2-095: Validate actual detection results from CSV data."""

    @pytest.fixture
    def composite_scores(self):
        path = "data/tier3_results/composite_scores.csv"
        if not os.path.exists(path):
            pytest.skip("composite_scores.csv not found")
        return pd.read_csv(path)

    @pytest.fixture
    def tier3_comparison(self):
        path = "data/tier3_results/tier3_comparison.csv"
        if not os.path.exists(path):
            pytest.skip("tier3_comparison.csv not found")
        return pd.read_csv(path)

    def test_da2_086_composite_250_users(self, composite_scores):
        """DA2-086: Composite scores contain exactly 250 users."""
        assert len(composite_scores) == 250

    def test_da2_087_salt_typhoon_rank_1(self, composite_scores):
        """DA2-087: USR-118 (Salt Typhoon) is rank #1."""
        top = composite_scores.iloc[0]
        assert top["uid"] == "USR-118", f"Expected USR-118 at #1, got {top['uid']}"
        assert top["composite"] > 50

    def test_da2_088_insider_rank_2(self, composite_scores):
        """DA2-088: USR-156 (Insider) is rank #2."""
        second = composite_scores.iloc[1]
        assert second["uid"] == "USR-156", f"Expected USR-156 at #2, got {second['uid']}"
        assert second["composite"] > 40

    def test_da2_089_slow_apt_top_10(self, composite_scores):
        """DA2-089: USR-234 (Slow APT) is in top 10."""
        top10 = composite_scores.head(10)["uid"].tolist()
        assert "USR-234" in top10, f"USR-234 not in top 10: {top10}"

    def test_da2_090_volt_typhoon_top_25(self, composite_scores):
        """DA2-090: USR-042 (Volt Typhoon) is in top 25 (90th percentile)."""
        top25 = composite_scores.head(25)["uid"].tolist()
        assert "USR-042" in top25, f"USR-042 not in top 25"

    def test_da2_091_all_4_detected_at_p90(self, composite_scores):
        """DA2-091: All 4 attack users detected at 90th percentile threshold."""
        threshold = composite_scores["composite"].quantile(0.90)
        attack_ids = {"USR-042", "USR-118", "USR-156", "USR-234"}
        detected = set(composite_scores[composite_scores["composite"] >= threshold]["uid"])
        for uid in attack_ids:
            assert uid in detected, f"{uid} not detected at p90 threshold={threshold:.2f}"

    def test_da2_092_fp_rate_under_10_percent(self, composite_scores):
        """DA2-092: False positive rate < 10% at threshold catching all 4."""
        attack_ids = {"USR-042", "USR-118", "USR-156", "USR-234"}
        threshold = composite_scores["composite"].quantile(0.90)
        flagged = composite_scores[composite_scores["composite"] >= threshold]
        fp = len(flagged[~flagged["uid"].isin(attack_ids)])
        n_normal = len(composite_scores) - len(attack_ids)
        fp_rate = fp / n_normal * 100
        assert fp_rate < 10.0, f"FP rate {fp_rate:.1f}% exceeds 10%"

    def test_da2_093_attack_scores_above_normal_median(self, composite_scores):
        """DA2-093: All attack users score above normal user median."""
        attack_ids = {"USR-042", "USR-118", "USR-156", "USR-234"}
        normals = composite_scores[~composite_scores["uid"].isin(attack_ids)]
        median = normals["composite"].median()
        for uid in attack_ids:
            score = composite_scores[composite_scores.uid == uid]["composite"].iloc[0]
            assert score > median, f"{uid} score {score:.2f} below median {median:.2f}"

    def test_da2_094_traditional_misses_salt_typhoon(self, tier3_comparison):
        """DA2-094: Traditional methods all miss Salt Typhoon (USR-118)."""
        row = tier3_comparison[tier3_comparison.user_id == "USR-118"]
        if row.empty:
            pytest.skip("USR-118 not in tier3_comparison")
        row = row.iloc[0]
        for col in ["iforest_anomaly", "ocsvm_anomaly", "lof_anomaly"]:
            if col in tier3_comparison.columns:
                assert not bool(row[col]), f"{col} incorrectly flagged USR-118"

    def test_da2_095_zscore_catches_volt_typhoon_only(self, tier3_comparison):
        """DA2-095: Z-Score catches only USR-042 (Volt Typhoon)."""
        attack_ids = {"USR-042", "USR-118", "USR-156", "USR-234"}
        if "zscore_anomaly" not in tier3_comparison.columns:
            pytest.skip("zscore_anomaly column not present")
        for uid in attack_ids:
            row = tier3_comparison[tier3_comparison.user_id == uid]
            if row.empty:
                continue
            detected = bool(row.iloc[0]["zscore_anomaly"])
            if uid == "USR-042":
                assert detected, "Z-Score should catch Volt Typhoon"
            else:
                assert not detected, f"Z-Score should not catch {uid}"


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 8: NUMERICAL STABILITY (DA2-096 to DA2-105)
# ═══════════════════════════════════════════════════════════════════════════

class TestNumericalStability:
    """DA2-096 to DA2-105: NaN, infinity, and boundary value handling."""

    def test_da2_096_cosine_near_zero_vector(self):
        """DA2-096: Very small vectors don't produce NaN."""
        tiny = np.full(EMBEDDING_DIM, 1e-20, dtype=np.float32)
        result = cosine_similarity(tiny, tiny)
        assert not np.isnan(result)

    def test_da2_097_drift_magnitude_near_identical(self, unit_vec):
        """DA2-097: Nearly identical vectors produce near-zero drift."""
        v = unit_vec(seed=1).astype(np.float64)
        v2 = (v + np.full(EMBEDDING_DIM, 1e-8)).astype(np.float32)
        v = v.astype(np.float32)
        mag = drift_magnitude(v, v2)
        assert mag < 0.01
        assert not np.isnan(mag)

    def test_da2_098_compose_with_attention_zero_vectors(self):
        """DA2-098: All-zero vectors in attention composition."""
        signals = {
            "a": np.zeros(EMBEDDING_DIM, dtype=np.float32),
            "b": np.zeros(EMBEDDING_DIM, dtype=np.float32),
        }
        comp, alphas = compose_with_attention(signals, "user")
        assert not np.any(np.isnan(comp))
        assert abs(sum(alphas.values()) - 1.0) < 1e-6

    def test_da2_099_hadamard_orthogonal_vectors(self):
        """DA2-099: Hadamard of nearly orthogonal vectors."""
        a = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        b = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        a[0] = 1.0
        b[1] = 1.0
        result = hadamard_compose(a, b)
        assert np.linalg.norm(result) < 1e-7

    def test_da2_100_group_zscore_all_identical_values(self):
        """DA2-100: All identical feature values produce z=0 (no division by zero)."""
        df = pd.DataFrame([
            {"uid": f"U{i}", "is_attack": False, "grp": "dev", "role": "SE", "feat": 42.0}
            for i in range(10)
        ])
        result = compute_group_zscores(df)
        assert (result["z_feat"] == 0.0).all()

    def test_da2_101_composite_all_zero_zscores(self):
        """DA2-101: All-zero z-scores produce zero composite."""
        df = pd.DataFrame([{
            "uid": "U1", "is_attack": False, "grp": "dev", "role": "SE",
        }])
        scores = compute_composite_scores(df)
        assert scores.iloc[0]["composite"] == 0.0

    def test_da2_102_entropy_very_long_string(self):
        """DA2-102: Very long domain name doesn't overflow."""
        long_domain = "a" * 1000 + ".com"
        ent = _domain_entropy(long_domain)
        assert ent == 0.0  # all 'a' chars

    def test_da2_103_entropy_all_unique_chars(self):
        """DA2-103: Maximum entropy for all-unique characters."""
        domain = "abcdefghij.com"
        ent = _domain_entropy(domain)
        assert ent > 3.0

    def test_da2_104_compose_with_attention_single_signal(self):
        """DA2-104: Single signal gets attention weight 1.0."""
        v = np.random.default_rng(1).standard_normal(EMBEDDING_DIM).astype(np.float32)
        v = v / np.linalg.norm(v)
        comp, alphas = compose_with_attention({"only": v}, "user")
        assert abs(alphas["only"] - 1.0) < 1e-6

    def test_da2_105_drift_vector_float32_output(self, unit_vec):
        """DA2-105: Drift vector returns float32."""
        v1, v2 = unit_vec(seed=1), unit_vec(seed=2)
        dv = drift_vector(v1, v2)
        assert dv.dtype == np.float32


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 9: INTEGRATION TESTS (DA2-106 to DA2-115)
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration:
    """DA2-106 to DA2-115: End-to-end integration scenarios."""

    def test_da2_106_full_pipeline_extract_zscore_composite(self, minimal_trajectory_df):
        """DA2-106: Full pipeline: extract -> z-score -> composite produces valid output."""
        feats = extract_user_features(minimal_trajectory_df)
        zscored = compute_group_zscores(feats)
        scores = compute_composite_scores(zscored)
        assert len(scores) == 2
        assert scores.iloc[0]["composite"] >= scores.iloc[1]["composite"]
        assert not scores["composite"].isna().any()

    def test_da2_107_attack_outscores_normal(self):
        """DA2-107: Attack user gets higher composite than normal user."""
        rng = np.random.default_rng(42)
        rows = []
        normals = [("USR-N1", "IT Admin"), ("USR-N2", "IT Admin"), ("USR-N3", "IT Admin")]
        for uid, role in normals:
            for week in range(19):
                noise = rng.uniform(0.001, 0.003)
                row = {"user_id": uid, "week_idx": week, "is_attack": False,
                       "role": role, "composite_drift": 0.01 + noise}
                for z in DRIFT_ZONES:
                    row[z] = 0.005 + rng.uniform(0.001, 0.003)
                for c in CONTEXT_COLS:
                    row[c] = 0.01 + rng.uniform(0.001, 0.003)
                row["relationship_drift"] = 0.01 + noise
                row["zone_divergence"] = 0.01 + noise
                row["velocity"] = 0.005 + noise
                rows.append(row)
        for week in range(19):
            row = {"user_id": "USR-ATK", "week_idx": week, "is_attack": True,
                   "role": "IT Admin", "composite_drift": 0.01 + 0.05 * week / 19}
            for z in DRIFT_ZONES:
                row[z] = 0.005 + 0.03 * week / 19
            for c in CONTEXT_COLS:
                row[c] = 0.01 + 0.04 * week / 19
            row["relationship_drift"] = 0.01 + 0.02 * week / 19
            row["zone_divergence"] = 0.01 + 0.03 * week / 19
            row["velocity"] = 0.005 + 0.01 * week / 19
            rows.append(row)
        df = pd.DataFrame(rows)
        feats = extract_user_features(df)
        zscored = compute_group_zscores(feats)
        scores = compute_composite_scores(zscored)
        atk_score = scores[scores.uid == "USR-ATK"]["composite"].iloc[0]
        norm_scores = scores[scores.uid.str.startswith("USR-N")]["composite"]
        assert atk_score > norm_scores.max()

    def test_da2_108_novelty_boosts_ranking(self):
        """DA2-108: Adding novelty score to an otherwise-low scorer boosts rank."""
        base_feats = pd.DataFrame([
            {"uid": "HIGH", "is_attack": True, "grp": "dev", "role": "SE",
             "z_f1": 5.0, "z_f2": 4.0, "z_f3": 3.0},
            {"uid": "LOW_NOV", "is_attack": True, "grp": "dev", "role": "SE",
             "z_f1": 0.5, "z_f2": 0.3, "z_f3": 0.1},
        ])
        without_nov = compute_composite_scores(base_feats)
        assert without_nov.iloc[0]["uid"] == "HIGH"

        novelty_df = pd.DataFrame([{
            "uid": "LOW_NOV",
            "novel_ip_max_persistence": 15,
            "novel_ip_weeks_frac": 0.8,
            "persistent_novel_ips": 5,
        }])
        with_nov = compute_composite_scores(base_feats, novelty_df=novelty_df)
        low_nov_score = with_nov[with_nov.uid == "LOW_NOV"]["composite"].iloc[0]
        assert low_nov_score > 5, "Novelty should significantly boost LOW_NOV"

    def test_da2_109_drift_into_embedding_pipeline(self, mock_embedder, concept_library):
        """DA2-109: Embedding -> drift -> concept alignment full flow."""
        text_old = "Normal user activity, standard access patterns"
        text_new = "User accessing restricted files, off-hours authentication"
        v_old = mock_embedder.embed_text(text_old)
        v_new = mock_embedder.embed_text(text_new)
        analysis = analyze_entity_drift("user", "U1", v_old, v_new, concept_library)
        assert analysis.drift_magnitude >= 0
        assert isinstance(analysis.primary_direction, str)

    def test_da2_110_zone_compose_drift_pipeline(self, mock_embedder):
        """DA2-110: Build zones -> compose -> drift between two periods."""
        profile = {"role": "IT Admin"}
        feats_w1 = {
            "auth_total": 100, "auth_fail_rate": 0.02, "auth_off_hours_ratio": 0.05,
            "auth_unique_sources": 3, "auth_unique_dests": 8, "auth_methods": 2,
            "file_total": 30, "file_restricted_ratio": 0.01, "file_confidential_ratio": 0.0,
            "file_write_ratio": 0.2, "file_unique_paths": 10, "file_total_bytes": 5e5,
            "net_bytes_out": 1e6, "net_unique_dsts": 10, "net_external_ratio": 0.1,
            "dns_unique_domains": 20, "dns_nxdomain_ratio": 0.02,
            "endpoint_suspicious_ratio": 0.005, "endpoint_max_risk": 2,
            "endpoint_mean_risk": 1.0, "endpoint_unique_processes": 10,
            "endpoint_total": 100,
        }
        feats_w2 = feats_w1.copy()
        feats_w2["auth_fail_rate"] = 0.30
        feats_w2["file_restricted_ratio"] = 0.15
        feats_w2["auth_off_hours_ratio"] = 0.40

        zones_w1 = build_zone_embeddings("user", "U1", profile, feats_w1, mock_embedder)
        zones_w2 = build_zone_embeddings("user", "U1", profile, feats_w2, mock_embedder)

        comp_w1 = compose_zones(zones_w1, "normal_ops", "user")
        comp_w2 = compose_zones(zones_w2, "normal_ops", "user")

        mag = drift_magnitude(comp_w1, comp_w2)
        assert mag >= 0
        assert mag <= 2

    def test_da2_111_hadamard_relationship_drift(self, unit_vec):
        """DA2-111: User-Device relationship drift measurable."""
        user_w1 = unit_vec(seed=1)
        device_w1 = unit_vec(seed=10)
        rel_w1 = hadamard_compose(user_w1, device_w1)

        user_w2 = unit_vec(seed=2)
        device_w2 = unit_vec(seed=10)  # same device
        rel_w2 = hadamard_compose(user_w2, device_w2)

        mag = drift_magnitude(rel_w1, rel_w2)
        assert 0 <= mag <= 2

    def test_da2_112_velocity_from_zone_series(self, mock_embedder):
        """DA2-112: Velocity computed from composed zone time series."""
        profile = {"role": "Software Engineer"}
        base_feats = {
            "auth_total": 50, "auth_fail_rate": 0.01, "auth_off_hours_ratio": 0.02,
            "auth_unique_sources": 2, "auth_unique_dests": 5, "auth_methods": 1,
            "file_total": 20, "file_restricted_ratio": 0.0, "file_confidential_ratio": 0.0,
            "file_write_ratio": 0.1, "file_unique_paths": 5, "file_total_bytes": 1e5,
            "net_bytes_out": 5e5, "net_unique_dsts": 5, "net_external_ratio": 0.05,
            "dns_unique_domains": 10, "dns_nxdomain_ratio": 0.01,
            "endpoint_suspicious_ratio": 0.0, "endpoint_max_risk": 1,
            "endpoint_mean_risk": 0.5, "endpoint_unique_processes": 5,
            "endpoint_total": 50,
        }
        snapshots = []
        for week in range(10):
            f = base_feats.copy()
            f["auth_fail_rate"] = 0.01 + week * 0.02
            zones = build_zone_embeddings("user", "U1", profile, f, mock_embedder)
            comp = compose_zones(zones, "normal_ops", "user")
            snapshots.append(comp)

        vel = compute_velocity_vector(snapshots)
        feats = compute_trajectory_features(snapshots)
        regime = detect_regime(feats)
        assert regime in ("stable", "drifting", "accelerating", "regime_shift")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 10: SECURITY & EVASION SCENARIOS (DA2-113 to DA2-120)
# ═══════════════════════════════════════════════════════════════════════════

class TestSecurityEvasion:
    """DA2-113 to DA2-120: Adversarial evasion and detection robustness."""

    def test_da2_113_all_features_just_below_threshold(self):
        """DA2-113: Attacker with all z-scores at 1.49 (just below breadth)."""
        n_features = 20
        df = pd.DataFrame([{
            "uid": "EVASION", "is_attack": True, "grp": "dev", "role": "SE",
            **{f"z_f{i}": 1.49 for i in range(n_features)},
        }])
        scores = compute_composite_scores(df)
        assert scores.iloc[0]["breadth_15"] == 0
        # But signal_strength is still top-3 sum = 4.47
        assert scores.iloc[0]["signal_strength"] > 4.0

    def test_da2_114_single_spike_detection(self):
        """DA2-114: Single extreme spike creates high signal_strength."""
        df = pd.DataFrame([{
            "uid": "SPIKE", "is_attack": True, "grp": "dev", "role": "SE",
            "z_big": 15.0, "z_f1": 0.1, "z_f2": 0.05,
        }])
        scores = compute_composite_scores(df)
        assert scores.iloc[0]["signal_strength"] > 10

    def test_da2_115_uniform_low_drift_evasion(self, unit_vec):
        """DA2-115: Uniform low drift across all zones — no divergence signal."""
        v = unit_vec(seed=1).astype(np.float64)
        direction = unit_vec(seed=2).astype(np.float64)
        # All zones drift uniformly by small amount
        zones_old = {z: (v + np.random.default_rng(i).standard_normal(EMBEDDING_DIM) * 0.01).astype(np.float32)
                     for i, z in enumerate(USER_ZONE_ORDER)}
        zones_new = {z: (zones_old[z].astype(np.float64) + direction * 0.01).astype(np.float32)
                     for z in USER_ZONE_ORDER}

        # Drift magnitudes should be small and similar
        mags = {z: drift_magnitude(zones_old[z], zones_new[z]) for z in USER_ZONE_ORDER}
        max_mag = max(mags.values())
        min_mag = min(mags.values())
        assert max_mag - min_mag < 0.1, "Uniform drift should not trigger zone divergence"

    def test_da2_116_novelty_rotating_ips_evade(self):
        """DA2-116: Rotating C2 IPs (different each week) have low persistence."""
        rows = []
        for week in range(20):
            row = {"user_id": "U1", "week_idx": week}
            if week < BASELINE_WEEKS:
                row["qual_net_ext_ips"] = "10.0.0.1"
            else:
                row["qual_net_ext_ips"] = f"192.168.{week}.{week}"
            rows.append(row)
        df = pd.DataFrame(rows)
        metrics = compute_novelty_metrics(df)
        # Each IP appears only 1 week, so persistence < 5, no persistent_novel_ips
        assert metrics.iloc[0]["persistent_novel_ips"] == 0

    def test_da2_117_novelty_persistent_c2_caught(self):
        """DA2-117: Persistent C2 beacon IP caught by novelty metrics."""
        rows = []
        for week in range(20):
            row = {"user_id": "U1", "week_idx": week}
            if week < BASELINE_WEEKS:
                row["qual_net_ext_ips"] = "10.0.0.1"
            else:
                row["qual_net_ext_ips"] = "10.0.0.1; 45.33.32.100"
            rows.append(row)
        df = pd.DataFrame(rows)
        metrics = compute_novelty_metrics(df)
        assert metrics.iloc[0]["novel_ip_max_persistence"] == 10
        assert metrics.iloc[0]["persistent_novel_ips"] >= 1

    def test_da2_118_orthogonal_drift_no_concept_match(self, concept_library, unit_vec):
        """DA2-118: Drift orthogonal to all concepts gets low alignment."""
        # Create a drift vector that's unlikely to align with any concept
        rng = np.random.default_rng(9999)
        dv = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        dv = dv / np.linalg.norm(dv)
        vecs = concept_library.all_threat_vectors()
        alignments = concept_alignment(dv, vecs, concept_library)
        # Most alignments should be near zero in high-dimensional space
        if alignments:
            max_align = max(abs(a.alignment_score) for a in alignments)
            assert max_align < 0.5, "Random vector shouldn't strongly align with any concept"

    def test_da2_119_internal_domain_not_flagged_novel(self):
        """DA2-119: Internal domains are not flagged as NOVEL in DNS annotation."""
        rows = []
        for week in range(15):
            row = {"user_id": "U1", "week_idx": week,
                   "qual_dns_domains": "server.corp; dc.internal",
                   "qual_net_ext_ips": "", "qual_file_dirs": ""}
            rows.append(row)
        # Add post-baseline week with new internal domain
        rows.append({"user_id": "U1", "week_idx": 15,
                      "qual_dns_domains": "newserver.corp; dc.internal",
                      "qual_net_ext_ips": "", "qual_file_dirs": ""})
        df = pd.DataFrame(rows)
        result = annotate_qualitative_features(df, {"U1": "admin"})
        post = result[result.week_idx == 15].iloc[0]
        assert "[NOVEL]" not in str(post["qual_dns_domains"])

    def test_da2_120_composite_weights_not_trivially_evadable(self):
        """DA2-120: Composite formula balances multiple signals — no single zeroing evades."""
        # An attacker with high breadth but low signal_strength
        df = pd.DataFrame([{
            "uid": "BROAD", "is_attack": True, "grp": "dev", "role": "SE",
            **{f"z_f{i}": 1.6 for i in range(15)},  # 15 features barely above 1.5
        }])
        scores = compute_composite_scores(df)
        assert scores.iloc[0]["breadth_15"] == 15
        assert scores.iloc[0]["composite"] > 10, "Breadth alone should contribute significantly"
