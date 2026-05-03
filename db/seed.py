"""Load generated CSV data into PostgreSQL."""

import os
import glob
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.environ.get("DATABASE_URL", "postgresql://cyber_ueba:password@localhost:5433/cyber_ueba")

BATCH_SIZE = 1000

# Map entity CSV filenames to DB tables and their column order
ENTITY_TABLE_MAP = {
    "users.csv": {
        "table": "users",
        "columns": ["user_id", "username", "user_type", "department", "role",
                    "clearance_level", "manager_id", "tenure_days",
                    "primary_device_id", "primary_location", "subnet"],
        "rename": {"clearance": "clearance_level"},
    },
    "segments.csv": {
        "table": "network_segments",
        "columns": ["segment_id", "cidr", "vlan", "zone", "trust_level", "adjacent_segments"],
        "rename": {},
    },
    "devices.csv": {
        "table": "devices",
        "columns": ["device_id", "hostname", "device_type", "os", "ip_address",
                    "segment_id", "owner_user_id"],
        "rename": {},
    },
    "applications.csv": {
        "table": "applications",
        "columns": ["app_id", "app_name", "app_type", "data_classification",
                    "hosting_segment", "criticality"],
        "rename": {},
    },
}

# Map log subdirectory names to DB tables
LOG_TABLE_MAP = {
    "auth": {
        "table": "auth_logs",
        "columns": ["timestamp", "user_id", "device_id", "source_ip", "dest_system",
                    "success", "auth_method", "failure_reason", "geo_location"],
        "required": ["timestamp", "user_id"],
    },
    "network": {
        "table": "network_flows",
        "columns": ["timestamp", "src_ip", "dst_ip", "src_port", "dst_port",
                    "protocol", "bytes_in", "bytes_out", "duration_ms", "tcp_flags"],
        "required": ["timestamp", "src_ip"],
    },
    "dns": {
        "table": "dns_queries",
        "columns": ["timestamp", "device_id", "query_name", "record_type",
                    "response_code", "response_ip"],
        "required": ["timestamp", "device_id"],
    },
    "endpoint": {
        "table": "endpoint_telemetry",
        "columns": ["timestamp", "device_id", "user_id", "event_type", "process_name",
                    "parent_process", "command_line", "file_path", "risk_score"],
        "required": ["timestamp", "device_id"],
    },
    "file_access": {
        "table": "file_access_logs",
        "columns": ["timestamp", "user_id", "file_path", "operation",
                    "file_size_bytes", "data_classification", "success"],
        "required": ["timestamp", "user_id"],
    },
    "app": {
        "table": "app_activity_logs",
        "columns": ["timestamp", "user_id", "app_id", "event_type",
                    "data_volume_bytes", "response_code", "duration_ms"],
        "required": ["timestamp", "user_id"],
    },
    "privilege": {
        "table": "privilege_operations",
        "columns": ["timestamp", "actor_user_id", "target_user_id", "operation",
                    "resource", "justification", "approved"],
        "required": ["timestamp", "actor_user_id"],
    },
}


def _connect():
    """Create database connection."""
    return psycopg2.connect(DB_URL)


def _insert_batch(cursor, table, columns, rows):
    """Bulk insert rows using execute_values."""
    if not rows:
        return
    cols_str = ", ".join(columns)
    template = f"({', '.join(['%s'] * len(columns))})"
    sql = f"INSERT INTO {table} ({cols_str}) VALUES %s ON CONFLICT DO NOTHING"
    execute_values(cursor, sql, rows, template=template, page_size=BATCH_SIZE)


def seed_entities(cursor, data_dir: Path):
    """Load entity CSVs into database."""
    entities_dir = data_dir / "entities"
    if not entities_dir.exists():
        print(f"  No entities directory found at {entities_dir}")
        return

    for csv_name, mapping in ENTITY_TABLE_MAP.items():
        csv_path = entities_dir / csv_name
        if not csv_path.exists():
            print(f"  Skipping {csv_name} (not found)")
            continue

        df = pd.read_csv(csv_path)
        table = mapping["table"]
        columns = mapping["columns"]

        # Apply column renames
        renames = mapping.get("rename", {})
        if renames:
            df = df.rename(columns=renames)

        # Filter to only columns that exist in both DataFrame and target
        available = [c for c in columns if c in df.columns]
        if not available:
            print(f"  Skipping {csv_name} (no matching columns)")
            continue

        # Convert to records and sanitize NaN/None values for SQL
        def _sanitize(val):
            if val is None:
                return None
            if isinstance(val, float) and pd.isna(val):
                return None
            return val

        rows = [[_sanitize(v) for v in row] for row in df[available].values.tolist()]
        _insert_batch(cursor, table, available, rows)
        print(f"  {table}: {len(rows)} rows inserted")


def seed_logs(cursor, data_dir: Path):
    """Load daily log CSVs into database."""
    total_rows = 0

    for log_type, mapping in LOG_TABLE_MAP.items():
        log_dir = data_dir / log_type
        if not log_dir.exists():
            continue

        csv_files = sorted(glob.glob(str(log_dir / "*.csv")))
        if not csv_files:
            continue

        table = mapping["table"]
        columns = mapping["columns"]
        type_rows = 0

        for csv_path in csv_files:
            df = pd.read_csv(csv_path)

            # Filter to columns that exist
            available = [c for c in columns if c in df.columns]
            if not available:
                continue

            # Drop rows with null values in required columns (first 2 are typically required)
            required = mapping.get("required", [])
            req_available = [c for c in required if c in df.columns]
            if req_available:
                df = df.dropna(subset=req_available)

            # Replace NaN with None for SQL compatibility
            df = df.where(pd.notnull(df), None)

            rows = df[available].values.tolist()

            # Insert in batches
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i:i + BATCH_SIZE]
                _insert_batch(cursor, table, available, batch)

            type_rows += len(rows)

        if type_rows > 0:
            print(f"  {table}: {type_rows:,} rows inserted ({len(csv_files)} files)")
            total_rows += type_rows

    print(f"  Total log rows: {total_rows:,}")


def seed(data_dir: str = "data/generated"):
    """Main seed function: load entities then logs."""
    data_path = Path(data_dir)
    if not data_path.exists():
        print(f"ERROR: Data directory not found: {data_path.resolve()}")
        print("Run 'python -m simulator' first to generate data.")
        return

    print(f"Connecting to database: {DB_URL.split('@')[1] if '@' in DB_URL else DB_URL}")
    conn = _connect()
    conn.autocommit = False
    cursor = conn.cursor()

    try:
        print("\nSeeding entity tables...")
        seed_entities(cursor, data_path)

        print("\nSeeding log tables...")
        seed_logs(cursor, data_path)

        conn.commit()
        print("\nSeed complete.")
    except Exception as e:
        conn.rollback()
        print(f"\nERROR: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Seed PostgreSQL with generated UEBA data")
    parser.add_argument(
        "--data-dir", default="data/generated",
        help="Directory containing generated CSVs (default: data/generated)"
    )
    args = parser.parse_args()
    seed(data_dir=args.data_dir)


if __name__ == "__main__":
    main()
