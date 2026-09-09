#!/usr/bin/env python3
"""
DiscoverAI: Report AI Moderation accuracy from already-saved data
========================================================================

Read-only - no writes, nothing to --apply. The "Evaluate AI Accuracy"
button (and the per-review/batch moderate endpoints) already save
moderator_agreed the moment a review's AI Moderation run completes and
compares it against that review's existing human decision - this script
just aggregates what's already sitting in product_reviews, so it's
instant even though the underlying AI runs that produced the data were
slow (each one is a handful of real OpenAI calls).

If this reports 0 evaluated reviews, it means AI Moderation hasn't
actually been run against your approved/rejected reviews yet - this
script can't produce that data itself, only summarize it once the
"Evaluate AI Accuracy" button (or a moderate-batch/moderate call) has
populated it.

Usage:
    python CHECK_AI_MODERATION_ACCURACY.py
    python CHECK_AI_MODERATION_ACCURACY.py --product-id prod_985
"""

import argparse
import os
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--product-id", default=None, help="Limit the report to one product.")
    args = p.parse_args()

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    cur = conn.cursor()

    product_filter = ""
    params = []
    if args.product_id:
        product_filter = " AND product_id = %s"
        params.append(args.product_id)

    cur.execute(f"""
        SELECT
            COUNT(*) FILTER (WHERE moderator_agreed IS NOT NULL) AS evaluated,
            COUNT(*) FILTER (WHERE moderator_agreed = true)      AS agreed,
            COUNT(*) FILTER (WHERE moderator_agreed = false)     AS disagreed,
            COUNT(*) FILTER (WHERE ai_decision IS NULL)          AS not_yet_evaluated,
            COUNT(*)                                             AS total_decided
        FROM product_reviews
        WHERE status IN ('approved', 'rejected') {product_filter}
    """, params)
    evaluated, agreed, disagreed, not_yet, total = cur.fetchone()

    print(f"Approved + Rejected reviews{' for ' + args.product_id if args.product_id else ''}: {total}")
    print(f"  Already evaluated by AI Moderation: {evaluated}")
    print(f"  Not yet evaluated (ai_decision IS NULL): {not_yet}")

    if evaluated:
        accuracy = round(100 * agreed / evaluated, 1)
        print(f"\nAgreed:    {agreed}")
        print(f"Disagreed: {disagreed}")
        print(f"Accuracy:  {accuracy}%")
    else:
        print("\nNo reviews evaluated yet - run 'Evaluate AI Accuracy' on the admin page first.")

    if disagreed:
        print("\nDisagreements by (AI reason -> human reason):")
        cur.execute(f"""
            SELECT ai_rejection_reason, rejection_reason, COUNT(*)
            FROM product_reviews
            WHERE status IN ('approved', 'rejected') AND moderator_agreed = false {product_filter}
            GROUP BY ai_rejection_reason, rejection_reason
            ORDER BY COUNT(*) DESC
        """, params)
        for ai_reason, human_reason, count in cur.fetchall():
            print(f"  AI said {ai_reason or 'approved'!r:22} -> human said {human_reason or 'approved'!r:22} : {count}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
