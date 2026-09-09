#!/usr/bin/env python3
"""
DiscoverAI: Verify Pulses v2 landed correctly
=================================================

Checks every row in data/raw/pulses_products.csv against what's actually
live in the DB right now - not just counts, but that each id holds the
exact name/sku the v2 CSV intended.

Usage:
    python VERIFY_PULSES_V2.py
"""

import csv
import os
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

with open("data/raw/pulses_products.csv", newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

cur.execute("SELECT id, sku, name, category FROM products WHERE category = 'cat_016';")
live = {r[0]: {"sku": r[1], "name": r[2], "category": r[3]} for r in cur.fetchall()}

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

print(f"{len(rows)} rows expected from CSV.")
print(f"  correct in DB: {ok}")
print(f"  mismatched (wrong content at that id): {len(mismatches)}")
print(f"  missing entirely: {len(missing)}")

if mismatches:
    print("\nMISMATCHES:")
    for exp_id, exp_sku, exp_name, live_sku, live_name in mismatches[:20]:
        print(f"  {exp_id}: expected {exp_sku!r} {exp_name!r}")
        print(f"  {'':>{len(exp_id)}}    actual {live_sku!r} {live_name!r}")

if missing:
    print("\nMISSING:")
    for exp_id, exp_sku, exp_name in missing[:20]:
        print(f"  {exp_id} {exp_sku} {exp_name!r}")

cur.execute("SELECT COUNT(*) FROM products WHERE category = 'cat_016';")
total_live = cur.fetchone()[0]
print(f"\nTotal products live in cat_016 right now: {total_live} (expect {len(rows) + 6} - 140 new + 6 original Generic-brand ones)")

cur.close()
conn.close()
