#!/usr/bin/env python3
"""
DiscoverAI: Fruits & Vegetables Batch Importer
================================================

Loads the "Daily Cooking Staples" grocery batch (data/raw/fruits_vegetables_products_2026-07-25.csv,
450 rows) into Neon:

  1. Creates 6 new categories (cat_007a_05 .. cat_007a_10) as siblings of the existing
     Onions/Potatoes/Tomatoes/Garlic&Ginger categories under "Daily Cooking Staples" (cat_007a).
     These 6 ids are referenced by the CSV but don't exist in the categories table yet.
  2. Upserts all 450 products from the CSV into `products`. The first 84 rows (Onions,
     Potatoes, Tomatoes, Garlic&Ginger) already exist in the DB - ON CONFLICT (id) DO NOTHING
     means re-running this script is always safe and just skips what's already there.
  3. Derives and upserts `product_attributes` for every product: organic (bool), pack_size
     (e.g. "250g", "1kg"), quantity + unit (mandatory - e.g. 250/"gm", 1/"kg", 2/"pc"), and a
     prep_type (whole / chopped / diced / sliced / peeled / ...) stored in the free-form
     `attributes` json column, parsed from the product name.

This script must be run on a machine that can reach your Neon DB (this repo's own docs note
that DiscoverAI runs locally - run it from there, not from a sandboxed tool).

Usage:
    python IMPORT_FRUITS_VEGETABLES_BATCH.py            # do the real import
    python IMPORT_FRUITS_VEGETABLES_BATCH.py --dry-run   # parse + validate only, no DB writes/connection
"""

import csv
import json
import os
import re
import sys
from pathlib import Path

CSV_PATH = Path('data/raw/fruits_vegetables_products_2026-07-25.csv')

# ------------------------------------------------------------------
# 1. New categories to create (siblings of cat_007a_01..04 under
#    cat_007a "Daily Cooking Staples"). Ids/parent match what the CSV
#    already uses in its `category` column.
# ------------------------------------------------------------------
PARENT_PATH = "Grocery / Fruits & Vegetables / Daily Cooking Staples"
PARENT_ID = "cat_007a"
PARENT_LEVEL = 3

NEW_CATEGORIES = [
    {
        "id": "cat_007a_05",
        "category_code": "HERBS_LEAFY_GREENS",
        "name": "Herbs & Leafy Greens",
        "description": "Fresh coriander, mint, curry leaves, fenugreek and spinach for everyday cooking",
        "display_order": 5,
    },
    {
        "id": "cat_007a_06",
        "category_code": "GOURDS_BRINJAL_COLE",
        "name": "Gourds, Brinjal & Cole Crops",
        "description": "Bitter gourd, bottle gourd, ridge gourd, brinjal, cabbage, cauliflower and capsicum",
        "display_order": 6,
    },
    {
        "id": "cat_007a_07",
        "category_code": "ROOT_VEG_CUCUMBER",
        "name": "Root Veg & Cucumber",
        "description": "Beetroot, carrot, radish, cucumber and cluster beans",
        "display_order": 7,
    },
    {
        "id": "cat_007a_08",
        "category_code": "BEANS_PEAS_SWEET_POTATO",
        "name": "Beans, Peas & Sweet Potato",
        "description": "French beans, green peas, cowpea, cluster beans and sweet potato",
        "display_order": 8,
    },
    {
        "id": "cat_007a_09",
        "category_code": "CORN_MUSHROOM_PEPPERS",
        "name": "Corn, Mushroom & Bell Peppers",
        "description": "Baby corn, sweet corn, mushroom, broccoli, zucchini and bell peppers",
        "display_order": 9,
    },
    {
        "id": "cat_007a_10",
        "category_code": "EXOTIC_ROOTS_RAW_PRODUCE",
        "name": "Exotic Roots & Raw Produce",
        "description": "Turmeric, colocasia, yam, drumstick, ivy gourd, raw banana, raw mango, raw papaya and specialty gourds",
        "display_order": 10,
    },
]

# ------------------------------------------------------------------
# 2. Parsing helpers: derive product_attributes from name/brand
# ------------------------------------------------------------------

# Checked longest-phrase-first so e.g. "Peeled & Chopped" wins over "Chopped".
PREP_TYPE_MARKERS = [
    ("peeled & chopped", "peeled_chopped"),
    ("peeled & sliced", "peeled_sliced"),
    ("peeled & diced", "peeled_diced"),
    ("washed & chopped", "washed_chopped"),
    ("chopped / pre-cut", "chopped"),
    ("cut drumstick pieces", "cut"),
    ("cut florets", "cut_florets"),
    ("cut baby corn", "cut"),
    ("ring cut", "ring_cut"),
    ("slit", "slit"),
    ("shredded", "shredded"),
    ("grated", "grated"),
    ("plucked", "plucked"),
    ("chopped", "chopped"),
    ("diced", "diced"),
    ("sliced", "sliced"),
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
    """Pull the weight token out of the trailing parenthetical, e.g.
    'Coriander Leaves / Dhaniya (250g Pack)' -> '250g'."""
    m = PACK_SIZE_RE.search(name or "")
    if not m:
        return None
    inside = m.group(1)
    wm = WEIGHT_RE.search(inside)
    if not wm:
        return inside.strip() or None
    qty, unit = wm.groups()
    unit = unit.lower()
    if unit.startswith("kg"):
        unit = "kg"
    else:
        unit = "g"
    # normalize integer-looking floats (250.0 -> 250)
    qty_num = float(qty)
    qty_str = str(int(qty_num)) if qty_num == int(qty_num) else str(qty_num)
    return f"{qty_str}{unit}"


def derive_quantity_unit(pack_size):
    """Split the already-derived pack_size ('250g', '1kg', or a piece-count
    string like '2 PCs') into a mandatory (quantity, unit) pair. unit is
    'gm', 'kg', or 'pc'. Returns (None, None) if pack_size can't be parsed -
    callers must treat that as a validation error, not a silent gap."""
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
    """Return (product_tuple, attributes_tuple) for one CSV row."""
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
        print("Make sure you're running this from the project root, and the file")
        print("was copied to data/raw/ (it should already be there).")
        sys.exit(1)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    products = []
    attrs = []
    seen_ids = set()
    seen_skus = set()
    known_category_ids = {"cat_007a_01", "cat_007a_02", "cat_007a_03", "cat_007a_04"}
    known_category_ids |= {c["id"] for c in NEW_CATEGORIES}

    problems = []
    for i, row in enumerate(rows, start=2):
        product, attribute = parse_row(row)
        if product["id"] in seen_ids:
            problems.append(f"row {i}: duplicate id {product['id']}")
        if product["sku"] in seen_skus:
            problems.append(f"row {i}: duplicate sku {product['sku']}")
        seen_ids.add(product["id"])
        seen_skus.add(product["sku"])
        if product["category"] not in known_category_ids:
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

    # --- categories ---
    cat_inserted = 0
    for c in NEW_CATEGORIES:
        path = f"{PARENT_PATH} / {c['name']}"
        cur.execute(
            """
            INSERT INTO categories (id, category_code, name, parent_id, level, path, description, display_order, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)
            ON CONFLICT (id) DO NOTHING
            """,
            (c["id"], c["category_code"], c["name"], PARENT_ID, PARENT_LEVEL + 1, path, c["description"], c["display_order"]),
        )
        cat_inserted += cur.rowcount
    conn.commit()
    print(f"Categories: {cat_inserted} inserted (rest already existed or were skipped).")

    # --- products ---
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

    # --- product_attributes ---
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
    print("\nDone. Note: embedding columns are NOT populated by this script - run the")
    print("existing embeddings generator afterward if/when you want these searchable.")


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
