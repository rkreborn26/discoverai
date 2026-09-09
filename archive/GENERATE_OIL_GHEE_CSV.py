#!/usr/bin/env python3
"""
DiscoverAI: Generate Cooking Oil & Ghee Category CSV
========================================================

Populates cat_002b "Cooking Oil & Ghee" (new category, run
CREATE_STAPLES_CATEGORIES.py first). Each (brand, variety) combo varies
across pack size (500ml/1L), organic vs regular (except 24 Mantra Organic),
and Refined vs Cold-Pressed - the standard quality distinction for Indian
cooking oils (and used loosely for ghee too, as regular vs
hand-churned/bilona-style), playing the same role "polished/unpolished"
did for dal.

ids continue from prod_1850 (last Atta id) -> starts at prod_1851.
skus start at SKU2351.

Usage:
    python GENERATE_OIL_GHEE_CSV.py
Writes: data/raw/oil_ghee_products.csv
"""

import csv
from pathlib import Path

import staples_common as sc

OUT_PATH = Path("data/raw/oil_ghee_products.csv")
START_ID = 1851
START_SKU = 2351

CREATED_AT = "2026-07-27 09:00:00.000000"

CSV_COLUMNS = [
    "id", "sku", "name", "category", "brand", "price", "original_price",
    "discount_percentage", "in_stock", "stock_quantity", "image_url",
    "description", "rating", "review_count", "is_active",
    "created_at", "updated_at", "deleted_at",
    "embedding", "embedding_full", "embedding_category", "embedding_name",
]

CATEGORY = "cat_002b"
PACK_SIZES_ML = [500, 1000]
ORGANIC_MULTIPLIER = 1.3
COLD_PRESSED_MULTIPLIER = 1.2

# (brand, variety, price_per_liter, discount_pct, blurb, organic_locked)
PRODUCTS = [
    ("Fortune", "Sunflower Oil", 140, 10, "Light, everyday sunflower cooking oil", False),
    ("Fortune", "Soybean Oil", 130, 10, "Everyday soybean cooking oil", False),
    ("Saffola", "Sunflower Oil Gold", 160, 10, "Heart-friendly sunflower oil blend", False),
    ("Dhara", "Mustard Oil", 150, 10, "Pungent, flavourful mustard oil for Indian cooking", False),
    ("Patanjali", "Mustard Oil", 130, 8, "Patanjali's affordable mustard oil", False),
    ("Patanjali", "Groundnut Oil", 170, 8, "Patanjali's groundnut cooking oil", False),
    ("Patanjali", "Cow Ghee", 550, 10, "Patanjali's pure cow ghee", False),
    ("Amul", "Cow Ghee", 600, 10, "Amul's classic pure cow ghee", False),
    ("Amul", "Pure Ghee", 650, 12, "Amul's premium pure ghee", False),
    ("Mother Dairy", "Cow Ghee", 580, 10, "Mother Dairy's pure cow ghee", False),
    ("24 Mantra Organic", "Groundnut Oil", 220, 15, "Certified organic groundnut oil", True),
    ("24 Mantra Organic", "Mustard Oil", 200, 15, "Certified organic mustard oil", True),
]


def main():
    rows = []
    next_id = START_ID
    next_sku = START_SKU

    for brand, variety, price_per_liter, discount_pct, blurb, organic_locked in PRODUCTS:
        organic_options = [True] if organic_locked else [False, True]
        for ml in PACK_SIZES_ML:
            pack_label = sc.format_pack_label(ml, "ml")
            for organic in organic_options:
                for process in ("Refined", "Cold-Pressed"):
                    liters = ml / 1000.0
                    price = price_per_liter * liters * sc.bulk_factor(ml, anchor=500)
                    if organic and not organic_locked:
                        price *= ORGANIC_MULTIPLIER
                    if process == "Cold-Pressed":
                        price *= COLD_PRESSED_MULTIPLIER
                    price = round(price, 2)
                    original_price = round(price / (1 - discount_pct / 100), 2)

                    extra_tag = "Cold-Pressed" if process == "Cold-Pressed" else None
                    name = sc.build_variant_name(brand, variety, organic, organic_locked, extra_tag, pack_label)
                    organic_word = "Organic" if organic else "Regular"
                    description = f"{organic_word}, {process.lower()} {blurb}. Net volume: {pack_label}."

                    row = {}
                    row["id"] = f"prod_{next_id:03d}"
                    row["sku"] = f"SKU{next_sku}"
                    row["name"] = name
                    row["category"] = CATEGORY
                    row["brand"] = brand
                    row["price"] = f"{price:.2f}"
                    row["original_price"] = f"{original_price:.2f}"
                    row["discount_percentage"] = str(discount_pct)
                    row["in_stock"] = "t"
                    row["stock_quantity"] = "150"
                    row["image_url"] = ""
                    row["description"] = description
                    row["rating"] = "4.6"
                    row["review_count"] = "115"
                    row["is_active"] = "t"
                    row["created_at"] = CREATED_AT
                    row["updated_at"] = CREATED_AT
                    row["deleted_at"] = ""
                    row["embedding"] = ""
                    row["embedding_full"] = ""
                    row["embedding_category"] = ""
                    row["embedding_name"] = ""
                    rows.append(row)

                    next_id += 1
                    next_sku += 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUT_PATH}")
    print(f"id range: prod_{START_ID:03d} .. prod_{next_id - 1:03d}")
    print(f"sku range: SKU{START_SKU} .. SKU{next_sku - 1}")


if __name__ == "__main__":
    main()
