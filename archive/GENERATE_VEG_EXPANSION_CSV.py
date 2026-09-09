#!/usr/bin/env python3
"""
DiscoverAI: Generate Vegetables Category-Expansion CSV
=========================================================

Fills the 19 leaf categories under "Vegetables" that were still empty even
after the Daily Cooking Staples batch (see MISSING_CATEGORIES export) -
Green Beans/Peas/Okra, Asparagus & Artichokes, Mushrooms, Asian/Regional
Specialty Veggies, the 3 convenience/kit categories, Spinach & Kale,
Lettuces & Salad Mixes, Herbs & Seasonings, Microgreens & Sprouts, Carrots &
Beetroots, Radishes & Turnips, Yams/Taro & Exotic Tubers, Cucumbers,
Zucchini & Summer Squash, Pumpkins & Winter Squash, Broccoli & Cauliflower,
and Cabbage & Brussels Sprouts.

Every item here is deliberately DIFFERENT from what's already in Daily
Cooking Staples (cat_007a_01..10) - e.g. Kale instead of re-adding Spinach,
Brussels Sprouts instead of re-adding Cabbage, Oyster/Shiitake instead of
re-adding Button Mushroom - since a product can only live in one category
and duplicating the same vegetable elsewhere would just create confusing
near-duplicate listings. cat_008 ("Root Vegetables", a likely-duplicate of
cat_007c) is intentionally left empty per instruction.

ids continue from prod_846 (last fruits id) -> starts at prod_847.
skus start at SKU1347.

Usage:
    python GENERATE_VEG_EXPANSION_CSV.py
Writes: data/raw/veg_expansion_products.csv
"""

import csv
import math
import random
from pathlib import Path

random.seed(7)

OUT_PATH = Path("data/raw/veg_expansion_products.csv")
START_ID = 847
START_SKU = 1347

CREATED_AT = "2026-07-26 15:00:00.000000"

CSV_COLUMNS = [
    "id", "sku", "name", "category", "brand", "price", "original_price",
    "discount_percentage", "in_stock", "stock_quantity", "image_url",
    "description", "rating", "review_count", "is_active",
    "created_at", "updated_at", "deleted_at",
    "embedding", "embedding_full", "embedding_category", "embedding_name",
]

PREP_MARKUP = {
    "Whole": 1.0,
    "Chopped": 1.22,
    "Sliced": 1.20,
    "Shredded": 1.20,
    "Peeled": 1.15,
    "Peeled & Diced": 1.30,
    "Cut Florets": 1.25,
    "Halved": 1.15,
    "Plucked": 1.15,
    "Mix": 1.0,
}

ORGANIC_MULTIPLIER = 1.33

# Each product: category, name, price_per_kg (or per-pack-equivalent for
# kits), preps applied, pack sizes in grams, and a short flavor blurb.
PRODUCTS = [
    # --- cat_007e_03: Green Beans, Peas & Okra (distinct from French
    # Beans/Green Peas/Cowpea/Bhindi already in Daily Cooking Staples) ---
    dict(category="cat_007e_03", name="Snap Peas", price_per_kg=180,
         preps=["Whole"], pack_sizes=[100, 250, 500],
         flavor="Crisp, sweet snap peas eaten pod and all"),
    dict(category="cat_007e_03", name="Yardlong Beans / Chawli", price_per_kg=60,
         preps=["Whole", "Chopped"], pack_sizes=[250, 500, 1000],
         flavor="Long, tender beans popular in stir-fries and sabzi"),
    dict(category="cat_007e_03", name="Broad Beans / Papdi", price_per_kg=90,
         preps=["Whole", "Peeled"], pack_sizes=[250, 500, 1000],
         flavor="Flat, hearty broad beans with a mild earthy flavour"),
    dict(category="cat_007e_03", name="Runner Beans", price_per_kg=100,
         preps=["Whole", "Chopped"], pack_sizes=[250, 500, 1000],
         flavor="Robust green beans with a firm bite, great for curries"),

    # --- cat_007f_01: Asparagus & Artichokes ---
    dict(category="cat_007f_01", name="Asparagus", price_per_kg=400,
         preps=["Whole", "Chopped"], pack_sizes=[100, 250, 500],
         flavor="Tender asparagus spears, delicious grilled or sauteed"),
    dict(category="cat_007f_01", name="Artichoke", price_per_kg=350,
         preps=["Whole"], pack_sizes=[250, 500],
         flavor="Globe artichokes with a nutty, delicate heart"),

    # --- cat_007f_02: Mushrooms (distinct from Button Mushroom already
    # in Daily Cooking Staples) ---
    dict(category="cat_007f_02", name="Oyster Mushroom", price_per_kg=300,
         preps=["Whole", "Sliced"], pack_sizes=[100, 200, 500],
         flavor="Delicate, fan-shaped mushrooms with a mild savoury taste"),
    dict(category="cat_007f_02", name="Shiitake Mushroom", price_per_kg=600,
         preps=["Whole", "Sliced"], pack_sizes=[100, 200, 500],
         flavor="Rich, umami-packed shiitake, popular in Asian cooking"),
    dict(category="cat_007f_02", name="Portobello Mushroom", price_per_kg=450,
         preps=["Whole", "Sliced"], pack_sizes=[100, 200, 500],
         flavor="Large, meaty mushrooms great for grilling or stuffing"),
    dict(category="cat_007f_02", name="Milky Mushroom", price_per_kg=200,
         preps=["Whole", "Sliced"], pack_sizes=[100, 200, 500],
         flavor="Firm, chewy mushrooms popular in South Indian cooking"),

    # --- cat_007f_03: Asian / Regional Specialty Veggies (distinct from
    # Ivy Gourd/Knol Khol/Pointed Gourd/Snake Gourd/Drumstick already
    # in Daily Cooking Staples) ---
    dict(category="cat_007f_03", name="Bok Choy / Chinese Cabbage", price_per_kg=120,
         preps=["Whole", "Chopped"], pack_sizes=[250, 500],
         flavor="Mild, crunchy Asian greens perfect for stir-fries"),
    dict(category="cat_007f_03", name="Water Spinach / Kang Kong", price_per_kg=60,
         preps=["Whole", "Chopped"], pack_sizes=[250, 500],
         flavor="Tender aquatic greens with hollow stems, stir-fry favourite"),
    dict(category="cat_007f_03", name="Winged Bean", price_per_kg=150,
         preps=["Whole", "Sliced"], pack_sizes=[250, 500],
         flavor="Crunchy, four-angled beans popular across Southeast Asia"),
    dict(category="cat_007f_03", name="Banana Flower / Banana Blossom", price_per_kg=80,
         preps=["Whole", "Chopped"], pack_sizes=[250, 500],
         flavor="Purple banana blossom used in South & Southeast Asian dishes"),
    dict(category="cat_007f_03", name="Bamboo Shoot", price_per_kg=200,
         preps=["Whole", "Sliced"], pack_sizes=[250, 500],
         flavor="Crisp bamboo shoots, a staple in Asian stir-fries and soups"),

    # --- cat_007g_01: Pre-cut & Diced Veggies (combo packs) ---
    dict(category="cat_007g_01", name="Mixed Vegetable Curry Cut", price_per_kg=220,
         preps=["Mix"], pack_sizes=[200, 400, 600],
         flavor="Pre-cut carrot, beans, peas and potato, ready for curry"),
    dict(category="cat_007g_01", name="Sabzi Cut Mix (Aloo-Gobi-Matar)", price_per_kg=200,
         preps=["Mix"], pack_sizes=[200, 400, 600],
         flavor="Pre-cut potato, cauliflower and peas for a classic sabzi"),
    dict(category="cat_007g_01", name="Pulao Cut Veggies", price_per_kg=230,
         preps=["Mix"], pack_sizes=[200, 400, 600],
         flavor="Diced carrot, beans and peas ready to toss into pulao or fried rice"),
    dict(category="cat_007g_01", name="Onion-Tomato-Garlic Base Combo", price_per_kg=180,
         preps=["Mix"], pack_sizes=[200, 400, 600],
         flavor="Pre-chopped onion, tomato and garlic - the base for most Indian curries"),

    # --- cat_007g_02: Stir-fry & Soup Kits (combo packs) ---
    dict(category="cat_007g_02", name="Stir-Fry Vegetable Mix", price_per_kg=250,
         preps=["Mix"], pack_sizes=[200, 400, 600],
         flavor="Bell pepper, baby corn, broccoli and carrot, ready for the wok"),
    dict(category="cat_007g_02", name="Manchurian Veg Mix", price_per_kg=240,
         preps=["Mix"], pack_sizes=[200, 400, 600],
         flavor="Finely diced cabbage, carrot and capsicum for veg Manchurian"),
    dict(category="cat_007g_02", name="Clear Soup Vegetable Kit", price_per_kg=200,
         preps=["Mix"], pack_sizes=[200, 400, 600],
         flavor="Carrot, beans, celery and spring onion for a light clear soup"),
    dict(category="cat_007g_02", name="Hot & Sour Soup Mix", price_per_kg=210,
         preps=["Mix"], pack_sizes=[200, 400, 600],
         flavor="Mushroom, carrot, cabbage and spring onion for hot & sour soup"),

    # --- cat_007g_03: Salad Kits (combo packs) ---
    dict(category="cat_007g_03", name="Garden Salad Kit", price_per_kg=260,
         preps=["Mix"], pack_sizes=[200, 400],
         flavor="Lettuce, cucumber, tomato and carrot, ready to toss"),
    dict(category="cat_007g_03", name="Greek Salad Kit", price_per_kg=300,
         preps=["Mix"], pack_sizes=[200, 400],
         flavor="Cucumber, tomato, olives and feta-ready greens"),
    dict(category="cat_007g_03", name="Caesar Salad Kit", price_per_kg=280,
         preps=["Mix"], pack_sizes=[200, 400],
         flavor="Romaine lettuce, croutons-ready mix and parmesan-ready greens"),
    dict(category="cat_007g_03", name="Sprouts & Greens Salad Kit", price_per_kg=270,
         preps=["Mix"], pack_sizes=[200, 400],
         flavor="Mixed sprouts, microgreens and baby spinach for a protein-rich salad"),

    # --- cat_007b_01: Spinach & Kale (distinct from Spinach/Palak
    # already in Daily Cooking Staples) ---
    dict(category="cat_007b_01", name="Kale", price_per_kg=250,
         preps=["Whole", "Chopped"], pack_sizes=[100, 250, 500],
         flavor="Nutrient-dense curly kale, great in salads and smoothies"),
    dict(category="cat_007b_01", name="Malabar Spinach / Poi", price_per_kg=50,
         preps=["Whole", "Chopped"], pack_sizes=[250, 500],
         flavor="Mucilaginous, mild-tasting greens popular in eastern India"),
    dict(category="cat_007b_01", name="Red Amaranth Leaves / Lal Saag", price_per_kg=50,
         preps=["Whole", "Chopped"], pack_sizes=[250, 500],
         flavor="Vibrant red-green amaranth leaves, iron-rich and earthy"),

    # --- cat_007b_02: Lettuces & Salad Mixes ---
    dict(category="cat_007b_02", name="Iceberg Lettuce", price_per_kg=150,
         preps=["Whole", "Shredded"], pack_sizes=[250, 500],
         flavor="Crisp, mild iceberg lettuce - a salad and burger staple"),
    dict(category="cat_007b_02", name="Romaine Lettuce", price_per_kg=200,
         preps=["Whole", "Shredded"], pack_sizes=[250, 500],
         flavor="Crunchy romaine with a slightly sweet flavour, ideal for Caesar salad"),
    dict(category="cat_007b_02", name="Lollo Rosso Lettuce", price_per_kg=250,
         preps=["Whole"], pack_sizes=[100, 250],
         flavor="Frilly, wine-red lettuce leaves with a mild peppery bite"),
    dict(category="cat_007b_02", name="Mixed Salad Greens", price_per_kg=300,
         preps=["Whole"], pack_sizes=[100, 250],
         flavor="Ready-to-eat mix of baby lettuces and salad greens"),

    # --- cat_007b_03: Herbs & Seasonings (distinct from Coriander/Curry
    # Leaves/Mint/Fenugreek already in Daily Cooking Staples) ---
    dict(category="cat_007b_03", name="Basil", price_per_kg=400,
         preps=["Whole", "Plucked"], pack_sizes=[50, 100],
         flavor="Fragrant sweet basil, essential for pesto and Italian dishes"),
    dict(category="cat_007b_03", name="Parsley", price_per_kg=350,
         preps=["Whole", "Plucked"], pack_sizes=[50, 100],
         flavor="Fresh, mildly peppery parsley for garnish and seasoning"),
    dict(category="cat_007b_03", name="Dill / Suva", price_per_kg=100,
         preps=["Whole", "Plucked"], pack_sizes=[50, 100],
         flavor="Feathery, aromatic dill leaves used in dals and pickles"),
    dict(category="cat_007b_03", name="Lemongrass", price_per_kg=150,
         preps=["Whole", "Chopped"], pack_sizes=[50, 100],
         flavor="Citrusy lemongrass stalks for teas, soups and curries"),

    # --- cat_007b_04: Microgreens & Sprouts ---
    dict(category="cat_007b_04", name="Alfalfa Sprouts", price_per_kg=300,
         preps=["Whole"], pack_sizes=[100, 200],
         flavor="Delicate, crunchy sprouts great for salads and sandwiches"),
    dict(category="cat_007b_04", name="Moong Sprouts", price_per_kg=80,
         preps=["Whole"], pack_sizes=[100, 250, 500],
         flavor="Protein-rich sprouted moong, a classic Indian breakfast staple"),
    dict(category="cat_007b_04", name="Broccoli Microgreens", price_per_kg=600,
         preps=["Whole"], pack_sizes=[50, 100],
         flavor="Concentrated, peppery microgreens packed with nutrients"),
    dict(category="cat_007b_04", name="Mixed Microgreens", price_per_kg=700,
         preps=["Whole"], pack_sizes=[50, 100],
         flavor="A vibrant mix of microgreens for garnish and salads"),

    # --- cat_007c_01: Carrots & Beetroots (distinct varieties from the
    # Orange Carrot/Beetroot already in Daily Cooking Staples) ---
    dict(category="cat_007c_01", name="Golden Beetroot", price_per_kg=150,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500, 1000],
         flavor="Sweet, earthy golden beetroot that doesn't bleed like red"),
    dict(category="cat_007c_01", name="Black Carrot / Kali Gajar", price_per_kg=120,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500, 1000],
         flavor="Deep purple-black carrots, traditionally used for kanji"),
    dict(category="cat_007c_01", name="Baby Carrots", price_per_kg=180,
         preps=["Whole"], pack_sizes=[250, 500],
         flavor="Sweet, snack-sized baby carrots"),

    # --- cat_007c_02: Radishes & Turnips (distinct from White
    # Radish/Turnip already in Daily Cooking Staples) ---
    dict(category="cat_007c_02", name="Red Radish / Cherry Belle", price_per_kg=80,
         preps=["Whole", "Sliced"], pack_sizes=[250, 500],
         flavor="Small, peppery red radishes great in salads"),
    dict(category="cat_007c_02", name="Black Radish", price_per_kg=100,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500],
         flavor="Sharp, spicy black-skinned radish"),
    dict(category="cat_007c_02", name="Baby Turnips", price_per_kg=90,
         preps=["Whole"], pack_sizes=[250, 500],
         flavor="Tender, mild baby turnips, delicious roasted whole"),

    # --- cat_007c_03: Yams, Taro & Exotic Tubers (distinct from
    # Arbi/Colocasia/Elephant Foot Yam already in Daily Cooking Staples) ---
    dict(category="cat_007c_03", name="Purple Yam / Ratalu", price_per_kg=100,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500, 1000],
         flavor="Vibrant purple-fleshed yam with a mildly sweet, nutty taste"),
    dict(category="cat_007c_03", name="Tapioca / Cassava / Simla Aloo", price_per_kg=50,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500, 1000],
         flavor="Starchy tapioca root, popular in Kerala cuisine"),
    dict(category="cat_007c_03", name="Chinese Yam", price_per_kg=150,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500],
         flavor="Mild, slightly sweet yam used in East Asian cooking"),

    # --- cat_007d_01: Cucumbers (distinct varieties from
    # Cucumber/Kheera already in Daily Cooking Staples) ---
    dict(category="cat_007d_01", name="Persian Cucumber", price_per_kg=120,
         preps=["Whole", "Sliced"], pack_sizes=[250, 500],
         flavor="Thin-skinned, seedless cucumbers with a crisp bite"),
    dict(category="cat_007d_01", name="Armenian Cucumber", price_per_kg=140,
         preps=["Whole", "Sliced"], pack_sizes=[250, 500],
         flavor="Long, ribbed cucumber with a mild, sweet flavour"),
    dict(category="cat_007d_01", name="Gherkins", price_per_kg=200,
         preps=["Whole"], pack_sizes=[100, 250],
         flavor="Small pickling cucumbers, perfect for gherkins and salads"),

    # --- cat_007d_02: Zucchini & Summer Squash (distinct from
    # Zucchini already in Daily Cooking Staples) ---
    dict(category="cat_007d_02", name="Pattypan Squash", price_per_kg=180,
         preps=["Whole", "Diced"], pack_sizes=[250, 500],
         flavor="Scallop-shaped summer squash with a delicate, buttery flavour"),
    dict(category="cat_007d_02", name="Yellow Crookneck Squash", price_per_kg=160,
         preps=["Whole", "Diced"], pack_sizes=[250, 500],
         flavor="Curved yellow squash with a mild, slightly sweet taste"),
    dict(category="cat_007d_02", name="Chayote / Chow Chow", price_per_kg=60,
         preps=["Whole", "Diced"], pack_sizes=[250, 500, 1000],
         flavor="Mild, crunchy chayote squash, popular in South Indian cooking"),

    # --- cat_007d_03: Pumpkins & Winter Squash (distinct from Red
    # Pumpkin/Ash Gourd already in Daily Cooking Staples) ---
    dict(category="cat_007d_03", name="Butternut Squash", price_per_kg=150,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500, 1000],
         flavor="Sweet, nutty butternut squash, great for soups and roasting"),
    dict(category="cat_007d_03", name="Acorn Squash", price_per_kg=180,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500],
         flavor="Sweet, slightly peppery acorn squash with a ridged shell"),
    dict(category="cat_007d_03", name="Kabocha Squash", price_per_kg=200,
         preps=["Whole", "Peeled & Diced"], pack_sizes=[250, 500, 1000],
         flavor="Japanese pumpkin with a dense, sweet, chestnut-like flesh"),

    # --- cat_007e_01: Broccoli & Cauliflower (distinct varieties from
    # Broccoli/Cauliflower already in Daily Cooking Staples) ---
    dict(category="cat_007e_01", name="Romanesco Broccoli", price_per_kg=350,
         preps=["Whole", "Cut Florets"], pack_sizes=[250, 500],
         flavor="Striking fractal-patterned broccoli with a nutty flavour"),
    dict(category="cat_007e_01", name="Purple Cauliflower", price_per_kg=250,
         preps=["Whole", "Cut Florets"], pack_sizes=[250, 500],
         flavor="Vivid purple cauliflower, sweeter than the classic white variety"),
    dict(category="cat_007e_01", name="Broccolini", price_per_kg=400,
         preps=["Whole", "Chopped"], pack_sizes=[100, 250],
         flavor="Slender, tender-stemmed broccoli-kale hybrid"),

    # --- cat_007e_02: Cabbage & Brussels Sprouts (distinct from
    # Cabbage/Patta Gobi already in Daily Cooking Staples) ---
    dict(category="cat_007e_02", name="Brussels Sprouts", price_per_kg=300,
         preps=["Whole", "Halved"], pack_sizes=[250, 500],
         flavor="Miniature cabbages with a nutty flavour when roasted"),
    dict(category="cat_007e_02", name="Red Cabbage", price_per_kg=90,
         preps=["Whole", "Shredded"], pack_sizes=[250, 500, 1000],
         flavor="Crunchy, vibrant red cabbage, great raw or braised"),
    dict(category="cat_007e_02", name="Savoy Cabbage", price_per_kg=110,
         preps=["Whole", "Shredded"], pack_sizes=[250, 500, 1000],
         flavor="Crinkly-leaved, tender cabbage with a mild, sweet flavour"),
]


def bulk_factor(grams, anchor=250):
    """~7% cheaper per 100g as pack size doubles (matches earlier batches)."""
    doublings = math.log2(grams / anchor)
    return 0.933 ** doublings


def format_pack_size(grams):
    if grams >= 1000 and grams % 1000 == 0:
        kg = grams // 1000
        return f"{kg} kg" if kg > 1 else "1 kg"
    return f"{grams}g"


def price_for(price_per_kg, grams, prep):
    base = price_per_kg * (grams / 1000.0) * bulk_factor(grams)
    marked_up = base * PREP_MARKUP.get(prep, 1.2)
    return marked_up


def build_name(base_name, organic, prep, pack_label):
    parts = []
    if organic:
        parts.append("Organic")
    if prep not in ("Whole", "Mix"):
        parts.append(prep)
    parts.append(base_name)
    return f"{' '.join(parts)} ({pack_label})"


def build_description(organic, prep, flavor, pack_label):
    prefix = "Organic" if organic else "Regular"
    prep_word = "Ready-Mix" if prep == "Mix" else prep
    return f"{prefix} {prep_word} {flavor}. Net weight: {pack_label}."


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
