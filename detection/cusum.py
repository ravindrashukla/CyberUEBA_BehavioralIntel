"""CUSUM change-point detection for behavioral drift sequences.

Cumulative Sum (CUSUM) detects slow, sustained drift that individual-period
thresholds would miss. A slow APT drifting 0.02/month for 6 months triggers
CUSUM even though no single month crosses the 0.15 alert threshold.
"""
import numpy as np
from dataclasses import dataclass

from embeddings.composer import drift_magnitude

__all__ = [
    "CUSUMResult",
    "cusum_detect",
    "cusum_scan_entity",
    "batch_cusum_scan",
]


@dataclass
class CUSUMResult:
    change_detected: bool
    change_point_idx: int | None  # index where change was detected
    cumulative_sum: float  # current CUSUM value
    threshold: float  # detection threshold used
    run_length: int  # consecutive periods above threshold


def cusum_detect(
    drift_magnitudes: np.ndarray,
    threshold: float = 0.05,
    drift_threshold: float = 0.02,
    min_run_length: int = 2,
) -> CUSUMResult:
    """Detect sustained drift using one-sided CUSUM.

    The key insight: individual drift magnitudes may be small (below alert threshold),
    but CUSUM accumulates them. A slow APT that drifts 0.02/month for 6 months
    triggers CUSUM even though no single month crosses the 0.15 alert threshold.

    Args:
        drift_magnitudes: array of per-period cosine distances (monthly drift)
        threshold: CUSUM detection threshold (cumulative sum that triggers)
        drift_threshold: baseline drift allowance (subtracted each period)
        min_run_length: minimum consecutive periods above threshold for detection

    Returns:
        CUSUMResult with detection status and diagnostics
    """
    if len(drift_magnitudes) == 0:
        return CUSUMResult(
            change_detected=False,
            change_point_idx=None,
            cumulative_sum=0.0,
            threshold=threshold,
            run_length=0,
        )

    cusum = 0.0
    run_length = 0
    change_point_idx = None

    for i, mag in enumerate(drift_magnitudes):
        # Accumulate: add excess drift, floor at zero
        cusum = max(0.0, cusum + mag - drift_threshold)

        if cusum >= threshold:
            run_length += 1
            if run_length >= min_run_length and change_point_idx is None:
                # Change detected — report where the run started
                change_point_idx = i - run_length + 1
        else:
            run_length = 0

    change_detected = change_point_idx is not None

    return CUSUMResult(
        change_detected=change_detected,
        change_point_idx=change_point_idx,
        cumulative_sum=float(cusum),
        threshold=threshold,
        run_length=run_length,
    )


def cusum_scan_entity(
    snapshots: list[np.ndarray],
    threshold: float = 0.05,
    drift_threshold: float = 0.02,
) -> CUSUMResult:
    """Run CUSUM on a sequence of behavioral snapshots (1536-d vectors).

    Computes cosine distance between consecutive snapshots, then runs CUSUM.

    Args:
        snapshots: ordered list of embedding vectors (earliest first)
        threshold: CUSUM detection threshold
        drift_threshold: baseline drift allowance per period

    Returns:
        CUSUMResult from the computed drift magnitude series
    """
    if len(snapshots) < 2:
        return CUSUMResult(
            change_detected=False,
            change_point_idx=None,
            cumulative_sum=0.0,
            threshold=threshold,
            run_length=0,
        )

    magnitudes = np.array([
        drift_magnitude(snapshots[i], snapshots[i + 1])
        for i in range(len(snapshots) - 1)
    ])

    return cusum_detect(magnitudes, threshold=threshold, drift_threshold=drift_threshold)


def batch_cusum_scan(
    entity_snapshots: dict[str, list[np.ndarray]],
    threshold: float = 0.05,
) -> dict[str, CUSUMResult]:
    """Scan multiple entities, return those with change detections.

    Args:
        entity_snapshots: mapping of entity_id -> list of temporal snapshots
        threshold: CUSUM detection threshold

    Returns:
        dict of entity_id -> CUSUMResult for entities where change was detected
    """
    results = {}
    for entity_id, snapshots in entity_snapshots.items():
        result = cusum_scan_entity(snapshots, threshold=threshold)
        if result.change_detected:
            results[entity_id] = result
    return results
