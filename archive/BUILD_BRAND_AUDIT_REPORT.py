#!/usr/bin/env python3
"""
DiscoverAI: Brand audit report
===================================

Dumps every distinct value in products.brand, with how many products use
it and a couple of sample product names, to a file - so the real-brand
vs not-a-brand classification can be done by reading the file directly
rather than pasting hundreds of lines into chat.

Usage:
    python BUILD_BRAND_AUDIT_REPORT.py
Writes: data/exports/brand_audit.md
"""

import os
import sys
from pathlib import Path

OUT_PATH = Path("data/exports/brand_audit.md")


def main():
    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    cur = conn.cursor()

    cur.execute("""
        SELECT brand, COUNT(*) AS product_count
        FROM products
        WHERE brand IS NOT NULL
        GROUP BY brand
        ORDER BY brand
    """)
    brands = cur.fetchall()

    lines = ["# Brand Audit", "", f"{len(brands)} distinct brand values in `products.brand`.", ""]
    lines.append("| brand | product_count | sample product names |")
    lines.append("|---|---|---|")

    for brand, count in brands:
        cur.execute("SELECT name FROM products WHERE brand = %s LIMIT 3", (brand,))
        samples = "; ".join(r[0] for r in cur.fetchall())
        lines.append(f"| {brand} | {count} | {samples} |")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Wrote {len(brands)} distinct brands to {OUT_PATH}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
