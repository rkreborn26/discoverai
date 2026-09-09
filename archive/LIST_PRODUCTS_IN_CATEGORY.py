#!/usr/bin/env python3
"""
DiscoverAI: List Products in a Category
===========================================

Prints every product currently in a given category id, plus the current
max numeric id/sku across the WHOLE products table (so a new batch knows
where it's safe to start numbering from without colliding with anything -
including older data this project doesn't have full visibility into).

Usage:
    python LIST_PRODUCTS_IN_CATEGORY.py cat_005
"""

import os
import re
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set. Make sure .env exists and contains DATABASE_URL.")
    sys.exit(1)

if len(sys.argv) < 2:
    print("Usage: python LIST_PRODUCTS_IN_CATEGORY.py <category_id>")
    sys.exit(1)

category_id = sys.argv[1]

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

cur.execute("""
    SELECT p.id, p.sku, p.name, p.brand, p.price, pa.pack_size, pa.organic
    FROM products p
    LEFT JOIN product_attributes pa ON pa.product_id = p.id
    WHERE p.category = %s
    ORDER BY p.id;
""", (category_id,))
rows = cur.fetchall()

print(f"Products in {category_id}: {len(rows)}\n")
for pid, sku, name, brand, price, pack_size, organic in rows:
    print(f"  {pid:10s} {sku:10s} {name:45s} brand={brand!r:20s} price={price} pack={pack_size} organic={organic}")

# Highest numeric id/sku across the WHOLE table, so a new batch can pick a
# safe starting point regardless of what other data already exists.
cur.execute("""
    SELECT id FROM products WHERE id ~ '^prod_[0-9]+$';
""")
all_ids = [int(re.sub(r'\D', '', r[0])) for r in cur.fetchall()]

cur.execute("""
    SELECT sku FROM products WHERE sku ~ '^SKU[0-9]+$';
""")
all_skus = [int(re.sub(r'\D', '', r[0])) for r in cur.fetchall()]

print(f"\nMax numeric id across ALL products: prod_{max(all_ids):03d}" if all_ids else "\nNo prod_NNN-style ids found.")
print(f"Max numeric sku across ALL products: SKU{max(all_skus)}" if all_skus else "No SKUNNN-style skus found.")
print(f"Total products in table: {len(all_ids)}")

cur.close()
conn.close()
