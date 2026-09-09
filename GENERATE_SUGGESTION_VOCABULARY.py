#!/usr/bin/env python3
"""
DiscoverAI: Build/refresh the Auto Suggestion vocabulary
=============================================================

One script, two jobs (same logic, see requirements/auto_suggestion_ai_pm_plan.md):
  - Run once with an empty suggestion_vocabulary table -> full initial build.
  - Run daily thereafter -> the delta: new terms get embedded and inserted,
    terms no longer present in the catalog get soft-deactivated, unchanged
    terms are skipped entirely (no re-embedding, no OpenAI cost).

Facets embedded: category names, brands, variety values (the ones with
open-ended, fuzzy vocabularies). Organic (boolean) and pack_size
(number+unit) are deliberately NOT embedded - they're recognized live via
simple keyword/regex checks, not semantic matching.

Usage:
    python GENERATE_SUGGESTION_VOCABULARY.py            # dry run - shows the plan, writes nothing
    python GENERATE_SUGGESTION_VOCABULARY.py --apply    # embeds new terms, deactivates stale ones
"""

import json
import os
import sys

EMBEDDING_MODEL = "text-embedding-3-small"


def fetch_categories_with_products(cur):
    """Every category name that is the DIRECT category of at least one
    active product - i.e. exactly the condition the live drill-down query
    relies on (`c.name = %s` joined via `p.category = c.id`).

    Earlier version required the category to also be a tree LEAF (no
    children), on the theory that non-leaf categories are never a
    product's direct category. That's wrong for this catalog: "Rice" has
    child nodes in the tree (e.g. "Basmati Rice") but real rice products
    are tagged directly to "Rice" itself, with the variety captured in
    product_attributes instead of via the child category. The leaf check
    silently excluded "Rice" from the vocabulary entirely. Whether a
    category has children is irrelevant here - the only thing that
    matters is whether it's ever actually used as a product's category,
    which is exactly what this query checks directly."""
    cur.execute("""
        SELECT DISTINCT c.name
        FROM products p
        JOIN categories c ON c.id = p.category
        WHERE p.is_active = true AND c.name IS NOT NULL
    """)
    return {name.strip() for (name,) in cur.fetchall() if name and name.strip()}


def fetch_current_terms(cur):
    """Returns {(facet_type, term_text)} - every term that should currently
    be considered part of the vocabulary, straight from live catalog data."""
    terms = set()

    for name in fetch_categories_with_products(cur):
        terms.add(("category", name))

    cur.execute("SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL AND is_active = true")
    for (brand,) in cur.fetchall():
        if brand.strip():
            terms.add(("brand", brand.strip()))

    cur.execute("""
        SELECT DISTINCT attributes->>'variety' AS variety
        FROM product_attributes
        WHERE attributes->>'variety' IS NOT NULL
    """)
    for (variety,) in cur.fetchall():
        if variety and variety.strip():
            terms.add(("variety", variety.strip()))

    return terms


def main():
    apply_changes = "--apply" in sys.argv

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not database_url:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)
    if not openai_api_key:
        print("ERROR: OPENAI_API_KEY not set.")
        sys.exit(1)

    print("Connecting to Neon...")
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    print("Connected.\n")

    current_terms = fetch_current_terms(cur)
    by_facet = {}
    for facet_type, term_text in current_terms:
        by_facet.setdefault(facet_type, 0)
        by_facet[facet_type] += 1
    print("Current catalog terms: %s  (total %d)" % (dict(by_facet), len(current_terms)))

    cur.execute("SELECT facet_type, term_text, is_active FROM suggestion_vocabulary")
    existing_rows = {(r[0], r[1]): r[2] for r in cur.fetchall()}
    existing_terms = set(existing_rows.keys())

    to_add = current_terms - existing_terms
    to_reactivate = {t for t in current_terms & existing_terms if existing_rows[t] is False}
    to_deactivate = existing_terms - current_terms
    unchanged = (current_terms & existing_terms) - to_reactivate

    print("\nNew terms to embed + insert: %d" % len(to_add))
    print("Terms to reactivate (were deactivated, now present again - no re-embedding needed): %d" % len(to_reactivate))
    print("Terms to deactivate (no longer in catalog): %d" % len(to_deactivate))
    print("Unchanged (skipped entirely): %d" % len(unchanged))

    if to_add:
        print("\nNew terms:")
        for facet_type, term_text in sorted(to_add):
            print("  [%s] %r" % (facet_type, term_text))
    if to_deactivate:
        print("\nDeactivating:")
        for facet_type, term_text in sorted(to_deactivate):
            print("  [%s] %r" % (facet_type, term_text))

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.)")
        cur.close()
        conn.close()
        return

    if to_add:
        from openai import OpenAI
        client = OpenAI(api_key=openai_api_key)
        print()
        for i, (facet_type, term_text) in enumerate(sorted(to_add), start=1):
            print("  [%d/%d] embedding [%s] %r..." % (i, len(to_add), facet_type, term_text), end=" ", flush=True)
            try:
                response = client.embeddings.create(model=EMBEDDING_MODEL, input=term_text)
                embedding = response.data[0].embedding
                cur.execute(
                    """
                    INSERT INTO suggestion_vocabulary (term_text, facet_type, embedding, is_active)
                    VALUES (%s, %s, %s::vector, true)
                    ON CONFLICT (facet_type, term_text) DO UPDATE SET
                        embedding = EXCLUDED.embedding, is_active = true, updated_at = CURRENT_TIMESTAMP
                    """,
                    (term_text, facet_type, json.dumps(embedding)),
                )
                print("OK")
            except Exception as e:
                print("FAILED: %s" % e)
        conn.commit()

    if to_reactivate:
        for facet_type, term_text in to_reactivate:
            cur.execute(
                "UPDATE suggestion_vocabulary SET is_active = true, updated_at = CURRENT_TIMESTAMP "
                "WHERE facet_type = %s AND term_text = %s",
                (facet_type, term_text),
            )
        conn.commit()

    if to_deactivate:
        for facet_type, term_text in to_deactivate:
            cur.execute(
                "UPDATE suggestion_vocabulary SET is_active = false, updated_at = CURRENT_TIMESTAMP "
                "WHERE facet_type = %s AND term_text = %s",
                (facet_type, term_text),
            )
        conn.commit()

    print("\nDone. +%d new, %d reactivated, %d deactivated, %d unchanged." % (
        len(to_add), len(to_reactivate), len(to_deactivate), len(unchanged)
    ))

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
