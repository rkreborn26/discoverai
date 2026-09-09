#!/usr/bin/env python3
"""
DiscoverAI: Set product image_url (PLP product card photos)
=================================================================

Populates products.image_url so the PLP (see PLPProductCard / PLPPage
in backend/static/index.html) shows real photos instead of the
letter-tile fallback.

UPDATE: this used to point at loremflickr.com with a category-derived
keyword (see NAME_OVERRIDES / SECTION_ROOT_OVERRIDES below - kept in
this file, and still used by SET_CATEGORY_ICON_URLS.py, but no longer
read here). loremflickr proved unreliable in the browser - a PLP grid
firing 20+ simultaneous requests at it regularly got timeouts/dropped
connections, which the frontend gracefully falls back from (the
letter-tile avatar), but that showed up as "images aren't loading" for
a big chunk of the catalog even though image_url was correctly set for
every product.

Now uses picsum.photos/seed/{product_id}/400/400 instead - a much more
reliable CDN. Trade-off: picsum has no keyword/category support, so
images are generic stock photos rather than "looks like rice" for a
rice product. Deterministic per product id (same product always gets
the same photo), and every product still gets a DIFFERENT photo from
its neighbors since the seed is the product id, not the category.

Same Neon free-tier connection-drop resilience as
GENERATE_CATEGORY_SUGGESTION_PHRASES.py (ResilientConn, reconnect +
retry) since this can be a few hundred UPDATEs in one run.

Usage:
    python SET_PRODUCT_IMAGE_URLS.py            # dry run - shows the plan, writes nothing
    python SET_PRODUCT_IMAGE_URLS.py --apply    # writes image_url for every changed product
"""

import os
import re
import sys
import time

PLACEHOLDER_BASE = "https://picsum.photos/seed"

# Copied from SET_CATEGORY_ICON_URLS.py - keep these two dicts in sync
# if that script's overrides ever change.
SECTION_ROOT_OVERRIDES = {
    "cat_007": "vegetables",
    "cat_003a": "fruits",
    "cat_002": "grains",
}

NAME_OVERRIDES = {
    "Rice": "rice",
    "Atta & Wheat Flour": "wheat,flour",
    "Besan & Other Flours": "chickpea,flour",
    "Cooking Oil & Ghee": "cooking,oil",
    "Pulses & Lentils": "lentils",
    "Sugar & Salt": "sugar",

    "Onions & Shallots": "onions",
    "Potatoes & Sweet Potatoes": "potatoes",
    "Tomatoes & Chilies": "tomatoes",
    "Garlic & Ginger": "garlic",

    "Spinach & Kale": "spinach",
    "Lettuces & Salad Mixes": "lettuce",
    "Herbs & Seasonings": "fresh,herbs",
    "Microgreens & Sprouts": "microgreens",

    "Carrots & Beetroots": "carrots",
    "Radishes & Turnips": "radish",
    "Yams, Taro & Exotic Tubers": "yams",

    "Cucumbers": "cucumber",
    "Zucchini & Summer Squash": "zucchini",
    "Pumpkins & Winter Squash": "pumpkin",

    "Broccoli & Cauliflower": "broccoli",
    "Cabbage & Brussels Sprouts": "cabbage",
    "Green Beans, Peas & Okra": "green,beans",

    "Asparagus & Artichokes": "asparagus",
    "Mushrooms": "mushroom",
    "Asian / Regional Specialty Veggies": "bokchoy",

    "Pre-cut & Diced Veggies": "diced,vegetables",
    "Stir-fry & Soup Kits": "stirfry",
    "Salad Kits": "salad",

    "Citrus Fruits": "citrus,fruit",
    "Berries": "berries",
    "Melons": "melon",
    "Tropical & Exotic Fruits": "tropical,fruit",
    "Pome & Core Fruits": "apple",
    "Stone Fruits": "peach",
}


def slugify(name):
    """Same as SET_CATEGORY_ICON_URLS.py's slugify - comma-joins words
    so loremflickr ANDs each as its own tag, rather than searching for
    one literal hyphenated compound tag that likely doesn't exist."""
    cleaned = re.sub(r"[^a-z0-9\s]", "", (name or "").lower())
    words = cleaned.split()
    return ",".join(words) if words else "grocery"


def keyword_for_category(category_id, category_name):
    if category_id in SECTION_ROOT_OVERRIDES:
        return SECTION_ROOT_OVERRIDES[category_id]
    if category_name in NAME_OVERRIDES:
        return NAME_OVERRIDES[category_name]
    return slugify(category_name)


def image_url_for(product_id, category_id, category_name):
    # picsum has no keyword support, so category_id/category_name are
    # unused here now - kept as params so the call site (and the
    # NAME_OVERRIDES table above, still used by SET_CATEGORY_ICON_URLS.py)
    # doesn't need to change. Seeded by product id: deterministic and
    # unique per product.
    return "%s/%s/400/400" % (PLACEHOLDER_BASE, product_id)


class ResilientConn:
    """Wraps a Neon connection with automatic reconnect-and-retry on
    dropped connections (same pattern as
    GENERATE_CATEGORY_SUGGESTION_PHRASES.py) - a single dropped
    connection partway through a few-hundred-row run shouldn't crash
    the whole script."""

    MAX_RETRIES = 5

    def __init__(self, database_url):
        import psycopg2
        self._psycopg2 = psycopg2
        self.database_url = database_url
        self.conn = psycopg2.connect(database_url)
        self.cur = self.conn.cursor()

    def _reconnect(self):
        try:
            self.conn.close()
        except Exception:
            pass
        self.conn = self._psycopg2.connect(self.database_url)
        self.cur = self.conn.cursor()

    def _run(self, sql, params, commit):
        for attempt in range(1, self.MAX_RETRIES + 2):
            try:
                self.cur.execute(sql, params or ())
                if commit:
                    self.conn.commit()
                    return None
                return self.cur.fetchall()
            except (self._psycopg2.OperationalError, self._psycopg2.InterfaceError) as e:
                if attempt > self.MAX_RETRIES:
                    raise
                print(
                    "    connection dropped (%s), reconnecting (attempt %d/%d)..."
                    % (str(e)[:60], attempt, self.MAX_RETRIES),
                    end=" ",
                    flush=True,
                )
                try:
                    self._reconnect()
                    print("OK")
                except Exception as reconnect_error:
                    print("reconnect failed: %s" % str(reconnect_error)[:60])
                    time.sleep(2)

    def execute(self, sql, params=None):
        return self._run(sql, params, commit=False)

    def execute_write(self, sql, params=None):
        self._run(sql, params, commit=True)

    def close(self):
        try:
            self.cur.close()
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass


def main():
    apply_changes = "--apply" in sys.argv

    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    print("Connecting to Neon...")
    rc = ResilientConn(database_url)
    print("Connected.\n")

    rows = rc.execute("""
        SELECT p.id, p.category, c.name, p.image_url
        FROM products p
        LEFT JOIN categories c ON p.category = c.id
        WHERE p.is_active = true
        ORDER BY p.id
    """)

    plan = []
    for product_id, category_id, category_name, existing_url in rows:
        new_url = image_url_for(product_id, category_id, category_name or "")
        if existing_url != new_url:
            plan.append((product_id, category_name, existing_url, new_url))

    print("Products checked: %d" % len(rows))
    print("Would set/update image_url on: %d" % len(plan))
    for product_id, category_name, old, new in plan[:60]:
        marker = "NEW" if not old else "CHANGE"
        print("  [%s] %s (%s): %r -> %r" % (marker, product_id, category_name, old, new))
    if len(plan) > 60:
        print("  ... and %d more" % (len(plan) - 60))

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.")
        print(" To use different images later, edit NAME_OVERRIDES / SECTION_ROOT_OVERRIDES")
        print(" above and re-run --apply - or just UPDATE products SET image_url = ... directly.)")
        rc.close()
        return

    for i, (product_id, category_name, old, new) in enumerate(plan, start=1):
        rc.execute_write(
            "UPDATE products SET image_url = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (new, product_id),
        )
        if i % 100 == 0:
            print("  ...%d/%d written" % (i, len(plan)))

    print("\nDone. Updated %d products." % len(plan))
    rc.close()


if __name__ == "__main__":
    main()
