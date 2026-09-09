#!/usr/bin/env python3
"""
DiscoverAI: Create the review_images table (Ratings & Reviews module)
=========================================================================

Second migration for the Ratings & Review feature (run after
CREATE_PRODUCT_REVIEWS_TABLE.py) - adds photo attachments to a review.

Product rules this supports (see reviews_routes.py):
  - Up to 5 images per review, 5MB combined (not per-image) - enforced
    in the API, not by this schema, but file_size_bytes is stored per
    row so that total is auditable/recomputable later if the limit
    ever changes.
  - Images live on disk under backend/static/review_images/<review_id>/
    (this app already serves /static from Flask - no S3/CDN needed,
    consistent with how product photos work) - this table just stores
    the resulting URL, not the bytes themselves.
  - Resubmitting a review (same product+persona) REPLACES its images,
    not appends - see reviews_routes.py's submit_review(), which
    deletes old rows (and old files) before inserting new ones.
  - Images ride along with the review through moderation - there's no
    separate approve/reject for images, they inherit product_reviews.status
    via the review_id FK. ON DELETE CASCADE so removing a review (not
    currently exposed, but for safety) cleans up its image rows too.

Idempotent: CREATE TABLE IF NOT EXISTS, safe to re-run.

Usage:
    python CREATE_REVIEW_IMAGES_TABLE.py            # dry run - shows the plan, writes nothing
    python CREATE_REVIEW_IMAGES_TABLE.py --apply    # creates the table + index
"""

import os
import sys

CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS review_images (
        id character varying(50) PRIMARY KEY,
        review_id character varying(50) NOT NULL REFERENCES product_reviews(id) ON DELETE CASCADE,
        image_url character varying(500) NOT NULL,
        file_size_bytes integer,
        position integer NOT NULL DEFAULT 0,
        created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
    );
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_review_images_review ON review_images(review_id);",
]


def main():
    apply_changes = "--apply" in sys.argv

    print("Plan:")
    print("  CREATE TABLE IF NOT EXISTS review_images (...)")
    print("    - review_id REFERENCES product_reviews(id) ON DELETE CASCADE")
    print("    - image_url, file_size_bytes, position (display order)")
    print("  CREATE INDEX ... ON review_images(review_id)")

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

    cur.execute("SELECT to_regclass('product_reviews');")
    if cur.fetchone()[0] is None:
        print("\nERROR: product_reviews table doesn't exist yet.")
        print("Run CREATE_PRODUCT_REVIEWS_TABLE.py --apply first.")
        cur.close()
        conn.close()
        sys.exit(1)

    cur.execute(CREATE_TABLE_SQL)
    for stmt in CREATE_INDEX_SQL:
        cur.execute(stmt)
    conn.commit()

    print("\nDone. review_images table (and index) are ready.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
