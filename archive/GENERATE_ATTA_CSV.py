#!/usr/bin/env python3
"""
DiscoverAI: Generate Atta & Wheat Flour Category CSV
========================================================

Populates cat_002a "Atta & Wheat Flour" (new category, run
CREATE_STAPLES_CATEGORIES.py first). Each (brand, variety) combo varies
across pack size (1kg/5kg), organic vs regular (except 24 Mantra Organic,
which is organic-only), and milling: Roller Mill vs Stone-Ground (Chakki) -
a real, common premium distinction in Indian atta marketing, playing the
same role "polished/unpolished" did for dal.

ids continue from prod_1762 (last Rice-retrofit id) -> starts at prod_1763.
skus start at SKU2263.

Usage:
    python GENERATE_ATTA_CSV.py
Writes: data/raw/atta_products.csv
"""

import csv
from pathlib import Path

import staples_common as sc

OUT_PATH = Path("data/raw/atta_products.csv")
START_ID = 1763
START_SKU = 2263

CREATED_AT = "2026-07-27 09:00:00.000000"

CSV_COLUMNS = [
    "id", "sku", "name", "category", "brand", "price", "original_price",
    "discount_percentage", "in_stock", "stock_quantity", "image_url",
    "description", "rating", "review_count", "is_active",
    "created_at", "updated_at", "deleted_at",
    "embedding", "embedding_full", "embedding_category", "embedding_name",
]

CATEGORY = "cat_002a"
PACK_SIZES_KG = [1, 5]
ORGANIC_MULTIPLIER = 1.3
STONE_GROUND_MULTIPLIER = 1.15

# (brand, variety, price_per_kg, discount_pct, blurb, organic_locked)
PRODUCTS = [
    ("Aashirvaad", "Whole Wheat Atta", 45, 10, "100% whole wheat atta for soft rotis", False),
    ("Aashirvaad", "Multigrain Atta", 70, 10, "A blend of wheat, soy, oats and more", False),
    ("Aashirvaad", "Maida", 40, 8, "Refined flour for baking and street food", False),
    ("Pillsbury", "Whole Wheat Atta", 42, 10, "Chakki-fresh whole wheat atta", False),
    ("Pillsbury", "Chakki Fresh Atta", 48, 10, "Stone-ground for extra softness", False),
    ("Annapurna", "Whole Wheat Atta", 40, 8, "Everyday whole wheat atta", False),
    ("Fortune", "Whole Wheat Atta", 44, 10, "Fortune's everyday chakki atta", False),
    ("Fortune", "Multigrain Atta", 68, 10, "Multigrain atta with 6 grains and pulses", False),
    ("Patanjali", "Whole Wheat Atta", 38, 8, "Patanjali's affordable whole wheat atta", False),
    ("Patanjali", "Maida", 35, 8, "Patanjali's refined flour", False),
    ("24 Mantra Organic", "Whole Wheat Atta", 90, 15, "Certified organic whole wheat atta", True),
    ("24 Mantra Organic", "Multigrain Atta", 110, 15, "Certified organic multigrain atta", True),
]


def main():
    rows = []
    next_id = START_ID
    next_sku = START_SKU

    for brand, variety, price_per_kg, discount_pct, blurb, organic_locked in PRODUCTS:
        organic_options = [True] if organic_locked else [False, True]
        for kg in PACK_SIZES_KG:
            grams = kg * 1000
            pack_label = sc.format_pack_label(grams, "g")
            for organic in organic_options:
                for milling in ("Roller Mill", "Stone-Ground"):
                    price = price_per_kg * kg * sc.bulk_factor(kg, anchor=1)
                    if organic and not organic_locked:
                        price *= ORGANIC_MULTIPLIER
                    if milling == "Stone-Ground":
                        price *= STONE_GROUND_MULTIPLIER
                    price = round(price, 2)
                    original_price = round(price / (1 - discount_pct / 100), 2)

                    extra_tag = "Stone-Ground" if milling == "Stone-Ground" else None
                    name = sc.build_variant_name(brand, variety, organic, organic_locked, extra_tag, pack_label)
                    organic_word = "Organic" if organic else "Regular"
                    description = f"{organic_word}, {milling.lower()} {blurb}. Net weight: {pack_label}."

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
