#!/usr/bin/env python3
"""
DiscoverAI: Recompute Category level/path From parent_id
============================================================

Turns out parent_id for the vegetable subtype categories (Daily Cooking
Staples, Leafy Greens & Salad, Root & Tuber Vegetables, Cucurbits & Squash,
Cruciferous & Pods, Exotic & Specialty Vegetables, Convenience &
Ready-to-Cook) was already correctly set to cat_007 ("Vegetables") - the
real structure was fine. The bug is in the denormalized `path` (and
possibly `level`) text columns, which can go stale independently of
parent_id and were still missing the "Vegetables" segment, e.g.:

    stored path:  Grocery / Fruits & Vegetables / Daily Cooking Staples / Onions & Shallots
    correct path: Grocery / Fruits & Vegetables / Vegetables / Daily Cooking Staples / Onions & Shallots

This script re-derives level + path for every category purely from the
live parent_id chain (walking from each root down), and updates any row
where the stored value doesn't match what the real hierarchy implies.
parent_id itself is never touched. Safe to re-run - it's a no-op once
everything is consistent.

Usage:
    python FIX_VEGETABLE_CATEGORY_TREE.py            # dry run - prints every mismatch, writes nothing
    python FIX_VEGETABLE_CATEGORY_TREE.py --apply    # actually commits the fix
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

    cur.execute("SELECT id, name, parent_id, level, path FROM categories")
    rows = cur.fetchall()
    by_id = {r[0]: {"id": r[0], "name": r[1], "parent_id": r[2], "level": r[3], "path": r[4]} for r in rows}

    children = {}
    roots = []
    for r in by_id.values():
        if r["parent_id"] is None:
            roots.append(r["id"])
        else:
            if r["parent_id"] not in by_id:
                print(f"WARNING: {r['id']} has parent_id {r['parent_id']} which doesn't exist - skipping its subtree.")
                continue
            children.setdefault(r["parent_id"], []).append(r["id"])

    computed = {}  # id -> (level, path)

    def walk(node_id, level, path):
        computed[node_id] = (level, path)
        for child_id in children.get(node_id, []):
            child = by_id[child_id]
            walk(child_id, level + 1, f"{path} / {child['name']}")

    for root_id in roots:
        root = by_id[root_id]
        walk(root_id, 1, root["name"])

    mismatches = []
    unreachable = [cid for cid in by_id if cid not in computed]
    for cid, (new_level, new_path) in computed.items():
        old = by_id[cid]
        if old["level"] != new_level or old["path"] != new_path:
            mismatches.append((cid, old["level"], new_level, old["path"], new_path))

    print(f"Checked {len(by_id)} categories ({len(roots)} root(s), {len(unreachable)} unreachable from any root).")
    if unreachable:
        print("Unreachable (not touched - likely a cycle or dangling parent_id):", unreachable)

    if not mismatches:
        print("\nEverything already consistent - nothing to fix.")
        cur.close()
        conn.close()
        return

    print(f"\n{len(mismatches)} categories have a stale level and/or path:\n")
    for cid, old_lvl, new_lvl, old_path, new_path in mismatches[:30]:
        print(f"  {cid}")
        if old_lvl != new_lvl:
            print(f"    level: {old_lvl} -> {new_lvl}")
        if old_path != new_path:
            print(f"    path:  {old_path}")
            print(f"        -> {new_path}")
    if len(mismatches) > 30:
        print(f"  ... and {len(mismatches) - 30} more")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit this fix.)")
        cur.close()
        conn.close()
        return

    for cid, old_lvl, new_lvl, old_path, new_path in mismatches:
        cur.execute("UPDATE categories SET level = %s, path = %s WHERE id = %s", (new_lvl, new_path, cid))
    conn.commit()

    print(f"\nDone. Fixed level/path on {len(mismatches)} categories.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
