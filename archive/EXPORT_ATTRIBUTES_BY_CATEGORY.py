#!/usr/bin/env python3
"""
DiscoverAI: Export all captured attributes, grouped by leaf category
=========================================================================

For every product, combines the fixed product_attributes columns
(pack_size, quantity, unit, organic, color, size, material, fit_type,
storage_gb, ram_gb, processor, display_size_inch, connectivity_5g) with
whatever's in the free-form `attributes` json column (prep_type, variety,
polish, milling, process, grain, grind, etc.), grouped by leaf category so
you can see exactly what's captured per category.

Writes JSON by default; pass --xml for an XML export instead.

Usage:
    python EXPORT_ATTRIBUTES_BY_CATEGORY.py            # writes data/exports/attributes_by_category.json
    python EXPORT_ATTRIBUTES_BY_CATEGORY.py --xml      # writes data/exports/attributes_by_category.xml
"""

import json
import os
import sys
import xml.etree.ElementTree as ET
import xml.dom.minidom
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set.")
    sys.exit(1)

OUT_DIR = Path("data/exports")

FIXED_ATTR_COLUMNS = [
    "pack_size", "quantity", "unit", "organic", "color", "size", "material",
    "fit_type", "storage_gb", "ram_gb", "processor", "display_size_inch",
    "connectivity_5g",
]


def main():
    as_xml = "--xml" in sys.argv

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

    categories = {}
    for row in rows:
        category_id, category_name, category_path = row[0], row[1], row[2]
        product_id, product_name, brand, price = row[3], row[4], row[5], row[6]
        fixed_values = row[7:7 + len(FIXED_ATTR_COLUMNS)]
        free_form = row[7 + len(FIXED_ATTR_COLUMNS)]

        attributes = {}
        for col_name, value in zip(FIXED_ATTR_COLUMNS, fixed_values):
            if value is not None:
                attributes[col_name] = float(value) if col_name == "quantity" else value
        if isinstance(free_form, dict):
            for k, v in free_form.items():
                if v is not None:
                    attributes[k] = v

        cat_key = category_id or "uncategorized"
        if cat_key not in categories:
            categories[cat_key] = {
                "category_id": category_id,
                "category_name": category_name,
                "category_path": category_path,
                "products": [],
            }
        categories[cat_key]["products"].append({
            "id": product_id,
            "name": product_name,
            "brand": brand,
            "price": float(price) if price is not None else None,
            "attributes": attributes,
        })

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if as_xml:
        root = ET.Element("categories")
        for cat in categories.values():
            cat_el = ET.SubElement(root, "category", {
                "id": cat["category_id"] or "",
                "name": cat["category_name"] or "",
                "path": cat["category_path"] or "",
            })
            for prod in cat["products"]:
                prod_el = ET.SubElement(cat_el, "product", {
                    "id": prod["id"],
                    "name": prod["name"],
                    "brand": prod["brand"] or "",
                    "price": str(prod["price"]) if prod["price"] is not None else "",
                })
                attrs_el = ET.SubElement(prod_el, "attributes")
                for k, v in prod["attributes"].items():
                    attr_el = ET.SubElement(attrs_el, "attribute", {"key": str(k)})
                    attr_el.text = str(v)

        rough = ET.tostring(root, encoding="unicode")
        pretty = xml.dom.minidom.parseString(rough).toprettyxml(indent="  ")
        out_path = OUT_DIR / "attributes_by_category.xml"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(pretty)
    else:
        out_path = OUT_DIR / "attributes_by_category.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(list(categories.values()), f, indent=2, default=str)

    total_products = sum(len(c["products"]) for c in categories.values())
    print(f"Wrote {len(categories)} categories, {total_products} products to {out_path}")


if __name__ == "__main__":
    main()
