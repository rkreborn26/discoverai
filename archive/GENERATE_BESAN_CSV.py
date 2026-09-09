#!/usr/bin/env python3
"""
DiscoverAI: Generate Besan & Other Flours Category CSV
==========================================================

Populates cat_002d "Besan & Other Flours" (new category, run
CREATE_STAPLES_CATEGORIES.py first). Each (brand, variety) combo varies
across pack size (500g/1kg), organic vs regular (except 24 Mantra Organic),
and grind: Fine vs Coarse.

ids continue from prod_2026 (last Sugar & Salt id) -> starts at prod_2027.
skus start at SKU2527.

Usage:
    python GENERATE_BESAN_CSV.py
Writes: data/raw/besan_products.csv
"""

import csv
from pathlib import Path

import staples_common as sc

OUT_PATH = Path("data/raw/besan_products.csv")
START_ID = 2027
START_SKU = 2527

CREATED_AT = "2026-07-27 09:00:00.000000"

CSV_COLUMNS = [
    "id", "sku", "name", "category", "brand", "price", "original_price",
    "discount_percentage", "in_stock", "stock_quantity", "image_url",
    "description", "rating", "review_count", "is_active",
    "created_at", "updated_at", "deleted_at",
    "embedding", "embedding_full", "embedding_category", "embedding_name",
]

CATEGORY = "cat_002d"
PACK_SIZES_G = [500, 1000]
ORGANIC_MULTIPLIER = 1.3
COARSE_MULTIPLIER = 1.1

PRODUCTS = [
    ("Aashirvaad", "Besan", 90, 10, "Roasted gram flour for pakoras and curries", False),
    ("Aashirvaad", "Rava", 50, 8, "Semolina for upma and halwa", False),
    ("Fortune", "Besan", 85, 10, "Fortune's everyday besan", False),
    ("Fortune", "Rice Flour", 60, 8, "Fine rice flour for dosas and sweets", False),
    ("Patanjali", "Besan", 80, 8, "Patanjali's affordable besan", False),
    ("Patanjali", "Ragi Flour", 100, 10, "Finger millet flour, rich in calcium", False),
    ("Rajdhani", "Rava", 48, 8, "Rajdhani's everyday suji/rava", False),
    ("Rajdhani", "Rice Flour", 55, 8, "Rajdhani's rice flour", False),
    ("24 Mantra Organic", "Besan", 150, 15, "Certified organic besan", True),
    ("24 Mantra Organic", "Ragi Flour", 160, 15, "Certified organic ragi flour", True),
]


def main():
    rows = []
    next_id = START_ID
    next_sku = START_SKU

    for brand, variety, price_per_kg, discount_pct, blurb, organic_locked in PRODUCTS:
        organic_options = [True] if organic_locked else [False, True]
        for grams in PACK_SIZES_G:
            pack_label = sc.format_pack_label(grams, "g")
            for organic in organic_options:
                for grind in ("Fine", "Coarse"):
                    price = price_per_kg * (grams / 1000.0) * sc.bulk_factor(grams, anchor=500)
                    if organic and not organic_locked:
                        price *= ORGANIC_MULTIPLIER
                    if grind == "Coarse":
                        price *= COARSE_MULTIPLIER
                    price = round(price, 2)
                    original_price = round(price / (1 - discount_pct / 100), 2)

                    extra_tag = "Coarse" if grind == "Coarse" else None
                    name = sc.build_variant_name(brand, variety, organic, organic_locked, extra_tag, pack_label)
                    organic_word = "Organic" if organic else "Regular"
                    description = f"{organic_word}, {grind.lower()}-ground {blurb}. Net weight: {pack_label}."

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
