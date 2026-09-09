#!/usr/bin/env python3
"""
DiscoverAI: Vegetables Category-Expansion Batch Importer
============================================================

Loads data/raw/veg_expansion_products.csv (528 rows, SKU1347+) into Neon.
Fills the 19 previously-empty leaf categories under "Vegetables" with items
deliberately distinct from what's already in Daily Cooking Staples - no new
categories need to be created, they all already exist.

Same idempotent approach as the previous batches:
  1. Upsert all products from the CSV (ON CONFLICT (id) DO NOTHING - safe
     to re-run).
  2. Derive and upsert product_attributes for every product: organic
     (bool), pack_size, quantity + unit (mandatory - gm/kg/ml/L/pack/etc),
     and prep_type stored in the free-form `attributes` json column.

Must be run on a machine that can reach your Neon DB.

Usage:
    python IMPORT_VEG_EXPANSION_BATCH.py            # do the real import
    python IMPORT_VEG_EXPANSION_BATCH.py --dry-run   # parse + validate only, no DB writes/connection
"""

import csv
import json
import os
import re
import sys
from pathlib import Path

CSV_PATH = Path('data/raw/veg_expansion_products.csv')

KNOWN_CATEGORY_IDS = {
    "cat_007b_01", "cat_007b_02", "cat_007b_03", "cat_007b_04",
    "cat_007c_01", "cat_007c_02", "cat_007c_03",
    "cat_007d_01", "cat_007d_02", "cat_007d_03",
    "cat_007e_01", "cat_007e_02", "cat_007e_03",
    "cat_007f_01", "cat_007f_02", "cat_007f_03",
    "cat_007g_01", "cat_007g_02", "cat_007g_03",
}

# Existing ids that must NOT appear in this CSV (would mean an accidental
# collision with the vegetables or fruits batches already in the DB).
FORBIDDEN_ID_RANGE = (1, 846)

PREP_TYPE_MARKERS = [
    ("peeled & diced", "peeled_diced"),
    ("cut florets", "cut_florets"),
    ("chopped", "chopped"),
    ("shredded", "shredded"),
    ("sliced", "sliced"),
    ("diced", "diced"),
    ("halved", "halved"),
    ("plucked", "plucked"),
    ("peeled", "peeled"),
]

PACK_SIZE_RE = re.compile(r'\(([^)]*)\)\s*$')
WEIGHT_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(kg|kgs|g|gm|gms|gram|grams)\b', re.IGNORECASE)
QUANTITY_WEIGHT_RE = re.compile(r'^(\d+(?:\.\d+)?)\s*(kg|g)$', re.IGNORECASE)
PIECE_UNIT_RE = re.compile(r'pcs?\b', re.IGNORECASE)
PIECE_QTY_RE = re.compile(r'(\d+)')


def derive_organic(name, brand):
    name_l = (name or "").lower()
    brand_l = (brand or "").lower()
    return "organic" in name_l or "organic" in brand_l


def derive_pack_size(name):
    m = PACK_SIZE_RE.search(name or "")
    if not m:
        return None
    inside = m.group(1)
    wm = WEIGHT_RE.search(inside)
    if not wm:
        return inside.strip() or None
    qty, unit = wm.groups()
    unit = unit.lower()
    unit = "kg" if unit.startswith("kg") else "g"
    qty_num = float(qty)
    qty_str = str(int(qty_num)) if qty_num == int(qty_num) else str(qty_num)
    return f"{qty_str}{unit}"


def derive_quantity_unit(pack_size):
    if not pack_size:
        return None, None
    s = pack_size.strip()
    m = QUANTITY_WEIGHT_RE.match(s)
    if m:
        qty_str, unit = m.groups()
        qty = float(qty_str)
        if qty == int(qty):
            qty = int(qty)
        unit = "kg" if unit.lower() == "kg" else "gm"
        return qty, unit
    if PIECE_UNIT_RE.search(s):
        qty_match = PIECE_QTY_RE.search(s)
        qty = int(qty_match.group(1)) if qty_match else 1
        return qty, "pc"
    return None, None


def derive_prep_type(name):
    name_l = (name or "").lower()
    for marker, label in PREP_TYPE_MARKERS:
        if marker in name_l:
            return label
    return "whole"


def parse_bool(value):
    return str(value).strip().lower() in ("t", "true", "1", "yes")


def parse_row(row):
    product_id = row["id"].strip()
    name = row["name"].strip()
    brand = (row.get("brand") or "").strip()
    description = row.get("description") or ""

    product = {
        "id": product_id,
        "sku": row["sku"].strip(),
        "name": name,
        "category": row["category"].strip(),
        "brand": brand or None,
        "price": row["price"].strip(),
        "original_price": (row.get("original_price") or "").strip() or None,
        "discount_percentage": (row.get("discount_percentage") or "").strip() or None,
        "in_stock": parse_bool(row.get("in_stock", "t")),
        "stock_quantity": (row.get("stock_quantity") or "0").strip() or 0,
        "image_url": (row.get("image_url") or "").strip() or None,
        "description": description.strip() or None,
        "rating": (row.get("rating") or "0").strip() or 0,
        "review_count": (row.get("review_count") or "0").strip() or 0,
        "is_active": parse_bool(row.get("is_active", "t")),
    }

    pack_size = derive_pack_size(name)
    quantity, unit = derive_quantity_unit(pack_size)

    attributes = {
        "id": product_id.replace("prod_", "attr_"),
        "product_id": product_id,
        "pack_size": pack_size,
        "quantity": quantity,
        "unit": unit,
        "organic": derive_organic(name, brand),
        "attributes": json.dumps({"prep_type": derive_prep_type(name)}),
    }

    return product, attributes


def load_and_validate(csv_path):
    if not csv_path.exists():
        print(f"ERROR: CSV not found at {csv_path}")
        print("Make sure you're running this from the project root, and you've")
        print("run GENERATE_VEG_EXPANSION_CSV.py first.")
        sys.exit(1)

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    products, attrs = [], []
    seen_ids, seen_skus = set(), set()
    problems = []

    for i, row in enumerate(rows, start=2):
        product, attribute = parse_row(row)
        if product["id"] in seen_ids:
            problems.append(f"row {i}: duplicate id {product['id']}")
        if product["sku"] in seen_skus:
            problems.append(f"row {i}: duplicate sku {product['sku']}")
        seen_ids.add(product["id"])
        seen_skus.add(product["sku"])

        id_num = int(product["id"].replace("prod_", ""))
        if FORBIDDEN_ID_RANGE[0] <= id_num <= FORBIDDEN_ID_RANGE[1]:
            problems.append(f"row {i}: id {product['id']} collides with the vegetables/fruits batches (prod_001-846)")

        if product["category"] not in KNOWN_CATEGORY_IDS:
            problems.append(f"row {i}: unknown category {product['category']}")
        if not attribute["pack_size"]:
            problems.append(f"row {i}: could not derive pack_size from '{product['name']}'")
        elif attribute["quantity"] is None or attribute["unit"] is None:
            problems.append(
                f"row {i}: could not derive quantity/unit from pack_size '{attribute['pack_size']}' "
                f"(quantity+unit is mandatory) - product '{product['name']}'"
            )
        products.append(product)
        attrs.append(attribute)

    return products, attrs, problems


def print_summary(products, attrs, problems):
    print(f"Parsed {len(products)} product rows.")
    organic_count = sum(1 for a in attrs if a["organic"])
    prep_counts = {}
    for a in attrs:
        prep = json.loads(a["attributes"])["prep_type"]
        prep_counts[prep] = prep_counts.get(prep, 0) + 1
    print(f"  organic: {organic_count} / {len(attrs)}")
    print("  prep_type breakdown:")
    for prep, count in sorted(prep_counts.items(), key=lambda x: -x[1]):
        print(f"    {prep:16s} {count}")
    cat_counts = {}
    for p in products:
        cat_counts[p["category"]] = cat_counts.get(p["category"], 0) + 1
    print("  rows per category:")
    for cat, count in sorted(cat_counts.items()):
        print(f"    {cat:16s} {count}")
    if problems:
        print(f"\n{len(problems)} PROBLEM(S) FOUND:")
        for p in problems[:30]:
            print(f"  - {p}")
        if len(problems) > 30:
            print(f"  ... and {len(problems) - 30} more")
    else:
        print("\nNo problems found - data looks clean.")


def run_import(products, attrs):
    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set. Make sure .env exists and contains DATABASE_URL.")
        sys.exit(1)

    print("Connecting to Neon...")
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    print("Connected.\n")

    prod_inserted = 0
    for p in products:
        cur.execute(
            """
            INSERT INTO products (
                id, sku, name, category, brand, price, original_price,
                discount_percentage, in_stock, stock_quantity, image_url,
                description, rating, review_count, is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                p["id"], p["sku"], p["name"], p["category"], p["brand"], p["price"],
                p["original_price"], p["discount_percentage"], p["in_stock"],
                p["stock_quantity"], p["image_url"], p["description"], p["rating"],
                p["review_count"], p["is_active"],
            ),
        )
        prod_inserted += cur.rowcount
    conn.commit()
    print(f"Products: {prod_inserted} inserted, {len(products) - prod_inserted} already existed (skipped).")

    attr_inserted = 0
    for a in attrs:
        cur.execute(
            """
            INSERT INTO product_attributes (id, product_id, pack_size, quantity, unit, organic, attributes)
            VALUES (%s, %s, %s, %s, %s, %s, %s::json)
            ON CONFLICT (product_id) DO NOTHING
            """,
            (a["id"], a["product_id"], a["pack_size"], a["quantity"], a["unit"], a["organic"], a["attributes"]),
        )
        attr_inserted += cur.rowcount
    conn.commit()
    print(f"Product attributes: {attr_inserted} inserted, {len(attrs) - attr_inserted} already existed (skipped).")

    cur.close()
    conn.close()
    print("\nDone. Note: embedding columns are NOT populated by this script - run")
    print("FINAL_PRODUCTION_EMBEDDINGS_GENERATOR.py (extract, then insert) afterward")
    print("if/when you want these searchable - it only processes rows still missing")
    print("an embedding, so it's safe to run again without re-doing existing work.")


def main():
    dry_run = "--dry-run" in sys.argv
    products, attrs, problems = load_and_validate(CSV_PATH)
    print_summary(products, attrs, problems)

    if problems:
        print("\nRefusing to import until the problems above are resolved.")
        sys.exit(1)

    if dry_run:
        print("\n(--dry-run: no DB connection attempted, nothing was written)")
        return

    print()
    run_import(products, attrs)


if __name__ == "__main__":
    main()
