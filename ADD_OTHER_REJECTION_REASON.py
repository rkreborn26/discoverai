#!/usr/bin/env python3
"""
DiscoverAI: Add an 'Other' rejection reason (+ free-text note) to reviews
=============================================================================

Third migration for the Ratings & Review feature (run after
CREATE_PRODUCT_REVIEWS_TABLE.py and CREATE_REVIEW_IMAGES_TABLE.py).

Retailer Admin's Review Moderation panel had exactly 3 fixed rejection
reasons (profanity / not_relevant / needs_human_review) - no escape
hatch for a real rejection that doesn't cleanly fit one of those. This
adds a 4th: 'other', paired with a new `rejection_note` free-text
column that's required whenever a moderator picks it (enforced in
reviews_routes.py's reject_review(), not just the frontend) - so
"Other" always comes with an explanation, never a bare unexplained
rejection.

Postgres CHECK constraints can't be altered in place, so this drops and
recreates the one on rejection_reason - safe to re-run (DROP CONSTRAINT
IF EXISTS, ADD COLUMN IF NOT EXISTS).

Usage:
    python ADD_OTHER_REJECTION_REASON.py            # dry run - shows the plan, writes nothing
    python ADD_OTHER_REJECTION_REASON.py --apply    # applies the migration
"""

import os
import sys

STATEMENTS = [
    "ALTER TABLE product_reviews DROP CONSTRAINT IF EXISTS product_reviews_rejection_reason_check;",
    """ALTER TABLE product_reviews ADD CONSTRAINT product_reviews_rejection_reason_check
        CHECK (rejection_reason IN ('profanity', 'not_relevant', 'needs_human_review', 'other'));""",
    "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS rejection_note text;",
]


def main():
    apply_changes = "--apply" in sys.argv

    print("Plan:")
    print("  DROP + recreate the rejection_reason CHECK constraint, adding 'other'")
    print("  ADD COLUMN rejection_note text (free-text explanation, required when reason='other')")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to apply this migration.)")
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

    cur.execute("SELECT to_regclass('product_reviews');")
    if cur.fetchone()[0] is None:
        print("\nERROR: product_reviews table doesn't exist yet.")
        print("Run CREATE_PRODUCT_REVIEWS_TABLE.py --apply first.")
        cur.close()
        conn.close()
        sys.exit(1)

    for stmt in STATEMENTS:
        cur.execute(stmt)
    conn.commit()

    print("\nDone. 'other' is now a valid rejection_reason, and rejection_note is ready to use.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
