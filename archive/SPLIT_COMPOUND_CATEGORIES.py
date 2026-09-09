#!/usr/bin/env python3
"""
DiscoverAI: Split compound leaf categories (e.g. "Onions & Shallots")
==========================================================================

Second step of the leaf-category split work - run AUDIT_COMPOUND_LEAF_
CATEGORIES.py first and review its output. Only categories listed in
CATEGORY_IDS_TO_SPLIT below are touched; nothing is auto-discovered
here, on purpose - a compound name might be intentional (e.g. two
things that genuinely belong in one aisle), so which categories
actually get split is a manual call, made by editing the list below
after reading the audit.

For each category id in CATEGORY_IDS_TO_SPLIT:
  1. Parse its name into split terms the same way the audit script did
     ("Onions & Shallots" -> ["Onions", "Shallots"]).
  2. Create one new LEAF category per term, as a SIBLING of the
     original (same parent_id, same level) - not a child of it, so the
     path doesn't end up with the old compound name still baked in.
  3. Reassign every product whose name matches exactly ONE term to
     that new category.
  4. Leave products that match zero or multiple terms exactly where
     they are, under the original category - these are the ambiguous
     ones the audit script already flagged; this script never guesses.
  5. Write every reassigned product id to
     data/exports/products_needing_reembedding.csv - product.category
     changing means its embedding_full text (which bakes in the
     category path) is now stale. RE-EMBED_REASSIGNED_PRODUCTS.py (run
     after this) reads that file to know exactly which products to fix.

The original compound category is NEVER deleted or deactivated by this
script - if every product moved out cleanly, it just becomes an empty
leaf, which /api/categories/leaf already excludes automatically (leaves
with product_count = 0 aren't returned - see discovery_routes.py). If
some ambiguous products remain, it stays visible with just those.

Usage:
    python SPLIT_COMPOUND_CATEGORIES.py            # dry run - prints the plan, writes nothing
    python SPLIT_COMPOUND_CATEGORIES.py --apply    # commits the split + product reassignment
"""

import csv
import os
import re
import sys
from pathlib import Path

REEMBED_CSV = Path("data/exports/products_needing_reembedding.csv")

# Paste category ids here after reviewing AUDIT_COMPOUND_LEAF_CATEGORIES.py's
# output and confirming a CLEAN (or acceptably-reviewed) split for each, e.g.:
#   CATEGORY_IDS_TO_SPLIT = ["cat_0074", "cat_0091"]
CATEGORY_IDS_TO_SPLIT = [
]

SPLIT_PATTERN = re.compile(r"\s*(?:&|\band\b|/)\s*", re.IGNORECASE)


def split_terms(name):
    parts = [p.strip() for p in SPLIT_PATTERN.split(name) if p.strip()]
    return parts if len(parts) > 1 else []


def slugify_code(name):
    return re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")


def main():
    apply_changes = "--apply" in sys.argv

    if not CATEGORY_IDS_TO_SPLIT:
        print("CATEGORY_IDS_TO_SPLIT is empty - nothing to do.")
        print("Run AUDIT_COMPOUND_LEAF_CATEGORIES.py first, review its output, then")
        print("paste the category ids you've confirmed into CATEGORY_IDS_TO_SPLIT above.")
        return

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

    cur.execute("SELECT id, parent_id, name, level, path, display_order FROM categories")
    by_id = {
        r[0]: {"id": r[0], "parent_id": r[1], "name": r[2], "level": r[3], "path": r[4], "display_order": r[5]}
        for r in cur.fetchall()
    }

    new_category_inserts = []   # (sql, params, description)
    product_reassignments = []  # (product_id, product_name, old_category_id, new_category_id)
    skipped_products = []       # (product_id, product_name, category_id, reason)

    for cat_id in CATEGORY_IDS_TO_SPLIT:
        if cat_id not in by_id:
            print(f"WARNING: {cat_id} not found in categories - skipping.")
            continue
        cat = by_id[cat_id]
        terms = split_terms(cat["name"])
        if not terms:
            print(f"WARNING: {cat_id} ({cat['name']!r}) doesn't look like a compound name - skipping.")
            continue

        parent = by_id.get(cat["parent_id"])
        if parent is None:
            print(f"WARNING: {cat_id} has no resolvable parent - skipping (can't build a sibling path).")
            continue

        cur.execute("SELECT id, name FROM products WHERE category = %s AND is_active = true", (cat_id,))
        products = cur.fetchall()

        term_to_new_id = {}
        for i, term in enumerate(terms, start=1):
            new_id = f"{cat_id}_{i}"
            if new_id in by_id:
                print(f"WARNING: generated id {new_id} already exists - skipping split of {cat_id}.")
                term_to_new_id = {}
                break
            term_to_new_id[term] = new_id

        if not term_to_new_id:
            continue

        for term, new_id in term_to_new_id.items():
            new_path = f"{parent['path']} / {term}"
            new_category_inserts.append((
                """INSERT INTO categories
                       (id, category_code, name, parent_id, level, path, display_order, is_active)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, true)""",
                (new_id, slugify_code(term), term, cat["parent_id"], cat["level"], new_path, cat["display_order"]),
                f"Create {new_id!r} ({term!r}) as a sibling of {cat_id!r} under {cat['parent_id']!r}",
            ))
            by_id[new_id] = {"id": new_id, "parent_id": cat["parent_id"], "name": term,
                              "level": cat["level"], "path": new_path, "display_order": cat["display_order"]}

        for pid, pname in products:
            pname_l = pname.lower()
            hits = [term for term in terms if term.lower().rstrip("s") in pname_l or term.lower() in pname_l]
            if len(hits) == 1:
                product_reassignments.append((pid, pname, cat_id, term_to_new_id[hits[0]]))
            else:
                reason = "matches no term" if not hits else f"matches multiple terms {hits}"
                skipped_products.append((pid, pname, cat_id, reason))

    print(f"New categories to create: {len(new_category_inserts)}")
    for _, _, desc in new_category_inserts:
        print(f"  {desc}")

    print(f"\nProducts to reassign: {len(product_reassignments)}")
    for pid, pname, old_cat, new_cat in product_reassignments[:20]:
        print(f"  {pid} {pname!r}: {old_cat} -> {new_cat}")
    if len(product_reassignments) > 20:
        print(f"  ... and {len(product_reassignments) - 20} more")

    if skipped_products:
        print(f"\nProducts LEFT UNCHANGED (ambiguous - re-run the audit script to review): {len(skipped_products)}")
        for pid, pname, old_cat, reason in skipped_products[:10]:
            print(f"  {pid} {pname!r} in {old_cat}: {reason}")
        if len(skipped_products) > 10:
            print(f"  ... and {len(skipped_products) - 10} more")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.)")
        cur.close()
        conn.close()
        return

    for sql, params, _ in new_category_inserts:
        cur.execute(sql, params)

    for pid, pname, old_cat, new_cat in product_reassignments:
        cur.execute(
            "UPDATE products SET category = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (new_cat, pid),
        )

    conn.commit()
    print(f"\nDone. Created {len(new_category_inserts)} categories, reassigned {len(product_reassignments)} products.")

    REEMBED_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not REEMBED_CSV.exists()
    with open(REEMBED_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["product_id", "product_name", "old_category_id", "new_category_id"])
        writer.writerows(product_reassignments)
    print(f"Appended {len(product_reassignments)} row(s) to {REEMBED_CSV}")
    print("Run RE-EMBED_REASSIGNED_PRODUCTS.py next to refresh embeddings for these products")
    print("(their category path changed, so their embedded text is now stale).")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
