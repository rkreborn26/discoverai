#!/usr/bin/env python3
"""
DiscoverAI: Audit compound/mixed leaf categories
=====================================================

Read-only (writes nothing). First step of the leaf-category split work:
finds every LEAF category (no children of its own - same "leaf" test
discovery_routes.py uses for the Home/PLP pages) whose name is a
compound like "Onions & Shallots" or "Radishes & Turnips", and checks
whether its products can be confidently re-bucketed by matching each
product's name against the split terms (e.g. does the name contain
"onion" or "shallot"?).

For each compound leaf, prints:
  - the candidate split terms parsed from the category name
  - how many products would land in each term's bucket
  - how many products match NONE of the terms (ambiguous - would need
    a manual look, the script won't guess for these)
  - how many products match MORE THAN ONE term (also ambiguous - a
    name like "Onion & Shallot Mix 500g" genuinely could go either way)

This is the review step - SPLIT_COMPOUND_CATEGORIES.py only touches
categories you've confirmed from this output are safe to split
cleanly. Every run also writes the full output (untruncated, unlike
the console preview) to data/exports/compound_category_audit.log, so
you've got something to actually read/share/paste back rather than
just scrollback - each run overwrites it with a fresh timestamp, since
the log is meant to reflect the CURRENT state, not a history.

Usage:
    python AUDIT_COMPOUND_LEAF_CATEGORIES.py
"""

import os
import re
from datetime import datetime
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

LOG_PATH = Path("data/exports/compound_category_audit.log")

# Matches "&", " and ", "/", or a comma used as a separator between two
# distinct things - NOT commas/ampersands that are just part of a single
# name (there aren't any in this catalog's category names today, but
# this keeps the split intentionally narrow rather than exploding any
# comma it sees).
SPLIT_PATTERN = re.compile(r"\s*(?:&|\band\b|/)\s*", re.IGNORECASE)


def split_terms(name):
    parts = [p.strip() for p in SPLIT_PATTERN.split(name) if p.strip()]
    return parts if len(parts) > 1 else []


class Logger:
    """Prints to the console AND writes the same line to the log file -
    one call site instead of a print() + file.write() pair everywhere.
    The console preview stays short (head(5) previews); the log file
    gets everything via log(..., full=True)."""

    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(path, "w", encoding="utf-8")
        self._f.write(f"Compound leaf category audit - {datetime.now().isoformat(timespec='seconds')}\n\n")

    def __call__(self, line="", console=True, full=True):
        if console:
            print(line)
        if full:
            self._f.write(line + "\n")

    def close(self):
        self._f.close()


def main():
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set.")
        raise SystemExit(1)

    log = Logger(LOG_PATH)

    print("Connecting to Neon...")
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    print("Connected.\n")

    cur.execute("SELECT id, parent_id, name FROM categories")
    all_cats = cur.fetchall()
    parent_ids = {parent_id for _, parent_id, _ in all_cats if parent_id}
    leaves = [(cid, name) for cid, pid, name in all_cats if cid not in parent_ids]

    compound_leaves = [(cid, name, split_terms(name)) for cid, name in leaves]
    compound_leaves = [c for c in compound_leaves if c[2]]

    log(f"Leaf categories total: {len(leaves)}")
    log(f"Compound-named leaves found: {len(compound_leaves)}\n")

    if not compound_leaves:
        log("Nothing to review.")
        log.close()
        cur.close()
        conn.close()
        return

    for cid, name, terms in compound_leaves:
        cur.execute("SELECT id, name FROM products WHERE category = %s AND is_active = true", (cid,))
        products = cur.fetchall()

        buckets = {term: [] for term in terms}
        unmatched = []
        multi_matched = []
        for pid, pname in products:
            pname_l = pname.lower()
            hits = [term for term in terms if term.lower().rstrip("s") in pname_l or term.lower() in pname_l]
            if len(hits) == 0:
                unmatched.append((pid, pname))
            elif len(hits) > 1:
                multi_matched.append((pid, pname, hits))
            else:
                buckets[hits[0]].append((pid, pname))

        log(f"[{cid}] {name}")
        log(f"    split terms: {terms}")
        log(f"    total active products: {len(products)}")
        for term in terms:
            log(f"      -> {term!r}: {len(buckets[term])} product(s)")
        if multi_matched:
            log(f"      -> AMBIGUOUS (matches >1 term): {len(multi_matched)} product(s)")
            for pid, pname, hits in multi_matched[:5]:
                log(f"           {pname!r} matches {hits}", console=True)
            if len(multi_matched) > 5:
                log(f"           ... and {len(multi_matched) - 5} more", console=False)
                for pid, pname, hits in multi_matched[5:]:
                    log(f"           {pname!r} matches {hits}", console=False)
        if unmatched:
            log(f"      -> UNMATCHED (matches no term): {len(unmatched)} product(s)")
            for pid, pname in unmatched[:5]:
                log(f"           {pname!r}", console=True)
            if len(unmatched) > 5:
                log(f"           ... and {len(unmatched) - 5} more (full list below)", console=True)
                for pid, pname in unmatched[5:]:
                    log(f"           {pname!r}", console=False)
        clean = len(unmatched) == 0 and len(multi_matched) == 0
        log(f"    -> {'CLEAN split (safe to automate)' if clean else 'NEEDS REVIEW before splitting'}\n")

    log.close()
    cur.close()
    conn.close()
    print(f"\nFull review written to {LOG_PATH}")


if __name__ == "__main__":
    main()
