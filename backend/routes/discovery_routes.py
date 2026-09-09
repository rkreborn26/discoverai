"""
DiscoverAI Backend: Discovery API Routes
===========================================

Supports the Home / Search page flow (see
requirements/auto_suggestion_ai_pm_plan.md):

  - GET  /api/categories/leaf     - leaf categories with products, grouped
                                     under Vegetables / Fruits / Staples,
                                     for the Home page tile grid.
  - GET  /api/popular-searches    - the current ranked Popular Searches list.
  - POST /api/events/search       - log a search.
  - POST /api/events/impressions  - log every product actually shown for a
                                     query (batched, one call per results
                                     load) - the denominator for a real
                                     click-through-rate, not just clicks/search.
  - POST /api/events/click        - log a product click from a results page.
  - POST /api/events/add-to-cart  - log an add-to-cart action.

Every event (search / impression / click / add-to-cart) accepts an
optional `query_type`: 'popular_search' (chip tap), 'manual_entered'
(typed), or 'auto_suggestion_picked' (reserved for the not-yet-built Auto
Suggestion feature). This is what makes the Popular Search adoption rate
measurable - what fraction of searches/clicks/carts trace back to a chip
tap vs. manual typing (see requirements/auto_suggestion_ai_pm_plan.md,
Step 5 - Measurement).

Kept separate from search_routes.py since that file is scoped to the
semantic search feature itself; this one is scoped to the Home/Search page
and the event logging that feeds the popularity scoring job.
"""

import json
import logging

from flask import Blueprint, request, jsonify

from db import get_cursor

logger = logging.getLogger(__name__)

discovery = Blueprint('discovery', __name__, url_prefix='/api')

# Curated top-level sections for the Home page. Vegetables and Fruits
# aren't top-level categories themselves (they're both children of
# "Fruits & Vegetables"), and Staples & Grains is - the tree depth is
# inconsistent, so this is a deliberately curated list, not a generic
# "get children of X" query. Label is "Veggies" (not "Vegetables") per
# product decision on the Home page redesign.
HOME_SECTIONS = [
    ("Veggies", "cat_007"),
    ("Fruits", "cat_003a"),
    ("Staples", "cat_002"),
]

DEFAULT_POPULAR_SEARCHES_LIMIT = 20
VALID_EVENT_TYPES = {"search", "product_click", "add_to_cart", "product_impression"}
VALID_QUERY_TYPES = {"popular_search", "manual_entered", "auto_suggestion_picked"}
MAX_IMPRESSIONS_PER_CALL = 50  # matches search's own MAX_LIMIT - a sanity cap, not a real constraint


def _clean_query_type(query_type):
    """None/blank is fine (older callers, or a caller that doesn't know
    yet) - anything non-empty must be one of the recognized values."""
    if not query_type:
        return None
    query_type = query_type.strip()
    if not query_type:
        return None
    if query_type not in VALID_QUERY_TYPES:
        raise ValueError("Invalid query_type '" + query_type + "'. Must be one of: " + str(sorted(VALID_QUERY_TYPES)))
    return query_type


def _load_category_tree(cur):
    """Every category with its direct-product count, plus a parent_id ->
    children[] index - the shared shape both /categories/leaf and
    /sections/<root_id>/products walk to find leaf categories."""
    cur.execute("""
        SELECT c.id, c.parent_id, c.name, c.path, c.icon_url,
               COUNT(p.id) AS product_count
        FROM categories c
        LEFT JOIN products p ON p.category = c.id AND p.is_active = true
        GROUP BY c.id, c.parent_id, c.name, c.path, c.icon_url
    """)
    rows = cur.fetchall()

    by_id = {
        r[0]: {"id": r[0], "parent_id": r[1], "name": r[2], "path": r[3], "icon_url": r[4], "product_count": r[5]}
        for r in rows
    }
    children = {}
    for cat in by_id.values():
        children.setdefault(cat["parent_id"], []).append(cat["id"])
    return by_id, children


def _collect_leaves_with_products(by_id, children, root_id):
    """DFS from root_id, returning every descendant leaf (no children of
    its own) that has product_count > 0, sorted by name."""
    result = []
    stack = list(children.get(root_id, []))
    while stack:
        cat_id = stack.pop()
        cat = by_id.get(cat_id)
        if not cat:
            continue
        kids = children.get(cat_id, [])
        if kids:
            stack.extend(kids)
        elif cat["product_count"] > 0:
            result.append(cat)
    result.sort(key=lambda c: c["name"])
    return result


@discovery.route('/categories/leaf', methods=['GET'])
def leaf_categories():
    """
    Leaf categories (no children) that currently have at least one
    product, grouped under the curated Home-page sections.

    icon_url is returned per leaf category AND per section (the
    section's own root category's icon_url) - the Home page uses the
    former for tile images and the latter for the sticky Veggies/Fruits/
    Staples pill images. NULL is valid (not every category has one set
    yet) - the frontend falls back to a letter-avatar when absent, so
    this never blocks rendering.
    """
    with get_cursor() as cur:
        by_id, children = _load_category_tree(cur)

    sections = []
    for label, root_id in HOME_SECTIONS:
        leaves = _collect_leaves_with_products(by_id, children, root_id)
        root_cat = by_id.get(root_id)
        sections.append({
            "name": label,
            "root_category_id": root_id,
            "icon_url": root_cat["icon_url"] if root_cat else None,
            "categories": [
                {
                    "id": c["id"], "name": c["name"], "path": c["path"],
                    "icon_url": c["icon_url"], "product_count": c["product_count"],
                }
                for c in leaves
            ],
        })

    return jsonify({"sections": sections}), 200


@discovery.route('/sections/<root_id>/products', methods=['GET'])
def section_products(root_id):
    """
    Every leaf category under one curated Home-page section
    (Veggies/Fruits/Staples), each with its own product list, in a
    single call.

    Powers the PLP's continuous scroll: rather than re-fetching every
    time the customer picks a different category in the left rail, the
    whole section loads once and the page just scrolls to (and
    scrollspy-highlights) whichever leaf category is in view - the same
    smooth, no-reload pattern as the Home page's Veggies/Fruits/Staples
    pill nav, just one level deeper.
    """
    label = next((l for l, rid in HOME_SECTIONS if rid == root_id), None)
    if label is None:
        return jsonify({"error": "Unknown section."}), 404

    with get_cursor() as cur:
        by_id, children = _load_category_tree(cur)
        leaves = _collect_leaves_with_products(by_id, children, root_id)
        leaf_ids = [leaf["id"] for leaf in leaves]

        products_by_category = {}
        if leaf_ids:
            cur.execute("""
                SELECT p.category, p.id, p.name, p.brand, p.price, p.original_price,
                       p.discount_percentage, p.image_url, p.rating, p.review_count, p.in_stock,
                       pa.pack_size
                FROM products p
                LEFT JOIN product_attributes pa ON pa.product_id = p.id
                WHERE p.category = ANY(%s) AND p.is_active = true
                ORDER BY p.category, p.name ASC
            """, (leaf_ids,))
            for row in cur.fetchall():
                (cat_id, product_id, name, brand, price, original_price,
                 discount_percentage, image_url, rating, review_count, in_stock, pack_size) = row
                products_by_category.setdefault(cat_id, []).append({
                    "id": product_id,
                    "name": name,
                    "brand": brand or "Generic",
                    "price": float(price) if price is not None else None,
                    "original_price": float(original_price) if original_price is not None else None,
                    "discount_percentage": discount_percentage,
                    "image_url": image_url,
                    "rating": rating,
                    "review_count": review_count,
                    "in_stock": in_stock,
                    "pack_size": pack_size,
                })

    categories_out = [
        {
            "id": leaf["id"],
            "name": leaf["name"],
            "icon_url": leaf["icon_url"],
            "products": products_by_category.get(leaf["id"], []),
        }
        for leaf in leaves
    ]

    return jsonify({
        "section": {"name": label, "root_category_id": root_id},
        "categories": categories_out,
    }), 200


@discovery.route('/categories/<category_id>/products', methods=['GET'])
def category_products(category_id):
    """
    Every active product filed directly under one leaf category - the
    PLP a customer lands on after tapping a category tile on the Home
    page. Deliberately NOT a semantic search: plain filter + sort, no
    embeddings/ranking involved (that's what /api/search is for).
    """
    with get_cursor() as cur:
        cur.execute("SELECT id, name FROM categories WHERE id = %s", (category_id,))
        cat_row = cur.fetchone()
        if not cat_row:
            return jsonify({"error": "Category not found."}), 404

        cur.execute("""
            SELECT p.id, p.name, p.brand, p.price, p.original_price, p.discount_percentage,
                   p.image_url, p.rating, p.review_count, p.in_stock, pa.pack_size
            FROM products p
            LEFT JOIN product_attributes pa ON pa.product_id = p.id
            WHERE p.category = %s AND p.is_active = true
            ORDER BY p.name ASC
        """, (category_id,))
        rows = cur.fetchall()

    products = [
        {
            "id": r[0],
            "name": r[1],
            "brand": r[2] or "Generic",
            "price": float(r[3]) if r[3] is not None else None,
            "original_price": float(r[4]) if r[4] is not None else None,
            "discount_percentage": r[5],
            "image_url": r[6],
            "rating": r[7],
            "review_count": r[8],
            "in_stock": r[9],
            "pack_size": r[10],
        }
        for r in rows
    ]

    return jsonify({
        "category": {"id": cat_row[0], "name": cat_row[1]},
        "products": products,
    }), 200


@discovery.route('/products/<product_id>', methods=['GET'])
def product_detail(product_id):
    """
    Full detail for one product - the PDP a customer lands on after
    tapping a product card anywhere in the app (Home/PLP/Search Results
    all link here the same way, via /product/:productId).

    Returns every attribute column plus the free-form `attributes` JSON
    blob (identical parsing to search.py's custom_attributes handling,
    kept consistent so the same prep_type/variety/polish values shown
    in Search Results' filter chips also show up here), the category's
    full breadcrumb path, and a handful of related products from the
    same leaf category so browsing doesn't dead-end on this page.
    """
    with get_cursor() as cur:
        cur.execute("""
            SELECT p.id, p.sku, p.name, p.description, p.brand, p.price, p.original_price,
                   p.discount_percentage, p.in_stock, p.stock_quantity, p.image_url,
                   p.rating, p.review_count, p.category, c.name, c.path,
                   pa.pack_size, pa.organic, pa.color, pa.size, pa.material, pa.fit_type,
                   pa.ram_gb, pa.storage_gb, pa.connectivity_5g, pa.processor,
                   pa.display_size_inch, pa.attributes
            FROM products p
            LEFT JOIN categories c ON p.category = c.id
            LEFT JOIN product_attributes pa ON pa.product_id = p.id
            WHERE p.id = %s AND p.is_active = true
        """, (product_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Product not found."}), 404

        (pid, sku, name, description, brand, price, original_price, discount_percentage,
         in_stock, stock_quantity, image_url, rating, review_count, category_id, category_name,
         category_path, pack_size, organic, color, size, material, fit_type, ram_gb, storage_gb,
         connectivity_5g, processor, display_size_inch, raw_attributes) = row

        # Same dict-or-JSON-string handling as search.py's custom_attributes
        # - psycopg2 has returned this column both ways depending on driver
        # version, so handle both rather than assuming one.
        if isinstance(raw_attributes, dict):
            custom_attributes = raw_attributes
        elif raw_attributes:
            try:
                custom_attributes = json.loads(raw_attributes)
            except (TypeError, ValueError):
                custom_attributes = {}
        else:
            custom_attributes = {}

        related_rows = []
        if category_id:
            cur.execute("""
                SELECT p.id, p.name, p.brand, p.price, p.original_price, p.discount_percentage,
                       p.image_url, p.rating, p.review_count, p.in_stock, pa.pack_size
                FROM products p
                LEFT JOIN product_attributes pa ON pa.product_id = p.id
                WHERE p.category = %s AND p.is_active = true AND p.id != %s
                ORDER BY p.rating DESC NULLS LAST, p.name ASC
                LIMIT 10
            """, (category_id, product_id))
            related_rows = cur.fetchall()

        # Ratings & Reviews (see reviews_routes.py for the write side / the
        # moderation queue). The average includes every 'approved' row -
        # pure ratings (no text, auto-approved) and moderator-approved
        # written reviews both count - so a product's score reflects all
        # approved feedback, not just the ones with something written. The
        # written-review LIST below is narrower: only approved rows that
        # actually have text, since an empty "review" has nothing to show.
        cur.execute("""
            SELECT ROUND(AVG(rating)::numeric, 1), COUNT(*)
            FROM product_reviews
            WHERE product_id = %s AND status = 'approved'
        """, (product_id,))
        avg_rating, rating_count = cur.fetchone()

        cur.execute("""
            SELECT id, persona_id, rating, review_text, created_at
            FROM product_reviews
            WHERE product_id = %s AND status = 'approved'
              AND review_text IS NOT NULL AND review_text != ''
            ORDER BY created_at DESC
            LIMIT 20
        """, (product_id,))
        review_rows = cur.fetchall()

        # Photos attached to those reviews (see reviews_routes.py's
        # review_images table) - one batched query for every review on
        # this page rather than one per review.
        review_ids = [r[0] for r in review_rows]
        images_by_review = {}
        if review_ids:
            cur.execute("""
                SELECT id, review_id, image_url
                FROM review_images
                WHERE review_id = ANY(%s)
                ORDER BY review_id, position ASC
            """, (review_ids,))
            for image_id, review_id, image_url in cur.fetchall():
                images_by_review.setdefault(review_id, []).append(
                    {"id": image_id, "image_url": image_url}
                )

        # AI Review Summary (see review_summary_routes.py for the write/
        # moderation side) - only the PUBLISHED text is ever read here;
        # a draft sitting unpublished in Retailer Admin is invisible to
        # the storefront by design. published_text is a JSON object with
        # 3 keys (praises/criticism/neutral) - same parsing rules as
        # review_summary_routes.py's _parse_summary_json, duplicated here
        # per this project's convention for small cross-file helpers
        # (see e.g. SET_PRODUCT_IMAGE_URLS.py's docstring) rather than
        # importing across route blueprints.
        cur.execute(
            "SELECT published_text FROM product_review_summaries WHERE product_id = %s",
            (product_id,),
        )
        summary_row = cur.fetchone()
        raw_summary = summary_row[0] if summary_row else None
        review_summary = None
        if raw_summary:
            try:
                parsed_summary = json.loads(raw_summary)
                if isinstance(parsed_summary, dict):
                    review_summary = {
                        key: str(parsed_summary.get(key) or "").strip()
                        for key in ("praises", "criticism", "neutral")
                    }
            except (TypeError, ValueError):
                pass
            if review_summary is None:
                # Legacy pre-3-section plain-paragraph summary - surface
                # it as "praises" so it still displays until regenerated.
                review_summary = {"praises": raw_summary.strip(), "criticism": "", "neutral": ""}

    related_products = [
        {
            "id": r[0],
            "name": r[1],
            "brand": r[2] or "Generic",
            "price": float(r[3]) if r[3] is not None else None,
            "original_price": float(r[4]) if r[4] is not None else None,
            "discount_percentage": r[5],
            "image_url": r[6],
            "rating": r[7],
            "review_count": r[8],
            "in_stock": r[9],
            "pack_size": r[10],
        }
        for r in related_rows
    ]

    reviews_out = [
        {
            "id": r[0],
            "persona_id": r[1],
            "rating": r[2],
            "review_text": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
            "images": images_by_review.get(r[0], []),
        }
        for r in review_rows
    ]

    product = {
        "id": pid,
        "sku": sku,
        "name": name,
        "description": description,
        "brand": brand or "Generic",
        "price": float(price) if price is not None else None,
        "original_price": float(original_price) if original_price is not None else None,
        "discount_percentage": discount_percentage,
        "in_stock": bool(in_stock) if in_stock is not None else True,
        "stock_quantity": stock_quantity,
        "image_url": image_url,
        "rating": float(rating) if rating is not None else None,
        "review_count": review_count,
        "category": {"id": category_id, "name": category_name, "path": category_path},
        "pack_size": pack_size,
        "organic": bool(organic) if organic is not None else None,
        "color": color,
        "size": size,
        "material": material,
        "fit_type": fit_type,
        "ram_gb": ram_gb,
        "storage_gb": storage_gb,
        "connectivity_5g": bool(connectivity_5g) if connectivity_5g is not None else None,
        "processor": processor,
        "display_size_inch": display_size_inch,
        "custom_attributes": custom_attributes,
    }

    return jsonify({
        "product": product,
        "related_products": related_products,
        "rating_summary": {
            "average": float(avg_rating) if avg_rating is not None else None,
            "count": rating_count or 0,
        },
        "reviews": reviews_out,
        "review_summary": review_summary,
    }), 200


@discovery.route('/popular-searches', methods=['GET'])
def popular_searches():
    """
    Current ranked Popular Searches. Returns the full ranked list (up to
    `limit`); the frontend shuffles for display variety rather than the
    API doing it, so repeated calls are stable/cacheable.
    """
    try:
        limit = int(request.args.get('limit', DEFAULT_POPULAR_SEARCHES_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_POPULAR_SEARCHES_LIMIT

    with get_cursor() as cur:
        cur.execute("""
            SELECT query_text, search_volume, click_rate, cart_rate, popularity_score, is_seed, rank
            FROM popular_queries
            ORDER BY rank ASC NULLS LAST, popularity_score DESC NULLS LAST
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()

    queries = [
        {
            "query": r[0],
            "search_volume": r[1],
            "click_rate": float(r[2]) if r[2] is not None else None,
            "cart_rate": float(r[3]) if r[3] is not None else None,
            "popularity_score": float(r[4]) if r[4] is not None else None,
            "is_seed": r[5],
        }
        for r in rows
    ]
    return jsonify({"queries": queries}), 200


def _log_event(event_type, query_text, product_id=None, position=None, query_type=None):
    if not query_text or not query_text.strip():
        raise ValueError("query_text is required")
    query_type = _clean_query_type(query_type)
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO search_events (query_text, event_type, product_id, position, query_type)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (query_text.strip(), event_type, product_id, position, query_type),
        )


@discovery.route('/events/search', methods=['POST'])
def log_search_event():
    data = request.get_json(silent=True) or {}
    try:
        _log_event("search", data.get("query_text"), query_type=data.get("query_type"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error("Failed to log search event: %s", e)
        return jsonify({"error": "Could not log event."}), 500
    return jsonify({"status": "ok"}), 201


@discovery.route('/events/impressions', methods=['POST'])
def log_impressions_event():
    """
    Batched: one call per results-page-load, logging every product that
    was actually shown (with its position) - not one HTTP round trip per
    product. Body:
        {"query_text": "...", "query_type": "popular_search",
         "positions": [{"product_id": "...", "position": 1}, ...]}
    query_type applies to every impression in the batch - they're all from
    the same results render, so they share the same "how did we get here".
    """
    data = request.get_json(silent=True) or {}
    query_text = (data.get("query_text") or "").strip()
    impressions = data.get("positions") or []

    try:
        query_type = _clean_query_type(data.get("query_type"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not query_text:
        return jsonify({"error": "query_text is required"}), 400
    if not isinstance(impressions, list) or not impressions:
        return jsonify({"error": "positions must be a non-empty list"}), 400
    if len(impressions) > MAX_IMPRESSIONS_PER_CALL:
        impressions = impressions[:MAX_IMPRESSIONS_PER_CALL]

    rows = []
    for item in impressions:
        product_id = item.get("product_id")
        position = item.get("position")
        if not product_id:
            continue
        rows.append((query_text, "product_impression", product_id, position, query_type))

    if not rows:
        return jsonify({"error": "no valid impressions in positions"}), 400

    try:
        # Single multi-row INSERT rather than one round trip per product -
        # impressions fire far more often than clicks/carts (every product
        # on every results page, not just the ones a customer acts on).
        with get_cursor(commit=True) as cur:
            values_sql = ", ".join(["(%s, %s, %s, %s, %s)"] * len(rows))
            flat_params = [value for row in rows for value in row]
            cur.execute(
                "INSERT INTO search_events (query_text, event_type, product_id, position, query_type) VALUES " + values_sql,
                flat_params,
            )
    except Exception as e:
        logger.error("Failed to log impression events: %s", e)
        return jsonify({"error": "Could not log events."}), 500

    return jsonify({"status": "ok", "logged": len(rows)}), 201


@discovery.route('/events/click', methods=['POST'])
def log_click_event():
    data = request.get_json(silent=True) or {}
    try:
        _log_event(
            "product_click", data.get("query_text"), data.get("product_id"), data.get("position"),
            query_type=data.get("query_type"),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error("Failed to log click event: %s", e)
        return jsonify({"error": "Could not log event."}), 500
    return jsonify({"status": "ok"}), 201


@discovery.route('/events/add-to-cart', methods=['POST'])
def log_add_to_cart_event():
    data = request.get_json(silent=True) or {}
    try:
        _log_event(
            "add_to_cart", data.get("query_text"), data.get("product_id"), data.get("position"),
            query_type=data.get("query_type"),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error("Failed to log add-to-cart event: %s", e)
        return jsonify({"error": "Could not log event."}), 500
    return jsonify({"status": "ok"}), 201
