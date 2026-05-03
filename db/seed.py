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
        "columns": ["username", "user_type", "department", "role", "clearance_level", "is_active"],
        "transforms": {
            "clearance": "clearance_level",
            "user_type": "user_type",
        },
    },
    "segments.csv": {
        "table": "network_segments",
        "columns": ["segment_name", "subnet_cidr", "vlan_id", "zone_type", "trust_level", "connected_segments"],
        "transforms": {
            "segment_id": "segment_name",
            "cidr": "subnet_cidr",
            "vlan": "vlan_id",
            "zone": "zone_type",
            "adjacent_segments": "connected_segments",
        },
    },
    "devices.csv": {
        "table": "devices",
        "columns": ["hostname", "device_type", "os_type", "ip_address"],
        "transforms": {
            "os": "os_type",
        },
    },
    "applications.csv": {
        "table": "applications",
        "columns": ["app_name", "app_type", "data_classification", "criticality"],
        "transforms": {},
    },
}

# Map log subdirectory names to DB tables
LOG_TABLE_MAP = {
    "auth": {
        "table": "auth_logs",
        "columns": ["timestamp", "source_ip", "dest_system", "success", "auth_method",
                    "failure_reason", "geo_location"],
    },
    "network": {
        "table": "network_flows",
        "columns": ["timestamp", "src_ip", "dst_ip", "src_port", "dst_port",
                    "protocol", "bytes_in", "bytes_out", "duration_ms", "tcp_flags"],
    },
    "dns": {
        "table": "dns_queries",
        "columns": ["timestamp", "client_ip", "query_domain", "query_type",
                    "response_code", "response_ip"],
    },
    "endpoint": {
        "table": "endpoint_telemetry",
        "columns": ["timestamp", "process_name", "parent_process", "command_line",
                    "file_access_path", "registry_key", "event_type"],
    },
    "app": {
        "table": "app_activity_logs",
        "columns": ["timestamp", "action", "resource", "status_code",
                    "response_time_ms", "data_volume_bytes"],
    },
    "privilege": {
        "table": "privilege_operations",
        "columns": ["timestamp", "operation", "target_resource", "previous_level",
                    "new_level", "justification", "auto_approved"],
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
        renames = mapping.get("transforms", {})
        df = df.rename(columns=renames)

        # Filter to only columns that exist in both DataFrame and target
        available = [c for c in columns if c in df.columns]
        if not available:
            print(f"  Skipping {csv_name} (no matching columns)")
            continue

        # Handle array columns (pipe-separated -> PostgreSQL array)
        for col in available:
            if col == "connected_segments":
                df[col] = df[col].apply(
                    lambda x: x.split("|") if isinstance(x, str) else None
                )

        rows = df[available].values.tolist()
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
