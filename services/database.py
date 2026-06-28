"""Database connection management and query helpers."""
import json
import logging
import os
from contextlib import contextmanager

import numpy as np
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, execute_values

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://cyber_ueba:password@localhost:5433/cyber_ueba"
)

# Mapping from entity_type to embedding table and ID column
_EMBEDDING_TABLES = {
    "user": ("user_behavioral_embeddings", "user_id"),
    "device": ("device_behavioral_embeddings", "device_id"),
    "segment": ("segment_behavioral_embeddings", "segment_id"),
    "app": ("app_behavioral_embeddings", "app_id"),
    "session": ("session_behavioral_embeddings", "session_id"),
}

# Mapping from entity_type to the 5 signal columns (order matters)
_SIGNAL_COLUMNS = {
    "user": [
        "beh_authentication", "beh_privilege", "beh_data_access",
        "beh_network", "beh_communication",
    ],
    "device": [
        "beh_process", "beh_network_traffic", "beh_resource",
        "beh_authentication", "beh_configuration",
    ],
    "segment": [
        "beh_traffic_volume", "beh_connections", "beh_protocols",
        "beh_threat_indicators", "beh_service_exposure",
    ],
    "app": [
        "beh_access_patterns", "beh_query_behavior", "beh_error_rates",
        "beh_performance", "beh_configuration",
    ],
    "session": [
        "beh_activity", "beh_risk_accum", "beh_data_movement",
        "beh_lateral", "beh_temporal",
    ],
}

# Signal key names corresponding to each column position (for dict I/O)
_SIGNAL_KEYS = {
    "user": ["auth", "privilege", "data_access", "network", "communication"],
    "device": ["process", "traffic", "resource", "auth", "config"],
    "segment": ["volume", "connections", "protocols", "threats", "exposure"],
    "app": ["access", "queries", "errors", "performance", "config"],
    "session": ["activity", "risk_accum", "data_movement", "lateral", "temporal"],
}

# Entity base tables
_ENTITY_TABLES = {
    "user": ("users", "user_id"),
    "device": ("devices", "device_id"),
    "segment": ("network_segments", "segment_id"),
    "app": ("applications", "app_id"),
}


def _vector_to_literal(v: np.ndarray) -> str:
    """Convert numpy vector to pgvector literal string '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.8f}" for x in v.tolist()) + "]"


def _parse_vector(val) -> np.ndarray | None:
    """Parse a pgvector value (string or None) into numpy array."""
    if val is None:
        return None
    if isinstance(val, (list, np.ndarray)):
        return np.array(val, dtype=np.float32)
    # pgvector returns as string like '[0.1,0.2,...]'
    s = str(val).strip("[]")
    if not s:
        return None
    return np.array([float(x) for x in s.split(",")], dtype=np.float32)


class Database:
    """PostgreSQL connection pool with helper methods."""

    _pool = None

    @classmethod
    def get_pool(cls):
        if cls._pool is None:
            cls._pool = pool.ThreadedConnectionPool(2, 10, DATABASE_URL)
        return cls._pool

    @classmethod
    @contextmanager
    def connection(cls):
        """Context manager for DB connections (auto-return to pool)."""
        p = cls.get_pool()
        conn = p.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            p.putconn(conn)

    @classmethod
    @contextmanager
    def cursor(cls, dict_cursor=True):
        """Context manager for DB cursors."""
        with cls.connection() as conn:
            cursor_factory = RealDictCursor if dict_cursor else None
            cur = conn.cursor(cursor_factory=cursor_factory)
            try:
                yield cur
            finally:
                cur.close()

    @classmethod
    def execute(cls, query, params=None):
        """Execute a query and return results."""
        with cls.cursor() as cur:
            cur.execute(query, params)
            if cur.description:
                return cur.fetchall()
            return None

    @classmethod
    def execute_many(cls, query, data):
        """Bulk insert using execute_values."""
        with cls.connection() as conn:
            cur = conn.cursor()
            try:
                execute_values(cur, query, data)
            finally:
                cur.close()

    # =========================================================================
    # Entity queries
    # =========================================================================

    @classmethod
    def get_entities(cls, entity_type=None, limit=50, offset=0):
        """Get entities with optional type filter.

        Returns a list of dicts from the appropriate base table.
        If entity_type is None, returns a combined list from all entity tables.
        """
        if entity_type and entity_type in _ENTITY_TABLES:
            table, id_col = _ENTITY_TABLES[entity_type]
            rows = cls.execute(
                f"SELECT * FROM {table} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            return [dict(r) for r in rows] if rows else []

        # All entity types
        results = []
        for etype, (table, id_col) in _ENTITY_TABLES.items():
            rows = cls.execute(
                f"SELECT *, %s AS entity_type FROM {table} "
                f"ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (etype, limit, offset),
            )
            if rows:
                results.extend(dict(r) for r in rows)
        return results[:limit]

    @classmethod
    def get_entity(cls, entity_type, entity_id):
        """Get single entity by type and ID."""
        if entity_type not in _ENTITY_TABLES:
            return None
        table, id_col = _ENTITY_TABLES[entity_type]
        rows = cls.execute(
            f"SELECT * FROM {table} WHERE {id_col} = %s", (entity_id,)
        )
        if rows:
            return dict(rows[0])
        return None

    # =========================================================================
    # Embedding queries
    # =========================================================================

    @classmethod
    def get_behavioral_embedding(cls, entity_type, entity_id):
        """Get current behavioral embeddings (5 signals + composite).

        Uses the most recent snapshot from behavioral_snapshots.
        Returns dict with keys: signal_vectors (dict), composite (ndarray),
        computed_at (datetime), or None if not found.
        """
        if entity_type not in _ENTITY_TABLES:
            return None

        signal_keys = _SIGNAL_KEYS.get(entity_type, [])

        rows = cls.execute(
            "SELECT signal_1, signal_2, signal_3, signal_4, signal_5, "
            "composite, created_at "
            "FROM behavioral_snapshots "
            "WHERE entity_type = %s AND entity_id = %s "
            "ORDER BY cutoff_date DESC LIMIT 1",
            (entity_type, entity_id),
        )
        if not rows:
            return None

        row = rows[0]
        signal_vectors = {}
        for i, key in enumerate(signal_keys):
            vec = _parse_vector(row[f"signal_{i+1}"])
            if vec is not None:
                signal_vectors[key] = vec

        return {
            "signal_vectors": signal_vectors,
            "composite": _parse_vector(row["composite"]),
            "computed_at": row["created_at"],
        }

    @classmethod
    def save_behavioral_embedding(cls, entity_type, entity_id, signal_vectors, composite):
        """Upsert behavioral embedding for an entity.

        Args:
            entity_type: one of user, device, segment, app, session
            entity_id: UUID string
            signal_vectors: dict mapping signal_key -> 1536-d numpy array
            composite: 1536-d numpy array
        """
        if entity_type not in _EMBEDDING_TABLES:
            raise ValueError(f"Unknown entity_type: {entity_type}")

        table, id_col = _EMBEDDING_TABLES[entity_type]
        signal_cols = _SIGNAL_COLUMNS[entity_type]
        signal_keys = _SIGNAL_KEYS[entity_type]

        # Build column list and values
        cols = [id_col]
        vals = [entity_id]

        for col, key in zip(signal_cols, signal_keys):
            cols.append(col)
            vec = signal_vectors.get(key)
            vals.append(_vector_to_literal(vec) if vec is not None else None)

        cols.append("beh_composite")
        vals.append(_vector_to_literal(composite))

        cols.append("computed_at")
        vals.append("now()")

        # Build upsert
        col_str = ", ".join(cols)
        placeholders = []
        query_params = []
        for i, (col, val) in enumerate(zip(cols, vals)):
            if val == "now()":
                placeholders.append("now()")
            else:
                placeholders.append("%s")
                query_params.append(val)

        placeholder_str = ", ".join(placeholders)

        # ON CONFLICT update all signal + composite columns
        update_cols = signal_cols + ["beh_composite", "computed_at"]
        update_parts = []
        for uc in update_cols:
            if uc == "computed_at":
                update_parts.append(f"{uc} = now()")
            else:
                update_parts.append(f"{uc} = EXCLUDED.{uc}")
        update_str = ", ".join(update_parts)

        query = (
            f"INSERT INTO {table} ({col_str}) VALUES ({placeholder_str}) "
            f"ON CONFLICT ({id_col}) DO UPDATE SET {update_str}"
        )
        cls.execute(query, query_params)

    @classmethod
    def find_similar(cls, entity_type, entity_id, top_k=10):
        """Find similar entities using pgvector cosine similarity on composite.

        Uses the most recent snapshot for each entity.
        Returns list of dicts with entity_id and distance.
        """
        if entity_type not in _ENTITY_TABLES:
            return []

        _, id_col = _ENTITY_TABLES[entity_type]

        # Get the target entity's most recent composite
        rows = cls.execute(
            "SELECT composite FROM behavioral_snapshots "
            "WHERE entity_type = %s AND entity_id = %s "
            "ORDER BY cutoff_date DESC LIMIT 1",
            (entity_type, entity_id),
        )
        if not rows or rows[0]["composite"] is None:
            return []

        target_vec = rows[0]["composite"]

        # Find most recent snapshot per entity and rank by cosine distance
        results = cls.execute(
            "SELECT DISTINCT ON (entity_id) entity_id, "
            "composite <=> %s AS distance "
            "FROM behavioral_snapshots "
            "WHERE entity_type = %s AND entity_id != %s AND composite IS NOT NULL "
            "ORDER BY entity_id, cutoff_date DESC",
            (target_vec, entity_type, entity_id),
        )
        if not results:
            return []

        # Sort by distance and take top_k
        sorted_results = sorted(results, key=lambda r: r["distance"])[:top_k]
        return [{id_col: r["entity_id"], "distance": r["distance"]} for r in sorted_results]

    # =========================================================================
    # Trajectory queries
    # =========================================================================

    @classmethod
    def get_trajectory_snapshots(cls, entity_type, entity_id, start_date=None, end_date=None):
        """Get monthly behavioral snapshots for trajectory analysis.

        Returns list of dicts with cutoff_date, signal vectors, composite.
        """
        query = (
            "SELECT id, cutoff_date, "
            "signal_1, signal_2, signal_3, signal_4, signal_5, "
            "composite, created_at "
            "FROM behavioral_snapshots "
            "WHERE entity_type = %s AND entity_id = %s"
        )
        params = [entity_type, entity_id]

        if start_date:
            query += " AND cutoff_date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND cutoff_date <= %s"
            params.append(end_date)

        query += " ORDER BY cutoff_date ASC"
        rows = cls.execute(query, params)

        if not rows:
            return []

        results = []
        for row in rows:
            results.append({
                "snapshot_id": row["id"],
                "cutoff_date": row["cutoff_date"],
                "signals": [
                    _parse_vector(row["signal_1"]),
                    _parse_vector(row["signal_2"]),
                    _parse_vector(row["signal_3"]),
                    _parse_vector(row["signal_4"]),
                    _parse_vector(row["signal_5"]),
                ],
                "composite": _parse_vector(row["composite"]),
                "computed_at": row["created_at"],
            })
        return results

    @classmethod
    def save_snapshot(cls, entity_type, entity_id, cutoff_date, signal_vectors, composite):
        """Insert a behavioral snapshot (upsert on unique constraint).

        Args:
            entity_type: entity type string
            entity_id: UUID string
            cutoff_date: date object for the snapshot period
            signal_vectors: list of 5 numpy arrays (or dict with 5 values)
            composite: 1536-d numpy array
        """
        # Accept dict or list
        if isinstance(signal_vectors, dict):
            vecs = list(signal_vectors.values())[:5]
        else:
            vecs = list(signal_vectors)[:5]

        # Pad to 5 if fewer
        while len(vecs) < 5:
            vecs.append(None)

        vec_literals = [
            _vector_to_literal(v) if v is not None else None for v in vecs
        ]
        composite_literal = _vector_to_literal(composite)

        cls.execute(
            "INSERT INTO behavioral_snapshots "
            "(entity_type, entity_id, cutoff_date, "
            "signal_1, signal_2, signal_3, signal_4, signal_5, "
            "composite) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (entity_type, entity_id, cutoff_date) DO UPDATE SET "
            "signal_1 = EXCLUDED.signal_1, "
            "signal_2 = EXCLUDED.signal_2, "
            "signal_3 = EXCLUDED.signal_3, "
            "signal_4 = EXCLUDED.signal_4, "
            "signal_5 = EXCLUDED.signal_5, "
            "composite = EXCLUDED.composite",
            (entity_type, entity_id, cutoff_date,
             vec_literals[0], vec_literals[1], vec_literals[2],
             vec_literals[3], vec_literals[4], composite_literal),
        )

    # =========================================================================
    # Detection queries
    # =========================================================================

    @classmethod
    def get_alerts(cls, severity=None, entity_type=None, status=None, limit=50):
        """Get alerts (trajectory_events) with filtering."""
        query = "SELECT * FROM trajectory_events WHERE 1=1"
        params = []

        if severity:
            query += " AND severity = %s"
            params.append(severity)
        if entity_type:
            query += " AND entity_type = %s"
            params.append(entity_type)
        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY detected_at DESC LIMIT %s"
        params.append(limit)

        rows = cls.execute(query, params)
        return [dict(r) for r in rows] if rows else []

    @classmethod
    def save_alert(cls, alert_dict):
        """Insert a new alert into trajectory_events.

        Args:
            alert_dict: dict with keys:
                entity_type, entity_id, event_type, severity,
                drift_magnitude, concept_alignments (JSONB),
                mitre_techniques (list), description, status,
                kill_chain_id (optional)
        """
        cls.execute(
            "INSERT INTO trajectory_events "
            "(entity_type, entity_id, event_type, severity, "
            "drift_magnitude, concept_alignments, "
            "mitre_techniques, description, status, kill_chain_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                alert_dict["entity_type"],
                alert_dict["entity_id"],
                alert_dict.get("event_type", "behavioral_shift"),
                alert_dict.get("severity", "medium"),
                alert_dict.get("drift_magnitude"),
                json.dumps(alert_dict.get("concept_alignments")) if alert_dict.get("concept_alignments") else None,
                alert_dict.get("mitre_techniques"),
                alert_dict.get("description"),
                alert_dict.get("status", "new"),
                alert_dict.get("kill_chain_id"),
            ),
        )

    @classmethod
    def update_alert_status(cls, alert_id, status):
        """Update alert status."""
        cls.execute(
            "UPDATE trajectory_events SET status = %s WHERE id = %s",
            (status, alert_id),
        )

    @classmethod
    def get_kill_chains(cls, status=None):
        """Get kill chain sequences."""
        query = "SELECT * FROM kill_chain_sequences WHERE 1=1"
        params = []
        if status:
            query += " AND status = %s"
            params.append(status)
        query += " ORDER BY created_at DESC"
        rows = cls.execute(query, params)
        return [dict(r) for r in rows] if rows else []

    @classmethod
    def save_kill_chain(cls, chain_dict):
        """Insert or update a kill chain.

        Args:
            chain_dict: dict with keys:
                id, status, severity, entities_involved (list), narrative
        """
        cls.execute(
            "INSERT INTO kill_chain_sequences "
            "(id, status, severity, entities_involved, narrative) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET "
            "status = EXCLUDED.status, "
            "severity = EXCLUDED.severity, "
            "entities_involved = EXCLUDED.entities_involved, "
            "narrative = EXCLUDED.narrative",
            (
                chain_dict["id"],
                chain_dict.get("status", "active"),
                chain_dict.get("severity", "high"),
                chain_dict.get("entities_involved"),
                chain_dict.get("narrative"),
            ),
        )

    @classmethod
    def get_dashboard_stats(cls):
        """Aggregate stats for dashboard."""
        stats = {}

        # Entity counts
        for etype, (table, _) in _ENTITY_TABLES.items():
            try:
                rows = cls.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
                stats[f"{etype}_count"] = rows[0]["cnt"] if rows else 0
            except Exception:
                stats[f"{etype}_count"] = 0

        # Embedding coverage from unified behavioral_snapshots table
        try:
            rows = cls.execute(
                "SELECT entity_type, COUNT(DISTINCT entity_id) AS cnt "
                "FROM behavioral_snapshots GROUP BY entity_type"
            )
            for r in (rows or []):
                stats[f"{r['entity_type']}_embeddings"] = r["cnt"]
        except Exception:
            pass

        # Recent alerts (use all events since our data is recent)
        try:
            rows = cls.execute(
                "SELECT severity, COUNT(*) AS cnt FROM trajectory_events "
                "GROUP BY severity"
            )
            stats["alerts_7d"] = {r["severity"]: r["cnt"] for r in rows} if rows else {}
        except Exception:
            stats["alerts_7d"] = {}

        # Active kill chains
        try:
            rows = cls.execute(
                "SELECT COUNT(*) AS cnt FROM kill_chain_sequences WHERE status = 'active'"
            )
            stats["active_kill_chains"] = rows[0]["cnt"] if rows else 0
        except Exception:
            stats["active_kill_chains"] = 0

        # Total snapshots
        try:
            rows = cls.execute("SELECT COUNT(*) AS cnt FROM behavioral_snapshots")
            stats["total_snapshots"] = rows[0]["cnt"] if rows else 0
        except Exception:
            stats["total_snapshots"] = 0

        return stats


def init_db():
    """Initialize database (run schema if tables don't exist)."""
    try:
        with Database.connection() as conn:
            cur = conn.cursor()
            # Check if core table exists
            cur.execute(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables "
                "  WHERE table_name = 'trajectory_snapshots'"
                ")"
            )
            exists = cur.fetchone()[0]
            cur.close()

            if not exists:
                schema_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), "db", "schema.sql"
                )
                if os.path.exists(schema_path):
                    cur = conn.cursor()
                    with open(schema_path, "r") as f:
                        cur.execute(f.read())
                    cur.close()
                    logger.info("Database schema initialized from %s", schema_path)
                else:
                    logger.warning("Schema file not found: %s", schema_path)
            else:
                logger.info("Database tables already exist, skipping schema init")
    except Exception as e:
        logger.error("Failed to initialize database: %s", e)
        raise


def check_connection() -> bool:
    """Test database connectivity."""
    try:
        rows = Database.execute("SELECT 1 AS ok")
        return rows is not None and rows[0]["ok"] == 1
    except Exception as e:
        logger.warning("Database connection check failed: %s", e)
        return False
