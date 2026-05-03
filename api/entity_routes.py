"""Entity API routes."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from datetime import datetime

from api.store import get_store

router = APIRouter()

VALID_ENTITY_TYPES = {"user", "device", "segment", "app", "session"}


# --- Response models ---

class EntitySummary(BaseModel):
    entity_type: str
    entity_id: str
    name: str
    metadata: dict


class EntityDetail(BaseModel):
    entity_type: str
    entity_id: str
    name: str
    metadata: dict
    has_embeddings: bool
    computed_at: str | None


class EmbeddingInfo(BaseModel):
    signal_name: str
    dimensions: int
    norm: float


class EntityEmbeddings(BaseModel):
    entity_type: str
    entity_id: str
    signals: list[EmbeddingInfo]
    composite_norm: float
    computed_at: str | None


class SimilarEntity(BaseModel):
    entity_type: str
    entity_id: str
    name: str
    similarity: float


class EntityStats(BaseModel):
    entity_type: str
    count: int
    with_embeddings: int


# --- Endpoints ---

@router.get("/", response_model=list[EntitySummary])
async def list_entities(
    entity_type: str = Query(None, description="Filter: user, device, segment, app"),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
):
    """List entities with optional filtering."""
    if entity_type and entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity_type. Must be one of: {sorted(VALID_ENTITY_TYPES)}",
        )

    store = get_store()
    entities = store.list_entities(entity_type=entity_type)

    # Paginate
    page = entities[offset : offset + limit]
    return [
        EntitySummary(
            entity_type=e["entity_type"],
            entity_id=e["entity_id"],
            name=e["name"],
            metadata=e.get("metadata", {}),
        )
        for e in page
    ]


@router.get("/stats", response_model=list[EntityStats])
async def entity_stats():
    """Summary counts by entity type."""
    store = get_store()
    stats = store.entity_stats()
    return [EntityStats(**s) for s in stats]


@router.get("/{entity_type}/{entity_id}", response_model=EntityDetail)
async def get_entity(entity_type: str, entity_id: str):
    """Get single entity details including current behavioral embedding."""
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity_type. Must be one of: {sorted(VALID_ENTITY_TYPES)}",
        )

    store = get_store()
    entity = store.get_entity(entity_type, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity {entity_type}:{entity_id} not found")

    return EntityDetail(
        entity_type=entity["entity_type"],
        entity_id=entity["entity_id"],
        name=entity["name"],
        metadata=entity.get("metadata", {}),
        has_embeddings=entity.get("has_embeddings", False),
        computed_at=entity.get("computed_at"),
    )


@router.get("/{entity_type}/{entity_id}/embeddings", response_model=EntityEmbeddings)
async def get_entity_embeddings(entity_type: str, entity_id: str):
    """Get current 5 signal embeddings + composite for an entity."""
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity_type. Must be one of: {sorted(VALID_ENTITY_TYPES)}",
        )

    store = get_store()
    embeddings = store.get_entity_embeddings(entity_type, entity_id)
    if embeddings is None:
        raise HTTPException(
            status_code=404,
            detail=f"No embeddings found for {entity_type}:{entity_id}",
        )

    return EntityEmbeddings(**embeddings)


@router.get("/{entity_type}/{entity_id}/similar", response_model=list[SimilarEntity])
async def find_similar_entities(
    entity_type: str,
    entity_id: str,
    top_k: int = Query(10, le=50),
):
    """Find entities with similar behavioral profiles (cosine similarity on composite)."""
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity_type. Must be one of: {sorted(VALID_ENTITY_TYPES)}",
        )

    store = get_store()
    entity = store.get_entity(entity_type, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity {entity_type}:{entity_id} not found")

    similar = store.find_similar(entity_type, entity_id, top_k=top_k)
    return [SimilarEntity(**s) for s in similar]
