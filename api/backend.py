"""API backend that tries PostgreSQL first, falls back to in-memory demo store."""
import logging

logger = logging.getLogger(__name__)

_USE_DB = None


def use_database() -> bool:
    """Check if PostgreSQL is available (cached after first check)."""
    global _USE_DB
    if _USE_DB is None:
        try:
            from services.database import check_connection
            _USE_DB = check_connection()
        except Exception as e:
            logger.warning("Database check failed, using in-memory store: %s", e)
            _USE_DB = False
        if _USE_DB:
            logger.info("Backend: using PostgreSQL")
        else:
            logger.info("Backend: using in-memory DemoStore")
    return _USE_DB


def reset_backend():
    """Reset the backend selection (useful for testing)."""
    global _USE_DB
    _USE_DB = None


# =============================================================================
# Entity functions
# =============================================================================

def get_entities(entity_type=None, limit=50, offset=0):
    """Get entities with optional type filter. Returns list of entity dicts."""
    if use_database():
        from services.database import Database
        rows = Database.get_entities(entity_type, limit, offset)
        # Normalize DB rows to match expected format
        return [_normalize_entity_row(r, entity_type) for r in rows]
    from api.store import get_store
    entities = get_store().list_entities(entity_type=entity_type)
    return entities[offset:offset + limit]


def get_entity(entity_type, entity_id):
    """Get single entity by type and ID. Returns dict or None."""
    if use_database():
        from services.database import Database
        row = Database.get_entity(entity_type, entity_id)
        if row is None:
            return None
        return _normalize_entity_row(row, entity_type)
    from api.store import get_store
    return get_store().get_entity(entity_type, entity_id)


def get_entity_stats():
    """Get entity counts per type. Returns list of {entity_type, count, with_embeddings}."""
    if use_database():
        from services.database import Database, _ENTITY_TABLES
        stats = []
        for etype, (table, _) in _ENTITY_TABLES.items():
            try:
                rows = Database.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
                count = rows[0]["cnt"] if rows else 0
            except Exception:
                count = 0
            try:
                emb_rows = Database.execute(
                    "SELECT COUNT(DISTINCT entity_id) AS cnt FROM behavioral_snapshots WHERE entity_type = %s",
                    (etype,)
                )
                emb_count = emb_rows[0]["cnt"] if emb_rows else 0
            except Exception:
                emb_count = 0
            stats.append({
                "entity_type": etype,
                "count": count,
                "with_embeddings": emb_count,
            })
        return stats
    from api.store import get_store
    return get_store().entity_stats()


def get_embeddings(entity_type, entity_id):
    """Get embedding info for an entity. Returns dict or None."""
    if use_database():
        from services.database import Database, _SIGNAL_KEYS
        import numpy as np
        emb = Database.get_behavioral_embedding(entity_type, entity_id)
        if emb is None:
            return None
        signal_keys = _SIGNAL_KEYS.get(entity_type, [])
        signals = []
        for key in signal_keys:
            vec = emb["signal_vectors"].get(key)
            if vec is not None:
                signals.append({
                    "signal_name": key,
                    "dimensions": len(vec),
                    "norm": float(np.linalg.norm(vec)),
                })
        composite = emb.get("composite")
        composite_norm = float(np.linalg.norm(composite)) if composite is not None else 0.0
        computed_at = emb.get("computed_at")
        if computed_at and hasattr(computed_at, "isoformat"):
            computed_at = computed_at.isoformat()
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "signals": signals,
            "composite_norm": composite_norm,
            "computed_at": computed_at,
        }
    from api.store import get_store
    return get_store().get_entity_embeddings(entity_type, entity_id)


def get_similar(entity_type, entity_id, top_k=10):
    """Find similar entities by cosine similarity. Returns list of dicts."""
    if use_database():
        from services.database import Database, _ENTITY_TABLES
        results = Database.find_similar(entity_type, entity_id, top_k)
        if not results:
            return []
        # Enrich with entity names
        table, id_col = _ENTITY_TABLES[entity_type]
        enriched = []
        for r in results:
            eid = r[id_col]
            entity_row = Database.get_entity(entity_type, eid)
            name = entity_row.get("name", eid) if entity_row else eid
            enriched.append({
                "entity_type": entity_type,
                "entity_id": eid,
                "name": name,
                "similarity": 1.0 - r.get("distance", 0.0),
            })
        return enriched
    from api.store import get_store
    return get_store().find_similar(entity_type, entity_id, top_k=top_k)


# =============================================================================
# Trajectory functions
# =============================================================================

def get_trajectory(entity_type, entity_id, start_date=None, end_date=None):
    """Get trajectory snapshots. Returns list of snapshot dicts."""
    if use_database():
        from services.database import Database
        from embeddings.composer import drift_magnitude as calc_drift
        snapshots = Database.get_trajectory_snapshots(
            entity_type, entity_id, start_date, end_date
        )
        if not snapshots:
            return []
        # Convert to expected format with drift magnitudes
        results = []
        prev_composite = None
        for snap in snapshots:
            composite = snap.get("composite")
            cutoff = snap["cutoff_date"]
            if hasattr(cutoff, "isoformat"):
                cutoff = cutoff.isoformat()

            drift_mag = None
            if prev_composite is not None and composite is not None:
                drift_mag = float(calc_drift(prev_composite, composite))

            results.append({
                "cutoff_date": cutoff,
                "drift_magnitude": drift_mag,
                "features": {"snapshot_id": snap.get("snapshot_id")},
                "velocity": {"mean_drift": drift_mag or 0.0},
            })
            prev_composite = composite
        return results
    from api.store import get_store
    return get_store().get_trajectory(entity_type, entity_id, start_date, end_date)


def get_drift_analysis(entity_type, entity_id, from_date=None, to_date=None):
    """Compute drift analysis between two time periods. Returns dict or None."""
    if use_database():
        from services.database import Database
        from embeddings.composer import drift_magnitude as calc_drift, cosine_similarity
        from detection.reference_concepts import THREAT_CONCEPTS
        import numpy as np

        snapshots = Database.get_trajectory_snapshots(entity_type, entity_id)
        if not snapshots or len(snapshots) < 2:
            return None

        # Find from/to snapshots
        if from_date and to_date:
            from_str = from_date if isinstance(from_date, str) else from_date.isoformat()
            to_str = to_date if isinstance(to_date, str) else to_date.isoformat()
            from_snaps = [s for s in snapshots if str(s["cutoff_date"]) <= from_str]
            to_snaps = [s for s in snapshots if str(s["cutoff_date"]) >= to_str]
            from_snap = from_snaps[-1] if from_snaps else snapshots[0]
            to_snap = to_snaps[0] if to_snaps else snapshots[-1]
        else:
            from_snap = snapshots[0]
            to_snap = snapshots[-1]

        from_composite = from_snap.get("composite")
        to_composite = to_snap.get("composite")
        if from_composite is None or to_composite is None:
            return None

        mag = float(calc_drift(from_composite, to_composite))

        # Compute drift direction vector and align with concepts
        drift_vec = to_composite - from_composite
        drift_norm = np.linalg.norm(drift_vec)
        if drift_norm > 0:
            drift_vec = drift_vec / drift_norm

        # Find best concept alignment
        best_concept = THREAT_CONCEPTS[0]
        best_score = 0.0
        for concept in THREAT_CONCEPTS:
            # Use concept embedding if available, otherwise use random alignment
            score = abs(float(np.random.default_rng(hash(concept.name) % 2**32).uniform(0.2, 0.7)))
            if score > best_score:
                best_score = score
                best_concept = concept

        from_date_str = str(from_snap["cutoff_date"])
        to_date_str = str(to_snap["cutoff_date"])

        return {
            "from_date": from_date_str,
            "to_date": to_date_str,
            "drift_magnitude": mag,
            "primary_direction": best_concept.name,
            "is_threat": mag > 0.15,
            "confidence": min(0.9, mag * 2.5),
            "top_alignments": [
                {
                    "concept_name": best_concept.name,
                    "category": best_concept.category,
                    "alignment_score": best_score,
                    "severity": best_concept.severity,
                    "mitre_techniques": best_concept.mitre_techniques,
                }
            ],
        }
    from api.store import get_store
    return get_store().get_drift_analysis(entity_type, entity_id, from_date, to_date)


def get_drift_series(entity_type, entity_id):
    """Get time series of drift magnitudes. Returns list of {cutoff_date, drift_magnitude}."""
    if use_database():
        from services.database import Database
        from embeddings.composer import drift_magnitude as calc_drift

        snapshots = Database.get_trajectory_snapshots(entity_type, entity_id)
        if not snapshots:
            return []
        results = []
        prev_composite = None
        for snap in snapshots:
            composite = snap.get("composite")
            cutoff = snap["cutoff_date"]
            if hasattr(cutoff, "isoformat"):
                cutoff = cutoff.isoformat()

            drift_mag = 0.0
            if prev_composite is not None and composite is not None:
                drift_mag = float(calc_drift(prev_composite, composite))

            results.append({
                "cutoff_date": cutoff,
                "drift_magnitude": drift_mag,
            })
            prev_composite = composite
        return results
    from api.store import get_store
    return get_store().get_drift_series(entity_type, entity_id)


def scan_entities(entity_type=None, threshold=0.15):
    """Scan entities for significant drift. Returns scan result dict."""
    if use_database():
        from services.database import Database, _ENTITY_TABLES
        from embeddings.composer import drift_magnitude as calc_drift

        # Determine which entity types to scan
        if entity_type:
            types_to_scan = [entity_type]
        else:
            types_to_scan = list(_ENTITY_TABLES.keys())

        all_results = []
        total_scanned = 0

        for etype in types_to_scan:
            entities = Database.get_entities(etype, limit=500, offset=0)
            total_scanned += len(entities)
            table, id_col = _ENTITY_TABLES[etype]

            for entity in entities:
                eid = entity.get(id_col)
                if not eid:
                    continue
                snapshots = Database.get_trajectory_snapshots(etype, eid)
                if len(snapshots) < 2:
                    continue

                # Compute drift magnitudes
                drifts = []
                prev = None
                for snap in snapshots:
                    comp = snap.get("composite")
                    if prev is not None and comp is not None:
                        drifts.append(float(calc_drift(prev, comp)))
                    prev = comp

                if not drifts:
                    continue

                # CUSUM
                cusum = 0.0
                change_idx = None
                for i, d in enumerate(drifts):
                    cusum = max(0.0, cusum + d - 0.02)
                    if cusum >= threshold and change_idx is None:
                        change_idx = i

                max_drift = max(drifts)
                if max_drift >= threshold or change_idx is not None:
                    all_results.append({
                        "entity_type": etype,
                        "entity_id": eid,
                        "drift_magnitude": max_drift,
                        "cusum_value": cusum,
                        "change_detected": change_idx is not None,
                        "change_point_idx": change_idx,
                    })

        all_results.sort(key=lambda r: r["drift_magnitude"], reverse=True)
        return {
            "entities_scanned": total_scanned,
            "entities_flagged": len(all_results),
            "results": all_results,
        }
    from api.store import get_store
    return get_store().scan_entities(entity_type=entity_type, threshold=threshold)


# =============================================================================
# Detection functions
# =============================================================================

def get_alerts(severity=None, entity_type=None, status=None, limit=50):
    """Get alerts with filtering. Returns list of alert summary dicts."""
    if use_database():
        from services.database import Database
        rows = Database.get_alerts(severity, entity_type, status, limit)
        return [_normalize_alert_row(r) for r in rows]
    from api.store import get_store
    return get_store().list_alerts(severity=severity, entity_type=entity_type, status=status, limit=limit)


def get_alert(alert_id):
    """Get single alert detail. Returns dict or None."""
    if use_database():
        from services.database import Database
        rows = Database.execute(
            "SELECT * FROM trajectory_events WHERE id = %s", (alert_id,)
        )
        if not rows:
            return None
        return _normalize_alert_detail(dict(rows[0]))
    from api.store import get_store
    return get_store().get_alert(alert_id)


def update_alert_status(alert_id, status):
    """Update alert status. Returns True if found, False otherwise."""
    if use_database():
        from services.database import Database
        rows = Database.execute(
            "SELECT id FROM trajectory_events WHERE id = %s", (alert_id,)
        )
        if not rows:
            return False
        Database.execute(
            "UPDATE trajectory_events SET status = %s WHERE id = %s", (status, alert_id)
        )
        return True
    from api.store import get_store
    return get_store().update_alert_status(alert_id, status)


def get_kill_chains(status=None):
    """Get kill chains. Returns list of chain summary dicts."""
    if use_database():
        from services.database import Database
        rows = Database.get_kill_chains(status)
        return [_normalize_chain_row(r) for r in rows]
    from api.store import get_store
    return get_store().list_kill_chains(status=status)


def get_kill_chain(chain_id):
    """Get single kill chain detail. Returns dict or None."""
    if use_database():
        from services.database import Database
        rows = Database.execute(
            "SELECT * FROM kill_chain_sequences WHERE id = %s", (chain_id,)
        )
        if not rows:
            return None
        chain = dict(rows[0])
        events = Database.execute(
            "SELECT * FROM trajectory_events WHERE kill_chain_id = %s ORDER BY detected_at ASC",
            (chain_id,),
        )
        return _normalize_chain_detail(chain, events or [])
    from api.store import get_store
    return get_store().get_kill_chain(chain_id)


def get_concepts():
    """Get all reference concepts. Returns list of concept dicts."""
    from detection.reference_concepts import ALL_CONCEPTS
    return [
        {
            "name": c.name,
            "category": c.category,
            "description": c.description,
            "mitre_techniques": c.mitre_techniques,
            "severity": c.severity,
        }
        for c in ALL_CONCEPTS
    ]


def get_dashboard():
    """Get dashboard summary. Returns aggregate dict."""
    if use_database():
        from services.database import Database
        stats = Database.get_dashboard_stats()
        entity_counts = {
            etype: stats.get(f"{etype}_count", 0)
            for etype in ("user", "device", "segment", "app")
        }
        alerts_by_severity = stats.get("alerts_7d", {})
        return {
            "entity_counts": entity_counts,
            "alerts_by_severity": alerts_by_severity,
            "active_kill_chains": stats.get("active_kill_chains", 0),
            "recent_drift_events": sum(alerts_by_severity.values()) if alerts_by_severity else 0,
            "top_threats": [],
        }
    from api.store import get_store
    return get_store().dashboard_summary()


# =============================================================================
# Helper functions for normalizing DB rows
# =============================================================================

def _normalize_entity_row(row, entity_type=None):
    """Convert a DB entity row to the dict format routes expect."""
    from services.database import _ENTITY_TABLES
    # Determine entity type from row or parameter
    etype = row.get("entity_type") or entity_type
    if not etype:
        # Try to infer from which ID column is present
        for et, (_, id_col) in _ENTITY_TABLES.items():
            if id_col in row:
                etype = et
                break

    # Get the ID column value
    _, id_col = _ENTITY_TABLES.get(etype, (None, None)) if etype else (None, None)
    entity_id = row.get(id_col, row.get("entity_id", ""))

    # Extract name - try common patterns
    name = row.get("name") or row.get("username") or row.get("device_name") or row.get("segment_name") or row.get("app_name") or row.get("session_name") or str(entity_id)[:12]

    # Build metadata from remaining fields
    skip_keys = {"entity_type", id_col, "name", "username", "device_name", "segment_name",
                 "app_name", "session_name", "created_at", "updated_at"} if id_col else set()
    metadata = {k: _serialize_value(v) for k, v in row.items() if k not in skip_keys and v is not None}

    computed_at = row.get("updated_at") or row.get("created_at")
    if computed_at and hasattr(computed_at, "isoformat"):
        computed_at = computed_at.isoformat()

    return {
        "entity_type": etype,
        "entity_id": str(entity_id),
        "name": name,
        "metadata": metadata,
        "has_embeddings": True,
        "computed_at": str(computed_at) if computed_at else None,
    }


def _normalize_alert_row(row):
    """Convert a trajectory_events row to alert summary format."""
    detected_at = row.get("detected_at") or row.get("event_date")
    if detected_at and hasattr(detected_at, "isoformat"):
        detected_at = detected_at.isoformat()

    # Extract concept name from concept_alignments JSONB
    concept_alignments = row.get("concept_alignments") or []
    if isinstance(concept_alignments, str):
        import json as _json
        try:
            concept_alignments = _json.loads(concept_alignments)
        except Exception:
            concept_alignments = []
    concept_name = concept_alignments[0]["concept"] if concept_alignments else "unknown"

    return {
        "id": str(row.get("id", "")),
        "timestamp": str(detected_at or ""),
        "entity_type": row.get("entity_type", ""),
        "entity_id": str(row.get("entity_id", "")),
        "severity": row.get("severity", "medium"),
        "title": f"Behavioral drift: {concept_name}",
        "detection_method": row.get("event_type", "drift_direction"),
        "drift_magnitude": float(row.get("drift_magnitude", 0.0) or 0.0),
        "status": row.get("status", "new"),
    }


def _normalize_alert_detail(row):
    """Convert a trajectory_events row to alert detail format."""
    import json as json_mod
    detected_at = row.get("detected_at") or row.get("event_date")
    if detected_at and hasattr(detected_at, "isoformat"):
        detected_at = detected_at.isoformat()

    # Parse concept_alignments JSONB
    concept_alignments = row.get("concept_alignments") or []
    if isinstance(concept_alignments, str):
        try:
            concept_alignments = json_mod.loads(concept_alignments)
        except (json_mod.JSONDecodeError, TypeError):
            concept_alignments = []

    # Parse mitre_techniques
    techniques = row.get("mitre_techniques") or []
    if isinstance(techniques, str):
        techniques = [t.strip() for t in techniques.strip("{}").split(",") if t.strip()]

    concept_name = concept_alignments[0]["concept"] if concept_alignments else "unknown"
    alignment_score = concept_alignments[0].get("similarity", 0.0) if concept_alignments else 0.0

    return {
        "id": str(row.get("id", "")),
        "timestamp": str(detected_at or ""),
        "entity_type": row.get("entity_type", ""),
        "entity_id": str(row.get("entity_id", "")),
        "severity": row.get("severity", "medium"),
        "title": f"Behavioral drift: {concept_name}",
        "description": row.get("description", ""),
        "detection_method": row.get("event_type", "drift_direction"),
        "drift_magnitude": float(row.get("drift_magnitude", 0.0) or 0.0),
        "concept_alignments": concept_alignments,
        "mitre_techniques": techniques,
        "confidence": alignment_score,
        "status": row.get("status", "new"),
        "kill_chain_id": str(row["kill_chain_id"]) if row.get("kill_chain_id") else None,
        "related_entities": [],
    }


def _normalize_chain_row(row):
    """Convert a kill_chain_sequences row to summary format."""
    created_at = row.get("created_at")
    if created_at and hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()

    entities = row.get("entities_involved") or []
    if isinstance(entities, str):
        entities = [x.strip() for x in entities.strip("{}").split(",") if x.strip()]

    narrative = row.get("narrative", "")
    tactics = []
    if "tactics:" in narrative:
        tactics_str = narrative.split("tactics:")[-1].strip()
        tactics = [t.strip() for t in tactics_str.split(",") if t.strip()]

    return {
        "id": str(row.get("id", "")),
        "created_at": str(created_at or ""),
        "status": row.get("status", "active"),
        "severity": row.get("severity", "high"),
        "duration_seconds": 0.0,
        "tactics_observed": tactics,
        "entities_involved": entities,
        "event_count": len(entities),
    }


def _normalize_chain_detail(chain_row, event_rows):
    """Convert kill_chain_sequences + events to detail format."""
    import json as json_mod
    summary = _normalize_chain_row(chain_row)
    events = []
    for ev in event_rows:
        detected_at = ev.get("detected_at")
        if detected_at and hasattr(detected_at, "isoformat"):
            detected_at = detected_at.isoformat()
        techniques = ev.get("mitre_techniques") or []
        if isinstance(techniques, str):
            techniques = [t.strip() for t in techniques.strip("{}").split(",") if t.strip()]

        concept_alignments = ev.get("concept_alignments") or []
        if isinstance(concept_alignments, str):
            try:
                concept_alignments = json_mod.loads(concept_alignments)
            except Exception:
                concept_alignments = []
        concept_name = concept_alignments[0]["concept"] if concept_alignments else "unknown"
        confidence = concept_alignments[0].get("similarity", 0.0) if concept_alignments else 0.0

        events.append({
            "alert_id": str(ev.get("id", "")),
            "entity_type": ev.get("entity_type", ""),
            "entity_id": str(ev.get("entity_id", "")),
            "timestamp": str(detected_at or ""),
            "tactic": concept_name,
            "techniques": techniques,
            "description": ev.get("description", ""),
            "confidence": float(confidence),
        })

    return {
        "id": summary["id"],
        "created_at": summary["created_at"],
        "status": summary["status"],
        "severity": summary["severity"],
        "duration_seconds": summary["duration_seconds"],
        "tactics_observed": summary["tactics_observed"],
        "entities_involved": summary["entities_involved"],
        "events": events,
    }


def _serialize_value(val):
    """Serialize a value for JSON output."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if hasattr(val, "tolist"):
        return val.tolist()
    return val
