#!/usr/bin/env python3
"""
DiscoverAI: Generate Pulses & Lentils Category CSV (v2 - full variant matrix)
=================================================================================

Populates cat_016 "Pulses & Lentils" with real branded dal products,
alongside the 6 existing brand='Generic' items already there.

Per your request, every (brand, variety) combo now varies across:
  - pack size: 500g, 1kg
  - organic vs regular (both offered per brand, except 24 Mantra Organic,
    which is an organic-only brand - no "regular" counterpart would make
    sense there)
  - polished vs unpolished (a real, common distinction in Indian dal
    marketing - Tata Sampann's whole positioning, for example, is
    "unpolished dal")

ids continue from prod_1442 (last Rice id) -> starts at prod_1443.
skus start at SKU1943.

Usage:
    python GENERATE_PULSES_CSV.py
Writes: data/raw/pulses_products.csv
"""

import csv
import math
from pathlib import Path

OUT_PATH = Path("data/raw/pulses_products.csv")
START_ID = 1443
START_SKU = 1943

CREATED_AT = "2026-07-26 19:00:00.000000"

CSV_COLUMNS = [
    "id", "sku", "name", "category", "brand", "price", "original_price",
    "discount_percentage", "in_stock", "stock_quantity", "image_url",
    "description", "rating", "review_count", "is_active",
    "created_at", "updated_at", "deleted_at",
    "embedding", "embedding_full", "embedding_category", "embedding_name",
]

CATEGORY = "cat_016"
PACK_SIZES_G = [500, 1000]

ORGANIC_MULTIPLIER = 1.3
UNPOLISHED_MULTIPLIER = 1.15

PRODUCTS = [
    ("Tata Sampann", "Toor Dal", 160, 10, "Toor dal, a kitchen staple", False),
    ("Tata Sampann", "Moong Dal Split", 150, 10, "Split moong dal, easy to cook and digest", False),
    ("Tata Sampann", "Chana Dal", 110, 10, "Chana dal for dal, snacks and sweets", False),
    ("Tata Sampann", "Masoor Dal", 130, 10, "Masoor dal, quick-cooking and protein-rich", False),

    ("Fortune", "Toor Dal", 150, 10, "Fortune's everyday toor dal", False),
    ("Fortune", "Urad Dal Split", 140, 10, "Split urad dal for dal makhani, idli and dosa batter", False),
    ("Fortune", "Kabuli Chana", 120, 10, "White chickpeas for chole, salads and curries", False),
    ("Fortune", "Rajma Chitra", 160, 12, "Speckled rajma beans, lighter than red kidney beans", False),

    ("Patanjali", "Moong Dal Split", 130, 8, "Patanjali's affordable split moong dal", False),
    ("Patanjali", "Chana Dal", 100, 8, "Patanjali's budget-friendly chana dal", False),
    ("Patanjali", "Rajma", 140, 8, "Patanjali's red kidney beans for rajma curry", False),

    ("24 Mantra Organic", "Toor Dal", 220, 15, "Certified organic toor dal", True),
    ("24 Mantra Organic", "Moong Dal Split", 210, 15, "Certified organic split moong dal", True),
    ("24 Mantra Organic", "Masoor Dal", 200, 15, "Certified organic masoor dal", True),

    ("Rajdhani", "Urad Dal Whole", 150, 10, "Whole black urad dal (sabut), used in dal makhani", False),
    ("Rajdhani", "Kala Chana", 100, 10, "Black chickpeas for chana chaat and curries", False),

    ("Laxmi", "Val Dal", 130, 10, "Val dal (lima bean split), a Gujarati/Maharashtrian staple", False),
    ("Amrit", "Horse Gram", 90, 8, "Horse gram (kulthi), rich in protein and iron", False),
    ("Aashirvaad", "Green Moong Whole", 140, 10, "Whole green moong beans, great for sprouting", False),
]


def bulk_factor(grams, anchor=500):
    doublings = math.log2(grams / anchor)
    return 0.933 ** doublings


def format_pack_size(grams):
    if grams >= 1000 and grams % 1000 == 0:
        kg = grams // 1000
        return f"{kg} kg" if kg > 1 else "1 kg"
    return f"{grams}g"


def build_name(brand, variety, organic, polish, pack_label):
    parts = []
    if organic and "organic" not in brand.lower():
        parts.append("Organic")
    if polish == "Unpolished":
        parts.append("Unpolished")
    parts.append(f"{brand} {variety}")
    return f"{' '.join(parts)} ({pack_label})"


def main():
    rows = []
    next_id = START_ID
    next_sku = START_SKU

    for brand, variety, price_per_kg, discount_pct, blurb, organic_locked in PRODUCTS:
        organic_options = [True] if organic_locked else [False, True]
        for grams in PACK_SIZES_G:
            pack_label = format_pack_size(grams)
            for organic in organic_options:
                for polish in ("Polished", "Unpolished"):
                    price = price_per_kg * (grams / 1000.0) * bulk_factor(grams)
                    if organic and not organic_locked:
                        price *= ORGANIC_MULTIPLIER
                    if polish == "Unpolished":
                        price *= UNPOLISHED_MULTIPLIER
                    price = round(price, 2)
                    original_price = round(price / (1 - discount_pct / 100), 2)

                    name = build_name(brand, variety, organic, polish, pack_label)
                    organic_word = "Organic" if organic else "Regular"
                    description = f"{organic_word}, {polish.lower()} {blurb}. Net weight: {pack_label}."

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
                    row["review_count"] = "110"
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
