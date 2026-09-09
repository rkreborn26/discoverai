#!/usr/bin/env python3
"""
DiscoverAI: Check for id collisions between our batches and legacy data
===========================================================================

We just discovered prod_002 is "Aashirvaad Basmati Rice" (sku SKU002) in
the live DB, but the vegetables CSV we imported expected prod_002 to be
"Peeled & Chopped Red Onion" (sku SKU502). Since `id` is the primary key
and our import scripts use ON CONFLICT (id) DO NOTHING, if a legacy
product already occupied an id we expected to use, our row would have been
silently skipped - not because it "already existed" as intended, but
because something else entirely lives at that id.

This script checks, for every id in our three batches (vegetables
prod_001-450, fruits prod_451-846, veg-expansion prod_847-1374), whether
the CSV's own product name actually matches what's live in the DB right
now. Any mismatch means that row from our batch never actually made it in.

Usage:
    python CHECK_ID_COLLISIONS.py
"""

import csv
import os
import re
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set.")
    sys.exit(1)

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

BATCHES = [
    ("vegetables", "data/raw/fruits_vegetables_products_2026-07-25.csv"),
    ("fruits", "data/raw/fruits_products_generated.csv"),
    ("veg_expansion", "data/raw/veg_expansion_products.csv"),
]

cur.execute("SELECT id, sku, name, category FROM products;")
live = {r[0]: {"sku": r[1], "name": r[2], "category": r[3]} for r in cur.fetchall()}

print(f"Live products table has {len(live)} rows total.\n")

overall_mismatches = 0
overall_missing = 0
overall_expected = 0

for batch_name, csv_path in BATCHES:
    if not os.path.exists(csv_path):
        print(f"=== {batch_name}: CSV not found at {csv_path}, skipping ===\n")
        continue

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    mismatches = []
    missing = []
    ok = 0

    for row in rows:
        expected_id = row["id"].strip()
        expected_sku = row["sku"].strip()
        expected_name = row["name"].strip()

        if expected_id not in live:
            missing.append((expected_id, expected_sku, expected_name))
            continue

        live_row = live[expected_id]
        if live_row["sku"] != expected_sku or live_row["name"] != expected_name:
            mismatches.append((expected_id, expected_sku, expected_name, live_row["sku"], live_row["name"]))
        else:
            ok += 1

    overall_expected += len(rows)
    overall_mismatches += len(mismatches)
    overall_missing += len(missing)

    print(f"=== {batch_name} ({len(rows)} rows in CSV) ===")
    print(f"  matches live DB correctly: {ok}")
    print(f"  id exists but holds a DIFFERENT product (collision): {len(mismatches)}")
    print(f"  id doesn't exist in DB at all (never inserted, no collision): {len(missing)}")

    if mismatches:
        print(f"\n  COLLISIONS (expected vs actual):")
        for exp_id, exp_sku, exp_name, live_sku, live_name in mismatches[:15]:
            print(f"    {exp_id}: expected {exp_sku!r} {exp_name!r}")
            print(f"       {'':>{len(exp_id)}}  actually  {live_sku!r} {live_name!r}")
        if len(mismatches) > 15:
            print(f"    ... and {len(mismatches) - 15} more")

    if missing:
        print(f"\n  MISSING ENTIRELY (first 10):")
        for exp_id, exp_sku, exp_name in missing[:10]:
            print(f"    {exp_id} {exp_sku} {exp_name!r}")
        if len(missing) > 10:
            print(f"    ... and {len(missing) - 10} more")

    print()

print("=" * 70)
print(f"TOTAL across all 3 batches: {overall_expected} expected rows")
print(f"  collisions (silently overwritten by nothing, but blocked by existing id): {overall_mismatches}")
print(f"  missing entirely: {overall_missing}")
print(f"  actually correct: {overall_expected - overall_mismatches - overall_missing}")

cur.close()
conn.close()
