"""
DiscoverAI Backend: Cart / Checkout / Orders API
====================================================

Backs the Cart -> Checkout -> Orders flow. There's no real user auth in
this portfolio app - every call is scoped by a plain `persona_id`
string (matching PERSONAS in backend/static/index.html: "priya",
"arjun", ...), passed as a query param on reads and a body field on
writes, standing in for "whoever is currently signed in".

  GET    /api/cart                       - current cart for a persona
  POST   /api/cart/items                 - add a product (increments
                                            quantity if already in cart)
  PATCH  /api/cart/items/<product_id>    - set an exact quantity
                                            (removes the item if <= 0)
  DELETE /api/cart/items/<product_id>    - remove an item entirely
  POST   /api/checkout                   - dummy "Place Order": snapshots
                                            the cart into a new order,
                                            clears the cart
  GET    /api/orders                     - a persona's order history
  GET    /api/orders/<order_id>          - one order's detail

Checkout is intentionally dummy - no payment, no fulfillment pipeline -
so every order is created with a fixed status ('Placed') and never
changes after that. order_items SNAPSHOTS product name/brand/price/
image/pack_size at order time rather than joining live to products, so
an order keeps showing what was actually bought at the price actually
paid even if the catalog changes later.
"""

import logging
import uuid

from flask import Blueprint, request, jsonify

from db import get_cursor

logger = logging.getLogger(__name__)

cart = Blueprint('cart', __name__, url_prefix='/api')


def _row_to_cart_item(row):
    product_id, quantity, name, brand, price, image_url, in_stock, pack_size = row
    price = float(price) if price is not None else 0.0
    return {
        "product_id": product_id,
        "name": name,
        "brand": brand or "Generic",
        "price": price,
        "image_url": image_url,
        "pack_size": pack_size,
        "in_stock": in_stock,
        "quantity": quantity,
        "line_total": round(price * quantity, 2),
    }


def _fetch_cart(cur, persona_id):
    cur.execute("""
        SELECT ci.product_id, ci.quantity, p.name, p.brand, p.price,
               p.image_url, p.in_stock, pa.pack_size
        FROM cart_items ci
        JOIN products p ON p.id = ci.product_id
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE ci.persona_id = %s
        ORDER BY ci.created_at ASC
    """, (persona_id,))
    items = [_row_to_cart_item(r) for r in cur.fetchall()]
    subtotal = round(sum(i["line_total"] for i in items), 2)
    return items, subtotal


@cart.route('/cart', methods=['GET'])
def get_cart():
    persona_id = request.args.get('persona_id', '').strip()
    if not persona_id:
        return jsonify({"error": "persona_id is required"}), 400

    try:
        with get_cursor() as cur:
            items, subtotal = _fetch_cart(cur, persona_id)
    except Exception as e:
        logger.error("Failed to fetch cart for persona=%r: %s", persona_id, e)
        return jsonify({"error": "Could not load cart."}), 500

    return jsonify({"items": items, "subtotal": subtotal}), 200


@cart.route('/cart/items', methods=['POST'])
def add_cart_item():
    data = request.get_json(silent=True) or {}
    persona_id = (data.get('persona_id') or '').strip()
    product_id = (data.get('product_id') or '').strip()
    quantity = data.get('quantity', 1)

    if not persona_id or not product_id:
        return jsonify({"error": "persona_id and product_id are required"}), 400
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = 1
    if quantity < 1:
        quantity = 1

    try:
        with get_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO cart_items (persona_id, product_id, quantity)
                VALUES (%s, %s, %s)
                ON CONFLICT (persona_id, product_id)
                DO UPDATE SET quantity = cart_items.quantity + EXCLUDED.quantity,
                              updated_at = CURRENT_TIMESTAMP
            """, (persona_id, product_id, quantity))
            items, subtotal = _fetch_cart(cur, persona_id)
    except Exception as e:
        logger.error("Failed to add cart item persona=%r product=%r: %s", persona_id, product_id, e)
        return jsonify({"error": "Could not add to cart."}), 500

    return jsonify({"items": items, "subtotal": subtotal}), 200


@cart.route('/cart/items/<product_id>', methods=['PATCH'])
def set_cart_item_quantity(product_id):
    data = request.get_json(silent=True) or {}
    persona_id = (data.get('persona_id') or '').strip()
    quantity = data.get('quantity')

    if not persona_id:
        return jsonify({"error": "persona_id is required"}), 400
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return jsonify({"error": "quantity must be a number"}), 400

    try:
        with get_cursor(commit=True) as cur:
            if quantity <= 0:
                cur.execute(
                    "DELETE FROM cart_items WHERE persona_id = %s AND product_id = %s",
                    (persona_id, product_id),
                )
            else:
                cur.execute("""
                    UPDATE cart_items SET quantity = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE persona_id = %s AND product_id = %s
                """, (quantity, persona_id, product_id))
            items, subtotal = _fetch_cart(cur, persona_id)
    except Exception as e:
        logger.error("Failed to update cart item persona=%r product=%r: %s", persona_id, product_id, e)
        return jsonify({"error": "Could not update cart."}), 500

    return jsonify({"items": items, "subtotal": subtotal}), 200


@cart.route('/cart/items/<product_id>', methods=['DELETE'])
def remove_cart_item(product_id):
    persona_id = request.args.get('persona_id', '').strip()
    if not persona_id:
        return jsonify({"error": "persona_id is required"}), 400

    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "DELETE FROM cart_items WHERE persona_id = %s AND product_id = %s",
                (persona_id, product_id),
            )
            items, subtotal = _fetch_cart(cur, persona_id)
    except Exception as e:
        logger.error("Failed to remove cart item persona=%r product=%r: %s", persona_id, product_id, e)
        return jsonify({"error": "Could not update cart."}), 500

    return jsonify({"items": items, "subtotal": subtotal}), 200


@cart.route('/checkout', methods=['POST'])
def checkout():
    """
    Dummy "Place Order": snapshots whatever's currently in the cart into
    a new order + order_items, then clears the cart - all in a single
    transaction (one commit=True get_cursor block), so a failure partway
    through never leaves an order without its items or a cart that was
    cleared without an order being created.
    """
    data = request.get_json(silent=True) or {}
    persona_id = (data.get('persona_id') or '').strip()
    if not persona_id:
        return jsonify({"error": "persona_id is required"}), 400

    order_id = "ORD-" + uuid.uuid4().hex[:8].upper()

    try:
        with get_cursor(commit=True) as cur:
            items, subtotal = _fetch_cart(cur, persona_id)
            if not items:
                return jsonify({"error": "Your cart is empty."}), 400

            cur.execute(
                "INSERT INTO orders (id, persona_id, status, total_amount) VALUES (%s, %s, 'Placed', %s)",
                (order_id, persona_id, subtotal),
            )
            for item in items:
                cur.execute("""
                    INSERT INTO order_items
                        (order_id, product_id, product_name, brand, price, quantity, image_url, pack_size)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    order_id, item["product_id"], item["name"], item["brand"],
                    item["price"], item["quantity"], item["image_url"], item["pack_size"],
                ))
            cur.execute("DELETE FROM cart_items WHERE persona_id = %s", (persona_id,))
    except Exception as e:
        logger.error("Checkout failed for persona=%r: %s", persona_id, e)
        return jsonify({"error": "Checkout failed. Please try again."}), 500

    return jsonify({
        "order": {
            "id": order_id,
            "status": "Placed",
            "total_amount": subtotal,
            "items": items,
        },
    }), 201


@cart.route('/orders', methods=['GET'])
def list_orders():
    persona_id = request.args.get('persona_id', '').strip()
    if not persona_id:
        return jsonify({"error": "persona_id is required"}), 400

    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT o.id, o.status, o.total_amount, o.placed_at, COUNT(oi.id) AS item_count
                FROM orders o
                LEFT JOIN order_items oi ON oi.order_id = o.id
                WHERE o.persona_id = %s
                GROUP BY o.id, o.status, o.total_amount, o.placed_at
                ORDER BY o.placed_at DESC
            """, (persona_id,))
            rows = cur.fetchall()
    except Exception as e:
        logger.error("Failed to list orders for persona=%r: %s", persona_id, e)
        return jsonify({"error": "Could not load orders."}), 500

    orders = [
        {
            "id": r[0],
            "status": r[1],
            "total_amount": float(r[2]) if r[2] is not None else 0.0,
            "placed_at": r[3].isoformat() if r[3] else None,
            "item_count": r[4],
        }
        for r in rows
    ]
    return jsonify({"orders": orders}), 200


@cart.route('/orders/<order_id>', methods=['GET'])
def get_order(order_id):
    persona_id = request.args.get('persona_id', '').strip()
    if not persona_id:
        return jsonify({"error": "persona_id is required"}), 400

    try:
        with get_cursor() as cur:
            cur.execute(
                "SELECT id, persona_id, status, total_amount, placed_at FROM orders WHERE id = %s",
                (order_id,),
            )
            order_row = cur.fetchone()
            if not order_row or order_row[1] != persona_id:
                return jsonify({"error": "Order not found."}), 404

            cur.execute("""
                SELECT product_id, product_name, brand, price, quantity, image_url, pack_size
                FROM order_items
                WHERE order_id = %s
            """, (order_id,))
            item_rows = cur.fetchall()
    except Exception as e:
        logger.error("Failed to load order=%r: %s", order_id, e)
        return jsonify({"error": "Could not load order."}), 500

    items = [
        {
            "product_id": r[0],
            "name": r[1],
            "brand": r[2],
            "price": float(r[3]) if r[3] is not None else 0.0,
            "quantity": r[4],
            "image_url": r[5],
            "pack_size": r[6],
        }
        for r in item_rows
    ]

    return jsonify({
        "order": {
            "id": order_row[0],
            "status": order_row[2],
            "total_amount": float(order_row[3]) if order_row[3] is not None else 0.0,
            "placed_at": order_row[4].isoformat() if order_row[4] else None,
            "items": items,
        },
    }), 200
