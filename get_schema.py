"""
DiscoverAI: Schema Extractor
============================

Connects to your Neon database and pulls the REAL, current schema
(tables, columns, types, defaults, primary keys, foreign keys, and indexes)
directly from information_schema / pg_catalog.

Writes the result to schema.sql in this same folder.

Usage:
    python get_schema.py
"""

import os
import re
import psycopg2
from dotenv import load_dotenv
from pathlib import Path

env_path = Path('.env')
if env_path.exists():
    load_dotenv(env_path)

DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in .env")
    exit(1)

print("Connecting to NEON...")
try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    print("OK: Connected!")
except Exception as e:
    print(f"ERROR: Connection failed: {e}")
    exit(1)

output_lines = []

def write(line=""):
    print(line)
    output_lines.append(line)

write("-- ============================================================")
write("-- DiscoverAI Database Schema")
write("-- Auto-generated from Neon via get_schema.py")
write("-- ============================================================\n")

# 1. Installed extensions (e.g. pgvector) - these must be created before
# any CREATE TABLE that uses a type they provide (e.g. the "vector" type
# used by the embedding columns below). Previously this section only
# wrote comments describing which extensions were installed, so a fresh
# database had no extensions at all and every CREATE TABLE using "vector"
# failed with "type \"vector\" does not exist" partway through the file.
write("-- Extensions")
write("-- ----------")
cur.execute("SELECT extname, extversion FROM pg_extension ORDER BY extname;")
extensions = cur.fetchall()
for name, version in extensions:
    if name == 'plpgsql':
        continue  # built into every Postgres database already, not extension-installed
    write(f'CREATE EXTENSION IF NOT EXISTS "{name}";  -- v{version} on source db')
write()

# 2. Tables in public schema
cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    ORDER BY table_name;
""")
tables = [r[0] for r in cur.fetchall()]

if not tables:
    write("-- No tables found in public schema.")

for table in tables:
    write(f"-- ------------------------------------------------------------")
    write(f"-- TABLE: {table}")
    write(f"-- ------------------------------------------------------------")

    # Row count
    try:
        cur.execute(f'SELECT COUNT(*) FROM public."{table}"')
        row_count = cur.fetchone()[0]
        write(f"-- Row count: {row_count}")
    except Exception as e:
        conn.rollback()
        write(f"-- Row count: error ({e})")

    # Columns
    cur.execute("""
        SELECT column_name, data_type, udt_name, is_nullable, column_default,
               character_maximum_length, numeric_precision, numeric_scale
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position;
    """, (table,))
    columns = cur.fetchall()

    # Primary key columns
    cur.execute("""
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = 'public' AND tc.table_name = %s AND tc.constraint_type = 'PRIMARY KEY';
    """, (table,))
    pk_cols = {r[0] for r in cur.fetchall()}

    # Foreign keys
    cur.execute("""
        SELECT
            kcu.column_name,
            ccu.table_name AS foreign_table,
            ccu.column_name AS foreign_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
        WHERE tc.table_schema = 'public' AND tc.table_name = %s AND tc.constraint_type = 'FOREIGN KEY';
    """, (table,))
    fks = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    # Sequences backing any "DEFAULT nextval('seq_name'::regclass)" column.
    # information_schema reports the default expression as-is, but doesn't
    # create the sequence object it refers to - the original tables have
    # these because SERIAL/bigserial auto-created them years ago. A fresh
    # CREATE TABLE run against this file needs the sequence to already
    # exist, or nextval() has nothing to point at (this is exactly the
    # "relation ... _id_seq does not exist" error a fresh restore hits).
    seq_defs = []
    for col_name, _, _, _, default, _, _, _ in columns:
        if not default:
            continue
        m = re.search(r"nextval\('([^']+)'::regclass\)", default)
        if m:
            seq_defs.append((m.group(1), col_name))

    for seq_name, _ in seq_defs:
        write(f'CREATE SEQUENCE IF NOT EXISTS "{seq_name}";')
    if seq_defs:
        write()

    # IF NOT EXISTS so re-running this file against a partially-created
    # database (e.g. one that failed partway through before this fix)
    # doesn't error out on every table that already succeeded - matches
    # the idempotent CREATE TABLE IF NOT EXISTS convention every other
    # migration script in this repo already follows.
    write(f"CREATE TABLE IF NOT EXISTS {table} (")
    col_defs = []
    for col_name, data_type, udt_name, nullable, default, char_len, num_prec, num_scale in columns:
        # Resolve real type name (vector, etc show up oddly in data_type)
        type_str = udt_name if data_type == 'USER-DEFINED' else data_type
        if char_len:
            type_str += f"({char_len})"
        elif data_type == 'numeric' and num_prec:
            type_str += f"({num_prec},{num_scale or 0})"

        line = f"    {col_name} {type_str}"
        if col_name in pk_cols:
            line += " PRIMARY KEY"
        if nullable == 'NO' and col_name not in pk_cols:
            line += " NOT NULL"
        if default:
            line += f" DEFAULT {default}"
        col_defs.append((line, fks.get(col_name)))

    # Emit the real "," column separator FIRST, then the FK note as a
    # trailing line comment. Doing it in the other order (comment first,
    # comma appended after via str.join) let the "--" comment swallow the
    # comma to end of line, silently dropping the separator between
    # columns and producing invalid SQL if this file were ever run as-is.
    rendered_lines = []
    last_index = len(col_defs) - 1
    for i, (line, fk) in enumerate(col_defs):
        suffix = "," if i < last_index else ""
        if fk:
            ftable, fcol = fk
            rendered_lines.append(f"{line}{suffix}  -- FK -> {ftable}.{fcol}")
        else:
            rendered_lines.append(f"{line}{suffix}")
    write("\n".join(rendered_lines))
    write(");")
    write()

    for seq_name, col_name in seq_defs:
        write(f'ALTER SEQUENCE "{seq_name}" OWNED BY "{table}"."{col_name}";')
    if seq_defs:
        write()

    # Indexes
    cur.execute("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public' AND tablename = %s;
    """, (table,))
    indexes = cur.fetchall()
    if indexes:
        write(f"-- Indexes on {table}:")
        for idx_name, idx_def in indexes:
            write(f"-- {idx_def};")
        write()

cur.close()
conn.close()

with open('schema.sql', 'w', encoding='utf-8') as f:
    f.write("\n".join(output_lines))

print("\nDone! Full schema written to schema.sql")
