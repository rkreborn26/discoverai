#!/usr/bin/env python3
"""
DiscoverAI: Create query clustering tables
==============================================

Backend for semantic query deduplication (Step 6 - the one native-AI
capability we decided was actually worth adding to Popular Searches, see
requirements/auto_suggestion_ai_pm_plan.md). Without this, "cooking oil",
"oil", and "edible oil" fragment volume/CTR across 3 separate rows in
popular_queries even though they mean the same thing to a shopper.

  - query_embeddings: cache of one embedding per distinct query_text, so
    CLUSTER_QUERIES.py doesn't re-call OpenAI for a query it's already
    embedded before.
  - query_aliases: the raw query_text -> canonical_query mapping produced
    by clustering. A canonical query aliases to itself (similarity=1.0)
    for simplicity - every query_text that's ever been clustered has
    exactly one row here, canonical or not.

Uses the pgvector extension already enabled for product embeddings - no
new extension needed.

Usage:
    python CREATE_QUERY_CLUSTERING_TABLES.py            # dry run
    python CREATE_QUERY_CLUSTERING_TABLES.py --apply    # creates the tables
"""

import os
import sys

CREATE_QUERY_EMBEDDINGS_SQL = """
CREATE TABLE IF NOT EXISTS query_embeddings (
    query_text VARCHAR(255) PRIMARY KEY,
    embedding vector,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_QUERY_ALIASES_SQL = """
CREATE TABLE IF NOT EXISTS query_aliases (
    query_text VARCHAR(255) PRIMARY KEY,
    canonical_query VARCHAR(255) NOT NULL,
    similarity NUMERIC(6,4),
    computed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
"""


def main():
    apply_changes = "--apply" in sys.argv

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    print("Connecting to Neon...")
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    print("Connected.\n")

    print("Plan:")
    print("  - CREATE TABLE IF NOT EXISTS query_embeddings (query_text PK, embedding vector)")
    print("  - CREATE TABLE IF NOT EXISTS query_aliases (query_text PK, canonical_query, similarity)")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.)")
        cur.close()
        conn.close()
        return

    cur.execute(CREATE_QUERY_EMBEDDINGS_SQL)
    cur.execute(CREATE_QUERY_ALIASES_SQL)
    conn.commit()

    print("\nDone. Tables created (or already existed).")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
