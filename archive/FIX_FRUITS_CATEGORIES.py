#!/usr/bin/env python3
"""
DiscoverAI: Fruits Category Fixes
==================================

Three fixes under "Fruits" (cat_003a):

  1. Restore the "Melons" category at cat_003a3 (the id gap between Berries
     [cat_003a2] and Tropical & Exotic Fruits [cat_003a4] suggests it used
     to exist and was removed/lost).
  2. Add a new "Stone Fruits" category (mango, peach, plum, apricot, litchi)
     at cat_003a6 - these don't fit Citrus/Berries/Melons/Tropical&Exotic/
     Pome&Core cleanly, so they get their own category.
  3. Fix the "Pom & Core Fruits" typo -> "Pome & Core Fruits" on cat_003a5
     (name, path, and category_code if it has the same typo).

Defensive: checks by name (ILIKE) before creating Melons/Stone Fruits, in
case they already exist under a different id, and only rewrites cat_003a5
if it still has the typo. Safe to re-run.

Usage:
    python FIX_FRUITS_CATEGORIES.py            # dry run - prints the plan, writes nothing
    python FIX_FRUITS_CATEGORIES.py --apply    # actually commits the fix
"""

import os
import sys


def main():
    apply_changes = "--apply" in sys.argv

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set. Make sure .env exists and contains DATABASE_URL.")
        sys.exit(1)

    print("Connecting to Neon...")
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    print("Connected.\n")

    cur.execute("SELECT id, category_code, name, parent_id, level, path FROM categories")
    rows = cur.fetchall()
    by_id = {
        r[0]: {"id": r[0], "category_code": r[1], "name": r[2], "parent_id": r[3], "level": r[4], "path": r[5]}
        for r in rows
    }

    if "cat_003a" not in by_id:
        print("ERROR: cat_003a ('Fruits') not found - aborting.")
        sys.exit(1)
    fruits = by_id["cat_003a"]
    child_level = fruits["level"] + 1

    actions = []  # list of ("insert"|"update", description, sql, params)

    # --- 1. Melons ---
    cur.execute("SELECT id, name FROM categories WHERE name ILIKE %s", ("%melon%",))
    melon_match = cur.fetchall()
    if melon_match:
        print(f"Melons already exists: {melon_match} - skipping creation.")
    else:
        path = f"{fruits['path']} / Melons"
        actions.append((
            "insert",
            "Create 'Melons' at cat_003a3",
            """INSERT INTO categories (id, category_code, name, parent_id, level, path, description, display_order, is_active)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)""",
            ("cat_003a3", "MELONS", "Melons", "cat_003a", child_level, path,
             "Watermelon, muskmelon, cantaloupe and other melons", 3),
        ))

    # --- 2. Stone Fruits ---
    cur.execute("SELECT id, name FROM categories WHERE name ILIKE %s", ("%stone fruit%",))
    stone_match = cur.fetchall()
    if stone_match:
        print(f"Stone Fruits already exists: {stone_match} - skipping creation.")
    else:
        path = f"{fruits['path']} / Stone Fruits"
        actions.append((
            "insert",
            "Create 'Stone Fruits' at cat_003a6",
            """INSERT INTO categories (id, category_code, name, parent_id, level, path, description, display_order, is_active)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)""",
            ("cat_003a6", "STONE_FRUITS", "Stone Fruits", "cat_003a", child_level, path,
             "Mango, peach, plum, apricot and litchi", 6),
        ))

    # --- 3. Fix Pom & Core Fruits typo ---
    if "cat_003a5" in by_id and "pom &" in by_id["cat_003a5"]["name"].lower():
        new_name = "Pome & Core Fruits"
        new_path = f"{fruits['path']} / {new_name}"
        old_code = by_id["cat_003a5"]["category_code"] or ""
        new_code = old_code.replace("POM_", "POME_") if old_code.upper().startswith("POM_") else old_code
        actions.append((
            "update",
            f"Fix cat_003a5 name/path (and code {old_code!r} -> {new_code!r})" if new_code != old_code
            else "Fix cat_003a5 name/path",
            "UPDATE categories SET name = %s, path = %s, category_code = %s WHERE id = %s",
            (new_name, new_path, new_code, "cat_003a5"),
        ))
    elif "cat_003a5" in by_id:
        print(f"cat_003a5 name is already '{by_id['cat_003a5']['name']}' - no typo to fix.")
    else:
        print("WARNING: cat_003a5 not found - can't fix the Pome/Pom typo.")

    if not actions:
        print("\nNothing to do.")
        cur.close()
        conn.close()
        return

    print(f"\n{len(actions)} change(s) planned:")
    for kind, desc, _, _ in actions:
        print(f"  [{kind}] {desc}")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.)")
        cur.close()
        conn.close()
        return

    for _, _, sql, params in actions:
        cur.execute(sql, params)
    conn.commit()
    print(f"\nDone. Applied {len(actions)} change(s).")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
