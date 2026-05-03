"""Detection and alerting API routes."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api import backend

router = APIRouter()


# --- Response models ---

class ConceptAlignmentInfo(BaseModel):
    concept: str
    similarity: float
    category: str
    severity: str
    mitre_techniques: list[str]


class AlertSummary(BaseModel):
    id: str
    timestamp: str
    entity_type: str
    entity_id: str
    severity: str
    title: str
    detection_method: str
    drift_magnitude: float
    status: str


class AlertDetail(BaseModel):
    id: str
    timestamp: str
    entity_type: str
    entity_id: str
    severity: str
    title: str
    description: str
    detection_method: str
    drift_magnitude: float
    concept_alignments: list[ConceptAlignmentInfo]
    mitre_techniques: list[str]
    confidence: float
    status: str
    kill_chain_id: str | None
    related_entities: list[str]


class AlertStatusUpdate(BaseModel):
    id: str
    status: str
    updated: bool


class KillChainEventInfo(BaseModel):
    alert_id: str
    entity_type: str
    entity_id: str
    timestamp: str
    tactic: str
    techniques: list[str]
    description: str
    confidence: float


class KillChainSummary(BaseModel):
    id: str
    created_at: str
    status: str
    severity: str
    duration_seconds: float
    tactics_observed: list[str]
    entities_involved: list[str]
    event_count: int


class KillChainDetail(BaseModel):
    id: str
    created_at: str
    status: str
    severity: str
    duration_seconds: float
    tactics_observed: list[str]
    entities_involved: list[str]
    events: list[KillChainEventInfo]


class ConceptInfo(BaseModel):
    name: str
    category: str
    description: str
    mitre_techniques: list[str]
    severity: str


class DashboardSummary(BaseModel):
    entity_counts: dict[str, int]
    alerts_by_severity: dict[str, int]
    active_kill_chains: int
    recent_drift_events: int
    top_threats: list[dict]


VALID_STATUSES = {"new", "investigating", "confirmed", "false_positive", "resolved"}


# --- Endpoints ---

@router.get("/alerts", response_model=list[AlertSummary])
async def list_alerts(
    severity: str = Query(None, description="Filter: critical, high, medium, low"),
    entity_type: str = Query(None),
    status: str = Query(None),
    limit: int = Query(50, le=200),
):
    """List alerts with filtering."""
    alerts = backend.get_alerts(
        severity=severity,
        entity_type=entity_type,
        status=status,
        limit=limit,
    )
    return [AlertSummary(**a) for a in alerts]


@router.get("/alerts/{alert_id}", response_model=AlertDetail)
async def get_alert(alert_id: str):
    """Get alert details including concept alignments and MITRE mapping."""
    alert = backend.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return AlertDetail(**alert)


@router.patch("/alerts/{alert_id}/status", response_model=AlertStatusUpdate)
async def update_alert_status(alert_id: str, status: str = Query(...)):
    """Update alert status (investigating, confirmed, false_positive, resolved)."""
    if status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {sorted(VALID_STATUSES)}",
        )

    updated = backend.update_alert_status(alert_id, status)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    return AlertStatusUpdate(id=alert_id, status=status, updated=True)


@router.get("/kill-chains", response_model=list[KillChainSummary])
async def list_kill_chains(status: str = Query(None)):
    """List reconstructed attack kill-chains."""
    chains = backend.get_kill_chains(status=status)
    return [KillChainSummary(**c) for c in chains]


@router.get("/kill-chains/{chain_id}", response_model=KillChainDetail)
async def get_kill_chain(chain_id: str):
    """Get kill-chain details with event timeline and MITRE tactic progression."""
    chain = backend.get_kill_chain(chain_id)
    if chain is None:
        raise HTTPException(status_code=404, detail=f"Kill-chain {chain_id} not found")
    return KillChainDetail(**chain)


@router.get("/concepts", response_model=list[ConceptInfo])
async def list_concepts():
    """List all reference concepts with their descriptions and MITRE mappings."""
    concepts = backend.get_concepts()
    return [ConceptInfo(**c) for c in concepts]


@router.get("/dashboard", response_model=DashboardSummary)
async def dashboard_summary():
    """Dashboard aggregate: entity counts, active alerts by severity, active kill-chains, recent drift events."""
    return DashboardSummary(**backend.get_dashboard())
