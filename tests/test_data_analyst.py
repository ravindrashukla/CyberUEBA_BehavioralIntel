"""Data Analyst test suite for ACECARD Cyber UEBA system.

Validates embedding math, cohort detection, CUSUM change-point detection,
drift direction analysis, signal weights, and entity counts.
"""
import sys
import os

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from embeddings.composer import cosine_similarity, drift_magnitude, SIGNAL_WEIGHTS
from detection.cohort_analysis import CohortMember, detect_cohorts
from detection.cusum import batch_cusum_scan
from detection.drift_direction import analyze_entity_drift, batch_drift_analysis
from api.store import DemoStore, ENTITY_COUNTS


# ---------------------------------------------------------------------------
# DA-001: Drift series first entry has magnitude 0
# ---------------------------------------------------------------------------
@pytest.mark.p1
def test_drift_series_first_null():
    store = DemoStore()
    # Find a valid entity to query
    entities = store.list_entities("user")
    assert len(entities) > 0
    entity = entities[0]
    series = store.get_drift_series("user", entity["entity_id"])
    assert len(series) > 0, "Drift series should have at least one entry"
    assert series[0]["drift_magnitude"] == 0.0


# ---------------------------------------------------------------------------
# DA-002: Drift magnitude is bounded in [0, 2]
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_drift_magnitude_bounded(random_unit_vector):
    for seed in range(100):
        a = random_unit_vector(seed=seed)
        b = random_unit_vector(seed=seed + 1000)
        mag = drift_magnitude(a, b)
        assert 0.0 <= mag <= 2.0, f"drift_magnitude={mag} out of [0,2] range"


# ---------------------------------------------------------------------------
# DA-003: Cosine similarity is symmetric
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_cosine_similarity_symmetry(random_unit_vector):
    for seed in range(100):
        a = random_unit_vector(seed=seed)
        b = random_unit_vector(seed=seed + 500)
        assert np.isclose(
            cosine_similarity(a, b),
            cosine_similarity(b, a),
            atol=1e-7,
        ), f"Symmetry violated at seed={seed}"


# ---------------------------------------------------------------------------
# DA-004: Drift magnitude is symmetric
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_drift_magnitude_symmetry(random_unit_vector):
    for seed in range(100):
        a = random_unit_vector(seed=seed)
        b = random_unit_vector(seed=seed + 500)
        assert np.isclose(
            drift_magnitude(a, b),
            drift_magnitude(b, a),
            atol=1e-7,
        ), f"Symmetry violated at seed={seed}"


# ---------------------------------------------------------------------------
# DA-005: Cohort detection respects min_cluster_size
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_cohort_min_cluster_size():
    rng = np.random.default_rng(42)
    direction = rng.standard_normal(1536).astype(np.float32)
    direction /= np.linalg.norm(direction)

    members = [
        CohortMember(
            entity_type="device",
            entity_id=f"dev_{i:03d}",
            drift_magnitude=0.3,
            drift_direction=direction,
        )
        for i in range(2)
    ]
    result = detect_cohorts(members, similarity_threshold=0.5, min_cluster_size=3)
    assert len(result) == 0, "Should not form a cohort with only 2 members"


# ---------------------------------------------------------------------------
# DA-006: Cohort detection finds aligned drifts
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_cohort_finds_aligned_drifts():
    rng = np.random.default_rng(99)
    direction = rng.standard_normal(1536).astype(np.float32)
    direction /= np.linalg.norm(direction)

    members = [
        CohortMember(
            entity_type="device",
            entity_id=f"dev_{i:03d}",
            drift_magnitude=0.5,
            drift_direction=direction.copy(),
        )
        for i in range(5)
    ]
    cohorts = detect_cohorts(members, similarity_threshold=0.5, min_cluster_size=3)
    assert len(cohorts) == 1, f"Expected 1 cohort, got {len(cohorts)}"
    assert len(cohorts[0].members) == 5


# ---------------------------------------------------------------------------
# DA-007: Cohort coherence is in [0, 1]
# ---------------------------------------------------------------------------
@pytest.mark.p1
def test_cohort_coherence_range():
    rng = np.random.default_rng(77)
    direction = rng.standard_normal(1536).astype(np.float32)
    direction /= np.linalg.norm(direction)

    members = [
        CohortMember(
            entity_type="user",
            entity_id=f"user_{i:03d}",
            drift_magnitude=0.4,
            drift_direction=direction.copy(),
        )
        for i in range(5)
    ]
    cohorts = detect_cohorts(members, similarity_threshold=0.5, min_cluster_size=3)
    for cohort in cohorts:
        assert 0.0 <= cohort.coherence <= 1.0, (
            f"Coherence {cohort.coherence} outside [0,1]"
        )


# ---------------------------------------------------------------------------
# DA-008: Cohort detection ignores zero-drift entities
# ---------------------------------------------------------------------------
@pytest.mark.p1
def test_cohort_ignores_zero_drift():
    rng = np.random.default_rng(55)
    direction = rng.standard_normal(1536).astype(np.float32)
    direction /= np.linalg.norm(direction)

    members = [
        CohortMember(
            entity_type="device",
            entity_id=f"dev_{i:03d}",
            drift_magnitude=0.001,
            drift_direction=direction.copy(),
        )
        for i in range(10)
    ]
    cohorts = detect_cohorts(members, similarity_threshold=0.5, min_cluster_size=3)
    assert len(cohorts) == 0, "Should ignore entities with drift_magnitude <= 0.01"


# ---------------------------------------------------------------------------
# DA-009: batch_cusum_scan returns only detected entities
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_batch_cusum_returns_detected_only(random_unit_vector):
    # Create drifting entities: snapshots that accumulate enough drift
    rng = np.random.default_rng(42)
    entity_snapshots = {}

    # Drifting entities: each snapshot shifts noticeably from the previous
    for i in range(3):
        base = random_unit_vector(seed=i)
        snapshots = [base]
        current = base.copy()
        for _ in range(10):
            noise = rng.standard_normal(1536).astype(np.float32)
            noise /= np.linalg.norm(noise)
            current = 0.9 * current + 0.1 * noise
            current /= np.linalg.norm(current)
            snapshots.append(current.copy())
        entity_snapshots[f"drifting_{i}"] = snapshots

    # Stable entities: identical snapshots
    for i in range(3):
        base = random_unit_vector(seed=i + 100)
        # Very minor perturbation so they stay essentially the same
        snapshots = [base]
        for _ in range(10):
            tiny_noise = rng.standard_normal(1536).astype(np.float32) * 1e-6
            snap = base + tiny_noise
            snap /= np.linalg.norm(snap)
            snapshots.append(snap)
        entity_snapshots[f"stable_{i}"] = snapshots

    results = batch_cusum_scan(entity_snapshots, threshold=0.05)

    # All returned entities should have change_detected=True
    for eid, result in results.items():
        assert result.change_detected is True, (
            f"Entity '{eid}' in results but change_detected is False"
        )

    # Stable entities should NOT appear in results
    for i in range(3):
        assert f"stable_{i}" not in results, (
            f"Stable entity 'stable_{i}' should not have change detected"
        )


# ---------------------------------------------------------------------------
# DA-010: batch_drift_analysis results sorted descending
# ---------------------------------------------------------------------------
@pytest.mark.p1
def test_batch_drift_sorted_descending(random_unit_vector, concept_library):
    entity_snapshots = {}
    for i in range(5):
        v_old = random_unit_vector(seed=i)
        v_new = random_unit_vector(seed=i + 100)
        entity_snapshots[f"entity_{i}"] = (v_old, v_new)

    results = batch_drift_analysis(
        entity_snapshots,
        entity_type="user",
        concept_library=concept_library,
        min_drift_magnitude=0.0,
    )

    magnitudes = [r.drift_magnitude for r in results]
    for i in range(len(magnitudes) - 1):
        assert magnitudes[i] >= magnitudes[i + 1], (
            f"Not sorted desc at index {i}: {magnitudes[i]} < {magnitudes[i+1]}"
        )


# ---------------------------------------------------------------------------
# DA-011: batch_drift_analysis filters by min_magnitude
# ---------------------------------------------------------------------------
@pytest.mark.p1
def test_batch_drift_filters_min_magnitude(random_unit_vector, concept_library):
    entity_snapshots = {}
    # Create pairs with varying drift: some will be large, some small
    for i in range(10):
        v_old = random_unit_vector(seed=i)
        # For half, make v_new very similar (small drift)
        if i < 5:
            noise = np.random.default_rng(i + 200).standard_normal(1536).astype(np.float32) * 0.01
            v_new = v_old + noise
            v_new /= np.linalg.norm(v_new)
        else:
            v_new = random_unit_vector(seed=i + 300)
        entity_snapshots[f"entity_{i}"] = (v_old, v_new)

    results = batch_drift_analysis(
        entity_snapshots,
        entity_type="device",
        concept_library=concept_library,
        min_drift_magnitude=0.5,
    )

    for r in results:
        assert r.drift_magnitude >= 0.5, (
            f"Entity {r.entity_id} has drift {r.drift_magnitude} below 0.5 threshold"
        )


# ---------------------------------------------------------------------------
# DA-012: Drift analysis is_threat flag is a boolean
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_drift_analysis_is_threat_flag(random_unit_vector, concept_library):
    v_old = random_unit_vector(seed=0)
    v_new = random_unit_vector(seed=999)

    analysis = analyze_entity_drift(
        entity_type="device",
        entity_id="dev_test",
        v_old=v_old,
        v_new=v_new,
        concept_library=concept_library,
        alignment_threshold=0.3,
    )

    assert isinstance(analysis.is_threat, bool), (
        f"is_threat should be bool, got {type(analysis.is_threat)}"
    )
    assert analysis.drift_magnitude > 0.0, "Two random vectors should have non-zero drift"


# ---------------------------------------------------------------------------
# DA-013: Drift analysis top alignments capped at 5
# ---------------------------------------------------------------------------
@pytest.mark.p1
def test_drift_analysis_top_5_alignments(random_unit_vector, concept_library):
    v_old = random_unit_vector(seed=10)
    v_new = random_unit_vector(seed=20)

    analysis = analyze_entity_drift(
        entity_type="user",
        entity_id="user_test",
        v_old=v_old,
        v_new=v_new,
        concept_library=concept_library,
    )

    assert len(analysis.top_alignments) <= 5, (
        f"Expected at most 5 alignments, got {len(analysis.top_alignments)}"
    )


# ---------------------------------------------------------------------------
# DA-014: Signal weights sum to 1.0 for all entity types
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_signal_weights_sum_to_one_all_types():
    for entity_type, weights in SIGNAL_WEIGHTS.items():
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-10, (
            f"Weights for '{entity_type}' sum to {total}, expected 1.0"
        )


# ---------------------------------------------------------------------------
# DA-015: DemoStore entity count matches expected 190
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_demo_store_entity_count():
    expected_total = sum(ENTITY_COUNTS.values())
    assert expected_total == 190, (
        f"ENTITY_COUNTS sum is {expected_total}, expected 190"
    )

    store = DemoStore()
    entities = store.list_entities()
    assert len(entities) == 190, (
        f"DemoStore has {len(entities)} entities, expected 190"
    )
