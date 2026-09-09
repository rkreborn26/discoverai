#!/usr/bin/env python3
"""
DiscoverAI: Create category_suggestion_phrases table
==========================================================

Replaces the flat-facet approach (suggestion_vocabulary + live drill-down)
with precomputed, category-aware, natural-language suggestion phrases.

Why: the flat-facet approach decomposed a query into independent
category/brand facets via generic trigram matching, then reassembled them
with one formatting function that didn't know Rice should read differently
from Fragrances. That caused a string of bugs (case sensitivity, trigram
argument-order, brand crowding, catalog-wide fallback into unrelated
departments) all rooted in the same design flaw. This table instead
stores finished phrases, built offline per category using domain
knowledge of how that category is naturally described (see
GENERATE_CATEGORY_SUGGESTION_PHRASES.py) - so at request time the
endpoint just ranks precomputed strings, no live product-table joins,
no facet recomposition.

  - phrase_text: the finished suggestion string, e.g. "India Gate Rice 5kg"
  - category: which category this phrase belongs to (informational -
    matching at request time is across ALL active phrases regardless of
    category, since the phrase text itself already carries that meaning)
  - is_active: soft-deactivated when the underlying combination no longer
    exists in the catalog (same delta pattern as the rest of this project)

Usage:
    python CREATE_CATEGORY_SUGGESTION_PHRASES_TABLE.py            # dry run
    python CREATE_CATEGORY_SUGGESTION_PHRASES_TABLE.py --apply    # creates the table
"""

import os
import sys

CREATE_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS category_suggestion_phrases (
    id BIGSERIAL PRIMARY KEY,
    category VARCHAR(255) NOT NULL,
    phrase_text VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (category, phrase_text)
);
"""

CREATE_TRGM_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_category_suggestion_phrases_trgm
ON category_suggestion_phrases USING gin (phrase_text gin_trgm_ops);
"""

CREATE_ACTIVE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_category_suggestion_phrases_active
ON category_suggestion_phrases (is_active);
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
    print("  - CREATE TABLE IF NOT EXISTS category_suggestion_phrases (category, phrase_text, is_active)")
    print("  - CREATE INDEX ... USING gin (phrase_text gin_trgm_ops)  -- fast fuzzy matching")
    print("  - CREATE INDEX ... (is_active)")

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
