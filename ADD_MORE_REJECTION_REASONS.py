#!/usr/bin/env python3
"""
DiscoverAI: Add 'spam' and 'personal_info' rejection reasons
=================================================================

Fourth migration for the Ratings & Review feature (run after
CREATE_PRODUCT_REVIEWS_TABLE.py, CREATE_REVIEW_IMAGES_TABLE.py, and
ADD_OTHER_REJECTION_REASON.py). Rounds the rejection reason set out
from 4 to 6:
    profanity, not_relevant, needs_human_review, other,
    spam, personal_info

  - 'spam' - fake, incentivized, or clearly bot-generated reviews.
  - 'personal_info' - a review that pastes in a phone number, email,
    address, or other contact/personal info that shouldn't be public.

Same DROP + recreate CHECK constraint approach as
ADD_OTHER_REJECTION_REASON.py, since Postgres can't alter a CHECK in
place. Safe to re-run.

Usage:
    python ADD_MORE_REJECTION_REASONS.py            # dry run - shows the plan, writes nothing
    python ADD_MORE_REJECTION_REASONS.py --apply    # applies the migration
"""

import os
import sys

STATEMENTS = [
    "ALTER TABLE product_reviews DROP CONSTRAINT IF EXISTS product_reviews_rejection_reason_check;",
    """ALTER TABLE product_reviews ADD CONSTRAINT product_reviews_rejection_reason_check
        CHECK (rejection_reason IN (
            'profanity', 'not_relevant', 'needs_human_review', 'other', 'spam', 'personal_info'
        ));""",
]


def main():
    apply_changes = "--apply" in sys.argv

    print("Plan:")
    print("  DROP + recreate the rejection_reason CHECK constraint, adding 'spam' and 'personal_info'")
    print("  (full set after this: profanity, not_relevant, needs_human_review, other, spam, personal_info)")

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

    print("\nDone. 'spam' and 'personal_info' are now valid rejection_reason values.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
