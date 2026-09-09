#!/usr/bin/env python3
"""
DiscoverAI: Pulses & Lentils Batch Importer (v2 - full variant matrix)
==========================================================================

Loads data/raw/pulses_products.csv (140 rows, SKU1943+) into cat_016
"Pulses & Lentils", alongside the 6 existing brand='Generic' items already
there. Variety (Toor Dal, Moong Dal Split, etc.) and polish (polished /
unpolished) are both stored as product attributes (attributes json),
matching the pattern used for Rice - not separate categories.

Same idempotent approach as previous batches - ON CONFLICT DO NOTHING on
both products and product_attributes, safe to re-run.

Usage:
    python IMPORT_PULSES_BATCH.py            # do the real import
    python IMPORT_PULSES_BATCH.py --dry-run   # parse + validate only, no DB writes/connection
"""

import csv
import json
import os
import re
import sys
from pathlib import Path

CSV_PATH = Path('data/raw/pulses_products.csv')
KNOWN_CATEGORY_IDS = {"cat_016"}

VARIETY_MARKERS = [
    ("Urad Dal Whole", "Urad Dal (Whole)"),
    ("Urad Dal Split", "Urad Dal (Split)"),
    ("Moong Dal Split", "Moong Dal (Split)"),
    ("Green Moong Whole", "Moong (Whole)"),
    ("Toor Dal", "Toor Dal"),
    ("Chana Dal", "Chana Dal"),
    ("Masoor Dal", "Masoor Dal"),
    ("Kabuli Chana", "Kabuli Chana"),
    ("Kala Chana", "Kala Chana"),
    ("Rajma Chitra", "Rajma (Chitra)"),
    ("Rajma", "Rajma"),
    ("Val Dal", "Val Dal"),
    ("Horse Gram", "Horse Gram"),
]

PACK_SIZE_RE = re.compile(r'\(([^)]*)\)\s*$')
WEIGHT_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(kg|kgs|g|gm|gms|gram|grams)\b', re.IGNORECASE)
QUANTITY_WEIGHT_RE = re.compile(r'^(\d+(?:\.\d+)?)\s*(kg|g)$', re.IGNORECASE)


def derive_organic(name, brand):
    name_l = (name or "").lower()
    brand_l = (brand or "").lower()
    return "organic" in name_l or "organic" in brand_l


def derive_polish(name):
    return "unpolished" if "unpolished" in name.lower() else "polished"


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

    product = {}
    product["id"] = product_id
    product["sku"] = row["sku"].strip()
    product["name"] = name
    product["category"] = row["category"].strip()
    product["brand"] = brand or None
    product["price"] = row["price"].strip()
    product["original_price"] = (row.get("original_price") or "").strip() or None
    product["discount_percentage"] = (row.get("discount_percentage") or "").strip() or None
    product["in_stock"] = parse_bool(row.get("in_stock", "t"))
    product["stock_quantity"] = (row.get("stock_quantity") or "0").strip() or 0
    product["image_url"] = (row.get("image_url") or "").strip() or None
    product["description"] = description.strip() or None
    product["rating"] = (row.get("rating") or "0").strip() or 0
    product["review_count"] = (row.get("review_count") or "0").strip() or 0
    product["is_active"] = parse_bool(row.get("is_active", "t"))

    pack_size = derive_pack_size(name)
    quantity, unit = derive_quantity_unit(pack_size)
    variety = derive_variety(name)
    polish = derive_polish(name)

    attributes = {}
    attributes["id"] = product_id.replace("prod_", "attr_")
    attributes["product_id"] = product_id
    attributes["pack_size"] = pack_size
    attributes["quantity"] = quantity
    attributes["unit"] = unit
    attributes["organic"] = derive_organic(name, brand)
    attributes["attributes"] = json.dumps({"variety": variety, "polish": polish})

    return product, attributes


def load_and_validate(csv_path):
    if not csv_path.exists():
        print(f"ERROR: CSV not found at {csv_path}")
        print("Run GENERATE_PULSES_CSV.py first.")
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
    polish_counts = {}
    for a in attrs:
        parsed = json.loads(a["attributes"])
        variety_counts[parsed["variety"]] = variety_counts.get(parsed["variety"], 0) + 1
        polish_counts[parsed["polish"]] = polish_counts.get(parsed["polish"], 0) + 1
    print(f"  organic: {organic_count} / {len(attrs)}")
    print(f"  polish breakdown: {polish_counts}")
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
    print("\nDone.")


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
