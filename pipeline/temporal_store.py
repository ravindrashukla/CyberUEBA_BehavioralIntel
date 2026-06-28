"""Bi-temporal writer helpers for CyberUEBA.

All mutations to temporalized tables route through this module.
Ported from DLA MVP's models/temporal_store.py.

Two axes of time:
  - valid_from / valid_to      : when the fact is true in the real world
  - knowledge_from / knowledge_to : when we learned the fact
"""

from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any


class TemporalStoreError(RuntimeError):
    pass


def set_temporal_write(conn, on: bool) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT app_set_temporal_write(%s)", (bool(on),))


@contextmanager
def temporal_write(conn):
    set_temporal_write(conn, True)
    try:
        yield
    finally:
        try:
            set_temporal_write(conn, False)
        except Exception:
            pass


_EMBEDDING_SPEC = {
    "user": {
        "history_table": "user_embeddings_history",
        "pk_cols": ("user_id",),
        "flavors": (
            "zone_identity", "zone_access_pattern", "zone_data_behavior",
            "zone_network_footprint", "zone_risk_posture", "composite",
        ),
    },
}


def _embedding_spec(entity_type: str) -> dict[str, Any]:
    try:
        return _EMBEDDING_SPEC[entity_type]
    except KeyError as exc:
        raise TemporalStoreError(
            f"entity_type {entity_type!r} has no embedding history wired"
        ) from exc


def _vec_equal(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return str(a) == str(b)


def upsert_embedding_version(
    conn,
    entity_type: str,
    pk: dict[str, Any],
    vectors: dict[str, Any],
    valid_from: date,
    knowledge_from: datetime | None = None,
    reason: str = "",
    embedding_model: str = "v1",
) -> None:
    """SCD2 upsert for embedding history. 3-step protocol:
    1. Supersede current open row (set knowledge_to)
    2. Insert closed-valid historical row with OLD vectors
    3. Insert new open row with NEW vectors
    """
    spec = _embedding_spec(entity_type)
    table = spec["history_table"]
    pk_cols = spec["pk_cols"]
    flavors = spec["flavors"]

    now_ts = knowledge_from or datetime.now(timezone.utc)

    pk_where = " AND ".join(f"{c} = %s" for c in pk_cols)
    pk_vals = tuple(pk[c] for c in pk_cols)

    select_cols = ", ".join(("history_id", "valid_from", *flavors))
    fetch_sql = (
        f"SELECT {select_cols} FROM {table} "
        f"WHERE {pk_where} AND embedding_model = %s "
        "AND valid_to IS NULL AND knowledge_to IS NULL "
        "FOR UPDATE"
    )

    insert_cols = (*pk_cols, *flavors, "embedding_model",
                   "valid_from", "valid_to",
                   "knowledge_from", "knowledge_to", "reason")
    insert_placeholders = ", ".join(["%s"] * len(insert_cols))
    insert_sql = (
        f"INSERT INTO {table} ({', '.join(insert_cols)}) "
        f"VALUES ({insert_placeholders})"
    )

    with temporal_write(conn):
        with conn.cursor() as cur:
            cur.execute(fetch_sql, (*pk_vals, embedding_model))
            row = cur.fetchone()

            if row is None:
                values = (
                    *pk_vals,
                    *(vectors.get(f) for f in flavors),
                    embedding_model,
                    valid_from, None, now_ts, None,
                    reason or "initial_load",
                )
                cur.execute(insert_sql, values)
                return

            current_history_id = row[0]
            current_valid_from = row[1]
            current_vectors = dict(zip(flavors, row[2:]))

            merged = dict(current_vectors)
            merged.update(vectors)

            if all(_vec_equal(current_vectors[f], merged[f]) for f in flavors):
                return

            if valid_from <= current_valid_from:
                raise TemporalStoreError(
                    f"valid_from {valid_from} must be > current "
                    f"{current_valid_from} for {entity_type} {pk}"
                )

            cur.execute(
                f"UPDATE {table} SET knowledge_to = %s WHERE history_id = %s",
                (now_ts, current_history_id),
            )

            historical_values = (
                *pk_vals,
                *(current_vectors[f] for f in flavors),
                embedding_model,
                current_valid_from, valid_from, now_ts, None,
                reason or "superseded",
            )
            cur.execute(insert_sql, historical_values)

            new_values = (
                *pk_vals,
                *(merged[f] for f in flavors),
                embedding_model,
                valid_from, None, now_ts, None,
                reason or "update",
            )
            cur.execute(insert_sql, new_values)


def embedding_as_of(
    conn,
    entity_type: str,
    pk: dict[str, Any],
    valid_at: date | datetime,
    knowledge_at: datetime | None = None,
    embedding_model: str = "v1",
) -> dict[str, Any] | None:
    """Bi-temporal point query on embedding history."""
    spec = _embedding_spec(entity_type)
    table = spec["history_table"]
    pk_cols = spec["pk_cols"]
    flavors = spec["flavors"]

    knowledge_ts = knowledge_at or datetime.now(timezone.utc)
    pk_where = " AND ".join(f"{c} = %s" for c in pk_cols)
    pk_vals = tuple(pk[c] for c in pk_cols)
    select_cols = ", ".join(flavors)

    sql = (
        f"SELECT {select_cols} FROM {table} "
        f"WHERE {pk_where} AND embedding_model = %s "
        "AND valid_from <= %s AND (valid_to IS NULL OR valid_to > %s) "
        "AND knowledge_from <= %s AND (knowledge_to IS NULL OR knowledge_to > %s)"
    )

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (*pk_vals, embedding_model, valid_at, valid_at, knowledge_ts, knowledge_ts),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip(flavors, row))


def record_trajectory_event(
    conn,
    entity_type: str,
    entity_id: str,
    event_date: date,
    event_type: str,
    severity: str,
    magnitude: float | None = None,
    shift_type: str | None = None,
    direction: str | None = None,
    contributing_factors: dict | None = None,
    from_regime: dict | None = None,
    to_regime: dict | None = None,
    mitre_techniques: list[str] | None = None,
    description: str | None = None,
) -> int:
    """Append a trajectory event. Returns event_id."""
    import json
    factors_json = json.dumps(contributing_factors or {})
    from_json = json.dumps(from_regime) if from_regime else None
    to_json = json.dumps(to_regime) if to_regime else None

    sql = """
        INSERT INTO trajectory_events (
            entity_type, entity_id, event_date, event_type, shift_type,
            severity, magnitude, direction, contributing_factors,
            from_regime, to_regime, mitre_techniques, description
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s::jsonb,
            %s::jsonb, %s::jsonb, %s, %s
        ) RETURNING event_id
    """
    with temporal_write(conn):
        with conn.cursor() as cur:
            cur.execute(sql, (
                entity_type, entity_id, event_date, event_type, shift_type,
                severity, magnitude, direction, factors_json,
                from_json, to_json, mitre_techniques, description,
            ))
            return cur.fetchone()[0]
