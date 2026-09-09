"""
DiscoverAI Backend: AI Review Summary
=========================================

Retailer Admin side (a moderator generates/edits - see the Review
Summary tool page):
  GET   /api/admin/products/<product_id>/review-summary             - eligibility + current summary
  POST  /api/admin/products/<product_id>/review-summary/generate     - generate + auto-publish
  PATCH /api/admin/products/<product_id>/review-summary              - edit + auto-publish
  POST  /api/admin/products/<product_id>/review-summary/publish      - re-publish current draft (after an Unpublish)
  POST  /api/admin/products/<product_id>/review-summary/unpublish    - pull the summary off the PDP
  POST  /api/admin/review-summaries/batch-generate                   - bulk utility, see below

Storefront side: discovery_routes.py's product_detail() reads
published_text directly (a plain read, no write path) and returns it as
"review_summary" alongside everything else PDP already fetches.

REVISED design (per explicit follow-up direction - supersedes the
original draft-then-publish writeup):
  1. Only APPROVED reviews (with text) ever feed generation - see
     _fetch_reviews_for_summary()/_count_eligible_reviews() below, both
     filter status='approved'. This was already true from the first
     build; noting it here since it was explicitly confirmed as a
     requirement.
  2. A generated summary is AUTO-PUBLISHED immediately - draft_text and
     published_text are written together in the same call, both by
     generate_review_summary() and by a moderator's edit
     (edit_review_summary()). There's no separate "review before it
     goes live" gate anymore. draft_text/published_text stay as two
     columns for the Unpublish/re-Publish escape hatch (pulling a bad
     summary down without losing the text, or bringing it back), but
     day-to-day they move together.
  3. batch-generate is a bulk utility, not a background job - a
     moderator clicks it, it runs once, synchronously, over every
     currently-qualifying product:
       - never summarized before: >=5 approved written reviews
       - already summarized: >=3 approved written reviews submitted
         AFTER the existing summary's generated_at (i.e. genuinely new
         feedback since last time, not just "grew past a number")
     Each qualifying product is generated AND auto-published in the
     same run, same as the single-product endpoint.
  4. The summary is no longer one paragraph - it's 3 sections:
     "praises" / "criticism" / "neutral" (internal keys; the admin/PDP
     UI shows them as "What Customers Love" / "What Could Be Better" /
     "Mixed Feedback"). No schema migration for this - draft_text and
     published_text still store a single string each, it's just JSON
     now (see _parse_summary_json/SECTION_KEYS) instead of plain prose.
     Older, pre-this-change summaries were a plain paragraph, not JSON -
     _parse_summary_json() falls back to treating that legacy text as
     the "praises" section so old rows don't crash the API; Regenerate
     replaces them with the real 3-part structure.
"""

import json
import logging
import os
import uuid

from flask import Blueprint, request, jsonify

from db import get_cursor

logger = logging.getLogger(__name__)

review_summary = Blueprint('review_summary', __name__, url_prefix='/api')

MIN_REVIEWS_FOR_SUMMARY = 5
SUMMARY_MODEL = "gpt-4o-mini"
MAX_REVIEWS_IN_PROMPT = 50  # most recent - a sane cap so the prompt doesn't grow unbounded

# Internal keys (used in the stored JSON and every API payload). Display
# titles are a frontend concern (see index.html's SUMMARY_SECTION_DEFS) -
# kept out of here on purpose so relabeling them later isn't a backend change.
SECTION_KEYS = ("praises", "criticism", "neutral")

_client = None


def _get_client():
    """Lazy-init OpenAI client, same pattern as search.py's _get_client()."""
    global _client
    if _client is None:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set. Make sure .env exists and contains OPENAI_API_KEY.")
        from openai import OpenAI
        _client = OpenAI(api_key=api_key)
    return _client


def _parse_summary_json(raw_text):
    """draft_text/published_text store a JSON object with SECTION_KEYS.
    Returns None for an empty/NULL column (nothing generated/published
    yet) or a dict with all 3 keys present (empty string for any section
    the model had nothing to say). Falls back to treating unparseable
    text as a legacy plain-paragraph summary (pre-3-section format) -
    surfaced entirely as "praises" so it still displays as SOMETHING
    rather than erroring, until it's regenerated into the real format.
    """
    if not raw_text:
        return None
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return {key: str(parsed.get(key) or "").strip() for key in SECTION_KEYS}
    except (TypeError, ValueError):
        pass
    return {"praises": raw_text.strip(), "criticism": "", "neutral": ""}


def _row_to_summary(row):
    (summary_id, product_id, draft_text, published_text, review_count_at_generation,
     is_edited, generated_at, published_at) = row
    return {
        "id": summary_id,
        "product_id": product_id,
        "draft": _parse_summary_json(draft_text),
        "published": _parse_summary_json(published_text),
        "review_count_at_generation": review_count_at_generation,
        "is_edited": is_edited,
        "generated_at": generated_at.isoformat() if generated_at else None,
        "published_at": published_at.isoformat() if published_at else None,
        "has_unpublished_changes": bool(draft_text) and draft_text != published_text,
    }


SUMMARY_ROW_COLUMNS = """id, product_id, draft_text, published_text,
                          review_count_at_generation, is_edited, generated_at, published_at"""


def _fetch_reviews_for_summary(cur, product_id):
    cur.execute("""
        SELECT rating, review_text
        FROM product_reviews
        WHERE product_id = %s AND status = 'approved'
          AND review_text IS NOT NULL AND review_text != ''
        ORDER BY created_at DESC
        LIMIT %s
    """, (product_id, MAX_REVIEWS_IN_PROMPT))
    return cur.fetchall()


def _count_eligible_reviews(cur, product_id):
    cur.execute("""
        SELECT COUNT(*)
        FROM product_reviews
        WHERE product_id = %s AND status = 'approved'
          AND review_text IS NOT NULL AND review_text != ''
    """, (product_id,))
    return cur.fetchone()[0]


def _generate_summary_sections(product_name, reviews):
    """Calls OpenAI to synthesize `reviews` (list of (rating, text)) into 3
    short sections keyed by SECTION_KEYS. Raises on API failure OR on a
    response that isn't the expected JSON shape - caller decides how to
    surface that (no silent partial/garbled summary ever gets saved)."""
    lines = [f"{rating} out of 5 stars: {text.strip()}" for rating, text in reviews]
    reviews_block = "\n".join(lines)

    system_prompt = (
        "You analyze customer product reviews for an e-commerce retailer's internal "
        "moderation tool. Classify the feedback into exactly three sections and return "
        "STRICT JSON with exactly these keys: \"praises\", \"criticism\", \"neutral\".\n"
        "- \"praises\": common positive themes customers mention.\n"
        "- \"criticism\": common complaints or negative themes customers mention.\n"
        "- \"neutral\": mixed, lukewarm, or ambivalent feedback that isn't clearly positive "
        "or negative (e.g. \"decent but nothing special\").\n"
        "Each value is a short, factual string (1-3 sentences, plain prose, no bullet points, "
        "no markdown) IN PROPORTION to how often that sentiment actually appears - or an empty "
        "string \"\" if a section genuinely doesn't apply. Never invent a detail that isn't in "
        "the reviews. Do not mention star ratings as numbers inside the text - describe "
        "sentiment in words."
    )
    user_prompt = f"Product: {product_name}\n\nReviews ({len(reviews)} total):\n{reviews_block}"

    client = _get_client()
    response = client.chat.completions.create(
        model=SUMMARY_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=400,
        temperature=0.4,
        response_format={"type": "json_object"},
    )
    parsed = json.loads(response.choices[0].message.content)
    if not isinstance(parsed, dict):
        raise ValueError("Model response was not a JSON object.")
    return {key: str(parsed.get(key) or "").strip() for key in SECTION_KEYS}


@review_summary.route('/admin/products/<product_id>/review-summary', methods=['GET'])
def get_review_summary(product_id):
    try:
        with get_cursor() as cur:
            cur.execute("SELECT id, name FROM products WHERE id = %s", (product_id,))
            product_row = cur.fetchone()
            if not product_row:
                return jsonify({"error": "Product not found."}), 404

            eligible_count = _count_eligible_reviews(cur, product_id)

            cur.execute(f"SELECT {SUMMARY_ROW_COLUMNS} FROM product_review_summaries WHERE product_id = %s", (product_id,))
            summary_row = cur.fetchone()
    except Exception as e:
        logger.error("Failed to load review summary for product=%r: %s", product_id, e)
        return jsonify({
            "error": "Could not load review summary. Has CREATE_REVIEW_SUMMARIES_TABLE.py --apply been run?"
        }), 500

    return jsonify({
        "product": {"id": product_row[0], "name": product_row[1]},
        "eligible_review_count": eligible_count,
        "min_reviews_required": MIN_REVIEWS_FOR_SUMMARY,
        "eligible": eligible_count >= MIN_REVIEWS_FOR_SUMMARY,
        "summary": _row_to_summary(summary_row) if summary_row else None,
    }), 200


def _generate_and_save(product_id, product_name, eligible_count, reviews):
    """Core generate-then-auto-publish logic, shared by the single-product
    endpoint below and batch-generate. Raises on failure (OpenAI call or
    DB write) - callers decide how to report that.

    generated_at/published_at are stamped with SQL CURRENT_TIMESTAMP, NOT
    Python's datetime.now() - they get compared later against
    product_reviews.created_at (also DEFAULT CURRENT_TIMESTAMP, set by
    Postgres) to find "reviews submitted since the last summary"
    (_find_batch_candidates). Stamping one side in Python's local time and
    the other in Postgres's session time (Neon runs in UTC) silently
    breaks that comparison whenever the two clocks disagree - which is
    every non-UTC server. Computing both sides in Postgres keeps them on
    the same clock, always.
    """
    sections = _generate_summary_sections(product_name, reviews)
    sections_json = json.dumps(sections)

    summary_id = "SUM-" + uuid.uuid4().hex[:10].upper()
    with get_cursor(commit=True) as cur:
        cur.execute(f"""
            INSERT INTO product_review_summaries
                (id, product_id, draft_text, published_text, review_count_at_generation,
                 is_edited, generated_at, published_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (product_id) DO UPDATE SET
                draft_text = EXCLUDED.draft_text,
                published_text = EXCLUDED.published_text,
                review_count_at_generation = EXCLUDED.review_count_at_generation,
                is_edited = false,
                generated_at = CURRENT_TIMESTAMP,
                published_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            RETURNING {SUMMARY_ROW_COLUMNS}
        """, (summary_id, product_id, sections_json, sections_json, eligible_count))
        return cur.fetchone()


@review_summary.route('/admin/products/<product_id>/review-summary/generate', methods=['POST'])
def generate_review_summary(product_id):
    try:
        with get_cursor() as cur:
            cur.execute("SELECT id, name FROM products WHERE id = %s", (product_id,))
            product_row = cur.fetchone()
            if not product_row:
                return jsonify({"error": "Product not found."}), 404

            eligible_count = _count_eligible_reviews(cur, product_id)
            if eligible_count < MIN_REVIEWS_FOR_SUMMARY:
                return jsonify({
                    "error": f"Needs at least {MIN_REVIEWS_FOR_SUMMARY} approved written reviews "
                             f"(currently {eligible_count})."
                }), 400

            reviews = _fetch_reviews_for_summary(cur, product_id)
    except Exception as e:
        logger.error("Failed to look up product/reviews for summary generation product=%r: %s", product_id, e)
        return jsonify({
            "error": "Could not read reviews. Has CREATE_REVIEW_SUMMARIES_TABLE.py --apply been run?"
        }), 500

    try:
        row = _generate_and_save(product_id, product_row[1], eligible_count, reviews)
    except Exception as e:
        logger.error("Failed to generate review summary for product=%r: %s", product_id, e)
        return jsonify({"error": "Could not generate summary right now. Please try again."}), 502

    return jsonify({"summary": _row_to_summary(row)}), 200


@review_summary.route('/admin/products/<product_id>/review-summary', methods=['PATCH'])
def edit_review_summary(product_id):
    """Moderator hand-edit of the 3 sections - auto-publishes immediately,
    same as generate_review_summary(): a correction IS the new live text,
    there's no separate confirm-and-publish step for it. Body:
    {"praises": "...", "criticism": "...", "neutral": "..."} - any key
    may be omitted/empty (a section can legitimately be blank), but at
    least one of the three must have content."""
    data = request.get_json(silent=True) or {}
    sections = {key: (data.get(key) or "").strip() for key in SECTION_KEYS}
    if not any(sections.values()):
        return jsonify({"error": "At least one section (praises, criticism, or neutral) is required."}), 400
    sections_json = json.dumps(sections)

    try:
        with get_cursor(commit=True) as cur:
            cur.execute(f"""
                UPDATE product_review_summaries
                SET draft_text = %s, published_text = %s, is_edited = true,
                    published_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE product_id = %s
                RETURNING {SUMMARY_ROW_COLUMNS}
            """, (sections_json, sections_json, product_id))
            row = cur.fetchone()
    except Exception as e:
        logger.error("Failed to edit review summary for product=%r: %s", product_id, e)
        return jsonify({"error": "Could not save edit."}), 500

    if not row:
        return jsonify({"error": "No summary exists for this product yet - generate one first."}), 404

    return jsonify({"summary": _row_to_summary(row)}), 200


@review_summary.route('/admin/products/<product_id>/review-summary/publish', methods=['POST'])
def publish_review_summary(product_id):
    try:
        with get_cursor(commit=True) as cur:
            cur.execute(f"""
                UPDATE product_review_summaries
                SET published_text = draft_text, published_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE product_id = %s AND draft_text IS NOT NULL
                RETURNING {SUMMARY_ROW_COLUMNS}
            """, (product_id,))
            row = cur.fetchone()
    except Exception as e:
        logger.error("Failed to publish review summary for product=%r: %s", product_id, e)
        return jsonify({"error": "Could not publish summary."}), 500

    if not row:
        return jsonify({"error": "No draft summary to publish for this product."}), 404

    return jsonify({"summary": _row_to_summary(row)}), 200


@review_summary.route('/admin/products/<product_id>/review-summary/unpublish', methods=['POST'])
def unpublish_review_summary(product_id):
    """Pulls the summary off the PDP without touching draft_text - the
    draft stays exactly as it was, just not live anymore."""
    try:
        with get_cursor(commit=True) as cur:
            cur.execute(f"""
                UPDATE product_review_summaries
                SET published_text = NULL, published_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE product_id = %s
                RETURNING {SUMMARY_ROW_COLUMNS}
            """, (product_id,))
            row = cur.fetchone()
    except Exception as e:
        logger.error("Failed to unpublish review summary for product=%r: %s", product_id, e)
        return jsonify({"error": "Could not unpublish summary."}), 500

    if not row:
        return jsonify({"error": "No summary exists for this product."}), 404

    return jsonify({"summary": _row_to_summary(row)}), 200


NEW_REVIEWS_FOR_REGENERATION = 3


def _find_batch_candidates(cur):
    """Two groups of products, per the agreed batch rule:
      - never summarized: >=MIN_REVIEWS_FOR_SUMMARY approved written reviews
      - already summarized: >=NEW_REVIEWS_FOR_REGENERATION approved written
        reviews submitted AFTER the existing summary's generated_at (genuinely
        new feedback since last time, not just "the total grew").
    Returns a list of (product_id, product_name, eligible_count) - eligible_count
    is the CURRENT total (used for the prompt + the new review_count_at_generation
    snapshot), not the delta.
    """
    cur.execute(f"""
        SELECT p.id, p.name, COUNT(pr.id)
        FROM products p
        JOIN product_reviews pr
            ON pr.product_id = p.id AND pr.status = 'approved'
           AND pr.review_text IS NOT NULL AND pr.review_text != ''
        LEFT JOIN product_review_summaries s ON s.product_id = p.id
        WHERE s.id IS NULL
        GROUP BY p.id, p.name
        HAVING COUNT(pr.id) >= %s
    """, (MIN_REVIEWS_FOR_SUMMARY,))
    never_summarized = cur.fetchall()

    cur.execute(f"""
        SELECT p.id, p.name, total.total_count, new_since.new_count
        FROM products p
        JOIN product_review_summaries s ON s.product_id = p.id
        JOIN LATERAL (
            SELECT COUNT(*) AS total_count
            FROM product_reviews pr
            WHERE pr.product_id = p.id AND pr.status = 'approved'
              AND pr.review_text IS NOT NULL AND pr.review_text != ''
        ) total ON true
        JOIN LATERAL (
            SELECT COUNT(*) AS new_count
            FROM product_reviews pr
            WHERE pr.product_id = p.id AND pr.status = 'approved'
              AND pr.review_text IS NOT NULL AND pr.review_text != ''
              AND pr.created_at > s.generated_at
        ) new_since ON true
        WHERE new_since.new_count >= %s
    """, (NEW_REVIEWS_FOR_REGENERATION,))
    needs_refresh = cur.fetchall()

    candidates = [(pid, name, count) for pid, name, count in never_summarized]
    candidates += [(pid, name, total_count) for pid, name, total_count, _new_count in needs_refresh]
    return candidates


@review_summary.route('/admin/review-summaries/batch-generate', methods=['POST'])
def batch_generate_review_summaries():
    """
    Bulk utility for the admin panel - NOT a background job. A moderator
    clicks this once, it runs synchronously over every currently-qualifying
    product (see _find_batch_candidates), generating and auto-publishing a
    summary for each. One product's failure (e.g. a transient OpenAI error)
    doesn't stop the rest of the batch - each is tried independently and
    the per-product outcome is reported back.
    """
    try:
        with get_cursor() as cur:
            candidates = _find_batch_candidates(cur)
            reviews_by_product = {
                product_id: _fetch_reviews_for_summary(cur, product_id)
                for product_id, _name, _count in candidates
            }
    except Exception as e:
        logger.error("Failed to find batch-generate candidates: %s", e)
        return jsonify({
            "error": "Could not scan for eligible products. Has CREATE_REVIEW_SUMMARIES_TABLE.py --apply been run?"
        }), 500

    results = []
    for product_id, product_name, eligible_count in candidates:
        try:
            row = _generate_and_save(product_id, product_name, eligible_count, reviews_by_product[product_id])
            results.append({
                "product_id": product_id, "product_name": product_name,
                "status": "generated", "summary": _row_to_summary(row),
            })
        except Exception as e:
            logger.error("Batch summary generation failed for product=%r: %s", product_id, e)
            results.append({
                "product_id": product_id, "product_name": product_name,
                "status": "failed", "error": str(e)[:200],
            })

    return jsonify({
        "candidates_found": len(candidates),
        "generated": sum(1 for r in results if r["status"] == "generated"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "results": results,
    }), 200
