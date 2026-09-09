"""
DiscoverAI: Seed Data Loader
==============================

Loads the CSV files produced by EXPORT_SEED_DATA.py into a target
database, in the load order recorded in seed_data/manifest.json (so
foreign-key dependencies are respected without this script needing to
know the schema itself).

Assumes schema.sql has already been applied to the target database and
its tables are empty - this is a one-time seed for a fresh setup, not a
sync/merge tool. If a target table already has rows, this script will
refuse to load into it (see --apply behavior below) rather than risk
duplicate rows or a primary-key collision.

Follows the same dry-run-by-default pattern as every other migration
script in this repo:
    python LOAD_SEED_DATA.py            # dry run - shows the plan, writes nothing
    python LOAD_SEED_DATA.py --apply    # actually loads the data

After a successful --apply, resets every loaded table's serial/identity
sequence to MAX(id)+1, so the running app's own INSERTs don't collide
with the imported rows' ids.
"""

import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in .env")
    exit(1)

SEED_DIR = Path('seed_data')
MANIFEST_PATH = SEED_DIR / 'manifest.json'

APPLY = '--apply' in sys.argv


def get_connection():
    print("Connecting to NEON...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("OK: Connected!")
        return conn
    except Exception as e:
        print(f"ERROR: Connection failed: {e}")
        exit(1)


def load_manifest():
    if not MANIFEST_PATH.exists():
        print(f"ERROR: {MANIFEST_PATH} not found. Run EXPORT_SEED_DATA.py first "
              f"(against a database that has data) to produce it.")
        exit(1)
    with open(MANIFEST_PATH, encoding='utf-8') as f:
        return json.load(f)


def get_serial_columns(cur, table):
    """Columns on this table backed by a sequence (bigint/serial identity)."""
    cur.execute("""
        SELECT column_name, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
          AND column_default LIKE 'nextval(%%';
    """, (table,))
    return [r[0] for r in cur.fetchall()]


def main():
    manifest = load_manifest()
    load_order = manifest.get('load_order', [])

    if not load_order:
        print("Nothing to load - manifest.json has no tables recorded.")
        return

    conn = get_connection()
    cur = conn.cursor()

    print(f"\n{'APPLYING' if APPLY else 'DRY RUN'} - {len(load_order)} table(s) to load, "
          f"in this order:\n")

    plan = []
    blocked = False

    for entry in load_order:
        table = entry['table']
        expected_rows = entry['row_count']
        csv_path = SEED_DIR / f"{table}.csv"

        if not csv_path.exists():
            print(f"  MISSING  {table:<35} expected {csv_path} - skipping this table.")
            continue

        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        current_rows = cur.fetchone()[0]

        if current_rows > 0:
            print(f"  SKIP     {table:<35} target already has {current_rows} row(s) - "
                  f"not touching it (this script only fills empty tables).")
            continue

        print(f"  OK       {table:<35} {expected_rows} row(s) in CSV, target is empty.")
        plan.append((table, csv_path))

    if not plan:
        print("\nNothing left to load (every table either missing its CSV or already has data).")
        cur.close()
        conn.close()
        return

    if not APPLY:
        print(f"\nDry run only - no changes made. Re-run with --apply to load {len(plan)} table(s).")
        cur.close()
        conn.close()
        return

    print()
    for table, csv_path in plan:
        with open(csv_path, encoding='utf-8') as f:
            cur.copy_expert(f'COPY "{table}" FROM STDIN WITH CSV HEADER', f)
        print(f"  loaded {table}")

    print("\nResetting sequences on loaded tables...")
    for table, _ in plan:
        for col in get_serial_columns(cur, table):
            # table/col come from information_schema (trusted metadata, not
            # user input), so splicing them into the identifier positions is
            # safe here - same pattern get_schema.py already uses elsewhere.
            cur.execute(
                f'SELECT setval(pg_get_serial_sequence(%s, %s), '
                f'COALESCE((SELECT MAX("{col}") FROM "{table}"), 1))',
                (table, col),
            )
            print(f"  {table}.{col} sequence -> synced to MAX({col})")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone! Loaded {len(plan)} table(s).")


if __name__ == '__main__':
    main()
