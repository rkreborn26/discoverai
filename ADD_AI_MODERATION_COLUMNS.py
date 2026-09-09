#!/usr/bin/env python3
"""
DiscoverAI: Add AI Moderation columns to product_reviews
=============================================================

Schema for the agentic AI moderation feature (see AI_Moderation_PRD.docx
and AI_Moderation_Intent_Specification.docx for the full design). Adds
the AI's own recommendation alongside the existing human decision
columns - never overwrites status/rejection_reason/rejection_note/
moderated_at, which keep meaning exactly what they mean today (the
moderator's final call).

New columns on product_reviews:
  - ai_decision          'approved' | 'rejected' | NULL (NULL = AI
                          moderation hasn't been run for this review yet)
  - ai_rejection_reason   same 8-code taxonomy as rejection_reason
                          (see below), NULL when ai_decision is 'approved'
                          or hasn't run yet
  - ai_note               AI-written explanation - always populated for
                          'other'/'needs_human_review', assembled from
                          every contributing agent's note otherwise
  - ai_confidence         numeric 0.00-1.00, confidence of the winning
                          check specifically (not an average across agents)
  - ai_agent_trace        jsonb - every agent's verdict from the run, for
                          auditability (see Intent Spec Section 4)
  - ai_moderated_at       timestamp - when the AI run completed
  - moderator_agreed      boolean, NULL until a human acts on the review -
                          true if the human's final status/rejection_reason
                          matches ai_decision/ai_rejection_reason, false
                          otherwise. Powers the accuracy metric directly.

Also extends the rejection_reason taxonomy (both the existing human
column AND the new ai_rejection_reason column share the same 8 codes)
from 6 to 8, adding:
  - 'hate_speech'  - targeted hate/discrimination against a person or
    group. Previously had no code of its own (fell under 'profanity');
    split out because it's higher-severity and gets its own AI agent.
  - 'image_policy' - a photo that doesn't show the product, is offensive,
    or is a stock/watermarked image rather than a genuine customer photo.
    Previously had no code at all (had to be filed as 'other').

Same DROP + recreate CHECK constraint approach as
ADD_OTHER_REJECTION_REASON.py / ADD_MORE_REJECTION_REASONS.py, since
Postgres can't alter a CHECK in place. Idempotent, safe to re-run.

Usage:
    python ADD_AI_MODERATION_COLUMNS.py            # dry run - shows the plan, writes nothing
    python ADD_AI_MODERATION_COLUMNS.py --apply    # applies the migration
"""

import os
import sys

FULL_REASON_SET = (
    "'profanity', 'not_relevant', 'needs_human_review', 'other', 'spam', "
    "'personal_info', 'hate_speech', 'image_policy'"
)

STATEMENTS = [
    # Extend the existing human rejection_reason taxonomy to 8 codes.
    "ALTER TABLE product_reviews DROP CONSTRAINT IF EXISTS product_reviews_rejection_reason_check;",
    f"""ALTER TABLE product_reviews ADD CONSTRAINT product_reviews_rejection_reason_check
        CHECK (rejection_reason IN ({FULL_REASON_SET}));""",

    # New AI columns.
    "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS ai_decision character varying(20);",
    "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS ai_rejection_reason character varying(50);",
    "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS ai_note text;",
    "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS ai_confidence numeric(3,2);",
    "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS ai_agent_trace jsonb;",
    "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS ai_moderated_at timestamp without time zone;",
    "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS moderator_agreed boolean;",

    # CHECK constraints on the new AI columns, same taxonomy.
    "ALTER TABLE product_reviews DROP CONSTRAINT IF EXISTS product_reviews_ai_decision_check;",
    """ALTER TABLE product_reviews ADD CONSTRAINT product_reviews_ai_decision_check
        CHECK (ai_decision IS NULL OR ai_decision IN ('approved', 'rejected'));""",
    "ALTER TABLE product_reviews DROP CONSTRAINT IF EXISTS product_reviews_ai_rejection_reason_check;",
    f"""ALTER TABLE product_reviews ADD CONSTRAINT product_reviews_ai_rejection_reason_check
        CHECK (ai_rejection_reason IS NULL OR ai_rejection_reason IN ({FULL_REASON_SET}));""",
]


def main():
    apply_changes = "--apply" in sys.argv

    print("Plan:")
    print("  1. DROP + recreate rejection_reason CHECK, adding 'hate_speech' and 'image_policy'")
    print("     (full set after this: profanity, not_relevant, needs_human_review, other,")
    print("      spam, personal_info, hate_speech, image_policy)")
    print("  2. ADD COLUMN IF NOT EXISTS x7: ai_decision, ai_rejection_reason, ai_note,")
    print("     ai_confidence, ai_agent_trace, ai_moderated_at, moderator_agreed")
    print("  3. CHECK constraints on ai_decision / ai_rejection_reason (same 8-code taxonomy)")

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

    print("\nDone. product_reviews now has AI moderation columns, and the rejection")
    print("reason taxonomy includes 'hate_speech' and 'image_policy'.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
