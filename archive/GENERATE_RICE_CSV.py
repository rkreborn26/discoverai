#!/usr/bin/env python3
"""
DiscoverAI: Generate Rice Category CSV
=========================================

Populates cat_005 "Rice" with real Indian rice brands. Per your call,
variety (Basmati, Sona Masuri, Brown Rice, etc.) is NOT a separate category -
every row here goes into cat_005 directly, and the variety is captured as a
product attribute instead (see IMPORT_RICE_BATCH.py's VARIETY_MARKERS).
cat_006 "Basmati Rice" is intentionally left unused, same treatment as
cat_008 earlier.

Unlike the produce batches, most rice brands here are NOT offered in both
organic/regular versions - only 24 Mantra Organic's lines are organic (it's
an organic-focused brand), matching how rice is actually sold in India
rather than mechanically forcing an organic toggle everywhere.

ids continue from prod_1374 (last veg-expansion id) -> starts at prod_1375.
skus start at SKU1875.

Usage:
    python GENERATE_RICE_CSV.py
Writes: data/raw/rice_products.csv
"""

import csv
import math
from pathlib import Path

OUT_PATH = Path("data/raw/rice_products.csv")
START_ID = 1375
START_SKU = 1875

CREATED_AT = "2026-07-26 18:00:00.000000"

CSV_COLUMNS = [
    "id", "sku", "name", "category", "brand", "price", "original_price",
    "discount_percentage", "in_stock", "stock_quantity", "image_url",
    "description", "rating", "review_count", "is_active",
    "created_at", "updated_at", "deleted_at",
    "embedding", "embedding_full", "embedding_category", "embedding_name",
]

CATEGORY = "cat_005"
PACK_SIZES_KG = [1, 2, 5, 10]

# (brand, name_suffix_used_in_product_name, price_per_kg, discount_pct, blurb)
# name_suffix must contain a phrase from VARIETY_MARKERS in IMPORT_RICE_BATCH.py.
PRODUCTS = [
    ("India Gate", "Classic Basmati Rice", 130, 12,
     "India Gate's everyday basmati - long grain, aromatic, a household staple"),
    ("India Gate", "Extra Long Basmati Rice", 180, 12,
     "Extra long-grain basmati from India Gate, aged for extra aroma"),
    ("India Gate", "Parboiled Rice", 80, 10,
     "Parboiled rice that stays fluffy and separate, ideal for daily meals"),

    ("Daawat", "Rozana Basmati Rice", 110, 10,
     "Daawat's everyday basmati rice - consistent quality for daily cooking"),
    ("Daawat", "Traditional Aged Basmati Rice", 200, 15,
     "Daawat's signature aged basmati, extra long grains with rich aroma"),

    ("Kohinoor", "Charminar Basmati Rice", 140, 12,
     "Kohinoor's classic basmati, a trusted name for biryani and pulao"),

    ("Fortune", "Everyday Basmati Rice", 100, 10,
     "Fortune's value basmati rice for everyday meals"),
    ("Fortune", "Sona Masuri Rice", 60, 8,
     "Lightweight, easy-to-digest Sona Masuri rice popular in South India"),
    ("Fortune", "Brown Rice", 90, 10,
     "Unpolished brown rice, rich in fibre and nutrients"),

    ("Patanjali", "Basmati Rice", 95, 8,
     "Patanjali's affordable basmati rice"),
    ("Patanjali", "Sona Masuri Rice", 55, 8,
     "Patanjali's budget-friendly Sona Masuri rice"),

    ("24 Mantra Organic", "Organic Basmati Rice", 220, 15,
     "Certified organic basmati rice, grown without synthetic pesticides"),
    ("24 Mantra Organic", "Organic Brown Rice", 150, 15,
     "Certified organic brown rice, unpolished and nutrient-rich"),
    ("24 Mantra Organic", "Organic Sona Masuri Rice", 100, 15,
     "Certified organic Sona Masuri rice for everyday cooking"),

    ("Laxmi Bhog", "Gobindobhog Rice", 120, 10,
     "Fragrant short-grain Gobindobhog rice, a Bengali festive favourite"),
    ("Aachi", "Ponni Boiled Rice", 50, 8,
     "Ponni boiled rice, a South Indian staple for everyday meals"),
    ("Amira", "Idli Rice", 70, 8,
     "Parboiled idli rice for soft, fluffy idlis and crisp dosas"),
]


def bulk_factor(kg, anchor=1):
    doublings = math.log2(kg / anchor)
    return 0.933 ** doublings


def format_pack_size(kg):
    return f"{kg} kg" if kg > 1 else "1 kg"


def main():
    rows = []
    next_id = START_ID
    next_sku = START_SKU

    for brand, name_suffix, price_per_kg, discount_pct, blurb in PRODUCTS:
        organic = "organic" in brand.lower()
        for kg in PACK_SIZES_KG:
            pack_label = format_pack_size(kg)
            price = round(price_per_kg * kg * bulk_factor(kg), 2)
            original_price = round(price / (1 - discount_pct / 100), 2)

            name = f"{brand} {name_suffix} ({pack_label})"
            prefix = "Organic" if organic else "Regular"
            description = f"{prefix} {blurb}. Net weight: {pack_label}."

            rows.append({
                "id": f"prod_{next_id:03d}",
                "sku": f"SKU{next_sku}",
                "name": name,
                "category": CATEGORY,
                "brand": brand,
                "price": f"{price:.2f}",
                "original_price": f"{original_price:.2f}",
                "discount_percentage": str(discount_pct),
                "in_stock": "t",
                "stock_quantity": "150",
                "image_url": "",
                "description": description,
                "rating": "4.6",
                "review_count": "120",
                "is_active": "t",
                "created_at": CREATED_AT,
                "updated_at": CREATED_AT,
                "deleted_at": "",
                "embedding": "", "embedding_full": "", "embedding_category": "", "embedding_name": "",
            })
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
