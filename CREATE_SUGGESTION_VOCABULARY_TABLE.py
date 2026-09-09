#!/usr/bin/env python3
"""
DiscoverAI: Create suggestion_vocabulary table + enable pg_trgm
====================================================================

Backend for the actual Auto Suggestion feature (see
requirements/auto_suggestion_ai_pm_plan.md, "Auto Suggestion - Second
Iteration"). Stores a FLAT vocabulary of individual facet terms (category
names, brand names, variety values) - not precomputed combinations, which
was tried and rejected for not generalizing past 2 typed facets.

  - embedding: used only by the offline vocabulary-build job
    (GENERATE_SUGGESTION_VOCABULARY.py) - never called live per keystroke.
  - pg_trgm (Postgres trigram similarity extension): used by the live
    /api/auto-suggest endpoint for fast, local, indexed fuzzy matching of
    the customer's typed text against term_text - no embedding calls in
    the per-keystroke path, which is what keeps it fast.

Usage:
    python CREATE_SUGGESTION_VOCABULARY_TABLE.py            # dry run
    python CREATE_SUGGESTION_VOCABULARY_TABLE.py --apply    # creates the table + extension
"""

import os
import sys

CREATE_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS suggestion_vocabulary (
    id BIGSERIAL PRIMARY KEY,
    term_text VARCHAR(255) NOT NULL,
    facet_type VARCHAR(20) NOT NULL CHECK (facet_type IN ('category', 'brand', 'variety')),
    embedding vector,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (facet_type, term_text)
);
"""

CREATE_TRGM_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_suggestion_vocab_trgm
ON suggestion_vocabulary USING gin (term_text gin_trgm_ops);
"""

CREATE_ACTIVE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_suggestion_vocab_active
ON suggestion_vocabulary (facet_type, is_active);
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
    print("  - CREATE EXTENSION IF NOT EXISTS pg_trgm")
    print("  - CREATE TABLE IF NOT EXISTS suggestion_vocabulary (term_text, facet_type, embedding, is_active)")
    print("  - CREATE INDEX ... USING gin (term_text gin_trgm_ops)  -- fast fuzzy matching")
    print("  - CREATE INDEX ... (facet_type, is_active)")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.)")
        cur.close()
        conn.close()
        return

    cur.execute(CREATE_EXTENSION_SQL)
    cur.execute(CREATE_TABLE_SQL)
    cur.execute(CREATE_TRGM_INDEX_SQL)
    cur.execute(CREATE_ACTIVE_INDEX_SQL)
    conn.commit()

    print("\nDone.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
