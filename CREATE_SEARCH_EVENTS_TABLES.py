#!/usr/bin/env python3
"""
DiscoverAI: Create search_events + popular_queries tables
==============================================================

Backend for the Popular Searches feature (see
requirements/auto_suggestion_ai_pm_plan.md):

  - search_events: raw log of search / product_click / add_to_cart events,
    including the result `position` a clicked/added product was shown at
    (enables position-bias-aware analysis later, not just raw CTR).
  - popular_queries: the computed, ranked output the API actually serves -
    seeded with the 17 launch queries (is_seed=true, no real stats yet).

Usage:
    python CREATE_SEARCH_EVENTS_TABLES.py            # dry run - shows the plan, writes nothing
    python CREATE_SEARCH_EVENTS_TABLES.py --apply    # creates tables + seeds popular_queries
"""

import os
import sys

SEED_QUERIES = [
    "ghee", "dal", "oil", "cooking oil", "vegetables", "oranges", "mangoes",
    "atta", "moong", "tata sampann dal", "potato", "onion", "spinach",
    "blueberries", "watermelon", "bananas", "apples",
]

CREATE_SEARCH_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS search_events (
    id BIGSERIAL PRIMARY KEY,
    query_text VARCHAR(255) NOT NULL,
    event_type VARCHAR(20) NOT NULL CHECK (event_type IN ('search', 'product_click', 'add_to_cart')),
    product_id VARCHAR(50) REFERENCES products(id),
    position INTEGER,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_SEARCH_EVENTS_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_search_events_query_text ON search_events (query_text);",
    "CREATE INDEX IF NOT EXISTS idx_search_events_created_at ON search_events (created_at);",
    "CREATE INDEX IF NOT EXISTS idx_search_events_event_type ON search_events (event_type);",
]

CREATE_POPULAR_QUERIES_SQL = """
CREATE TABLE IF NOT EXISTS popular_queries (
    query_text VARCHAR(255) PRIMARY KEY,
    search_volume INTEGER DEFAULT 0,
    click_rate NUMERIC(6,4) DEFAULT 0,
    cart_rate NUMERIC(6,4) DEFAULT 0,
    popularity_score NUMERIC(6,4) DEFAULT 0,
    is_seed BOOLEAN DEFAULT false,
    rank INTEGER,
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
    print("  - CREATE TABLE IF NOT EXISTS search_events (+ 3 indexes)")
    print("  - CREATE TABLE IF NOT EXISTS popular_queries")
    print(f"  - seed popular_queries with {len(SEED_QUERIES)} queries (is_seed=true), skipping any already present")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.)")
        cur.close()
        conn.close()
        return

    cur.execute(CREATE_SEARCH_EVENTS_SQL)
    for stmt in CREATE_SEARCH_EVENTS_INDEXES_SQL:
        cur.execute(stmt)
    cur.execute(CREATE_POPULAR_QUERIES_SQL)
    conn.commit()
    print("\nTables created (or already existed).")

    seeded = 0
    for rank, query_text in enumerate(SEED_QUERIES, start=1):
        cur.execute(
            """
            INSERT INTO popular_queries (query_text, search_volume, click_rate, cart_rate, popularity_score, is_seed, rank)
            VALUES (%s, 0, 0, 0, 0, true, %s)
            ON CONFLICT (query_text) DO NOTHING
            """,
            (query_text, rank),
        )
        seeded += cur.rowcount
    conn.commit()
    print(f"Seeded {seeded} new queries ({len(SEED_QUERIES) - seeded} already existed).")

    cur.close()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
