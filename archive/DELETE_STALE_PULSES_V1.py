#!/usr/bin/env python3
"""
DiscoverAI: Delete stale v1 Pulses rows
==========================================

The original Pulses & Lentils batch (v1, 57 rows) occupied prod_1443
through prod_1499. It's been superseded by the v2 batch (140 rows, full
organic/polish/pack-size variant matrix), which unfortunately reuses the
same starting id - so some v1 rows are still sitting at ids v2 wants to
use for different products, and got silently kept via ON CONFLICT DO
NOTHING when v2 was imported.

This deletes exactly those 57 ids (prod_1443..prod_1499) from both
product_attributes and products, scoped defensively to category='cat_016'
so nothing outside Pulses & Lentils can ever be touched. After running
this, re-run IMPORT_PULSES_BATCH.py to insert the correct v2 rows at those
now-freed ids.

Usage:
    python DELETE_STALE_PULSES_V1.py            # dry run - shows what would be deleted
    python DELETE_STALE_PULSES_V1.py --apply    # actually deletes
"""

import os
import sys

STALE_IDS = [f"prod_{i}" for i in range(1443, 1500)]  # prod_1443 .. prod_1499
SAFE_CATEGORY = "cat_016"


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

    cur.execute(
        "SELECT id, name, category FROM products WHERE id = ANY(%s)",
        (STALE_IDS,),
    )
    rows = cur.fetchall()

    wrong_category = [r for r in rows if r[2] != SAFE_CATEGORY]
    if wrong_category:
        print("ABORTING: some of these ids belong to a different category than expected:")
        for r in wrong_category:
            print(f"  {r[0]} ({r[2]}): {r[1]}")
        print("Refusing to delete anything - investigate before proceeding.")
        cur.close()
        conn.close()
        sys.exit(1)

    print(f"Found {len(rows)} matching product(s) in {SAFE_CATEGORY}, safe to delete:\n")
    for pid, name, category in rows:
        print(f"  {pid}: {name!r}")

    if not apply_changes:
        print("\n(dry run - nothing deleted. Re-run with --apply to commit,")
        print("then run IMPORT_PULSES_BATCH.py again to insert the v2 rows.)")
        cur.close()
        conn.close()
        return

    cur.execute("DELETE FROM product_attributes WHERE product_id = ANY(%s)", (STALE_IDS,))
    attr_deleted = cur.rowcount
    cur.execute("DELETE FROM products WHERE id = ANY(%s) AND category = %s", (STALE_IDS, SAFE_CATEGORY))
    prod_deleted = cur.rowcount
    conn.commit()

    print(f"\nDeleted {prod_deleted} products and {attr_deleted} product_attributes rows.")
    print("Now run: python IMPORT_PULSES_BATCH.py")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
