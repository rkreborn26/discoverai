#!/usr/bin/env python3
"""
DiscoverAI: Seed test reviews for one product (Ratings & Reviews QA)
=========================================================================

Generates a batch of test product_reviews rows for a single product so
the Review Moderation panel (and PDP) has real volume to test against,
without needing 100 real personas manually clicking through the app.

IMPORTANT CONTENT NOTE - read before running:
  The request behind this script asked for content covering profanity,
  hate speech, irrelevant reviews, delivery/wrong-product complaints,
  and image-policy violations, so a moderator has one real example of
  each rejection reason to practice on. This script generates safe
  STAND-INS for two of those instead of the real thing:
    - "Hate speech against someone" -> generic abusive/insulting
      language directed at the seller/brand (rude, not something
      that'd pass moderation - but NOT slurs or attacks on a
      protected characteristic). Real hate speech isn't something
      this script will generate, even as throwaway test data.
    - "Image does not follow policy standard" -> no image is actually
      attached (nothing generated or downloaded for this bucket) -
      the review text just reads as if a photo was attached, so you
      can still practice picking "needs_human_review" as the
      rejection reason. If you want a real inappropriate-image test
      case, that's on you to add manually - not something to generate.
  Every other bucket (profanity, not relevant at all, relevant to
  delivery/another product) uses mild, clearly-fake placeholder text -
  nothing here is real customer content.

What it does:
  - 60 rows of ordinary, varied-rating reviews (1-5 stars, realistic
    text) - written straight to status='approved' so they show up on
    the PDP immediately without you having to click Approve 60 times.
  - 40 rows split across 5 "worth rejecting" categories (8 each) -
    left at status='submitted', in the moderation queue, so you can
    practice the actual Approve/Reject flow (including picking the
    matching reason) in the Retailer Admin panel. An answer key
    (intended category per review) is printed at the end so you can
    check your own moderation calls against it.
  - Uses synthetic persona_ids ("seed_<product_id>_001", ...) rather
    than the real PERSONAS list, since product_reviews has a UNIQUE
    (product_id, persona_id) constraint - one product can only have as
    many reviews as there are personas otherwise. The frontend already
    falls back to a generic "Shopper" label for any persona_id it
    doesn't recognize (see ReviewCard/AdminReviewCard), so these
    display fine, just without a named avatar.
  - Safe to re-run: any existing seed_<product_id>_* rows for this
    product are deleted first, so re-running replaces rather than
    stacks duplicates.

Usage:
    python SEED_PRODUCT_REVIEWS.py prod_985            # dry run - shows the plan, writes nothing
    python SEED_PRODUCT_REVIEWS.py prod_985 --apply    # inserts the rows
"""

import os
import random
import sys
import uuid
from datetime import datetime

TOTAL_REVIEWS = 100
REJECT_WORTHY_COUNT = 40
GOOD_COUNT = TOTAL_REVIEWS - REJECT_WORTHY_COUNT

GOOD_TEMPLATES = {
    5: [
        "{product} exceeded my expectations - freshness and quality were great. Will definitely reorder.",
        "Excellent quality, arrived well packed, exactly as described. Highly recommend!",
        "Best purchase this month - {product} is exactly what I was looking for.",
        "Five stars, no complaints at all. Fast delivery and great quality.",
        "Really happy with {product}, tastes/works exactly as expected. Will buy again.",
    ],
    4: [
        "Good quality overall, though packaging could be a bit better. Still satisfied.",
        "{product} is decent, works fine, would buy again but not amazing.",
        "Pretty good for the price. A couple of minor things could be better.",
        "Happy with this purchase, met my expectations without any issues.",
    ],
    3: [
        "Average experience. {product} was okay but nothing special, a bit pricier than expected.",
        "It's fine - does the job, but I've had better from other brands.",
        "Mixed feelings - some things were good, some just okay. Reason: inconsistent quality batch to batch.",
    ],
    2: [
        "Not very satisfied - {product} quality was below what I expected for the price. Reason: quality felt lower than similar products I've bought before.",
        "Disappointing for the price point. Reason: packaging was damaged on arrival, product itself was fine but experience wasn't great.",
    ],
    1: [
        "Disappointed - {product} arrived in poor condition. Reason: item looked old/stale despite recent delivery date.",
        "Would not buy again. Reason: quality was noticeably worse than pictured on the listing.",
    ],
}

# Suggested rejection_reason values match reviews_routes.py's
# VALID_REJECTION_REASONS exactly: profanity / not_relevant / needs_human_review.
REJECT_BUCKETS = {
    "profanity": {
        "suggested_reason": "profanity",
        "label": "Profanity / abusive language about the product",
        "templates": [
            "This product is absolute garbage, whoever approved this for sale should be ashamed.",
            "Total waste of money, I'm so pissed off right now, never buying this again.",
            "This is crap, don't waste your time or money on this junk.",
            "Worst damn purchase I've made all year, utter trash.",
            "Are you kidding me with this garbage quality?! Ridiculous.",
            "This product sucks, plain and simple. Don't bother.",
            "What a joke of a product, complete rip-off.",
            "Absolute trash, I'm furious I paid for this.",
        ],
    },
    "abusive_personal": {
        "suggested_reason": "profanity",
        "label": "Abusive/insulting language aimed at the seller (stand-in for 'hate speech against someone' - see script docstring)",
        "templates": [
            "Whoever runs this store clearly doesn't care about customers, completely incompetent.",
            "The seller is a total fraud, scamming people for profit, avoid this shady operation.",
            "I hope this company goes out of business, terrible people running it.",
            "The people behind this brand are lazy and don't deserve anyone's money.",
            "Shame on whoever is running quality control here, clueless and careless.",
            "This seller is a joke, clearly hires incompetent people.",
            "Whoever approved this product for sale should lose their job.",
            "Disgraceful management, this company doesn't deserve any customers.",
        ],
    },
    "not_relevant": {
        "suggested_reason": "not_relevant",
        "label": "Review not relevant to this product at all",
        "templates": [
            "Can someone recommend a good laptop under 50000?",
            "What time does the mall close on Sundays?",
            "Does anyone know a good electrician nearby?",
            "Is anyone else having trouble logging into the app today?",
            "Looking for recommendations on a good gym near Koramangala.",
            "Does this website have a referral program?",
            "Random question - does anyone know a good plumber in the area?",
            "Not related to this item, but does the app have a dark mode?",
        ],
    },
    "not_relevant_delivery": {
        "suggested_reason": "not_relevant",
        "label": "Review relevant to delivery/another product, not this one",
        "templates": [
            "Delivery took over a week and the driver was rude, nothing to do with the product itself.",
            "I ordered this but received a completely different item in the box.",
            "Courier left the package outside in the rain, product might be fine but service was bad.",
            "The delivery partner was very unprofessional, this review is about that experience.",
            "Wrong item delivered entirely - got a bag of rice instead of what I ordered.",
            "Packaging box was crushed by the courier, haven't even opened the product yet.",
            "This review is actually about a different order - the app grouped them wrong.",
            "Customer support never responded to my delivery complaint, unrelated to product quality.",
        ],
    },
    "image_policy": {
        "suggested_reason": "needs_human_review",
        "label": "Simulates an image-policy violation (no real image attached - see script docstring)",
        "templates": [
            "Attaching a photo of what arrived - not what I expected honestly.",
            "See the photo I attached, packaging looked odd on arrival.",
            "Photo attached for reference, wanted to show the condition on arrival.",
            "Added a picture below showing what I received.",
            "Check the attached image, this is what showed up at my door.",
            "Photo attached - please review this before others see it.",
            "Uploading a picture of the item as received.",
            "Attached an image showing the actual product next to the listing photo.",
        ],
    },
}


def build_persona_id(product_id, index):
    return f"seed_{product_id}_{index:03d}"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply_changes = "--apply" in sys.argv
    product_id = args[0] if args else "prod_985"

    random.seed(f"discoverai-seed-{product_id}")  # deterministic across dry-run vs --apply

    # Build the 60 "good" rows.
    good_rows = []
    rating_pool = [5, 5, 5, 4, 4, 4, 3, 3, 2, 1]  # weighted toward positive, still varied
    for i in range(1, GOOD_COUNT + 1):
        rating = random.choice(rating_pool)
        text = random.choice(GOOD_TEMPLATES[rating]).format(product="this product")
        good_rows.append({"rating": rating, "review_text": text, "bucket": "good"})

    # Build the 40 "worth rejecting" rows, 8 per bucket.
    reject_rows = []
    for bucket_key, bucket in REJECT_BUCKETS.items():
        for template in bucket["templates"]:
            rating = random.choice([1, 2, 3, 4, 5])
            reject_rows.append({
                "rating": rating,
                "review_text": template,
                "bucket": bucket_key,
                "suggested_reason": bucket["suggested_reason"],
            })

    all_rows = good_rows + reject_rows
    random.shuffle(all_rows)
    for i, row in enumerate(all_rows, start=1):
        row["persona_id"] = build_persona_id(product_id, i)
        row["id"] = "REV-" + uuid.uuid4().hex[:10].upper()

    print(f"Product: {product_id}")
    print(f"Plan: {GOOD_COUNT} approved reviews + {REJECT_WORTHY_COUNT} submitted (reject-worthy) reviews = {len(all_rows)} total\n")

    bucket_counts = {}
    for row in all_rows:
        bucket_counts[row["bucket"]] = bucket_counts.get(row["bucket"], 0) + 1
    for bucket, count in bucket_counts.items():
        label = "Legitimate (auto-approved)" if bucket == "good" else REJECT_BUCKETS[bucket]["label"]
        print(f"  {bucket:20} x{count:<3}  {label}")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to insert these rows.)")
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

    cur.execute("SELECT 1 FROM products WHERE id = %s", (product_id,))
    if not cur.fetchone():
        print(f"\nERROR: product '{product_id}' not found.")
        cur.close()
        conn.close()
        sys.exit(1)

    # Re-runnable: clear any previous seed data for this product first.
    cur.execute(
        "DELETE FROM product_reviews WHERE product_id = %s AND persona_id LIKE %s",
        (product_id, f"seed_{product_id}_%"),
    )
    deleted = cur.rowcount
    if deleted:
        print(f"Removed {deleted} previously seeded review(s) for this product before re-inserting.")

    now = datetime.now()
    answer_key = []
    for row in all_rows:
        status = "approved" if row["bucket"] == "good" else "submitted"
        cur.execute("""
            INSERT INTO product_reviews
                (id, product_id, persona_id, rating, review_text, status, moderated_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """, (
            row["id"], product_id, row["persona_id"], row["rating"], row["review_text"],
            status, now if status == "approved" else None,
        ))
        if status == "submitted":
            answer_key.append((row["id"], row["bucket"], row["suggested_reason"]))

    conn.commit()
    print(f"\nDone. Inserted {len(all_rows)} reviews ({GOOD_COUNT} approved, {REJECT_WORTHY_COUNT} submitted).")

    print("\nAnswer key for the 40 submitted reviews (check your moderation calls against this):")
    print(f"{'review_id':16} {'bucket':20} suggested reason")
    for review_id, bucket, suggested_reason in answer_key:
        print(f"  {review_id:14} {bucket:20} {suggested_reason}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
