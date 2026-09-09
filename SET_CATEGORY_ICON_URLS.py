#!/usr/bin/env python3
"""
DiscoverAI: Set category icon_url (Home page tile/pill images)
====================================================================

The Home page redesign replaces letter-avatar circles with real photos
per category tile, and the sticky Veggies/Fruits/Staples pill nav also
shows a small photo alongside its label - both read from
categories.icon_url, which already exists in the schema.

Product decision: use real stock photos now, with the explicit
understanding this is an easily swappable placeholder - icon_url is
just a URL string, so pointing a category at a different image later is
a one-row UPDATE (or just re-run this script after editing the
overrides below), not a code change.

UPDATE: was loremflickr.com (free, keyword-based photo URLs). Switched
to picsum.photos - loremflickr was unreliable in the browser (timeouts/
dropped connections under load, causing tiles to silently fall back to
the letter-avatar even though icon_url was correctly set - see
SET_PRODUCT_IMAGE_URLS.py, which hit the identical issue and was fixed
the same way). Trade-off: picsum has no keyword support, so these are
now generic stock photos rather than category-relevant ones. The
NAME_OVERRIDES / SECTION_ROOT_OVERRIDES dicts below are no longer read,
kept only as a reference in case keyword-based photos are wanted again
later (e.g. pointing at a different, more reliable keyword-photo API).

NAME_OVERRIDES hand-picks a better search keyword for categories whose
own name wouldn't make a good photo query as-is (too long, has "&",
awkward punctuation - e.g. "Besan & Other Flours" -> "chickpea-flour").
SECTION_ROOT_OVERRIDES does the same for the 3 curated Home-page section
roots (Veggies/Fruits/Staples), keyed by category id since their raw
names in the DB aren't what's displayed as the section label. Any
category in neither dict falls back to its own name, slugified - so
nothing is left without an image, but the ones that matter most (a small,
curated list) can be hand-tuned.

Usage:
    python SET_CATEGORY_ICON_URLS.py            # dry run - shows the plan, writes nothing
    python SET_CATEGORY_ICON_URLS.py --apply    # writes icon_url for every changed category
"""

import os
import re
import sys

PLACEHOLDER_BASE = "https://picsum.photos/seed"

SECTION_ROOT_OVERRIDES = {
    "cat_007": "vegetables",
    "cat_003a": "fruits",
    "cat_002": "grains",
}

NAME_OVERRIDES = {
    # loremflickr treats a comma-separated list as multiple tags ANDed
    # together (e.g. "wheat,flour" = photos tagged both "wheat" AND
    # "flour"); a hyphenated single segment (e.g. "wheat-flour") instead
    # searches for that exact literal compound tag, which rarely exists
    # on Flickr - with no match it silently falls back to an arbitrary
    # random photo, which is why several categories looked unrelated to
    # their name. Genuine single-word concepts stay as one word; anything
    # that's really two concepts is now comma-separated.
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
    """Fallback for any category not in NAME_OVERRIDES - lowercase,
    strip everything except letters/numbers/spaces, and join words with
    commas (not hyphens) so loremflickr ANDs each word as its own tag
    rather than searching for one literal hyphenated compound tag that
    likely doesn't exist (see the comment on NAME_OVERRIDES). Not
    hand-curated, but never leaves a category with no image at all."""
    cleaned = re.sub(r"[^a-z0-9\s]", "", name.lower())
    words = cleaned.split()
    return ",".join(words) if words else "grocery"


def icon_url_for(category_id, name):
    # picsum has no keyword support, so `name` is unused now - kept as
    # a param so the call site doesn't need to change. Seeded by
    # category id: deterministic (fixed across reloads/re-runs), and
    # every category gets a different photo since the seed is unique.
    return "%s/%s/400/400" % (PLACEHOLDER_BASE, category_id)


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

    cur.execute("SELECT id, name, icon_url FROM categories WHERE is_active = true ORDER BY name")
    rows = cur.fetchall()

    plan = []
    for cat_id, name, existing_icon_url in rows:
        new_url = icon_url_for(cat_id, name)
        if existing_icon_url != new_url:
            plan.append((cat_id, name, existing_icon_url, new_url))

    print("Categories checked: %d" % len(rows))
    print("Would set/update icon_url on: %d" % len(plan))
    for cat_id, name, old, new in plan[:60]:
        marker = "NEW" if not old else "CHANGE"
        print("  [%s] %s %r: %r -> %r" % (marker, cat_id, name, old, new))
    if len(plan) > 60:
        print("  ... and %d more" % (len(plan) - 60))

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.")
        print(" To use different images later, edit NAME_OVERRIDES / SECTION_ROOT_OVERRIDES")
        print(" above and re-run --apply - or just UPDATE categories SET icon_url = ... directly.)")
        cur.close()
        conn.close()
        return

    for cat_id, name, old, new in plan:
        cur.execute(
            "UPDATE categories SET icon_url = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (new, cat_id),
        )
    conn.commit()

    print("\nDone. Updated %d categories." % len(plan))

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
