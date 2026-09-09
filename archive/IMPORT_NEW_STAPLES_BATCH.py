#!/usr/bin/env python3
"""
DiscoverAI: Import Atta, Cooking Oil & Ghee, Sugar & Salt, Besan
=====================================================================

Loads all 4 new-staples CSVs (data/raw/atta_products.csv,
oil_ghee_products.csv, sugar_salt_products.csv, besan_products.csv) into
their respective new categories (cat_002a/b/c/d - run
CREATE_STAPLES_CATEGORIES.py first). One shared script since all 4 follow
the same shape: brand x pack_size x organic/regular x a second quality
axis (milling / refinement / grain), rather than 4 near-duplicate files.

Same idempotent approach as every batch so far - ON CONFLICT DO NOTHING on
both products and product_attributes, safe to re-run.

Usage:
    python IMPORT_NEW_STAPLES_BATCH.py            # do the real import (all 4 CSVs)
    python IMPORT_NEW_STAPLES_BATCH.py --dry-run   # parse + validate only, no DB writes/connection
"""

import csv
import json
import os
import sys
from pathlib import Path

import staples_common as sc

# Each entry: (csv_path, category_id, variety_markers, extra_tag_markers, extra_tag_key, extra_tag_default)
# variety_markers / extra_tag_markers: list of (substring, label), longest/most
# specific first. extra_tag_key names the attribute stored alongside "variety"
# in the attributes json (e.g. "milling", "process", "grain").
BATCHES = [
    (
        "data/raw/atta_products.csv", "cat_002a",
        [
            ("Multigrain Atta", "Multigrain Atta"),
            ("Chakki Fresh Atta", "Chakki Fresh Atta"),
            ("Whole Wheat Atta", "Whole Wheat Atta"),
            ("Maida", "Maida"),
        ],
        [("Stone-Ground", "stone_ground")],
        "milling", "roller_mill",
    ),
    (
        "data/raw/oil_ghee_products.csv", "cat_002b",
        [
            ("Sunflower Oil Gold", "Sunflower Oil (Gold)"),
            ("Sunflower Oil", "Sunflower Oil"),
            ("Soybean Oil", "Soybean Oil"),
            ("Mustard Oil", "Mustard Oil"),
            ("Groundnut Oil", "Groundnut Oil"),
            ("Cow Ghee", "Cow Ghee"),
            ("Pure Ghee", "Pure Ghee"),
        ],
        [("Cold-Pressed", "cold_pressed")],
        "process", "refined",
    ),
    (
        "data/raw/sugar_salt_products.csv", "cat_002c",
        [
            ("Iodised Salt", "Iodised Salt"),
            ("Rock Salt", "Rock Salt"),
            ("Black Salt", "Black Salt"),
            ("Powdered Sugar", "Powdered Sugar"),
            ("Refined Sugar", "Refined Sugar"),
            ("Brown Sugar", "Brown Sugar"),
            ("Jaggery", "Jaggery"),
        ],
        [("Coarse", "coarse")],
        "grain", "fine",
    ),
    (
        "data/raw/besan_products.csv", "cat_002d",
        [
            ("Besan", "Besan"),
            ("Rava", "Rava"),
            ("Rice Flour", "Rice Flour"),
            ("Ragi Flour", "Ragi Flour"),
        ],
        [("Coarse", "coarse")],
        "grind", "fine",
    ),
]


def parse_row(row, variety_markers, extra_tag_markers, extra_tag_key, extra_tag_default):
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
    product["in_stock"] = sc.parse_bool(row.get("in_stock", "t"))
    product["stock_quantity"] = (row.get("stock_quantity") or "0").strip() or 0
    product["image_url"] = (row.get("image_url") or "").strip() or None
    product["description"] = description.strip() or None
    product["rating"] = (row.get("rating") or "0").strip() or 0
    product["review_count"] = (row.get("review_count") or "0").strip() or 0
    product["is_active"] = sc.parse_bool(row.get("is_active", "t"))

    pack_size = sc.derive_pack_size(name)
    quantity, unit = sc.derive_quantity_unit(pack_size)
    variety = sc.derive_marker(name, variety_markers, None)
    extra_tag_value = sc.derive_marker(name, extra_tag_markers, extra_tag_default)

    attrs_json = {"variety": variety, extra_tag_key: extra_tag_value}

    attribute = {}
    attribute["id"] = product_id.replace("prod_", "attr_")
    attribute["product_id"] = product_id
    attribute["pack_size"] = pack_size
    attribute["quantity"] = quantity
    attribute["unit"] = unit
    attribute["organic"] = sc.derive_organic(name, brand)
    attribute["attributes"] = json.dumps(attrs_json)

    return product, attribute


def load_and_validate_one(csv_path, category_id, variety_markers, extra_tag_markers, extra_tag_key, extra_tag_default):
    path = Path(csv_path)
    if not path.exists():
        return None, None, [f"CSV not found at {csv_path} - run its generator script first."]

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    products, attrs = [], []
    seen_ids, seen_skus = set(), set()
    problems = []

    for i, row in enumerate(rows, start=2):
        product, attribute = parse_row(row, variety_markers, extra_tag_markers, extra_tag_key, extra_tag_default)
        if product["id"] in seen_ids:
            problems.append(f"{csv_path} row {i}: duplicate id {product['id']}")
        if product["sku"] in seen_skus:
            problems.append(f"{csv_path} row {i}: duplicate sku {product['sku']}")
        seen_ids.add(product["id"])
        seen_skus.add(product["sku"])
        if product["category"] != category_id:
            problems.append(f"{csv_path} row {i}: unexpected category {product['category']} (expected {category_id})")
        if not attribute["pack_size"]:
            problems.append(f"{csv_path} row {i}: could not derive pack_size from '{product['name']}'")
        elif attribute["quantity"] is None or attribute["unit"] is None:
            problems.append(f"{csv_path} row {i}: could not derive quantity/unit from pack_size '{attribute['pack_size']}'")
        if json.loads(attribute["attributes"])["variety"] is None:
            problems.append(f"{csv_path} row {i}: could not derive variety from '{product['name']}'")
        products.append(product)
        attrs.append(attribute)

    return products, attrs, problems


def print_summary(csv_path, products, attrs):
    print(f"  {csv_path}: {len(products)} rows")
    organic_count = sum(1 for a in attrs if a["organic"])
    print(f"    organic: {organic_count} / {len(attrs)}")
    brand_counts = {}
    for p in products:
        brand_counts[p["brand"]] = brand_counts.get(p["brand"], 0) + 1
    print(f"    brands: {dict(sorted(brand_counts.items()))}")


def run_import(cur, conn, products, attrs):
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

    return prod_inserted, attr_inserted


def main():
    dry_run = "--dry-run" in sys.argv

    all_products = {}
    all_attrs = {}
    all_problems = []

    print("Validating all 4 CSVs...\n")
    for csv_path, category_id, variety_markers, extra_tag_markers, extra_tag_key, extra_tag_default in BATCHES:
        products, attrs, problems = load_and_validate_one(
            csv_path, category_id, variety_markers, extra_tag_markers, extra_tag_key, extra_tag_default
        )
        if products is None:
            all_problems.extend(problems)
            continue
        print_summary(csv_path, products, attrs)
        all_products[csv_path] = products
        all_attrs[csv_path] = attrs
        all_problems.extend(problems)

    total_rows = sum(len(v) for v in all_products.values())
    print(f"\nTotal rows across all 4 CSVs: {total_rows}")

    if all_problems:
        print(f"\n{len(all_problems)} PROBLEM(S) FOUND:")
        for p in all_problems[:30]:
            print(f"  - {p}")
        if len(all_problems) > 30:
            print(f"  ... and {len(all_problems) - 30} more")
        print("\nRefusing to import until the problems above are resolved.")
        sys.exit(1)

    print("\nNo problems found - data looks clean.")

    if dry_run:
        print("\n(--dry-run: no DB connection attempted, nothing was written)")
        return

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set. Make sure .env exists and contains DATABASE_URL.")
        sys.exit(1)

    print("\nConnecting to Neon...")
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    print("Connected.\n")

    for csv_path in all_products:
        prod_inserted, attr_inserted = run_import(cur, conn, all_products[csv_path], all_attrs[csv_path])
        total = len(all_products[csv_path])
        prod_skipped = total - prod_inserted
        attr_skipped = total - attr_inserted
        line1 = f"{csv_path}: products {prod_inserted} inserted / {prod_skipped} already existed; "
        line2 = f"attributes {attr_inserted} inserted / {attr_skipped} already existed"
        print(line1 + line2)

    cur.close()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
