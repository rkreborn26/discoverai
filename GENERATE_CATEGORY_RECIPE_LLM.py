#!/usr/bin/env python3
"""
DiscoverAI: LLM-generated category suggestion recipe (prototype)
======================================================================

Instead of a human hand-writing a suggestion "recipe" per category (the
Rice recipe in GENERATE_CATEGORY_SUGGESTION_PHRASES.py was written by
hand), this asks an LLM to design the recipe - given the category's real
attribute data, propose the natural phrasing pattern for that category.

This is offline, one-time-per-category authoring, NOT part of the live
per-keystroke path - so none of the latency concerns that ruled out
embeddings in the online auto-suggest endpoint apply here.

Grounding stays with the deterministic pipeline, not the LLM: the LLM
only proposes the STRUCTURE (which attributes, what order, when to
include a noun, when Organic applies) - it does not invent phrases. Every
candidate phrase this script prints is rendered by our own code against
real (brand, variety, pack_size, organic) combinations that actually
exist in the catalog, the same "never suggest what isn't real" rule used
everywhere else in this project. The LLM never gets to hallucinate a
brand/pack_size combo that doesn't exist - it only judges phrasing.

This is a REVIEW PROTOTYPE - it prints the proposed recipe and the
phrases it would generate, but writes nothing to the database. A human
(you) reviews the output before it's ever wired into
GENERATE_CATEGORY_SUGGESTION_PHRASES.py's RECIPES registry.

Usage:
    python GENERATE_CATEGORY_RECIPE_LLM.py "Cooking Oil & Ghee"
"""

import json
import os
import sys

CHAT_MODEL = "gpt-4o-mini"

# Unconditionally guaranteed regardless of what the LLM proposes - these
# never use {noun}, so they're safe for any category shaped like this one
# (has brand/variety/pack_size attributes), and basic structural coverage
# isn't left to the LLM's non-deterministic discretion. See the docstring
# on validate_and_harden_recipe for why this was added.
BASELINE_PATTERNS = [
    "{brand} {variety} {pack_size}",
    "{variety} {pack_size}",
    "{brand} {variety}",
]

# Given to the LLM as a worked example of the schema and the kind of
# judgment we want - this is the Rice recipe we wrote by hand, expressed
# in the same JSON shape we're asking the LLM to produce.
RICE_EXAMPLE = {
    "category": "Rice",
    "noun": "Rice",
    "patterns": [
        "{noun} {pack_size}",
        "{variety} {noun}",
        "{brand} {noun}",
        "{brand} {noun} {pack_size}",
        "{variety} {noun} {pack_size}",
    ],
    "organic_prefix": True,
    "notes": (
        "Variety values for Rice (Basmati, Sona Masuri, Brown Rice) do NOT "
        "already contain the word 'Rice', so every pattern re-appends "
        "{noun}='Rice' explicitly."
    ),
}

SYSTEM_PROMPT = """You design search-suggestion phrasing recipes for an e-commerce catalog.

You will be given: a product category name, its parent category, and a sample of
real (brand, variety, pack_size, organic) attribute combinations that actually
exist in the catalog for that category.

Your job: propose a JSON "recipe" describing how customers naturally search for
products in this category - which attributes to combine, in what order, and
whether a generic category noun needs to be appended.

CRITICAL judgment call: look at the actual "variety" values you're given. If a
variety value already reads naturally as a complete product name (e.g. "Cow
Ghee", "Mustard Oil" - it already contains the product noun), do NOT append a
separate {noun} to patterns that include {variety} - that would produce an
awkward, redundant phrase (e.g. "Cow Ghee Ghee"). Only append {noun} where the
variety is a pure modifier that doesn't stand alone (e.g. "Basmati" needs
"Rice" appended to make sense).

Respond with ONLY a JSON object matching this exact schema:
{
  "category": "<category name>",
  "noun": "<generic noun to append, or empty string if variety values already
           stand alone as complete product names>",
  "patterns": ["<list of pattern strings using {brand}, {variety}, {pack_size},
                and optionally {noun} placeholders>"],
  "organic_prefix": <true or false - whether an "Organic {phrase}" variant
                     makes sense for this category>,
  "notes": "<1-2 sentences explaining your reasoning, especially about the
             noun/variety judgment call above>"
}

Do not invent brands, varieties, or pack sizes beyond what's given to you - you
are designing the PATTERN, not the specific product list."""


def fetch_category_context(cur, category_name):
    cur.execute("SELECT id, parent_id, name FROM categories WHERE name = %s", (category_name,))
    row = cur.fetchone()
    if not row:
        return None, None
    cat_id, parent_id, name = row
    parent_name = None
    if parent_id:
        cur.execute("SELECT name FROM categories WHERE id = %s", (parent_id,))
        parent_row = cur.fetchone()
        if parent_row:
            parent_name = parent_row[0]
    return cat_id, parent_name


def fetch_sample_combos(cur, category_name, limit=40):
    cur.execute(
        """
        SELECT DISTINCT p.brand, pa.attributes->>'variety' AS variety, pa.pack_size, pa.organic
        FROM products p
        JOIN categories c ON c.id = p.category
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE c.name = %s AND p.is_active = true
        LIMIT %s
        """,
        (category_name, limit),
    )
    return cur.fetchall()


def _common_variety_noun(combos):
    """If every non-null variety ends with the same last word (like Rice,
    where every variety - Basmati, Sona Masuri, Brown Rice - is a pure
    modifier and none of them ends in a product-type word of its own),
    that word is a safe category-wide noun. If varieties end in DIFFERENT
    words (Cooking Oil & Ghee: some end in "Oil", some in "Ghee"), there
    is no single noun that's true for every product in the category -
    returns None in that case."""
    last_words = set()
    for _, variety, _, _ in combos:
        if variety:
            last_words.add(variety.strip().split()[-1].lower())
    if len(last_words) == 1:
        return next(iter(last_words))
    return None


def validate_and_harden_recipe(recipe, combos):
    """Deterministic safety net that does NOT depend on the LLM following
    instructions correctly - live testing on "Cooking Oil & Ghee" showed
    it won't always, in two rounds:

      Round 1 (raw LLM output): noun="Oil" plus a pattern with neither
      {variety} nor any per-row check produced "Amul Oil 1L" for a
      product whose actual variety is "Cow Ghee" - factually wrong, and
      "Mustard Oil Oil" - duplicated.

      Round 2 (after dropping only the {noun}-without-{variety} patterns
      and adding a per-row "does variety already END WITH noun" dedup):
      the exact-suffix dedup fixed "Mustard Oil Oil" (variety "Groundnut
      Oil" ends with "Oil", so the extra "Oil" got dropped for that row)
      but MISSED "Cow Ghee Oil 500ml" - "Cow Ghee" doesn't end with
      "Oil", so the dedup didn't trigger, and the pattern still had
      {variety} so it wasn't in the dropped set either. The suffix check
      only detects redundancy (variety already says the same word); it
      can't detect a genuine CONFLICT (variety says a different product
      type than the fixed noun value) - "Cow Ghee" ending in "Ghee"
      instead of "Oil" is a conflict, not an omission.

    The category-level fix in round 1 (removing {noun}-without-{variety}
    patterns) already correctly reduces `noun` to unreliable-per-row
    information the moment varieties don't share one common trailing
    word. The only fully safe response to that is to stop using {noun}
    in ANY pattern for a heterogeneous category, not just the ones
    missing {variety} - there's no per-row rule that can tell, generically,
    whether "Oil" happens to be right for this specific row without
    already knowing all the category's real product-type words (which is
    exactly the ambiguity that made the category heterogeneous in the
    first place).

    One more thing found live: the LLM is non-deterministic, so recipe
    COMPLETENESS varies run to run even once correctness is handled - one
    call proposed 5 patterns, a later call for the same category proposed
    only 3, and losing 2 of those to the {noun} safety check left just 1
    surviving pattern, dropping perfectly safe, useful phrases like
    "Cow Ghee 1L" (variety+pack, no brand) purely because that particular
    call didn't think to include the pattern - not because it was unsafe.
    BASELINE_PATTERNS below are unconditionally guaranteed regardless of
    what the LLM proposes: they never use {noun}, so they're safe for any
    category shaped like this one (has brand/variety/pack_size), and
    completeness for them isn't left up to chance. The LLM's proposed
    patterns are merged on top - its only real job is the judgment call
    (does a noun apply, does Organic apply, any extra creative patterns),
    not guaranteeing basic structural coverage."""
    common_noun = _common_variety_noun(combos)
    noun = (recipe.get("noun") or "").strip()
    patterns = list(recipe.get("patterns") or [])
    warnings = []

    if noun and common_noun is None:
        unsafe = [p for p in patterns if "{noun}" in p]
        if unsafe:
            warnings.append(
                "Varieties in this category don't share one common noun (heterogeneous - "
                "e.g. Oil vs Ghee), so noun=%r cannot be validated per-row even in patterns "
                "that also include {variety} (would append 'Oil' onto a Ghee product, e.g. "
                "'Cow Ghee Oil'). Dropping every pattern that uses {noun}: %s" % (noun, unsafe)
            )
            patterns = [p for p in patterns if "{noun}" not in p]
        noun = ""

    added_baseline = [p for p in BASELINE_PATTERNS if p not in patterns]
    if added_baseline:
        warnings.append(
            "LLM's proposed patterns didn't include some structurally-safe baseline "
            "patterns (these never depend on {noun}, so completeness for them "
            "shouldn't be left to chance): adding %s" % added_baseline
        )
        patterns = patterns + added_baseline

    recipe = dict(recipe)
    recipe["noun"] = noun
    recipe["patterns"] = patterns
    return recipe, warnings


def render_phrases(recipe, combos):
    """Render the (validated/hardened) recipe against real combos - the
    same grounding principle as GENERATE_CATEGORY_SUGGESTION_PHRASES.py:
    only render a pattern when every placeholder it strictly needs
    (brand/variety/pack_size) is actually present in that combo, so
    nothing invented ever surfaces. {noun} is treated as always-optional
    here (never blocks rendering) - it either contributes a word or
    quietly drops out, which is what lets the per-row dedup below work
    without skipping the whole phrase."""
    noun = (recipe.get("noun") or "").strip()
    patterns = recipe.get("patterns") or []
    organic_prefix = bool(recipe.get("organic_prefix"))

    phrases = set()
    for brand, variety, pack_size, organic in combos:
        row_noun = noun
        if row_noun and variety and variety.strip().lower().endswith(row_noun.lower()):
            # this row's variety already ends with the noun - drop it for
            # this row only, instead of duplicating ("Cow Ghee" + "Ghee").
            row_noun = ""
        values = {"brand": brand, "variety": variety, "pack_size": pack_size, "noun": row_noun}
        for pattern in patterns:
            needed = [key for key in ("brand", "variety", "pack_size") if f"{{{key}}}" in pattern]
            if any(not values.get(key) for key in needed):
                continue
            phrase = pattern.format(**values).strip()
            phrase = " ".join(phrase.split())  # collapse any double spaces from empty {noun}
            if not phrase:
                continue
            phrases.add(phrase)
            if organic_prefix and organic:
                phrases.add(f"Organic {phrase}")
    return sorted(phrases)


def main():
    if len(sys.argv) < 2:
        print('Usage: python GENERATE_CATEGORY_RECIPE_LLM.py "<category name>"')
        sys.exit(1)
    category_name = sys.argv[1]

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

    cat_id, parent_name = fetch_category_context(cur, category_name)
    if cat_id is None:
        print(f"ERROR: category {category_name!r} not found.")
        sys.exit(1)

    combos = fetch_sample_combos(cur, category_name)
    print(f"Category: {category_name!r}  (parent: {parent_name!r})")
    print(f"Sample real (brand, variety, pack_size, organic) combos: {len(combos)}")
    for combo in combos[:10]:
        print(f"  {combo}")
    if len(combos) > 10:
        print(f"  ... and {len(combos) - 10} more")

    user_prompt = json.dumps({
        "worked_example": RICE_EXAMPLE,
        "target_category": category_name,
        "target_category_parent": parent_name,
        "sample_combos": [
            {"brand": b, "variety": v, "pack_size": p, "organic": o}
            for b, v, p, o in combos
        ],
    }, indent=2)

    print("\nCalling LLM (%s) to design the recipe...\n" % CHAT_MODEL)
    from openai import OpenAI
    client = OpenAI(api_key=openai_api_key)
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    raw = response.choices[0].message.content
    try:
        recipe = json.loads(raw)
    except json.JSONDecodeError:
        print("ERROR: LLM did not return valid JSON:")
        print(raw)
        sys.exit(1)

    print("=" * 70)
    print("PROPOSED RECIPE (as returned by the LLM, before validation)")
    print("=" * 70)
    print(json.dumps(recipe, indent=2))

    hardened_recipe, warnings = validate_and_harden_recipe(recipe, combos)
    if warnings:
        print("\n" + "=" * 70)
        print("VALIDATION WARNINGS - recipe auto-corrected before rendering")
        print("=" * 70)
        for w in warnings:
            print(f"  ! {w}")
        print("\nHardened patterns actually used for rendering:")
        print(json.dumps(hardened_recipe["patterns"], indent=2))

    phrases = render_phrases(hardened_recipe, combos)
    print("\n" + "=" * 70)
    print(f"CANDIDATE PHRASES this recipe would generate ({len(phrases)} total)")
    print("=" * 70)
    for phrase in phrases:
        print(f"  {phrase!r}")

    print("\n(Review only - nothing was written to the database or to")
    print(" GENERATE_CATEGORY_SUGGESTION_PHRASES.py's RECIPES registry.)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
