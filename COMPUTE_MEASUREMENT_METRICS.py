#!/usr/bin/env python3
"""
DiscoverAI: Measurement metrics (Step 5)
=============================================

Computes the two metrics from requirements/auto_suggestion_ai_pm_plan.md,
Step 5:

  1. Popular Search adoption rate - what fraction of searches came from
     tapping a chip (query_type='popular_search') vs typing manually
     (query_type='manual_entered'), vs the reserved but not-yet-used
     'auto_suggestion_picked'.
  2. Per-product click-through rate - product_click count / product_impression
     count, overall and broken down by query_type (does a chip-driven
     search convert differently than a manually-typed one?).

Read-only - just reports, doesn't write anything. Safe to run any time.

Usage:
    python COMPUTE_MEASUREMENT_METRICS.py
"""

import os
import sys


def pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "n/a"


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

    print("=" * 70)
    print("METRIC 1: Popular Search adoption rate")
    print("=" * 70)

    cur.execute("""
        SELECT COALESCE(query_type, 'unknown (logged before query_type existed)'), COUNT(*)
        FROM search_events
        WHERE event_type = 'search'
        GROUP BY 1
        ORDER BY 2 DESC
    """)
    rows = cur.fetchall()
    total_searches = sum(r[1] for r in rows)

    if total_searches == 0:
        print("No search events logged yet.")
    else:
        for query_type, count in rows:
            print(f"  {query_type:45s} {count:6d}  ({pct(count, total_searches)})")
        print(f"  {'TOTAL':45s} {total_searches:6d}")

    print()
    print("=" * 70)
    print("METRIC 2: Per-product click-through rate (clicks / impressions)")
    print("=" * 70)

    cur.execute("SELECT COUNT(*) FROM search_events WHERE event_type = 'product_impression'")
    total_impressions = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM search_events WHERE event_type = 'product_click'")
    total_clicks = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM search_events WHERE event_type = 'add_to_cart'")
    total_carts = cur.fetchone()[0]

    print(f"  Overall: {total_clicks} clicks / {total_impressions} impressions = CTR {pct(total_clicks, total_impressions)}")
    print(f"  Overall: {total_carts} add-to-carts / {total_impressions} impressions = cart rate {pct(total_carts, total_impressions)}")

    print("\n  Broken down by query_type:")
    cur.execute("""
        SELECT COALESCE(query_type, 'unknown'),
               COUNT(*) FILTER (WHERE event_type = 'product_impression') AS impressions,
               COUNT(*) FILTER (WHERE event_type = 'product_click') AS clicks,
               COUNT(*) FILTER (WHERE event_type = 'add_to_cart') AS carts
        FROM search_events
        WHERE event_type IN ('product_impression', 'product_click', 'add_to_cart')
        GROUP BY 1
        ORDER BY impressions DESC
    """)
    for query_type, impressions, clicks, carts in cur.fetchall():
        print(f"    {query_type:20s} impressions={impressions:5d}  clicks={clicks:4d} (CTR {pct(clicks, impressions)})"
              f"  carts={carts:4d} (rate {pct(carts, impressions)})")

    print("\n  Broken down by position (are clicks concentrated at the top regardless of quality?):")
    cur.execute("""
        SELECT position,
               COUNT(*) FILTER (WHERE event_type = 'product_impression') AS impressions,
               COUNT(*) FILTER (WHERE event_type = 'product_click') AS clicks
        FROM search_events
        WHERE event_type IN ('product_impression', 'product_click') AND position IS NOT NULL
        GROUP BY position
        ORDER BY position
        LIMIT 12
    """)
    for position, impressions, clicks in cur.fetchall():
        print(f"    position {position:>2}: impressions={impressions:5d}  clicks={clicks:4d} (CTR {pct(clicks, impressions)})")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
