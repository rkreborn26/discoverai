#!/usr/bin/env python3
"""
DiscoverAI: Fix "Organic Organic" naming bug in Rice
========================================================

The original Rice generator combined brand="24 Mantra Organic" with a name
suffix that also started with "Organic" (e.g. "Organic Basmati Rice"),
producing redundant names like "24 Mantra Organic Organic Basmati Rice".
This was caught and fixed in the Pulses generator before import, but Rice
was already live in the DB by then. This fixes the 12 affected rows.

Usage:
    python FIX_RICE_NAMING.py            # dry run - shows what would change
    python FIX_RICE_NAMING.py --apply    # commits the fix
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
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    print("Connecting to Neon...")
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    print("Connected.\n")

    cur.execute("SELECT id, name FROM products WHERE name LIKE '%Organic Organic%'")
    rows = cur.fetchall()

    if not rows:
        print("Nothing to fix - no 'Organic Organic' names found.")
        cur.close()
        conn.close()
        return

    print(f"{len(rows)} product(s) with redundant naming:\n")
    updates = []
    for pid, name in rows:
        fixed = name.replace("Organic Organic", "Organic", 1)
        updates.append((pid, name, fixed))
        print(f"  {pid}: {name!r}")
        print(f"      -> {fixed!r}")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.)")
        cur.close()
        conn.close()
        return

    for pid, old_name, fixed in updates:
        cur.execute("UPDATE products SET name = %s WHERE id = %s", (fixed, pid))
    conn.commit()
    print(f"\nDone. Fixed {len(updates)} product name(s).")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
