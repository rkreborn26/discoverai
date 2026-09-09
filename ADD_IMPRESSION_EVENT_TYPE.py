#!/usr/bin/env python3
"""
DiscoverAI: Add 'product_impression' to search_events.event_type
=====================================================================

Adds a 4th event type - fired once per product per results-page-load,
capturing exactly which products were actually shown (and at what
position) for a query. This is the missing denominator for a real
click-through-rate (clicks / impressions, not just clicks / searches) and
sets up the same for add-to-cart-rate later, without changing the current
popularity formula today.

Drops and recreates the CHECK constraint on search_events.event_type to
include the new value (Postgres has no "ALTER CHECK" - this is the normal
way to widen one). Looks up the real constraint name defensively instead
of assuming Postgres's default naming.

Usage:
    python ADD_IMPRESSION_EVENT_TYPE.py            # dry run
    python ADD_IMPRESSION_EVENT_TYPE.py --apply    # commits the change
"""

import os
import sys

NEW_EVENT_TYPES = ("search", "product_click", "add_to_cart", "product_impression")


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
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        WHERE rel.relname = 'search_events' AND con.contype = 'c'
    """)
    check_constraints = [r[0] for r in cur.fetchall()]
    print(f"Found CHECK constraint(s) on search_events: {check_constraints}")

    if not check_constraints:
        print("No existing CHECK constraint found - nothing to drop, just adding the new one.")

    print(f"\nNew allowed event_type values: {NEW_EVENT_TYPES}")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.)")
        cur.close()
        conn.close()
        return

    for name in check_constraints:
        cur.execute(f"ALTER TABLE search_events DROP CONSTRAINT {name}")

    values_sql = ", ".join(f"'{v}'" for v in NEW_EVENT_TYPES)
    cur.execute(f"ALTER TABLE search_events ADD CONSTRAINT search_events_event_type_check "
                f"CHECK (event_type IN ({values_sql}))")
    conn.commit()

    print("\nDone. search_events.event_type now accepts:", NEW_EVENT_TYPES)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
