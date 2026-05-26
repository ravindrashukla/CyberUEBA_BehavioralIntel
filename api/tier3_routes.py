"""Tier 3 Digital Entity detection API routes."""
from fastapi import APIRouter, HTTPException, Query

from api import backend

router = APIRouter()


@router.get("/summary")
async def tier3_summary():
    """Three-tier detection summary: methods, detection rates, FP rates."""
    return backend.get_tier3_summary()


@router.get("/comparison")
async def tier3_comparison(
    attacks_only: bool = Query(False, description="Return only attack entities"),
    detected_only: bool = Query(False, description="Return only entities detected by any tier"),
):
    """Full three-tier comparison table for all entities."""
    results = backend.get_tier3_comparison()
    if attacks_only:
        results = [r for r in results if r.get("is_attack")]
    if detected_only:
        results = [r for r in results if r.get("all_tiers_combined") or r.get("t3_combined_detected") or r.get("combined_detected")]
    return results


@router.get("/entity/{user_id}")
async def tier3_entity(user_id: str):
    """Tier 3 detail for a single entity: zones, phase state, relationships."""
    entity = backend.get_tier3_entity(user_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity {user_id} not found in Tier 3 results")
    return entity
