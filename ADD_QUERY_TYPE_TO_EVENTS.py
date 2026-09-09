#!/usr/bin/env python3
"""
DiscoverAI: Add query_type to search_events
================================================

Adds a `query_type` column so every event (search, impression, click,
add-to-cart) can be tagged with how the search was initiated:

  - 'popular_search'        - customer tapped a Popular Search chip
  - 'manual_entered'        - customer typed the query themselves
  - 'auto_suggestion_picked' - customer picked an as-you-type suggestion
                                (reserved now for the not-yet-built Auto
                                Suggestion feature, so no second migration
                                is needed later)

This is what makes Measurement metric #1 possible - Popular Search
adoption rate (what fraction of searches/clicks/carts trace back to a
chip tap vs. manual typing).

Nullable, since existing rows logged before this column existed won't
have a value - not backfilled, just left NULL.

Usage:
    python ADD_QUERY_TYPE_TO_EVENTS.py            # dry run
    python ADD_QUERY_TYPE_TO_EVENTS.py --apply    # commits the change
"""

import os
import sys

QUERY_TYPES = ("popular_search", "manual_entered", "auto_suggestion_picked")


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

    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'search_events' AND column_name = 'query_type'
    """)
    already_has_column = cur.fetchone() is not None
    print(f"query_type column already exists: {already_has_column}")

    values_sql = ", ".join(f"'{v}'" for v in QUERY_TYPES)
    print(f"Allowed values: {QUERY_TYPES} (NULL also allowed, for rows logged before this migration)")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.)")
        cur.close()
        conn.close()
        return

    if not already_has_column:
        cur.execute("ALTER TABLE search_events ADD COLUMN query_type VARCHAR(30)")

    cur.execute("""
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE rel.relname = 'search_events' AND con.contype = 'c' AND con.conname LIKE '%query_type%'
    """)
    for (name,) in cur.fetchall():
        cur.execute(f"ALTER TABLE search_events DROP CONSTRAINT {name}")

    cur.execute(f"""
        ALTER TABLE search_events ADD CONSTRAINT search_events_query_type_check
        CHECK (query_type IS NULL OR query_type IN ({values_sql}))
    """)
    conn.commit()

    print("\nDone. search_events.query_type is ready.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
