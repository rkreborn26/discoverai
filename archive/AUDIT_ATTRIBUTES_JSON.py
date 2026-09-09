#!/usr/bin/env python3
"""
DiscoverAI: Audit the attributes JSON column
================================================

We've used the free-form `attributes` json column (on product_attributes,
joined to products) inconsistently across batches:
  - vegetables/fruits: {"prep_type": "..."}
  - original Rice (before the retrofit): {"variety": "..."}
  - Rice retrofit / Pulses: {"variety": "...", "polish": "..."}
  - Atta: {"variety": "...", "milling": "..."}
  - Oil & Ghee: {"variety": "...", "process": "..."}
  - Sugar & Salt: {"variety": "...", "grain": "..."}
  - Besan: {"variety": "...", "grind": "..."}

This queries the live DB and shows, per category, which JSON keys are
actually present and a sample of their values - so we can see the real
picture (including anything from before this conversation) rather than
just what our own scripts intended.

Usage:
    python AUDIT_ATTRIBUTES_JSON.py
"""

import os
import sys
from collections import defaultdict

import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set.")
    sys.exit(1)

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

cur.execute("""
    SELECT c.id, c.name, pa.attributes
    FROM product_attributes pa
    JOIN products p ON p.id = pa.product_id
    LEFT JOIN categories c ON c.id = p.category
    WHERE pa.attributes IS NOT NULL AND pa.attributes::text != '{}';
""")
rows = cur.fetchall()

by_category = defaultdict(lambda: {"count": 0, "key_sets": defaultdict(int), "samples": {}})

for cat_id, cat_name, attributes in rows:
    label = f"{cat_id} ({cat_name})" if cat_id else "(no category)"
    entry = by_category[label]
    entry["count"] += 1
    keys = tuple(sorted(attributes.keys())) if isinstance(attributes, dict) else ()
    entry["key_sets"][keys] += 1
    if keys not in entry["samples"]:
        entry["samples"][keys] = attributes

print(f"Total product_attributes rows with non-empty JSON: {len(rows)}\n")

for label in sorted(by_category.keys()):
    entry = by_category[label]
    print(f"=== {label}: {entry['count']} rows ===")
    for keys, count in sorted(entry["key_sets"].items(), key=lambda x: -x[1]):
        sample = entry["samples"][keys]
        print(f"  keys={keys!r:50s} count={count:5d}  e.g. {sample}")
    print()

# Also: does anything have pack_size/quantity/unit/organic set at the
# product_attributes column level but no matching JSON attributes at all?
cur.execute("""
    SELECT COUNT(*) FROM product_attributes
    WHERE attributes IS NULL OR attributes::text = '{}';
""")
empty_count = cur.fetchone()[0]
print(f"product_attributes rows with NULL/empty attributes json: {empty_count}")

cur.close()
conn.close()
