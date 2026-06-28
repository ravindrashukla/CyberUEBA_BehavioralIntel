"""Step 5: Embedding history SCD2 ledger.

Backfills user_embeddings_history from behavioral_snapshots using
the bi-temporal SCD2 protocol from temporal_store.

Each user's daily embedding becomes a new SCD2 version, creating an
append-only audit trail of how embeddings evolved over time.

Usage:
    python -m pipeline.embedding_history
    python -m pipeline.embedding_history --start 2025-01-01 --end 2025-03-31
"""

import argparse
import time
from datetime import date

from pipeline.db_connect import get_connection
from pipeline.temporal_store import upsert_embedding_version


def _vec_to_list_str(pgvec) -> str | None:
    """Convert pgvector string to list-format string for SCD2 upsert."""
    if pgvec is None:
        return None
    s = str(pgvec).strip()
    if s.startswith("["):
        return s
    return None


def _available_dates(conn, start: date = None, end: date = None) -> list[date]:
    sql = "SELECT DISTINCT cutoff_date FROM behavioral_snapshots WHERE entity_type = 'user'"
    params = []
    if start:
        sql += " AND cutoff_date >= %s"
        params.append(start)
    if end:
        sql += " AND cutoff_date <= %s"
        params.append(end)
    sql += " ORDER BY cutoff_date"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [row[0] for row in cur.fetchall()]


def _fetch_snapshots_for_date(conn, cutoff: date) -> list[dict]:
    sql = """
        SELECT entity_id,
               zone_identity, zone_access_pattern, zone_data_behavior,
               zone_network_footprint, zone_risk_posture, composite
        FROM behavioral_snapshots
        WHERE entity_type = 'user' AND cutoff_date = %s
        ORDER BY entity_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (cutoff,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def process_day(conn, cutoff: date) -> int:
    """Backfill embedding history for all users on a given date."""
    snapshots = _fetch_snapshots_for_date(conn, cutoff)
    count = 0
    for snap in snapshots:
        vectors = {
            "zone_identity": _vec_to_list_str(snap["zone_identity"]),
            "zone_access_pattern": _vec_to_list_str(snap["zone_access_pattern"]),
            "zone_data_behavior": _vec_to_list_str(snap["zone_data_behavior"]),
            "zone_network_footprint": _vec_to_list_str(snap["zone_network_footprint"]),
            "zone_risk_posture": _vec_to_list_str(snap["zone_risk_posture"]),
            "composite": _vec_to_list_str(snap["composite"]),
        }
        try:
            upsert_embedding_version(
                conn,
                entity_type="user",
                pk={"user_id": snap["entity_id"]},
                vectors=vectors,
                valid_from=cutoff,
                reason="daily_backfill",
            )
            conn.commit()
            count += 1
        except Exception as e:
            conn.rollback()
            if "must be >" not in str(e):
                print(f"  [warn] {snap['entity_id']} @ {cutoff}: {e}")
    return count


def main():
    parser = argparse.ArgumentParser(description="Backfill embedding history from behavioral snapshots")
    parser.add_argument("--start", type=str)
    parser.add_argument("--end", type=str)
    args = parser.parse_args()

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    conn = get_connection()
    dates = _available_dates(conn, start, end)
    print(f"Found {len(dates)} days to backfill into embedding history")

    if not dates:
        print("No behavioral snapshots. Run pipeline.behavioral_snapshots first.")
        conn.close()
        return

    total = 0
    t0 = time.time()

    for i, d in enumerate(dates):
        n = process_day(conn, d)
        total += n
        if (i + 1) % 10 == 0 or i == len(dates) - 1:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(dates)}] {d} — {n} versions — "
                  f"total {total:,} — {elapsed:.1f}s")

    conn.close()
    elapsed = time.time() - t0
    print(f"\nDone. {total:,} embedding versions in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
