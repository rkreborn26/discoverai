"""
DiscoverAI: Seed Data Exporter
================================

Exports every non-empty table's data to one CSV file per table, under
seed_data/, so a fresh database (schema.sql applied, tables empty) can
be brought back to a working demo state instead of sitting empty.

Design notes:

- Uses Postgres's own COPY command (not a hand-rolled csv.writer loop)
  to do the actual export. That matters here because this schema has
  vector columns (pgvector embeddings), jsonb, and arrays - COPY's CSV
  output already quotes/escapes all of those correctly, so this script
  doesn't need to special-case any column type.

- Table load order is derived from the REAL foreign-key constraints in
  the database (read from information_schema), not a hand-maintained
  list. schema.sql went stale once already in this project's history
  by being hand-reasoned-about instead of introspected; this avoids
  repeating that mistake as new tables get added later.

- One self-referential table exists today (categories.parent_id ->
  categories.id). A same-table FK can't be fixed by table ordering -
  it needs row ordering, so that one table is special-cased to export
  parents before children (ORDER BY level, id). If another
  self-referential table is added later, this script will print a
  warning rather than silently getting the order wrong.

- Read-only against the source database: every query here is a SELECT
  or a COPY ... TO. Nothing is written back to Neon. Safe to run
  anytime, as many times as you like.

Usage:
    python EXPORT_SEED_DATA.py
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in .env")
    exit(1)

OUTPUT_DIR = Path('seed_data')

# categories.parent_id is self-referential; order children after parents
# using the table's own hierarchy column rather than just "id", since id
# values aren't guaranteed to sort parents before children.
SELF_REFERENTIAL_ROW_ORDER = {
    'categories': 'level, id',
}


def get_connection():
    print("Connecting to NEON...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("OK: Connected!")
        return conn
    except Exception as e:
        print(f"ERROR: Connection failed: {e}")
        exit(1)


def get_tables(cur):
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    """)
    return [r[0] for r in cur.fetchall()]


def get_fk_edges(cur):
    """
    Returns (edges, self_referential) where edges is a dict of
    referenced_table -> set of tables that reference it (must load
    first), and self_referential is the set of tables with a FK to
    themselves (handled via row order, not table order).
    """
    cur.execute("""
        SELECT DISTINCT tc.table_name AS referencing_table,
               ccu.table_name AS referenced_table
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
        WHERE tc.table_schema = 'public' AND tc.constraint_type = 'FOREIGN KEY';
    """)
    edges = {}
    self_referential = set()
    for referencing_table, referenced_table in cur.fetchall():
        if referencing_table == referenced_table:
            self_referential.add(referencing_table)
            continue
        edges.setdefault(referenced_table, set()).add(referencing_table)
    return edges, self_referential


def topological_order(all_tables, edges):
    """
    Kahn's algorithm: returns all_tables ordered so that every table
    referenced by a FK appears before the table(s) that reference it.
    """
    in_degree = {t: 0 for t in all_tables}
    for referenced_table, referencing_tables in edges.items():
        for t in referencing_tables:
            in_degree[t] += 1

    ready = sorted([t for t in all_tables if in_degree[t] == 0])
    ordered = []
    while ready:
        table = ready.pop(0)
        ordered.append(table)
        for dependent in sorted(edges.get(table, [])):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)
        ready.sort()

    if len(ordered) != len(all_tables):
        remaining = [t for t in all_tables if t not in ordered]
        print(f"WARNING: could not fully order {remaining} (unexpected FK cycle?) - appending as-is.")
        ordered.extend(remaining)

    return ordered


def export_table(cur, table, out_path):
    row_order = SELF_REFERENTIAL_ROW_ORDER.get(table)
    order_clause = f' ORDER BY {row_order}' if row_order else ''
    with open(out_path, 'w', encoding='utf-8', newline='') as f:
        cur.copy_expert(
            f'COPY (SELECT * FROM "{table}"{order_clause}) TO STDOUT WITH CSV HEADER',
            f,
        )


def main():
    conn = get_connection()
    cur = conn.cursor()

    all_tables = get_tables(cur)
    edges, self_referential = get_fk_edges(cur)
    load_order = topological_order(all_tables, edges)

    unexpected_self_ref = self_referential - set(SELF_REFERENTIAL_ROW_ORDER)
    if unexpected_self_ref:
        print(f"WARNING: {unexpected_self_ref} has a self-referential FK with no row-order rule "
              f"defined - exported row order may not satisfy the FK on import. Add it to "
              f"SELF_REFERENTIAL_ROW_ORDER above.")

    OUTPUT_DIR.mkdir(exist_ok=True)

    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "load_order": [],
        "skipped_empty": [],
    }

    for table in load_order:
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        row_count = cur.fetchone()[0]

        if row_count == 0:
            print(f"  skip  {table:<35} (0 rows)")
            manifest["skipped_empty"].append(table)
            continue

        out_path = OUTPUT_DIR / f"{table}.csv"
        export_table(cur, table, out_path)
        print(f"  wrote {table:<35} {row_count} rows -> {out_path}")
        manifest["load_order"].append({"table": table, "row_count": row_count})

    with open(OUTPUT_DIR / 'manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)

    cur.close()
    conn.close()

    print(f"\nDone! {len(manifest['load_order'])} table(s) exported to {OUTPUT_DIR}/, "
          f"{len(manifest['skipped_empty'])} empty table(s) skipped.")
    print("manifest.json records the load order for LOAD_SEED_DATA.py.")


if __name__ == '__main__':
    main()
