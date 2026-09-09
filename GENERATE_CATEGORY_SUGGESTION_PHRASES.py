#!/usr/bin/env python3
"""
DiscoverAI: Build/refresh category-aware suggestion phrases
=================================================================

Two categories registered so far:

  Rice (hand-written recipe) - given by domain knowledge of how rice is
  actually shopped for, not a generic attribute-concatenation formula:

    Rice {pack_size}                    e.g. "Rice 5kg"
    {variety} Rice                      e.g. "Basmati Rice"
    {brand} Rice                        e.g. "India Gate Rice"
    {brand} Rice {pack_size}            e.g. "India Gate Rice 5kg"
    {variety} Rice {pack_size}          e.g. "Basmati Rice 5kg"

  Cooking Oil & Ghee (LLM-proposed recipe, see
  GENERATE_CATEGORY_RECIPE_LLM.py) - no {noun} at all, since varieties
  here are heterogeneous (some end in "Oil", some in "Ghee") and no
  single noun is safe to apply to every row:

    {brand} {variety} {pack_size}       e.g. "Amul Cow Ghee 1L"
    {variety} {pack_size}               e.g. "Cow Ghee 1L"
    {brand} {variety}                   e.g. "Amul Cow Ghee"

Plus an "Organic" prefix on every pattern above ("Organic Rice 5kg",
"Organic Basmati Rice", ...) - but ONLY generated where an organic=true
product actually exists for that specific facet combination, same
"never suggest what isn't real" principle used throughout this project.

Each pattern is driven by a live DISTINCT query against actual product
data, not a cross-product of all known brands/varieties/pack sizes - so a
brand+pack_size combo that doesn't actually exist never gets suggested.

Every category gets its own recipe function, registered in RECIPES below,
because a generic template doesn't fit every category (Rice's "brand +
variety + noun + pack" shape doesn't make sense for Fragrances or
clothing). Recipes can be hand-written (rice_recipe) or LLM-proposed and
then hardened via GENERATE_CATEGORY_RECIPE_LLM.py's validation step,
rendered here through the generic build_pattern_recipe() helper.

Connection resilience: with 2 categories now (soon more), this script
runs many more sequential queries per run than it used to, and Neon's
lower tiers can drop an idle/long-lived connection mid-run ("server
closed the connection unexpectedly") - the same issue already hit and
fixed in FINAL_PRODUCTION_EMBEDDINGS_GENERATOR.py. ResilientConn below
applies the same reconnect-and-retry pattern here.

Usage:
    python GENERATE_CATEGORY_SUGGESTION_PHRASES.py            # dry run - shows the plan, writes nothing
    python GENERATE_CATEGORY_SUGGESTION_PHRASES.py --apply    # writes new phrases, deactivates stale ones
"""

import os
import sys
import time

import psycopg2


class ResilientConn:
    """Wraps a Neon connection with automatic reconnect-and-retry on
    dropped connections. Every recipe function and every write in main()
    goes through this instead of touching psycopg2 directly, so a single
    dropped connection anywhere in a run doesn't crash the whole script."""

    MAX_RETRIES = 5

    def __init__(self, database_url):
        self.database_url = database_url
        self.conn = psycopg2.connect(database_url)
        self.cur = self.conn.cursor()

    def _reconnect(self):
        try:
            self.conn.close()
        except Exception:
            pass
        self.conn = psycopg2.connect(self.database_url)
        self.cur = self.conn.cursor()

    def _run(self, sql, params, commit):
        for attempt in range(1, self.MAX_RETRIES + 2):
            try:
                self.cur.execute(sql, params or ())
                if commit:
                    self.conn.commit()
                    return None
                return self.cur.fetchall()
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                if attempt > self.MAX_RETRIES:
                    raise
                print(
                    "    connection dropped (%s), reconnecting (attempt %d/%d)..."
                    % (str(e)[:60], attempt, self.MAX_RETRIES),
                    end=" ",
                    flush=True,
                )
                try:
                    self._reconnect()
                    print("OK")
                except Exception as reconnect_error:
                    print("reconnect failed: %s" % str(reconnect_error)[:60])
                    time.sleep(2)

    def execute(self, sql, params=None):
        """SELECT - returns fetchall() results."""
        return self._run(sql, params, commit=False)

    def execute_write(self, sql, params=None):
        """INSERT/UPDATE - commits immediately (incrementally, so a drop
        mid-run doesn't lose everything already written)."""
        self._run(sql, params, commit=True)

    def close(self):
        try:
            self.cur.close()
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass


def _distinct(rc, sql, params):
    return rc.execute(sql, params)


PATTERN_COLUMN_SQL = {
    "brand": "p.brand",
    "variety": "pa.attributes->>'variety'",
    "pack_size": "pa.pack_size",
}


def build_pattern_recipe(rc, category, patterns, noun="", organic_prefix=True):
    """Generic pattern-driven recipe builder - for LLM-designed recipes
    (see GENERATE_CATEGORY_RECIPE_LLM.py) that don't need Rice's hardcoded
    {noun} handling. For each pattern string, queries the exact DISTINCT
    combination of only the placeholders that pattern actually uses -
    never more - so nothing invented can surface, the same grounding
    principle as rice_recipe below. {noun}, when a pattern uses it, is
    substituted as a fixed value (not queried), since by the time a
    recipe reaches this function it's already been through
    validate_and_harden_recipe() in GENERATE_CATEGORY_RECIPE_LLM.py,
    which only allows a fixed noun to survive when every product in the
    category shares one common trailing word (safe to apply everywhere) -
    see that script for the full "Oil vs Ghee" story of why this matters."""
    phrases = set()
    base_where = "c.name = %s AND p.is_active = true"

    for pattern in patterns:
        needed = [key for key in ("brand", "variety", "pack_size") if f"{{{key}}}" in pattern]
        if not needed:
            continue

        select_cols = ", ".join(f"{PATTERN_COLUMN_SQL[key]} AS {key}" for key in needed)
        not_null_clause = " AND ".join(f"{PATTERN_COLUMN_SQL[key]} IS NOT NULL" for key in needed)

        for organic_only in ([False, True] if organic_prefix else [False]):
            extra = " AND pa.organic = true" if organic_only else ""
            rows = rc.execute(
                f"""
                SELECT DISTINCT {select_cols}
                FROM products p
                JOIN categories c ON c.id = p.category
                LEFT JOIN product_attributes pa ON pa.product_id = p.id
                WHERE {base_where} AND {not_null_clause}{extra}
                """,
                (category,),
            )
            for row in rows:
                values = dict(zip(needed, row))
                values["noun"] = noun
                phrase = pattern.format(**values).strip()
                phrase = " ".join(phrase.split())
                if not phrase:
                    continue
                phrases.add(f"Organic {phrase}" if organic_only else phrase)

    return {(category, p) for p in phrases}


def cooking_oil_ghee_recipe(rc):
    """Rendered from an LLM-proposed recipe (GENERATE_CATEGORY_RECIPE_LLM.py
    "Cooking Oil & Ghee"), validated and hardened before being wired in
    here. The LLM initially proposed noun="Oil" - unsafe for this category
    since varieties are heterogeneous (some end in "Oil", some in "Ghee"),
    so no single noun is true for every product. validate_and_harden_recipe()
    dropped every pattern using {noun} down to these 3 noun-independent
    baseline patterns, confirmed via live testing to produce zero
    incorrect or duplicated phrases across all real combinations in the
    catalog (90 phrases, manually reviewed)."""
    return build_pattern_recipe(
        rc,
        category="Cooking Oil & Ghee",
        patterns=[
            "{brand} {variety} {pack_size}",
            "{variety} {pack_size}",
            "{brand} {variety}",
        ],
        noun="",
        organic_prefix=True,
    )


def rice_recipe(rc):
    """Returns {phrase_text} for the Rice category, per the patterns
    documented in the module docstring."""
    category = "Rice"
    noun = "Rice"
    phrases = set()

    base_where = "c.name = %s AND p.is_active = true"

    # Rice {pack_size} - any organic status
    for (pack_size,) in _distinct(rc, f"""
        SELECT DISTINCT pa.pack_size
        FROM products p
        JOIN categories c ON c.id = p.category
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE {base_where} AND pa.pack_size IS NOT NULL
    """, (category,)):
        phrases.add(f"{noun} {pack_size}")

    # Organic Rice {pack_size} - only where an organic product with that pack_size exists
    for (pack_size,) in _distinct(rc, f"""
        SELECT DISTINCT pa.pack_size
        FROM products p
        JOIN categories c ON c.id = p.category
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE {base_where} AND pa.pack_size IS NOT NULL AND pa.organic = true
    """, (category,)):
        phrases.add(f"Organic {noun} {pack_size}")

    # {variety} Rice - any organic status
    for (variety,) in _distinct(rc, f"""
        SELECT DISTINCT pa.attributes->>'variety' AS variety
        FROM products p
        JOIN categories c ON c.id = p.category
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE {base_where} AND pa.attributes->>'variety' IS NOT NULL
    """, (category,)):
        phrases.add(f"{variety} {noun}")

    # Organic {variety} Rice - only where that variety has an organic product
    for (variety,) in _distinct(rc, f"""
        SELECT DISTINCT pa.attributes->>'variety' AS variety
        FROM products p
        JOIN categories c ON c.id = p.category
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE {base_where} AND pa.attributes->>'variety' IS NOT NULL AND pa.organic = true
    """, (category,)):
        phrases.add(f"Organic {variety} {noun}")

    # {brand} Rice - any organic status
    for (brand,) in _distinct(rc, f"""
        SELECT DISTINCT p.brand
        FROM products p
        JOIN categories c ON c.id = p.category
        WHERE {base_where} AND p.brand IS NOT NULL
    """, (category,)):
        phrases.add(f"{brand} {noun}")

    # Organic {brand} Rice - only where that brand has an organic product
    for (brand,) in _distinct(rc, f"""
        SELECT DISTINCT p.brand
        FROM products p
        JOIN categories c ON c.id = p.category
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE {base_where} AND p.brand IS NOT NULL AND pa.organic = true
    """, (category,)):
        phrases.add(f"Organic {brand} {noun}")

    # {brand} Rice {pack_size} - only real co-occurring combos
    for (brand, pack_size) in _distinct(rc, f"""
        SELECT DISTINCT p.brand, pa.pack_size
        FROM products p
        JOIN categories c ON c.id = p.category
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE {base_where} AND p.brand IS NOT NULL AND pa.pack_size IS NOT NULL
    """, (category,)):
        phrases.add(f"{brand} {noun} {pack_size}")

    # Organic {brand} Rice {pack_size} - only real organic co-occurring combos
    for (brand, pack_size) in _distinct(rc, f"""
        SELECT DISTINCT p.brand, pa.pack_size
        FROM products p
        JOIN categories c ON c.id = p.category
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE {base_where} AND p.brand IS NOT NULL AND pa.pack_size IS NOT NULL AND pa.organic = true
    """, (category,)):
        phrases.add(f"Organic {brand} {noun} {pack_size}")

    # {variety} Rice {pack_size} - only real co-occurring combos
    for (variety, pack_size) in _distinct(rc, f"""
        SELECT DISTINCT pa.attributes->>'variety' AS variety, pa.pack_size
        FROM products p
        JOIN categories c ON c.id = p.category
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE {base_where} AND pa.attributes->>'variety' IS NOT NULL AND pa.pack_size IS NOT NULL
    """, (category,)):
        phrases.add(f"{variety} {noun} {pack_size}")

    # Organic {variety} Rice {pack_size} - only real organic co-occurring combos
    for (variety, pack_size) in _distinct(rc, f"""
        SELECT DISTINCT pa.attributes->>'variety' AS variety, pa.pack_size
        FROM products p
        JOIN categories c ON c.id = p.category
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE {base_where} AND pa.attributes->>'variety' IS NOT NULL AND pa.pack_size IS NOT NULL AND pa.organic = true
    """, (category,)):
        phrases.add(f"Organic {variety} {noun} {pack_size}")

    return {(category, p) for p in phrases}


# Registry: add one entry per category as recipes get built out.
# Rice was hand-written; Cooking Oil & Ghee came from
# GENERATE_CATEGORY_RECIPE_LLM.py, validated and hardened before landing
# here - see cooking_oil_ghee_recipe()'s docstring for that story.
RECIPES = {
    "Rice": rice_recipe,
    "Cooking Oil & Ghee": cooking_oil_ghee_recipe,
}


def fetch_current_phrases(rc):
    """Returns {(category, phrase_text)} across every registered recipe."""
    all_phrases = set()
    for category, recipe_fn in RECIPES.items():
        all_phrases |= recipe_fn(rc)
    return all_phrases


def main():
    apply_changes = "--apply" in sys.argv

    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    print("Connecting to Neon...")
    rc = ResilientConn(database_url)
    print("Connected.\n")

    current_phrases = fetch_current_phrases(rc)
    by_category = {}
    for category, phrase_text in current_phrases:
        by_category.setdefault(category, 0)
        by_category[category] += 1
    print("Current phrases from recipes: %s  (total %d)" % (dict(by_category), len(current_phrases)))

    existing_rows = {
        (r[0], r[1]): r[2]
        for r in rc.execute("SELECT category, phrase_text, is_active FROM category_suggestion_phrases")
    }
    existing_phrases = set(existing_rows.keys())

    to_add = current_phrases - existing_phrases
    to_reactivate = {t for t in current_phrases & existing_phrases if existing_rows[t] is False}
    to_deactivate = existing_phrases - current_phrases
    unchanged = (current_phrases & existing_phrases) - to_reactivate

    print("\nNew phrases to insert: %d" % len(to_add))
    print("Phrases to reactivate (were deactivated, now present again): %d" % len(to_reactivate))
    print("Phrases to deactivate (no longer valid): %d" % len(to_deactivate))
    print("Unchanged (skipped entirely): %d" % len(unchanged))

    if to_add:
        print("\nNew phrases (sample up to 40):")
        for category, phrase_text in sorted(to_add)[:40]:
            print("  [%s] %r" % (category, phrase_text))
        if len(to_add) > 40:
            print("  ... and %d more" % (len(to_add) - 40))
    if to_deactivate:
        print("\nDeactivating:")
        for category, phrase_text in sorted(to_deactivate):
            print("  [%s] %r" % (category, phrase_text))

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.)")
        rc.close()
        return

    for category, phrase_text in to_add:
        rc.execute_write(
            """
            INSERT INTO category_suggestion_phrases (category, phrase_text, is_active)
            VALUES (%s, %s, true)
            ON CONFLICT (category, phrase_text) DO UPDATE SET
                is_active = true, updated_at = CURRENT_TIMESTAMP
            """,
            (category, phrase_text),
        )

    for category, phrase_text in to_reactivate:
        rc.execute_write(
            "UPDATE category_suggestion_phrases SET is_active = true, updated_at = CURRENT_TIMESTAMP "
            "WHERE category = %s AND phrase_text = %s",
            (category, phrase_text),
        )

    for category, phrase_text in to_deactivate:
        rc.execute_write(
            "UPDATE category_suggestion_phrases SET is_active = false, updated_at = CURRENT_TIMESTAMP "
            "WHERE category = %s AND phrase_text = %s",
            (category, phrase_text),
        )

    print("\nDone. +%d new, %d reactivated, %d deactivated, %d unchanged." % (
        len(to_add), len(to_reactivate), len(to_deactivate), len(unchanged)
    ))

    rc.close()


if __name__ == "__main__":
    main()
