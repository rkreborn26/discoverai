#!/usr/bin/env python3
"""
DiscoverAI: List the actual (category, variety) groups needing an image
==========================================================================

Companion to COUNT_IMAGE_GENERATION_SCOPE.py - that script only prints
aggregate counts per category ("Rice: 3 varieties"). This script prints
and exports the actual GROUP LIST itself: one row per (category, variety)
combination that needs exactly one generated image, per the same
"compute once per meaningful group" pattern (a product with no variety
value falls back to a category-level group).

This is the shopping list for manually generating images with an
external tool (e.g. Gemini "Nano Banana", or any other image
generator) - each row includes a suggested filename so the images you
save can be matched back to the right products later by
INSERT_PRODUCT_IMAGE_URLS.py (the second half of this two-part
pipeline), without re-querying anything.

COMPOUND CATEGORY NAMES (e.g. "Onions & Shallots"): rather than
restructuring the categories table (see AUDIT_COMPOUND_LEAF_
CATEGORIES.py / SPLIT_COMPOUND_CATEGORIES.py for that, heavier, path -
skipped for now), this script splits them ITSELF, in memory, purely
for image-grouping purposes. The database is never touched. For any
category whose name contains "&"/"and"/"/", and whose products don't
already have a `variety` attribute (rice/pulses do; produce doesn't),
each product's NAME is matched against the category name's split terms
- "Fresh Shallots 250g" under "Onions & Shallots" becomes its own
"Shallots" group rather than sharing a group (and a photo) with onions.
A product that matches zero or multiple terms falls back to a shared
"(mixed/unmatched)" bucket for that category - same "don't guess"
behavior as the audit script.
INSERT_PRODUCT_IMAGE_URLS.py MUST use this identical matching logic
(effective_variety() below) to re-associate products with the right
generated image - it doesn't have a database column to just look up.

Read-only - writes nothing to the database. Writes one CSV to
data/exports/image_generation_groups.csv.

Usage:
    python LIST_IMAGE_GENERATION_GROUPS.py
"""

import csv
import os
import re
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

OUT_PATH = Path("data/exports/image_generation_groups.csv")

# Same pattern as AUDIT_COMPOUND_LEAF_CATEGORIES.py - kept in sync
# manually, per this project's existing convention for small shared
# helpers (see SET_PRODUCT_IMAGE_URLS.py's docstring).
SPLIT_PATTERN = re.compile(r"\s*(?:&|\band\b|/)\s*", re.IGNORECASE)


def split_terms(name):
    parts = [p.strip() for p in SPLIT_PATTERN.split(name) if p.strip()]
    return parts if len(parts) > 1 else []


def effective_variety(category_name, variety, product_name):
    """Returns (label, source) - the group a product belongs to within
    its category, and why:
      "attribute"  - pa.attributes->>'variety' was already set (rice/pulses)
      "name-split" - category name is compound and the product name
                     matched exactly one split term
      "generic"    - not compound, or nothing to split on - one shared
                     group for the whole category (unchanged behavior)
      "mixed"      - compound category, but the product name matched
                     zero or more-than-one split term - can't tell which
                     side it's on, so it does NOT silently join a
                     name-split bucket; it gets its own honestly-labeled
                     bucket instead of contaminating "Onions" or
                     "Shallots" with a guess.
    """
    if variety:
        return variety, "attribute"
    terms = split_terms(category_name)
    if not terms:
        return None, "generic"
    pname_l = product_name.lower()
    hits = [t for t in terms if t.lower().rstrip("s") in pname_l or t.lower() in pname_l]
    if len(hits) == 1:
        return hits[0], "name-split"
    return None, "mixed"


def slugify(value):
    """Filename-safe slug: lowercase, hyphens, no repeats/edges."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return cleaned or "unnamed"


def main():
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set.")
        raise SystemExit(1)

    print("Connecting to Neon...")
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    print("Connected.\n")

    # Row-level (not aggregated) so compound-category products can be
    # re-bucketed by name in Python before grouping.
    cur.execute("""
        SELECT p.id, p.name, c.id AS category_id, c.name AS category_name,
               pa.attributes->>'variety' AS variety
        FROM products p
        JOIN categories c ON p.category = c.id
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE p.is_active = true
        ORDER BY c.name, p.name
    """)
    products = cur.fetchall()
    cur.close()
    conn.close()

    # (category_id, category_name, group_label) -> {count, source, mixed_examples}
    grouped = {}
    for product_id, product_name, category_id, category_name, variety in products:
        label, source = effective_variety(category_name, variety, product_name)
        display_label = label or ("(mixed/unmatched)" if source == "mixed" else "(no variety)")
        key = (category_id, category_name, display_label)
        g = grouped.setdefault(key, {"count": 0, "source": source, "examples": []})
        g["count"] += 1
        if source == "mixed" and len(g["examples"]) < 5:
            g["examples"].append(product_name)

    # Build the group list with de-duplicated, collision-safe filenames
    # (two categories that slugify to the same thing would otherwise
    # silently clobber each other's suggested filename).
    used_filenames = set()
    groups = []
    for (category_id, category_name, variety_label), info in sorted(grouped.items(), key=lambda kv: (kv[0][1], kv[0][2])):
        cat_slug = slugify(category_name)
        variety_slug = "generic" if variety_label in ("(no variety)", "(mixed/unmatched)") else slugify(variety_label)
        base_filename = f"{cat_slug}__{variety_slug}.png"
        filename = base_filename
        n = 2
        while filename in used_filenames:
            filename = f"{cat_slug}__{variety_slug}-{n}.png"
            n += 1
        used_filenames.add(filename)

        groups.append({
            "category_id": category_id,
            "category_name": category_name,
            "variety": variety_label,
            "product_count": info["count"],
            "suggested_filename": filename,
            "needs_review": info["source"] == "mixed",
        })

    print(f"{'Category':30} {'Variety':30} {'Products':>9}  Suggested filename")
    print("-" * 100)
    for g in groups:
        flag = "  [NEEDS REVIEW]" if g["needs_review"] else ""
        print(f"{g['category_name'][:30]:30} {g['variety'][:30]:30} {g['product_count']:>9}  {g['suggested_filename']}{flag}")
    print("-" * 100)
    print(f"\nTotal groups (= images to generate): {len(groups)}")
    print(f"Total active products covered:        {sum(g['product_count'] for g in groups)}")
    review_count = sum(g["product_count"] for g in groups if g["needs_review"])
    if review_count:
        print(f"\n{review_count} product(s) sit in a [NEEDS REVIEW] '(mixed/unmatched)' bucket - their name")
        print("didn't clearly match one side of a compound category. They'll still get an image")
        print("(the generic one for that bucket), it just won't be as specific. Examples:")
        for (category_id, category_name, variety_label), info in grouped.items():
            if info["source"] == "mixed":
                for ex in info["examples"]:
                    print(f"    [{category_name}] {ex!r}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["category_id", "category_name", "variety", "product_count", "suggested_filename", "needs_review"]
        )
        writer.writeheader()
        writer.writerows(groups)

    print(f"\nWrote {OUT_PATH}")
    print("Generate one image per row, save it under that exact 'suggested_filename'")
    print("into backend/static/product_images/, then run INSERT_PRODUCT_IMAGE_URLS.py")
    print("to write image_url for every product in that group.")


if __name__ == "__main__":
    main()
