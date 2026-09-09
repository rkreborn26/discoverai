#!/usr/bin/env python3
"""
DiscoverAI: Export attributes as a single readable Markdown file
=====================================================================

For each leaf category, shows what attribute keys are actually captured
(pack_size, quantity, unit, organic, and whatever's in the free-form
attributes json - prep_type, variety, polish, milling, process, grain,
grind, etc.), the range of values seen for each, and a couple of example
products - rather than dumping every single product (hundreds of near-
identical rows), which wouldn't be readable in one sitting.

Usage:
    python EXPORT_ATTRIBUTES_MARKDOWN.py
Writes: data/exports/attributes_by_category.md
"""

import os
import sys
from collections import defaultdict
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set.")
    sys.exit(1)

OUT_PATH = Path("data/exports/attributes_by_category.md")

FIXED_ATTR_COLUMNS = [
    "pack_size", "quantity", "unit", "organic", "color", "size", "material",
    "fit_type", "storage_gb", "ram_gb", "processor", "display_size_inch",
    "connectivity_5g",
]


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute(f"""
        SELECT
            c.id AS category_id, c.name AS category_name, c.path AS category_path,
            p.id AS product_id, p.name AS product_name, p.brand, p.price,
            {', '.join('pa.' + col for col in FIXED_ATTR_COLUMNS)},
            pa.attributes
        FROM products p
        LEFT JOIN categories c ON c.id = p.category
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        ORDER BY c.path NULLS LAST, p.id;
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    # category_id -> {name, path, products: [ {id,name,brand,price,attrs} ]}
    categories = {}
    for row in rows:
        category_id, category_name, category_path = row[0], row[1], row[2]
        product_id, product_name, brand, price = row[3], row[4], row[5], row[6]
        fixed_values = row[7:7 + len(FIXED_ATTR_COLUMNS)]
        free_form = row[7 + len(FIXED_ATTR_COLUMNS)]

        attrs = {}
        for col_name, value in zip(FIXED_ATTR_COLUMNS, fixed_values):
            if value is not None:
                attrs[col_name] = value
        if isinstance(free_form, dict):
            for k, v in free_form.items():
                if v is not None:
                    attrs[k] = v

        cat_key = category_id or "uncategorized"
        if cat_key not in categories:
            categories[cat_key] = {
                "name": category_name or "(unknown)",
                "path": category_path or "",
                "products": [],
            }
        categories[cat_key]["products"].append({
            "id": product_id, "name": product_name, "brand": brand, "price": price, "attrs": attrs,
        })

    lines = []
    lines.append("# Product Attributes by Category\n")
    lines.append(f"Generated from the live DB. {len(categories)} categories with at least one product.\n")

    # Sort by path for a stable, tree-like reading order.
    for cat_key in sorted(categories.keys(), key=lambda k: categories[k]["path"]):
        cat = categories[cat_key]
        products = cat["products"]

        lines.append(f"\n## {cat_key} — {cat['name']}\n")
        lines.append(f"- **Path:** {cat['path']}")
        lines.append(f"- **Products:** {len(products)}\n")

        # Which attribute keys show up anywhere in this category, and what
        # distinct values each one takes (capped for readability).
        key_values = defaultdict(set)
        for p in products:
            for k, v in p["attrs"].items():
                key_values[k].add(str(v))

        if key_values:
            lines.append("**Attributes captured:**\n")
            for key in sorted(key_values.keys()):
                values = sorted(key_values[key])
                if len(values) > 10:
                    shown = ", ".join(values[:10]) + f", ... ({len(values)} distinct values)"
                else:
                    shown = ", ".join(values)
                lines.append(f"- `{key}`: {shown}")
        else:
            lines.append("*(no attributes captured for this category)*")

        # A couple of concrete examples so the shape is obvious, not just
        # the abstract key list.
        if products:
            lines.append("\n**Example products:**\n")
            for p in products[:3]:
                attr_str = ", ".join(f"{k}={v!r}" for k, v in p["attrs"].items())
                lines.append(f"- `{p['id']}` **{p['name']}** (brand: {p['brand']}, price: {p['price']}) — {attr_str}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    total_products = sum(len(c["products"]) for c in categories.values())
    print(f"Wrote {len(categories)} categories, {total_products} products to {OUT_PATH}")


if __name__ == "__main__":
    main()
