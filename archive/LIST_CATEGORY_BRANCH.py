#!/usr/bin/env python3
"""
DiscoverAI: List a Category Branch
=====================================

Prints a category and its full subtree (with current product counts per
leaf), so we can see what already exists before generating a new batch.

Since categories aren't always named exactly what you'd guess (e.g. the
"Vegetables" subtree turned out to hang off a non-obvious id), this first
searches by name (ILIKE) to find candidate root categories, then prints the
full subtree for whichever one you confirm - or for cat_002 by default,
which earlier category exports (MISSING_CATEGORIES.csv) showed as the
parent of "Pulses & Lentils" and "Breakfast Cereals", suggesting it may be
the "Staples" branch.

Usage:
    python LIST_CATEGORY_BRANCH.py                # search for "staple" and print cat_002's subtree
    python LIST_CATEGORY_BRANCH.py <search_term>   # search by a different name instead
    python LIST_CATEGORY_BRANCH.py --id cat_002    # print a specific category id's subtree directly
"""

import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set. Make sure .env exists and contains DATABASE_URL.")
    sys.exit(1)

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

cur.execute("""
    SELECT c.id, c.category_code, c.name, c.parent_id, c.level, c.path,
           COUNT(p.id) AS product_count
    FROM categories c
    LEFT JOIN products p ON p.category = c.id
    GROUP BY c.id, c.category_code, c.name, c.parent_id, c.level, c.path
    ORDER BY c.path NULLS LAST, c.id;
""")
all_rows = cur.fetchall()
by_id = {r[0]: r for r in all_rows}
children = {}
for r in all_rows:
    children.setdefault(r[3], []).append(r[0])


def print_subtree(root_id, indent=0):
    if root_id not in by_id:
        print(f"{'  ' * indent}(id {root_id} not found)")
        return
    _id, code, name, parent_id, level, path, count = by_id[root_id]
    print(f"{'  ' * indent}{_id:14s} {name:40s} products={count}")
    for child_id in sorted(children.get(root_id, [])):
        print_subtree(child_id, indent + 1)


args = sys.argv[1:]

if args and args[0] == "--id":
    print_subtree(args[1])
else:
    search_term = args[0] if args else "staple"
    print(f"Searching category names for {search_term!r}...\n")
    matches = [r for r in all_rows if search_term.lower() in (r[2] or "").lower()]
    if matches:
        for r in matches:
            print(f"  {r[0]:14s} {r[2]:40s} path={r[5]}")
        print()
    else:
        print("  no name matches.\n")

    print("Printing cat_002's subtree (suspected Staples branch, per MISSING_CATEGORIES.csv parentage):\n")
    print_subtree("cat_002")

cur.close()
conn.close()
