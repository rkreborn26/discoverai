#!/usr/bin/env python3
"""
DiscoverAI: Create cart_items, orders, order_items tables
================================================================

Backs the Cart / Checkout / Orders feature. There's no real user
auth in this portfolio app - the persona picker (see PERSONAS in
backend/static/index.html) stands in for "who's shopping", so every
row here is scoped by a plain persona_id string ("priya", "arjun",
...) rather than a foreign key into a users table that doesn't exist.

  - cart_items: one row per (persona_id, product_id) - the customer's
    current, unplaced cart. UNIQUE(persona_id, product_id) so adding
    the same product twice increments quantity instead of duplicating
    rows.
  - orders: one row per placed order. Checkout is a dummy "Place
    Order" button (no real payment/fulfillment), so every order is
    created with status 'Placed' and never changes - there's no
    fulfillment pipeline to advance it further yet.
  - order_items: line items for an order, with product name/brand/
    price/image SNAPSHOTTED at order time (not joined live to
    products) - so an order still shows what was actually bought at
    the price actually paid, even if the catalog changes later.

Usage:
    python CREATE_CART_ORDER_TABLES.py            # dry run
    python CREATE_CART_ORDER_TABLES.py --apply    # creates the tables
"""

import os
import sys

CREATE_CART_ITEMS_SQL = """
CREATE TABLE IF NOT EXISTS cart_items (
    id BIGSERIAL PRIMARY KEY,
    persona_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (persona_id, product_id)
);
"""

CREATE_CART_ITEMS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_cart_items_persona ON cart_items (persona_id);
"""

CREATE_ORDERS_SQL = """
CREATE TABLE IF NOT EXISTS orders (
    id VARCHAR(50) PRIMARY KEY,
    persona_id VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'Placed',
    total_amount NUMERIC(12,2) NOT NULL,
    placed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_ORDERS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_orders_persona ON orders (persona_id, placed_at DESC);
"""

CREATE_ORDER_ITEMS_SQL = """
CREATE TABLE IF NOT EXISTS order_items (
    id BIGSERIAL PRIMARY KEY,
    order_id VARCHAR(50) NOT NULL REFERENCES orders(id),
    product_id VARCHAR(50) NOT NULL REFERENCES products(id),
    product_name VARCHAR(255) NOT NULL,
    brand VARCHAR(100),
    price NUMERIC(12,2) NOT NULL,
    quantity INTEGER NOT NULL,
    image_url VARCHAR(500),
    pack_size VARCHAR(50)
);
"""

CREATE_ORDER_ITEMS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items (order_id);
"""


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

    print("Plan:")
    print("  - CREATE TABLE IF NOT EXISTS cart_items (persona_id, product_id, quantity)")
    print("  - CREATE INDEX ... cart_items (persona_id)")
    print("  - CREATE TABLE IF NOT EXISTS orders (id, persona_id, status, total_amount, placed_at)")
    print("  - CREATE INDEX ... orders (persona_id, placed_at DESC)")
    print("  - CREATE TABLE IF NOT EXISTS order_items (order_id, product snapshot fields, quantity)")
    print("  - CREATE INDEX ... order_items (order_id)")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.)")
        cur.close()
        conn.close()
        return

    cur.execute(CREATE_CART_ITEMS_SQL)
    cur.execute(CREATE_CART_ITEMS_INDEX_SQL)
    cur.execute(CREATE_ORDERS_SQL)
    cur.execute(CREATE_ORDERS_INDEX_SQL)
    cur.execute(CREATE_ORDER_ITEMS_SQL)
    cur.execute(CREATE_ORDER_ITEMS_INDEX_SQL)
    conn.commit()

    print("\nDone.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
