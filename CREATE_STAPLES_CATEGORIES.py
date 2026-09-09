#!/usr/bin/env python3
"""
DiscoverAI: Create New Staples Categories
=============================================

Adds 4 new leaf categories under cat_002 "Staples & Grains", alongside the
existing Rice/Pulses & Lentils/Breakfast Cereals:

  - Atta & Wheat Flour
  - Cooking Oil & Ghee
  - Sugar & Salt
  - Besan & Other Flours

Reads cat_002's live level/path first (rather than assuming) and builds
each child's path/level from that, following the same defensive,
check-before-create pattern as FIX_FRUITS_CATEGORIES.py. Ids use the
"cat_002a/b/c/d" sibling-lettering convention already used elsewhere in the
tree (e.g. cat_003a1) rather than a numeric id, to avoid guessing at which
plain numeric ids might already be taken elsewhere in the table.

Usage:
    python CREATE_STAPLES_CATEGORIES.py            # dry run - shows the plan, writes nothing
    python CREATE_STAPLES_CATEGORIES.py --apply    # actually commits the categories
"""

import os
import sys

NEW_CATEGORIES = [
    {
        "id": "cat_002a",
        "category_code": "ATTA_WHEAT_FLOUR",
        "name": "Atta & Wheat Flour",
        "description": "Whole wheat atta, multigrain atta, maida and refined flours",
        "display_order": 1,
    },
    {
        "id": "cat_002b",
        "category_code": "COOKING_OIL_GHEE",
        "name": "Cooking Oil & Ghee",
        "description": "Cooking oils (sunflower, groundnut, mustard) and ghee",
        "display_order": 2,
    },
    {
        "id": "cat_002c",
        "category_code": "SUGAR_SALT",
        "name": "Sugar & Salt",
        "description": "Sugar, jaggery and salt varieties",
        "display_order": 3,
    },
    {
        "id": "cat_002d",
        "category_code": "BESAN_OTHER_FLOURS",
        "name": "Besan & Other Flours",
        "description": "Besan (gram flour), rava/suji, rice flour and other speciality flours",
        "display_order": 4,
    },
]


def main():
    apply_changes = "--apply" in sys.argv

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    print("Connecting to Neon...")
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    print("Connected.\n")

    cur.execute("SELECT id, name, level, path FROM categories WHERE id = 'cat_002'")
    parent = cur.fetchone()
    if not parent:
        print("ERROR: cat_002 ('Staples & Grains') not found - aborting.")
        sys.exit(1)
    _, parent_name, parent_level, parent_path = parent
    print(f"Parent: cat_002 {parent_name!r}, level={parent_level}, path={parent_path!r}\n")

    cur.execute("SELECT id FROM categories WHERE id = ANY(%s)", ([c["id"] for c in NEW_CATEGORIES],))
    existing_ids = {r[0] for r in cur.fetchall()}

    to_create = [c for c in NEW_CATEGORIES if c["id"] not in existing_ids]
    already_there = [c for c in NEW_CATEGORIES if c["id"] in existing_ids]

    if already_there:
        print("Already exist (skipping):")
        for c in already_there:
            print(f"  {c['id']} {c['name']}")
        print()

    if not to_create:
        print("Nothing to create.")
        cur.close()
        conn.close()
        return

    print(f"Will create {len(to_create)} categories under cat_002:")
    for c in to_create:
        path = f"{parent_path} / {c['name']}"
        print(f"  {c['id']:10s} {c['name']:24s} level={parent_level + 1} path={path}")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.)")
        cur.close()
        conn.close()
        return

    for c in to_create:
        path = f"{parent_path} / {c['name']}"
        cur.execute(
            """
            INSERT INTO categories (id, category_code, name, parent_id, level, path, description, display_order, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)
            ON CONFLICT (id) DO NOTHING
            """,
            (c["id"], c["category_code"], c["name"], "cat_002", parent_level + 1, path, c["description"], c["display_order"]),
        )
    conn.commit()
    print(f"\nDone. Created {len(to_create)} categories.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
