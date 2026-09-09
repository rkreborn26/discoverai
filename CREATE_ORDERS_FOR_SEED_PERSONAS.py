#!/usr/bin/env python3
"""
DiscoverAI: Backfill orders for seeded review personas
=============================================================

The Velocity/Fraud AI moderation agent (see moderation_routes.py, rule
V2) rejects a review if that persona has placed ZERO orders (any
product) in the last 15 days. The synthetic personas created by
SEED_PRODUCT_REVIEWS.py ("seed_<product_id>_001", ...) never placed any
real order through the storefront, so every one of them would currently
fail V2 the moment AI Moderation runs on their reviews - not because
anything is actually wrong with those reviews, just because the test
data never gave them a purchase history.

This script backfills a purchase history for most (not all - see
--percent) of a product's seeded personas, so AI Moderation testing
exercises the OTHER rules (V1, V3, and the text/hate-speech/image
checks) instead of every single seeded review being rejected on V2 by
construction. The ~10% left without an order are intentional - useful
for confirming V2 actually fires when it's supposed to.

For each selected persona, creates ONE order containing ONE order_item
for the given product (defaults to the same product they reviewed -
incidental, V2 only checks "any purchase", not "purchased this
product"), dated randomly within the last 1-14 days (comfortably inside
the 15-day window, computed DB-side via CURRENT_TIMESTAMP - so this
can't drift out of range due to a Python/Postgres clock mismatch - see
the timezone lesson from the AI Review Summary feature).

Idempotent: deletes any existing orders (and their order_items) for
personas matching seed_<product_id>_% before recreating, so re-running
this after re-seeding reviews (which can change how many seed personas
exist) is safe.

Usage:
    python CREATE_ORDERS_FOR_SEED_PERSONAS.py                       # dry run for prod_985, 90%
    python CREATE_ORDERS_FOR_SEED_PERSONAS.py --apply                # applies it
    python CREATE_ORDERS_FOR_SEED_PERSONAS.py --product-id prod_123 --percent 80 --apply
"""

import argparse
import os
import random
import sys
import uuid


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--product-id", default="prod_985", help="Product whose seed_<product_id>_* personas to backfill orders for.")
    p.add_argument("--percent", type=float, default=90.0, help="Percent of seeded personas to give an order to (default 90).")
    p.add_argument("--apply", action="store_true", help="Actually write to the database (default is a dry run).")
    return p.parse_args()


def main():
    args = parse_args()
    product_id = args.product_id
    percent = args.percent

    print("Plan:")
    print(f"  - Find all distinct persona_id LIKE 'seed_{product_id}_%' in product_reviews (product_id={product_id})")
    print(f"  - Delete any existing orders (+ order_items) already backfilled for those personas")
    print(f"  - Give {percent:.0f}% of them (random selection) ONE order containing ONE order_item")
    print(f"    for {product_id}, placed_at randomly 1-14 days ago (comfortably inside the AI")
    print(f"    Moderation Velocity agent's 15-day 'no recent purchase' window)")
    print(f"  - The remaining ~{100 - percent:.0f}% are left with no order on purpose, so V2 can still")
    print(f"    be exercised in testing")

    if not args.apply:
        print("\n(dry run - nothing written. Re-run with --apply to write to the database.)")
        return

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    print("\nConnecting to Neon...")
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    print("Connected.")

    persona_pattern = f"seed_{product_id}_%"

    cur.execute(
        "SELECT DISTINCT persona_id FROM product_reviews WHERE product_id = %s AND persona_id LIKE %s ORDER BY persona_id",
        (product_id, persona_pattern),
    )
    all_personas = [r[0] for r in cur.fetchall()]

    if not all_personas:
        print(f"\nNo seed_{product_id}_* personas found in product_reviews. "
              f"Has SEED_PRODUCT_REVIEWS.py --product-id {product_id} --apply been run?")
        cur.close()
        conn.close()
        sys.exit(1)

    print(f"\nFound {len(all_personas)} seeded personas for {product_id}.")

    cur.execute("""
        SELECT p.name, p.brand, p.price, p.image_url, pa.pack_size
        FROM products p LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE p.id = %s
    """, (product_id,))
    product_row = cur.fetchone()
    if not product_row:
        print(f"\nERROR: product {product_id} not found in products table.")
        cur.close()
        conn.close()
        sys.exit(1)
    product_name, brand, price, image_url, pack_size = product_row
    price = float(price) if price is not None else 0.0

    # Clean slate for this product's seed personas - safe to re-run.
    cur.execute("""
        DELETE FROM order_items WHERE order_id IN (
            SELECT id FROM orders WHERE persona_id LIKE %s
        )
    """, (persona_pattern,))
    deleted_items = cur.rowcount
    cur.execute("DELETE FROM orders WHERE persona_id LIKE %s", (persona_pattern,))
    deleted_orders = cur.rowcount
    if deleted_orders:
        print(f"Removed {deleted_orders} previously-backfilled order(s) ({deleted_items} order_item(s)) for these personas.")

    random.seed(42)  # deterministic selection - re-running gives the same personas an order
    target_count = round(len(all_personas) * percent / 100.0)
    with_order = set(random.sample(all_personas, target_count))

    created = 0
    for persona_id in all_personas:
        if persona_id not in with_order:
            continue
        order_id = "ORD-" + uuid.uuid4().hex[:10].upper()
        quantity = random.randint(1, 2)
        total_amount = round(price * quantity, 2)
        days_ago = random.randint(1, 14)

        cur.execute("""
            INSERT INTO orders (id, persona_id, status, total_amount, placed_at)
            VALUES (%s, %s, 'Placed', %s, CURRENT_TIMESTAMP - %s::interval)
        """, (order_id, persona_id, total_amount, f"{days_ago} days"))

        cur.execute("""
            INSERT INTO order_items (order_id, product_id, product_name, brand, price, quantity, image_url, pack_size)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (order_id, product_id, product_name, brand, price, quantity, image_url, pack_size))
        created += 1

    conn.commit()

    skipped = len(all_personas) - created
    print(f"\nDone. {created} of {len(all_personas)} personas now have an order in the last 14 days "
          f"({skipped} intentionally left without one).")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
