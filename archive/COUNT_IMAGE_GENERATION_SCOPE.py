#!/usr/bin/env python3
"""
DiscoverAI: Count the actual scope of an AI image-generation pipeline
==========================================================================

Read-only diagnostic (writes nothing) for the Define stage of the
product-image discovery work: how many images would we actually need
if we generate per PRODUCT vs per (category, variety) GROUP - the
same "compute once per meaningful group" pattern already used for
Auto Suggestion phrases and category icon keywords.

Prints, per leaf category with at least one active product:
  - product count
  - distinct variety count (pa.attributes->>'variety')
  - products with NO variety value set (falls back to category-level
    grouping, since there's nothing finer to group by)

Then a total summary: total active products vs total distinct
(category, variety) groups needed - the real cost-reduction ratio.

Usage:
    python COUNT_IMAGE_GENERATION_SCOPE.py
"""

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()
database_url = os.getenv("DATABASE_URL")
if not database_url:
    print("ERROR: DATABASE_URL not set.")
    raise SystemExit(1)

print("Connecting to Neon...")
conn = psycopg2.connect(database_url)
cur = conn.cursor()
print("Connected.\n")

cur.execute("""
    SELECT c.id, c.name, COUNT(p.id) AS product_count,
           COUNT(DISTINCT pa.attributes->>'variety') FILTER (WHERE pa.attributes->>'variety' IS NOT NULL) AS variety_count,
           COUNT(*) FILTER (WHERE pa.attributes->>'variety' IS NULL) AS no_variety_count
    FROM categories c
    JOIN products p ON p.category = c.id AND p.is_active = true
    LEFT JOIN product_attributes pa ON pa.product_id = p.id
    GROUP BY c.id, c.name
    ORDER BY product_count DESC
""")
rows = cur.fetchall()

print(f"{'Category':40} {'Products':>9} {'Varieties':>10} {'No-variety':>11}")
print("-" * 72)
total_products = 0
total_groups = 0
for cat_id, name, product_count, variety_count, no_variety_count in rows:
    total_products += product_count
    # Groups needed for this category: one per distinct variety, plus
    # one more if any products in this category have no variety value
    # (they'd share a single category-level fallback image).
    groups_here = (variety_count or 0) + (1 if no_variety_count else 0)
    total_groups += max(groups_here, 1)
    print(f"{name[:40]:40} {product_count:>9} {variety_count or 0:>10} {no_variety_count or 0:>11}")

print("-" * 72)
print(f"\nTotal active products:            {total_products}")
print(f"Total leaf categories:             {len(rows)}")
print(f"Estimated (category, variety) groups needed: {total_groups}")
if total_products:
    pct = 100 * total_groups / total_products
    print(f"That's {pct:.1f}% of per-product generation ({total_products} -> {total_groups} images)")

cur.close()
conn.close()
