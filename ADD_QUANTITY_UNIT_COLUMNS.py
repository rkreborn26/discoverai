#!/usr/bin/env python3
"""
DiscoverAI: Add quantity + unit to product_attributes
=========================================================

Adds two structured columns that were missing but are mandatory for an
Indian grocery catalog: how much of something you're buying, split into a
number and a unit (e.g. quantity=500, unit="gm" for a 500g pack, or
quantity=1, unit="kg" for a 1kg pack) - not just the human-readable
`pack_size` string ("500g", "1 kg") that already existed.

Units are kept as-labeled (matching how the pack is actually sold: "gm" for
grams, "kg" for kilos) rather than normalized to a single base unit, since
that's how pack_size was already written and how it'll read naturally in
the UI/filters (e.g. "1 kg" instead of "1000 gm").

This script:
  1. ALTERs product_attributes to add `quantity numeric(10,2)` and
     `unit varchar(10)` (no-op if they already exist).
  2. Backfills both columns for every existing row by parsing the already-
     populated `pack_size` string.
  3. Reports how many rows were backfilled and loudly flags any pack_size
     value it couldn't parse (there shouldn't be any, given the vegetables
     and fruits batches, but this is meant to be mandatory going forward -
     nothing should silently stay NULL).

Usage:
    python ADD_QUANTITY_UNIT_COLUMNS.py            # dry run - shows the plan, writes nothing
    python ADD_QUANTITY_UNIT_COLUMNS.py --apply    # runs the ALTER + backfill
"""

import os
import re
import sys

WEIGHT_VOLUME_RE = re.compile(r'^(\d+(?:\.\d+)?)\s*(kg|g|ml|l|ltr|litre|liter)s?$', re.IGNORECASE)
TABLET_RE = re.compile(r'^(\d+)\s*tablets?$', re.IGNORECASE)
PACK_OF_RE = re.compile(r'^pack\s*(?:of\s*)?(\d+)$', re.IGNORECASE)
PIECE_UNIT_RE = re.compile(r'pcs?\b', re.IGNORECASE)
PIECE_QTY_RE = re.compile(r'(\d+)')

_VOLUME_UNIT_MAP = {"ml": "ml", "l": "L", "ltr": "L", "litre": "L", "liter": "L"}


def parse_quantity_unit(pack_size):
    """'250g' -> (250, 'gm'); '1kg' -> (1, 'kg'); '500ml' -> (500, 'ml');
    '1L' -> (1, 'L'); '60 tablets' -> (60, 'tablet'); 'Pack 6' -> (6, 'pack').

    A handful of vegetables are sold by piece rather than weight (whole
    cauliflower, corn cobs), where pack_size is a literal string like
    '1 Medium PC' or '2 PCs' - those map to unit='pc', quantity=piece count
    (defaulting to 1 if no leading number, e.g. just 'PC').
    """
    if not pack_size:
        return None, None
    s = pack_size.strip()

    m = WEIGHT_VOLUME_RE.match(s)
    if m:
        qty_str, unit = m.groups()
        qty = float(qty_str)
        if qty == int(qty):
            qty = int(qty)
        unit_l = unit.lower()
        if unit_l == "kg":
            return qty, "kg"
        if unit_l == "g":
            return qty, "gm"
        return qty, _VOLUME_UNIT_MAP[unit_l]

    m = TABLET_RE.match(s)
    if m:
        return int(m.group(1)), "tablet"

    m = PACK_OF_RE.match(s)
    if m:
        return int(m.group(1)), "pack"

    if PIECE_UNIT_RE.search(s):
        qty_match = PIECE_QTY_RE.search(s)
        qty = int(qty_match.group(1)) if qty_match else 1
        return qty, "pc"

    return None, None


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

    print("Ensuring columns exist (quantity numeric, unit varchar(10))...")
    if apply_changes:
        cur.execute("ALTER TABLE product_attributes ADD COLUMN IF NOT EXISTS quantity NUMERIC(10,2)")
        cur.execute("ALTER TABLE product_attributes ADD COLUMN IF NOT EXISTS unit VARCHAR(10)")
        conn.commit()
        print("  done.")
    else:
        print("  (dry run - would run ALTER TABLE ... ADD COLUMN IF NOT EXISTS quantity/unit)")

    # On a dry run the columns may not exist yet, so pa.quantity/pa.unit
    # can't be selected without erroring - fall back to a query that
    # doesn't reference them at all.
    if not apply_changes:
        # For the dry run, just re-select without the new columns so this
        # works even before the ALTER has ever been applied.
        cur.execute("SELECT id, product_id, pack_size FROM product_attributes WHERE pack_size IS NOT NULL")
        rows = [(r[0], r[1], r[2], None, None) for r in cur.fetchall()]
    else:
        cur.execute("""
            SELECT id, product_id, pack_size, quantity, unit
            FROM product_attributes
            WHERE pack_size IS NOT NULL
        """)
        rows = cur.fetchall()

    to_update = []
    unparseable = []
    already_set = 0

    for attr_id, product_id, pack_size, existing_qty, existing_unit in rows:
        if existing_qty is not None and existing_unit is not None:
            already_set += 1
            continue
        qty, unit = parse_quantity_unit(pack_size)
        if qty is None:
            unparseable.append((product_id, pack_size))
        else:
            to_update.append((attr_id, qty, unit))

    print(f"\n{len(rows)} rows have a pack_size.")
    print(f"  already have quantity/unit set: {already_set}")
    print(f"  will be backfilled: {len(to_update)}")
    if unparseable:
        print(f"  COULD NOT PARSE (needs manual fix - quantity/unit is mandatory): {len(unparseable)}")
        for pid, ps in unparseable[:100]:
            print(f"    {pid}: pack_size={ps!r}")
        if len(unparseable) > 100:
            print(f"    ... and {len(unparseable) - 100} more")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to add columns and backfill.)")
        cur.close()
        conn.close()
        return

    for attr_id, qty, unit in to_update:
        cur.execute("UPDATE product_attributes SET quantity = %s, unit = %s WHERE id = %s", (qty, unit, attr_id))
    conn.commit()
    print(f"\nDone. Backfilled quantity/unit on {len(to_update)} rows.")
    if unparseable:
        print(f"WARNING: {len(unparseable)} rows still have no quantity/unit - fix pack_size for those manually.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
