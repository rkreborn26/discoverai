#!/usr/bin/env python3
"""
DiscoverAI: Generate Fruits Product CSV
==========================================

Builds a synthetic-but-realistic Fruits catalog across the 6 existing Fruits
categories (Citrus, Berries, Melons, Tropical & Exotic, Pome & Core, Stone
Fruits), following the exact same conventions established by the Fruits &
Vegetables "Daily Cooking Staples" batch:

  - Two brands: "My-Farm" (regular) and "Organic India" (organic)
  - Prep variants baked into the name (Whole / Peeled / Diced / Sliced /
    Deseeded / Pitted / Cut), each an individual SKU
  - Multiple pack sizes per product, each an individual SKU
  - Price scales with pack size (~7% bulk discount per doubling), with a
    markup for organic (~33%) and for prepped/cut variants (~15-30%
    depending on how much labor the prep implies)

ids continue from prod_450 (last vegetable id) -> starts at prod_451.
skus start at SKU951 as requested.

Usage:
    python GENERATE_FRUITS_CSV.py
Writes: data/raw/fruits_products_generated.csv
"""

import csv
import math
import random
from pathlib import Path

random.seed(42)

OUT_PATH = Path("data/raw/fruits_products_generated.csv")
START_ID = 451
START_SKU = 951

CREATED_AT = "2026-07-26 09:00:00.000000"

CSV_COLUMNS = [
    "id", "sku", "name", "category", "brand", "price", "original_price",
    "discount_percentage", "in_stock", "stock_quantity", "image_url",
    "description", "rating", "review_count", "is_active",
    "created_at", "updated_at", "deleted_at",
    "embedding", "embedding_full", "embedding_category", "embedding_name",
]

# Prep label -> markup multiplier over the "Whole" price for that pack size.
PREP_MARKUP = {
    "Whole": 1.0,
    "Peeled": 1.15,
    "Peeled & Sliced": 1.28,
    "Peeled & Diced": 1.30,
    "Diced": 1.22,
    "Sliced": 1.20,
    "Deseeded": 1.30,
    "Pitted": 1.25,
    "Cut": 1.20,
}

ORGANIC_MULTIPLIER = 1.33

# ------------------------------------------------------------------
# Product catalog config.
#
# price_per_kg: regular/My-Farm, "Whole", anchor price at 250g-equivalent
#               scaling (see bulk_factor below).
# preps: list of prep labels applied (from PREP_MARKUP); "Whole" always
#        first / implicit (no name prefix).
# pack_sizes: list of pack sizes (grams) applied to every prep, OR a dict
#             {prep_label: [grams, ...]} if packs differ by prep (used for
#             melons: whole melons sold bigger than cut/diced melon).
# ------------------------------------------------------------------
PRODUCTS = [
    # --- Citrus Fruits: cat_003a1 ---
    dict(category="cat_003a1", name="Orange / Santra", price_per_kg=80,
         preps=["Whole", "Peeled"], pack_sizes=[250, 500, 1000],
         flavor="Juicy, vitamin-C rich oranges perfect for snacking or fresh juice"),
    dict(category="cat_003a1", name="Mosambi / Sweet Lime", price_per_kg=70,
         preps=["Whole"], pack_sizes=[250, 500, 1000],
         flavor="Mild, sweet citrus popularly juiced for its cooling properties"),
    dict(category="cat_003a1", name="Lemon / Nimbu", price_per_kg=60,
         preps=["Whole"], pack_sizes=[250, 500, 1000],
         flavor="Tangy everyday lemons for cooking, garnish and nimbu paani"),
    dict(category="cat_003a1", name="Grapefruit / Chakotra", price_per_kg=90,
         preps=["Whole", "Peeled"], pack_sizes=[250, 500, 1000],
         flavor="Tart-sweet grapefruit, a breakfast favourite rich in vitamin C"),
    dict(category="cat_003a1", name="Kinnow", price_per_kg=70,
         preps=["Whole"], pack_sizes=[250, 500, 1000],
         flavor="North Indian mandarin hybrid, easy to peel and extra juicy"),

    # --- Berries: cat_003a2 ---
    dict(category="cat_003a2", name="Strawberry", price_per_kg=400,
         preps=["Whole"], pack_sizes=[125, 250, 500],
         flavor="Sweet-tart strawberries, best enjoyed fresh or with cream"),
    dict(category="cat_003a2", name="Blueberry", price_per_kg=1200,
         preps=["Whole"], pack_sizes=[125, 250, 500],
         flavor="Antioxidant-rich blueberries, great for smoothies and cereal"),
    dict(category="cat_003a2", name="Blackberry", price_per_kg=900,
         preps=["Whole"], pack_sizes=[125, 250, 500],
         flavor="Deep, sweet-tart blackberries picked at peak ripeness"),
    dict(category="cat_003a2", name="Raspberry", price_per_kg=1400,
         preps=["Whole"], pack_sizes=[125, 250, 500],
         flavor="Delicate, fragrant raspberries for desserts and snacking"),
    dict(category="cat_003a2", name="Mulberry / Shahtoot", price_per_kg=300,
         preps=["Whole"], pack_sizes=[125, 250, 500],
         flavor="Seasonal mulberries with a rich, wine-sweet flavour"),

    # --- Melons: cat_003a3 ---
    dict(category="cat_003a3", name="Watermelon / Tarbuz", price_per_kg=25,
         preps=["Whole", "Diced"],
         pack_sizes={"Whole": [1000, 2000, 3000], "Diced": [250, 500, 1000]},
         flavor="Refreshing, hydrating watermelon - a summer favourite"),
    dict(category="cat_003a3", name="Muskmelon / Kharbuja", price_per_kg=40,
         preps=["Whole", "Diced"],
         pack_sizes={"Whole": [1000, 2000], "Diced": [250, 500, 1000]},
         flavor="Fragrant, sweet muskmelon with soft orange flesh"),
    dict(category="cat_003a3", name="Honeydew Melon", price_per_kg=90,
         preps=["Whole", "Diced"],
         pack_sizes={"Whole": [1000, 2000], "Diced": [250, 500, 1000]},
         flavor="Pale green, honey-sweet melon with a smooth texture"),

    # --- Tropical & Exotic Fruits: cat_003a4 ---
    dict(category="cat_003a4", name="Banana / Kela", price_per_kg=50,
         preps=["Whole", "Peeled & Sliced"], pack_sizes=[250, 500, 1000, 2000],
         flavor="Everyday bananas, a quick source of natural energy"),
    dict(category="cat_003a4", name="Papaya / Papita", price_per_kg=40,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500, 1000, 2000],
         flavor="Soft, sweet papaya rich in fibre and digestive enzymes"),
    dict(category="cat_003a4", name="Pineapple / Ananas", price_per_kg=60,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500, 1000, 2000],
         flavor="Tangy-sweet pineapple, delicious fresh or grilled"),
    dict(category="cat_003a4", name="Guava / Amrud", price_per_kg=70,
         preps=["Whole", "Diced"], pack_sizes=[250, 500, 1000],
         flavor="Crisp, fragrant guava packed with vitamin C"),
    dict(category="cat_003a4", name="Pomegranate / Anar", price_per_kg=150,
         preps=["Whole", "Deseeded"], pack_sizes=[250, 500, 1000],
         flavor="Juicy pomegranate arils, a favourite for salads and juice"),
    dict(category="cat_003a4", name="Dragon Fruit", price_per_kg=250,
         preps=["Whole", "Diced"], pack_sizes=[250, 500, 1000],
         flavor="Striking pink-skinned dragon fruit with mildly sweet flesh"),
    dict(category="cat_003a4", name="Kiwi", price_per_kg=400,
         preps=["Whole", "Peeled & Sliced"], pack_sizes=[250, 500, 1000],
         flavor="Tangy-sweet kiwi, an excellent source of vitamin C"),
    dict(category="cat_003a4", name="Chikoo / Sapota", price_per_kg=80,
         preps=["Whole", "Peeled"], pack_sizes=[250, 500, 1000],
         flavor="Malty-sweet chikoo, soft and naturally sugar-rich"),
    dict(category="cat_003a4", name="Custard Apple / Sitaphal", price_per_kg=120,
         preps=["Whole"], pack_sizes=[250, 500, 1000],
         flavor="Creamy, custard-like sitaphal pulp with a sweet flavour"),
    dict(category="cat_003a4", name="Grapes / Angoor (Green)", price_per_kg=90,
         preps=["Whole"], pack_sizes=[250, 500, 1000],
         flavor="Crisp, juicy seedless green grapes"),
    dict(category="cat_003a4", name="Grapes / Angoor (Black)", price_per_kg=90,
         preps=["Whole"], pack_sizes=[250, 500, 1000],
         flavor="Sweet, deep-coloured black grapes"),
    dict(category="cat_003a4", name="Coconut / Nariyal", price_per_kg=50,
         preps=["Whole", "Cut"], pack_sizes=[250, 500, 1000],
         flavor="Fresh coconut for cooking, chutneys and coconut water"),

    # --- Pome & Core Fruits: cat_003a5 ---
    dict(category="cat_003a5", name="Apple - Shimla / Kashmiri (Red)", price_per_kg=180,
         preps=["Whole", "Peeled & Sliced"], pack_sizes=[250, 500, 1000, 2000],
         flavor="Crisp, sweet red apples grown in the Himalayan foothills"),
    dict(category="cat_003a5", name="Apple - Green (Granny Smith style)", price_per_kg=200,
         preps=["Whole", "Peeled & Sliced"], pack_sizes=[250, 500, 1000, 2000],
         flavor="Tart, firm green apples great for snacking or baking"),
    dict(category="cat_003a5", name="Pear / Nashpati", price_per_kg=140,
         preps=["Whole", "Peeled & Sliced"], pack_sizes=[250, 500, 1000, 2000],
         flavor="Juicy, mildly sweet pears with a soft, grainy texture"),

    # --- Stone Fruits: cat_003a6 ---
    dict(category="cat_003a6", name="Mango / Aam (Alphonso)", price_per_kg=350,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500, 1000, 2000],
         flavor="The king of mangoes - rich, saffron-hued and intensely sweet"),
    dict(category="cat_003a6", name="Mango / Aam (Kesar)", price_per_kg=200,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500, 1000, 2000],
         flavor="Aromatic Kesar mango with a distinctive saffron-orange pulp"),
    dict(category="cat_003a6", name="Mango / Aam (Dasheri)", price_per_kg=120,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500, 1000, 2000],
         flavor="Fibreless, fragrant Dasheri mango - a North Indian favourite"),
    dict(category="cat_003a6", name="Mango / Aam (Totapuri)", price_per_kg=80,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500, 1000, 2000],
         flavor="Tangy, firm Totapuri mango, popular for slicing and salads"),
    dict(category="cat_003a6", name="Peach / Aadu", price_per_kg=200,
         preps=["Whole"], pack_sizes=[250, 500, 1000],
         flavor="Soft, fragrant peaches with a sweet-tart flavour"),
    dict(category="cat_003a6", name="Plum / Aloo Bukhara", price_per_kg=180,
         preps=["Whole"], pack_sizes=[250, 500, 1000],
         flavor="Juicy plums with a sweet-tart bite, perfect for snacking"),
    dict(category="cat_003a6", name="Apricot / Khubani", price_per_kg=300,
         preps=["Whole"], pack_sizes=[250, 500, 1000],
         flavor="Delicate, honey-sweet apricots with a velvety skin"),
    dict(category="cat_003a6", name="Litchi / Lychee", price_per_kg=250,
         preps=["Whole", "Peeled"], pack_sizes=[250, 500, 1000],
         flavor="Fragrant, juicy lychee with a floral sweetness"),
    dict(category="cat_003a6", name="Cherry", price_per_kg=800,
         preps=["Whole", "Pitted"], pack_sizes=[250, 500, 1000],
         flavor="Deep red, glossy cherries - a premium seasonal treat"),
]


def bulk_factor(grams, anchor=250):
    """~7% cheaper per 100g as pack size doubles (matches the vegetables batch)."""
    doublings = math.log2(grams / anchor)
    return 0.933 ** doublings


def format_pack_size(grams):
    if grams >= 1000 and grams % 1000 == 0:
        kg = grams // 1000
        return f"{kg} kg" if kg > 1 else "1 kg"
    return f"{grams}g"


def price_for(price_per_kg, grams, prep):
    base = price_per_kg * (grams / 1000.0) * bulk_factor(grams)
    marked_up = base * PREP_MARKUP.get(prep, 1.25)
    return marked_up


def build_name(base_name, organic, prep, pack_label):
    parts = []
    if organic:
        parts.append("Organic")
    if prep != "Whole":
        parts.append(prep)
    parts.append(base_name)
    return f"{' '.join(parts)} ({pack_label})"


def build_description(organic, prep, flavor, pack_label):
    prefix = "Organic" if organic else "Regular"
    return f"{prefix} {prep} {flavor}. Net weight: {pack_label}."


def main():
    rows = []
    next_id = START_ID
    next_sku = START_SKU

    for product in PRODUCTS:
        category = product["category"]
        base_name = product["name"]
        price_per_kg = product["price_per_kg"]
        flavor = product["flavor"]
        preps = product["preps"]
        pack_sizes_cfg = product["pack_sizes"]

        for prep in preps:
            grams_list = pack_sizes_cfg[prep] if isinstance(pack_sizes_cfg, dict) else pack_sizes_cfg
            for grams in grams_list:
                pack_label = format_pack_size(grams)
                for organic in (False, True):
                    brand = "Organic India" if organic else "My-Farm"
                    price = price_for(price_per_kg, grams, prep)
                    if organic:
                        price *= ORGANIC_MULTIPLIER
                    price = round(price, 2)
                    if price < 1:
                        price = 1.0

                    discount_pct = random.choice([8, 10, 12, 13, 15, 18])
                    original_price = round(price / (1 - discount_pct / 100), 2)

                    name = build_name(base_name, organic, prep, pack_label)
                    description = build_description(organic, prep, flavor, pack_label)
                    rating = round(random.uniform(4.3, 4.9), 1)
                    review_count = random.randint(35, 160)

                    rows.append({
                        "id": f"prod_{next_id:03d}",
                        "sku": f"SKU{next_sku}",
                        "name": name,
                        "category": category,
                        "brand": brand,
                        "price": f"{price:.2f}",
                        "original_price": f"{original_price:.2f}",
                        "discount_percentage": str(discount_pct),
                        "in_stock": "t",
                        "stock_quantity": "120",
                        "image_url": "",
                        "description": description,
                        "rating": str(rating),
                        "review_count": str(review_count),
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
