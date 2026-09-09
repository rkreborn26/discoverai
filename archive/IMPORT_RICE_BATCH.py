#!/usr/bin/env python3
"""
DiscoverAI: Rice Batch Importer
===================================

Loads data/raw/rice_products.csv (68 rows, SKU1875+) into cat_005 "Rice".
No new categories needed - variety (Basmati, Sona Masuri, Brown Rice, etc.)
is stored as a product attribute (attributes json -> "variety"), not a
separate category, per your call that Basmati Rice shouldn't be its own
category. cat_006 stays unused.

Same idempotent approach as previous batches:
  1. Upsert all products (ON CONFLICT (id) DO NOTHING - safe to re-run).
  2. Derive and upsert product_attributes: organic (bool, true only for
     24 Mantra Organic's lines), pack_size, quantity + unit (kg), and
     variety (parsed from the product name via VARIETY_MARKERS below).

Usage:
    python IMPORT_RICE_BATCH.py            # do the real import
    python IMPORT_RICE_BATCH.py --dry-run   # parse + validate only, no DB writes/connection
"""

import csv
import json
import os
import re
import sys
from pathlib import Path

CSV_PATH = Path('data/raw/rice_products.csv')
KNOWN_CATEGORY_IDS = {"cat_005"}

# Checked longest/most-specific first so e.g. "Extra Long Basmati" wins
# over the generic "Basmati" fallback.
VARIETY_MARKERS = [
    ("Extra Long Basmati", "Basmati (Extra Long)"),
    ("Traditional Aged Basmati", "Basmati (Traditional Aged)"),
    ("Classic Basmati", "Basmati (Classic)"),
    ("Rozana Basmati", "Basmati (Rozana)"),
    ("Charminar Basmati", "Basmati (Charminar)"),
    ("Everyday Basmati", "Basmati (Everyday)"),
    ("Organic Basmati", "Basmati (Organic)"),
    ("Basmati", "Basmati"),
    ("Organic Sona Masuri", "Sona Masuri (Organic)"),
    ("Sona Masuri", "Sona Masuri"),
    ("Organic Brown Rice", "Brown Rice (Organic)"),
    ("Brown Rice", "Brown Rice"),
    ("Gobindobhog", "Gobindobhog"),
    ("Ponni Boiled", "Ponni Boiled"),
    ("Idli Rice", "Idli Rice"),
    ("Parboiled Rice", "Parboiled"),
]

PACK_SIZE_RE = re.compile(r'\(([^)]*)\)\s*$')
WEIGHT_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(kg|kgs|g|gm|gms|gram|grams)\b', re.IGNORECASE)
QUANTITY_WEIGHT_RE = re.compile(r'^(\d+(?:\.\d+)?)\s*(kg|g)$', re.IGNORECASE)


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
    return None, None


def derive_variety(name):
    for marker, label in VARIETY_MARKERS:
        if marker.lower() in name.lower():
            return label
    return None


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
    variety = derive_variety(name)

    attributes = {
        "id": product_id.replace("prod_", "attr_"),
        "product_id": product_id,
        "pack_size": pack_size,
        "quantity": quantity,
        "unit": unit,
        "organic": derive_organic(name, brand),
        "attributes": json.dumps({"variety": variety}),
    }

    return product, attributes


def load_and_validate(csv_path):
    if not csv_path.exists():
        print(f"ERROR: CSV not found at {csv_path}")
        print("Run GENERATE_RICE_CSV.py first.")
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
        if product["category"] not in KNOWN_CATEGORY_IDS:
            problems.append(f"row {i}: unknown category {product['category']}")
        if not attribute["pack_size"]:
            problems.append(f"row {i}: could not derive pack_size from '{product['name']}'")
        elif attribute["quantity"] is None or attribute["unit"] is None:
            problems.append(
                f"row {i}: could not derive quantity/unit from pack_size '{attribute['pack_size']}' "
                f"(quantity+unit is mandatory) - product '{product['name']}'"
            )
        if json.loads(attribute["attributes"])["variety"] is None:
            problems.append(f"row {i}: could not derive variety from '{product['name']}'")
        products.append(product)
        attrs.append(attribute)

    return products, attrs, problems


def print_summary(products, attrs, problems):
    print(f"Parsed {len(products)} product rows.")
    organic_count = sum(1 for a in attrs if a["organic"])
    variety_counts = {}
    for a in attrs:
        v = json.loads(a["attributes"])["variety"]
        variety_counts[v] = variety_counts.get(v, 0) + 1
    print(f"  organic: {organic_count} / {len(attrs)}")
    print("  variety breakdown:")
    for v, count in sorted(variety_counts.items(), key=lambda x: -x[1]):
        print(f"    {str(v):24s} {count}")
    brand_counts = {}
    for p in products:
        brand_counts[p["brand"]] = brand_counts.get(p["brand"], 0) + 1
    print("  rows per brand:")
    for b, count in sorted(brand_counts.items()):
        print(f"    {b:24s} {count}")
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
    print("\nDone. Run FINAL_PRODUCTION_EMBEDDINGS_GENERATOR.py (extract, then insert)")
    print("afterward to make these searchable - it only processes rows still missing")
    print("an embedding.")


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
