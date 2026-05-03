"""Trajectory and drift analysis API routes."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from datetime import date

from api import backend

router = APIRouter()

VALID_ENTITY_TYPES = {"user", "device", "segment", "app", "session"}


# --- Response models ---

class TrajectorySnapshot(BaseModel):
    cutoff_date: str
    drift_magnitude: float | None
    features: dict | None
    velocity: dict | None


class TrajectoryResponse(BaseModel):
    entity_type: str
    entity_id: str
    snapshots: list[TrajectorySnapshot]
    total_snapshots: int


class ConceptAlignmentResult(BaseModel):
    concept_name: str
    category: str
    alignment_score: float
    severity: str
    mitre_techniques: list[str]


class DriftAnalysisResponse(BaseModel):
    entity_type: str
    entity_id: str
    from_date: str
    to_date: str
    drift_magnitude: float
    primary_direction: str
    is_threat: bool
    confidence: float
    top_alignments: list[ConceptAlignmentResult]


class DriftPoint(BaseModel):
    cutoff_date: str
    drift_magnitude: float


class DriftSeriesResponse(BaseModel):
    entity_type: str
    entity_id: str
    series: list[DriftPoint]


class ScanResult(BaseModel):
    entity_type: str
    entity_id: str
    drift_magnitude: float
    cusum_value: float
    change_detected: bool
    change_point_idx: int | None


class ScanResponse(BaseModel):
    threshold: float
    entities_scanned: int
    entities_flagged: int
    results: list[ScanResult]


# --- Endpoints ---

@router.get("/{entity_type}/{entity_id}", response_model=TrajectoryResponse)
async def get_trajectory(
    entity_type: str,
    entity_id: str,
    start_date: date = Query(None),
    end_date: date = Query(None),
):
    """Get behavioral trajectory: monthly snapshots with drift magnitudes."""
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity_type. Must be one of: {sorted(VALID_ENTITY_TYPES)}",
        )

    entity = backend.get_entity(entity_type, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity {entity_type}:{entity_id} not found")

    snapshots = backend.get_trajectory(
        entity_type, entity_id,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
    )

    return TrajectoryResponse(
        entity_type=entity_type,
        entity_id=entity_id,
        snapshots=[TrajectorySnapshot(**s) for s in snapshots],
        total_snapshots=len(snapshots),
    )


@router.get("/{entity_type}/{entity_id}/drift", response_model=DriftAnalysisResponse)
async def get_drift_analysis(
    entity_type: str,
    entity_id: str,
    from_date: date = Query(None, description="Baseline period"),
    to_date: date = Query(None, description="Current period"),
):
    """Analyze drift direction: concept alignment, MITRE mapping."""
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity_type. Must be one of: {sorted(VALID_ENTITY_TYPES)}",
        )

    entity = backend.get_entity(entity_type, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity {entity_type}:{entity_id} not found")

    analysis = backend.get_drift_analysis(
        entity_type, entity_id,
        from_date=from_date.isoformat() if from_date else None,
        to_date=to_date.isoformat() if to_date else None,
    )
    if analysis is None:
        raise HTTPException(
            status_code=404,
            detail=f"Not enough snapshots to compute drift for {entity_type}:{entity_id}",
        )

    return DriftAnalysisResponse(
        entity_type=entity_type,
        entity_id=entity_id,
        from_date=analysis["from_date"],
        to_date=analysis["to_date"],
        drift_magnitude=analysis["drift_magnitude"],
        primary_direction=analysis["primary_direction"],
        is_threat=analysis["is_threat"],
        confidence=analysis["confidence"],
        top_alignments=[ConceptAlignmentResult(**a) for a in analysis["top_alignments"]],
    )


@router.get("/{entity_type}/{entity_id}/drift-series", response_model=DriftSeriesResponse)
async def get_drift_series(entity_type: str, entity_id: str):
    """Time series of monthly drift magnitudes (for charting)."""
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity_type. Must be one of: {sorted(VALID_ENTITY_TYPES)}",
        )

    entity = backend.get_entity(entity_type, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity {entity_type}:{entity_id} not found")

    series = backend.get_drift_series(entity_type, entity_id)

    return DriftSeriesResponse(
        entity_type=entity_type,
        entity_id=entity_id,
        series=[DriftPoint(**p) for p in series],
    )


@router.post("/scan", response_model=ScanResponse)
async def scan_all_entities(
    entity_type: str = Query(None),
    threshold: float = Query(0.15, ge=0.0, le=1.0),
):
    """Scan all entities for significant drift (batch CUSUM + threshold)."""
    if entity_type and entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity_type. Must be one of: {sorted(VALID_ENTITY_TYPES)}",
        )

    scan = backend.scan_entities(entity_type=entity_type, threshold=threshold)

    return ScanResponse(
        threshold=threshold,
        entities_scanned=scan["entities_scanned"],
        entities_flagged=scan["entities_flagged"],
        results=[ScanResult(**r) for r in scan["results"]],
    )
