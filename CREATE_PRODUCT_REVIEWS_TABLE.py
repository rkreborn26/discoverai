#!/usr/bin/env python3
"""
DiscoverAI: Create the product_reviews table (Ratings & Reviews module)
=========================================================================

One-time schema migration for the Ratings & Review feature:

  - Customers rate a product 1-5 stars, optionally with written review text.
  - A rating given WITHOUT text is approved immediately (status='approved') -
    there's nothing to moderate.
  - A rating given WITH text goes to moderation first (status='submitted').
  - When rating is 3 stars or below, the frontend requires review text (a
    "reason") before it will submit at all - so every low rating that makes
    it to the backend already has text and is 'submitted', never a silent
    unexplained low score.
  - A moderator (Retailer Admin -> Review Moderation) approves or rejects
    each 'submitted' review. Rejecting requires picking one of three fixed
    reasons (see rejection_reason CHECK below).
  - PDP's average rating is computed live from every 'approved' row
    (pure ratings AND moderator-approved text reviews both count); the
    written-review list on PDP only shows 'approved' rows that actually
    have text.

One review per (product, persona) - re-rating the same product upserts
(overwrites) the previous row rather than creating a second one, since
there's no real user auth here, just a persona standing in for "whoever's
shopping" (see PERSONAS in backend/static/index.html).

Idempotent: CREATE TABLE IF NOT EXISTS, safe to re-run.

Usage:
    python CREATE_PRODUCT_REVIEWS_TABLE.py            # dry run - shows the plan, writes nothing
    python CREATE_PRODUCT_REVIEWS_TABLE.py --apply    # creates the table + indexes
"""

import os
import sys

CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS product_reviews (
        id character varying(50) PRIMARY KEY,
        product_id character varying(50) NOT NULL REFERENCES products(id),
        persona_id character varying(50) NOT NULL,
        rating integer NOT NULL CHECK (rating BETWEEN 1 AND 5),
        review_text text,
        status character varying(20) NOT NULL DEFAULT 'submitted'
            CHECK (status IN ('submitted', 'approved', 'rejected')),
        rejection_reason character varying(30)
            CHECK (rejection_reason IN ('profanity', 'not_relevant', 'needs_human_review')),
        moderated_at timestamp without time zone,
        created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
        updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (product_id, persona_id)
    );
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_product_reviews_product ON product_reviews(product_id);",
    "CREATE INDEX IF NOT EXISTS idx_product_reviews_status ON product_reviews(status);",
]


def main():
    apply_changes = "--apply" in sys.argv

    print("Plan:")
    print("  CREATE TABLE IF NOT EXISTS product_reviews (...)")
    print("    - rating 1-5 (CHECK), review_text optional")
    print("    - status: submitted / approved / rejected (CHECK)")
    print("    - rejection_reason: profanity / not_relevant / needs_human_review (CHECK)")
    print("    - UNIQUE (product_id, persona_id) - one review per shopper per product")
    print("  CREATE INDEX ... ON product_reviews(product_id)")
    print("  CREATE INDEX ... ON product_reviews(status)")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to create the table.)")
        return

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    print("\nConnecting to Neon...")
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    print("Connected.")

    cur.execute(CREATE_TABLE_SQL)
    for stmt in CREATE_INDEX_SQL:
        cur.execute(stmt)
    conn.commit()

    print("\nDone. product_reviews table (and indexes) are ready.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
