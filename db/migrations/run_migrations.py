"""Run database migrations in order.

Usage:
    python -m db.migrations.run_migrations [--reset]

    --reset   Drop ALL tables first and re-run from scratch.
              WARNING: destroys all data.
"""

import os
import sys
import glob
import argparse

import psycopg2


def get_connection():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5437")),
        dbname=os.getenv("DB_NAME", "cyber_ueba"),
        user=os.getenv("DB_USER", "cyber_ueba"),
        password=os.getenv("DB_PASSWORD", "password"),
    )


def run_migrations(reset: bool = False):
    conn = get_connection()
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.commit()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS _migration_log (
                    id          SERIAL PRIMARY KEY,
                    filename    TEXT NOT NULL UNIQUE,
                    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            conn.commit()

            if reset:
                print("[RESET] Dropping all application tables...")
                cur.execute("""
                    DO $$ DECLARE r RECORD;
                    BEGIN
                        FOR r IN (
                            SELECT tablename FROM pg_tables
                            WHERE schemaname = 'public'
                              AND tablename != '_migration_log'
                        ) LOOP
                            EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
                        END LOOP;
                    END $$;
                """)
                cur.execute("DELETE FROM _migration_log")
                conn.commit()
                print("[RESET] All tables dropped.")

        migrations_dir = os.path.dirname(os.path.abspath(__file__))
        sql_files = sorted(glob.glob(os.path.join(migrations_dir, "*.sql")))

        if not sql_files:
            print("No migration files found.")
            return

        with conn.cursor() as cur:
            cur.execute("SELECT filename FROM _migration_log")
            applied = {row[0] for row in cur.fetchall()}

        for sql_path in sql_files:
            filename = os.path.basename(sql_path)
            if filename in applied:
                print(f"  [skip] {filename} (already applied)")
                continue

            print(f"  [run]  {filename} ...")
            with open(sql_path, "r", encoding="utf-8") as f:
                sql = f.read()

            with conn.cursor() as cur:
                cur.execute(sql)
                conn.commit()

                cur.execute(
                    "INSERT INTO _migration_log (filename) VALUES (%s)",
                    (filename,),
                )
                conn.commit()

            print(f"  [done] {filename}")

        print("\nAll migrations applied successfully.")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
            """)
            tables = [row[0] for row in cur.fetchall()]
            print(f"\nTables in database ({len(tables)}):")
            for t in tables:
                cur.execute(f"SELECT count(*) FROM {t}")
                count = cur.fetchone()[0]
                print(f"  {t}: {count} rows")

    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR] Migration failed: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run CyberUEBA database migrations")
    parser.add_argument("--reset", action="store_true",
                        help="Drop all tables and re-run from scratch")
    args = parser.parse_args()
    run_migrations(reset=args.reset)
