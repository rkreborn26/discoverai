#!/usr/bin/env python3
"""
DiscoverAI: Retrofit Rice with organic/polish variants
==========================================================

The original Rice batch (68 rows, already imported) only had one
organic/polish combination per (brand, variety): regular+polished for most
brands, organic+polished for 24 Mantra Organic. This generates the MISSING
combinations only - regular+unpolished, organic+polished, and
organic+unpolished for the 14 non-organic-locked brands, and
organic+unpolished for 24 Mantra Organic - as new rows, leaving the
existing 68 untouched.

ids continue from prod_1582 (last Pulses id) -> starts at prod_1583.
skus start at SKU2083.

Usage:
    python GENERATE_RICE_RETROFIT_CSV.py
Writes: data/raw/rice_retrofit_products.csv
"""

import csv
import math
from pathlib import Path

OUT_PATH = Path("data/raw/rice_retrofit_products.csv")
START_ID = 1583
START_SKU = 2083

CREATED_AT = "2026-07-26 20:00:00.000000"

CSV_COLUMNS = [
    "id", "sku", "name", "category", "brand", "price", "original_price",
    "discount_percentage", "in_stock", "stock_quantity", "image_url",
    "description", "rating", "review_count", "is_active",
    "created_at", "updated_at", "deleted_at",
    "embedding", "embedding_full", "embedding_category", "embedding_name",
]

CATEGORY = "cat_005"
PACK_SIZES_KG = [1, 2, 5, 10]

ORGANIC_MULTIPLIER = 1.3
UNPOLISHED_MULTIPLIER = 1.15

# Same 17 (brand, base_suffix, price_per_kg, discount_pct, blurb) combos as
# the original Rice batch, with "Organic " already stripped from the 24
# Mantra Organic suffixes (organic_locked=True) since that redundancy was
# a naming bug (see FIX_RICE_NAMING.py for the already-live rows).
PRODUCTS = [
    ("India Gate", "Classic Basmati Rice", 130, 12,
     "India Gate's everyday basmati - long grain, aromatic, a household staple", False),
    ("India Gate", "Extra Long Basmati Rice", 180, 12,
     "Extra long-grain basmati from India Gate, aged for extra aroma", False),
    ("India Gate", "Parboiled Rice", 80, 10,
     "Parboiled rice that stays fluffy and separate, ideal for daily meals", False),

    ("Daawat", "Rozana Basmati Rice", 110, 10,
     "Daawat's everyday basmati rice - consistent quality for daily cooking", False),
    ("Daawat", "Traditional Aged Basmati Rice", 200, 15,
     "Daawat's signature aged basmati, extra long grains with rich aroma", False),

    ("Kohinoor", "Charminar Basmati Rice", 140, 12,
     "Kohinoor's classic basmati, a trusted name for biryani and pulao", False),

    ("Fortune", "Everyday Basmati Rice", 100, 10,
     "Fortune's value basmati rice for everyday meals", False),
    ("Fortune", "Sona Masuri Rice", 60, 8,
     "Lightweight, easy-to-digest Sona Masuri rice popular in South India", False),
    ("Fortune", "Brown Rice", 90, 10,
     "Brown rice, rich in fibre and nutrients", False),

    ("Patanjali", "Basmati Rice", 95, 8,
     "Patanjali's affordable basmati rice", False),
    ("Patanjali", "Sona Masuri Rice", 55, 8,
     "Patanjali's budget-friendly Sona Masuri rice", False),

    ("24 Mantra Organic", "Basmati Rice", 220, 15,
     "Certified organic basmati rice, grown without synthetic pesticides", True),
    ("24 Mantra Organic", "Brown Rice", 150, 15,
     "Certified organic brown rice, nutrient-rich", True),
    ("24 Mantra Organic", "Sona Masuri Rice", 100, 15,
     "Certified organic Sona Masuri rice for everyday cooking", True),

    ("Laxmi Bhog", "Gobindobhog Rice", 120, 10,
     "Fragrant short-grain Gobindobhog rice, a Bengali festive favourite", False),
    ("Aachi", "Ponni Boiled Rice", 50, 8,
     "Ponni boiled rice, a South Indian staple for everyday meals", False),
    ("Amira", "Idli Rice", 70, 8,
     "Parboiled idli rice for soft, fluffy idlis and crisp dosas", False),
]


def bulk_factor(kg, anchor=1):
    doublings = math.log2(kg / anchor)
    return 0.933 ** doublings


def format_pack_size(kg):
    return f"{kg} kg" if kg > 1 else "1 kg"


def build_name(brand, base_suffix, organic, polish):
    parts = []
    if organic and "organic" not in brand.lower():
        parts.append("Organic")
    if polish == "Unpolished":
        parts.append("Unpolished")
    parts.append(f"{brand} {base_suffix}")
    return " ".join(parts)


def main():
    rows = []
    next_id = START_ID
    next_sku = START_SKU
    skipped_existing = 0

    for brand, base_suffix, price_per_kg, discount_pct, blurb, organic_locked in PRODUCTS:
        organic_options = [True] if organic_locked else [False, True]
        for organic in organic_options:
            for polish in ("Polished", "Unpolished"):
                # The baseline combo (regular+polished for normal brands,
                # organic+polished for the organic-locked brand) already
                # exists from the original batch - skip it here.
                baseline = (organic == organic_locked) and polish == "Polished"
                if baseline:
                    skipped_existing += 1
                    continue

                for kg in PACK_SIZES_KG:
                    pack_label = format_pack_size(kg)
                    price = price_per_kg * kg * bulk_factor(kg)
                    if organic and not organic_locked:
                        price *= ORGANIC_MULTIPLIER
                    if polish == "Unpolished":
                        price *= UNPOLISHED_MULTIPLIER
                    price = round(price, 2)
                    original_price = round(price / (1 - discount_pct / 100), 2)

                    name = f"{build_name(brand, base_suffix, organic, polish)} ({pack_label})"
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
                    row["review_count"] = "120"
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
    print(f"(skipped {skipped_existing} baseline combos already live from the original batch)")
    print(f"id range: prod_{START_ID:03d} .. prod_{next_id - 1:03d}")
    print(f"sku range: SKU{START_SKU} .. SKU{next_sku - 1}")


if __name__ == "__main__":
    main()
