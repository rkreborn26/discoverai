"""
DiscoverAI Backend: Ratings & Reviews
=========================================

Storefront side (customer-facing, on the PDP):
  POST /api/products/<product_id>/reviews   - submit/update a rating (+ optional review + photos)

Retailer Admin side (Review Moderation panel):
  GET  /api/admin/reviews                   - list reviews for moderation, filterable by status
  POST /api/admin/reviews/<review_id>/approve
  POST /api/admin/reviews/<review_id>/reject

Moderation model:
  - A rating submitted WITHOUT review text is approved immediately - there's
    nothing for a moderator to read, so it never enters the queue.
  - A rating submitted WITH review text starts as 'submitted' and needs a
    moderator's decision before it can show up anywhere on the storefront.
  - Rating 3 stars or below REQUIRES review text (enforced here, not just in
    the frontend) - a low score always comes with an explanation, and by
    construction always lands in the moderation queue rather than being
    silently auto-approved.
  - One row per (product_id, persona_id) - re-submitting upserts (overwrites)
    rather than stacking duplicate reviews, and resets moderation state
    (any previous approval/rejection no longer applies to the new content).
  - Photos ride along with whatever the review's status ends up being (a
    pure rating's photos are approved instantly too, same as its rating) -
    there's no separate photo-only approval step. Moderators see them in
    the queue (see list_reviews_for_moderation) so an inappropriate image
    can still be caught even on an otherwise-fine-looking review.

See discovery_routes.py's product_detail() for how PDP reads the *results*
of moderation (rating_summary + the approved review list, images included)
- that's kept there since it's just more read queries alongside everything
else PDP already fetches, not a write path.
"""

import logging
import os
import uuid
from pathlib import Path

from flask import Blueprint, request, jsonify

from db import get_cursor

logger = logging.getLogger(__name__)

reviews = Blueprint('reviews', __name__, url_prefix='/api')

VALID_STATUSES = {"submitted", "approved", "rejected"}
VALID_REJECTION_REASONS = {
    "profanity", "not_relevant", "needs_human_review", "other", "spam", "personal_info",
    "hate_speech", "image_policy",
}

REJECTION_REASON_LABELS = {
    "profanity": "Profanity or abusive language",
    "not_relevant": "Not relevant to this product (delivery/other product issue)",
    "needs_human_review": "Needs further human review",
    "spam": "Spam / fake or incentivized review",
    "personal_info": "Contains personal or contact information",
    "other": "Other",
    # Added for AI Moderation (see AI_Moderation_PRD.docx Section 8) - both
    # previously had no code of their own; hate speech fell under
    # 'profanity' and image issues had to be filed as 'other'.
    "hate_speech": "Hate speech or discrimination",
    "image_policy": "Photo doesn't meet our image guidelines",
}

# Product decision: up to 5 photos per review, 5MB COMBINED (not per-image) -
# tight enough to keep backend/static/review_images/ small, generous enough
# for a handful of compressed phone photos.
MAX_IMAGES = 5
MAX_TOTAL_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# backend/static/review_images - same static folder Flask already serves
# product photos from (see app.py's static_folder='static'), just a
# dedicated subfolder so review uploads don't mix with the catalog's own
# image assets.
REVIEW_IMAGES_DIR = Path(__file__).resolve().parent.parent / "static" / "review_images"


REVIEW_ROW_COLUMNS = """id, product_id, persona_id, rating, review_text, status,
                         rejection_reason, rejection_note, moderated_at, created_at,
                         ai_decision, ai_rejection_reason, ai_note, ai_confidence,
                         ai_agent_trace, ai_moderated_at, moderator_agreed"""


def _row_to_review(row):
    """Accepts the full REVIEW_ROW_COLUMNS-shaped row (17 columns) - every
    query in this file and in moderation_routes.py selects that same set,
    in that same order, so this is the one place row-shape lives."""
    (review_id, product_id, persona_id, rating, review_text, status,
     rejection_reason, rejection_note, moderated_at, created_at,
     ai_decision, ai_rejection_reason, ai_note, ai_confidence,
     ai_agent_trace, ai_moderated_at, moderator_agreed) = row
    return {
        "id": review_id,
        "product_id": product_id,
        "persona_id": persona_id,
        "rating": rating,
        "review_text": review_text,
        "status": status,
        "rejection_reason": rejection_reason,
        "rejection_reason_label": REJECTION_REASON_LABELS.get(rejection_reason),
        "rejection_note": rejection_note,
        "moderated_at": moderated_at.isoformat() if moderated_at else None,
        "created_at": created_at.isoformat() if created_at else None,
        # AI Moderation (see moderation_routes.py) - ai_decision is None
        # until a moderator runs "Run AI Moderation" for this review.
        "ai_decision": ai_decision,
        "ai_rejection_reason": ai_rejection_reason,
        "ai_rejection_reason_label": REJECTION_REASON_LABELS.get(ai_rejection_reason),
        "ai_note": ai_note,
        "ai_confidence": float(ai_confidence) if ai_confidence is not None else None,
        "ai_agent_trace": ai_agent_trace,
        "ai_moderated_at": ai_moderated_at.isoformat() if ai_moderated_at else None,
        "moderator_agreed": moderator_agreed,
    }


def _fetch_images(cur, review_ids):
    """review_id -> [{"id", "image_url"}, ...] ordered by position, for
    every review_id in the given list. One query for the whole batch
    (list endpoints call this once, not per-row)."""
    if not review_ids:
        return {}
    cur.execute("""
        SELECT id, review_id, image_url
        FROM review_images
        WHERE review_id = ANY(%s)
        ORDER BY review_id, position ASC
    """, (list(review_ids),))
    by_review = {}
    for image_id, review_id, image_url in cur.fetchall():
        by_review.setdefault(review_id, []).append({"id": image_id, "image_url": image_url})
    return by_review


def _replace_review_images(cur, review_id, files):
    """Deletes this review's existing image rows + files, then saves the
    newly uploaded set (which may be empty - resubmitting with no photos
    attached clears any old ones, same "overwrite, don't append" model
    submit_review() already uses for review_text). Returns the new list
    of {"id", "image_url"}.
    """
    cur.execute("SELECT image_url FROM review_images WHERE review_id = %s", (review_id,))
    old_urls = [r[0] for r in cur.fetchall()]
    cur.execute("DELETE FROM review_images WHERE review_id = %s", (review_id,))

    review_dir = REVIEW_IMAGES_DIR / review_id
    for old_url in old_urls:
        old_path = REVIEW_IMAGES_DIR.parent.parent / old_url.lstrip("/")
        try:
            if old_path.exists():
                old_path.unlink()
        except OSError:
            pass  # best-effort cleanup - a stray file on disk isn't worth failing the request over

    saved = []
    if files:
        review_dir.mkdir(parents=True, exist_ok=True)
        for position, f in enumerate(files):
            f.stream.seek(0, os.SEEK_END)
            file_size = f.stream.tell()
            f.stream.seek(0)

            ext = Path(f.filename or "").suffix.lower()
            filename = f"{uuid.uuid4().hex}{ext}"
            f.save(review_dir / filename)
            image_url = f"/static/review_images/{review_id}/{filename}"
            image_id = "IMG-" + uuid.uuid4().hex[:10].upper()
            cur.execute(
                "INSERT INTO review_images (id, review_id, image_url, file_size_bytes, position) "
                "VALUES (%s, %s, %s, %s, %s)",
                (image_id, review_id, image_url, file_size, position),
            )
            saved.append({"id": image_id, "image_url": image_url})
    return saved


def _validate_images(files):
    """Returns an error string, or None if `files` is a valid (possibly
    empty) set of photos to attach. Checked before anything touches disk
    or the database."""
    if len(files) > MAX_IMAGES:
        return f"You can attach up to {MAX_IMAGES} photos."

    total_bytes = 0
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            return f"'{f.filename}' isn't a supported image type."
        f.stream.seek(0, os.SEEK_END)
        total_bytes += f.stream.tell()
        f.stream.seek(0)

    if total_bytes > MAX_TOTAL_IMAGE_BYTES:
        return "Photos must be 5MB or less combined."

    return None


@reviews.route('/products/<product_id>/reviews', methods=['POST'])
def submit_review(product_id):
    """
    Accepts multipart/form-data (not JSON) so a photo upload can ride
    along in the same request: persona_id / rating / review_text as form
    fields, photos as repeated 'images' file parts. Works the same with
    zero images attached - the frontend always posts FormData here now,
    review or no review, photos or no photos.
    """
    persona_id = (request.form.get('persona_id') or '').strip()
    review_text = (request.form.get('review_text') or '').strip() or None
    rating = request.form.get('rating')
    files = [f for f in request.files.getlist('images') if f and f.filename]

    if not persona_id:
        return jsonify({"error": "persona_id is required"}), 400

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return jsonify({"error": "rating must be a number from 1 to 5"}), 400
    if rating < 1 or rating > 5:
        return jsonify({"error": "rating must be between 1 and 5"}), 400

    # Mirrors the frontend's own gate (see ProductDetailPage's review form) -
    # enforced here too so this can never be bypassed by calling the API
    # directly. A low rating always needs an explanation.
    if rating <= 3 and not review_text:
        return jsonify({
            "error": "Please tell us why - a reason is required for a rating of 3 stars or below."
        }), 400

    image_error = _validate_images(files)
    if image_error:
        return jsonify({"error": image_error}), 400

    # Nothing to moderate for a pure rating (no text); a review with text
    # always starts in the queue, regardless of how high the rating is.
    status = "approved" if review_text is None else "submitted"

    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1 FROM products WHERE id = %s AND is_active = true", (product_id,))
            if not cur.fetchone():
                return jsonify({"error": "Product not found."}), 404
    except Exception as e:
        logger.error("Failed to look up product=%r for review: %s", product_id, e)
        return jsonify({"error": "Could not submit review."}), 500

    review_id = "REV-" + uuid.uuid4().hex[:10].upper()

    try:
        with get_cursor(commit=True) as cur:
            cur.execute(f"""
                INSERT INTO product_reviews
                    (id, product_id, persona_id, rating, review_text, status,
                     rejection_reason, rejection_note, moderated_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NULL, NULL, NULL, CURRENT_TIMESTAMP)
                ON CONFLICT (product_id, persona_id) DO UPDATE SET
                    rating = EXCLUDED.rating,
                    review_text = EXCLUDED.review_text,
                    status = EXCLUDED.status,
                    rejection_reason = NULL,
                    rejection_note = NULL,
                    moderated_at = NULL,
                    -- Content changed (new/edited rating or text) - any
                    -- previous AI moderation opinion is stale, and so is
                    -- whatever moderator_agreed said about the old content.
                    ai_decision = NULL,
                    ai_rejection_reason = NULL,
                    ai_note = NULL,
                    ai_confidence = NULL,
                    ai_agent_trace = NULL,
                    ai_moderated_at = NULL,
                    moderator_agreed = NULL,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING {REVIEW_ROW_COLUMNS}
            """, (review_id, product_id, persona_id, rating, review_text, status))
            row = cur.fetchone()
            actual_review_id = row[0]  # the pre-existing id on an upsert-update, not the freshly generated one
            images = _replace_review_images(cur, actual_review_id, files)
    except Exception as e:
        logger.error("Failed to submit review product=%r persona=%r: %s", product_id, persona_id, e)
        return jsonify({"error": "Could not submit review."}), 500

    result = _row_to_review(row)
    result["images"] = images
    return jsonify({"review": result}), 201


@reviews.route('/admin/reviews', methods=['GET'])
def list_reviews_for_moderation():
    """
    Review Moderation panel's list - filterable by status (defaults to
    'submitted', the actual moderation queue) with product name/image
    joined in so a moderator has context without a second lookup.
    """
    status = (request.args.get('status') or 'submitted').strip().lower()
    if status != 'all' and status not in VALID_STATUSES:
        return jsonify({"error": "status must be one of: all, " + ", ".join(sorted(VALID_STATUSES))}), 400

    sql = f"""
        SELECT r.id, r.product_id, r.persona_id, r.rating, r.review_text, r.status,
               r.rejection_reason, r.rejection_note, r.moderated_at, r.created_at,
               r.ai_decision, r.ai_rejection_reason, r.ai_note, r.ai_confidence,
               r.ai_agent_trace, r.ai_moderated_at, r.moderator_agreed,
               p.name, p.image_url
        FROM product_reviews r
        JOIN products p ON p.id = r.product_id
    """
    params = ()
    if status != 'all':
        sql += " WHERE r.status = %s"
        params = (status,)
    sql += " ORDER BY r.created_at DESC"

    try:
        with get_cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            images_by_review = _fetch_images(cur, [r[0] for r in rows])
    except Exception as e:
        logger.error("Failed to list reviews for moderation (status=%r): %s", status, e)
        return jsonify({
            "error": "Could not load reviews. Has ADD_AI_MODERATION_COLUMNS.py --apply been run?"
        }), 500

    reviews_out = []
    for r in rows:
        base = _row_to_review(r[:17])
        base["product_name"] = r[17]
        base["product_image_url"] = r[18]
        base["images"] = images_by_review.get(r[0], [])
        reviews_out.append(base)

    return jsonify({"reviews": reviews_out}), 200


@reviews.route('/admin/reviews/<review_id>/approve', methods=['POST'])
def approve_review(review_id):
    """
    Manual Approve - this is the "Override" action once AI Moderation has
    run (see moderation_routes.py's accept-ai for the one-click "Accept"
    path). moderator_agreed is computed here regardless of whether the
    moderator actually clicked Accept or manually approved anyway: NULL
    if AI moderation hasn't run yet for this review, true if the AI's
    call was also 'approved', false otherwise.
    """
    try:
        with get_cursor(commit=True) as cur:
            cur.execute(f"""
                UPDATE product_reviews
                SET status = 'approved', rejection_reason = NULL, rejection_note = NULL,
                    moderated_at = CURRENT_TIMESTAMP,
                    moderator_agreed = CASE WHEN ai_decision IS NULL THEN NULL
                                             ELSE (ai_decision = 'approved') END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING {REVIEW_ROW_COLUMNS}
            """, (review_id,))
            row = cur.fetchone()
    except Exception as e:
        logger.error("Failed to approve review=%r: %s", review_id, e)
        return jsonify({"error": "Could not approve review."}), 500

    if not row:
        return jsonify({"error": "Review not found."}), 404

    return jsonify({"review": _row_to_review(row)}), 200


@reviews.route('/admin/reviews/<review_id>/reject', methods=['POST'])
def reject_review(review_id):
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()
    note = (data.get('note') or '').strip() or None

    if reason not in VALID_REJECTION_REASONS:
        return jsonify({
            "error": "reason must be one of: " + ", ".join(sorted(VALID_REJECTION_REASONS))
        }), 400

    # "Other" always needs an explanation - it's the escape hatch for
    # whatever the fixed reasons don't cleanly cover, so a bare,
    # unexplained "Other" rejection isn't allowed.
    if reason == "other" and not note:
        return jsonify({"error": "Please describe the reason when selecting Other."}), 400

    try:
        with get_cursor(commit=True) as cur:
            cur.execute(f"""
                UPDATE product_reviews
                SET status = 'rejected', rejection_reason = %s, rejection_note = %s,
                    moderated_at = CURRENT_TIMESTAMP,
                    moderator_agreed = CASE WHEN ai_decision IS NULL THEN NULL
                                             ELSE (ai_decision = 'rejected' AND ai_rejection_reason = %s) END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING {REVIEW_ROW_COLUMNS}
            """, (reason, note, reason, review_id))
            row = cur.fetchone()
    except Exception as e:
        logger.error("Failed to reject review=%r: %s", review_id, e)
        return jsonify({"error": "Could not reject review."}), 500

    if not row:
        return jsonify({"error": "Review not found."}), 404

    return jsonify({"review": _row_to_review(row)}), 200


@reviews.route('/admin/reviews/<review_id>/resubmit', methods=['POST'])
def resubmit_review(review_id):
    """
    Sends an already-Approved or already-Rejected review back to the
    'submitted' queue for a second look - the undo button for a
    moderation mistake. Clears the human decision (rejection_reason/
    rejection_note/moderated_at reset to NULL, moderator_agreed reset to
    NULL since there's no human decision to compare against anymore) -
    but deliberately LEAVES the ai_* columns alone. The AI's opinion
    didn't become wrong just because a human wants a second look at
    their own past decision; it's still shown, and re-running AI
    Moderation is a separate, explicit action if a fresh opinion is
    wanted. Note this is a MODERATION-side reset, distinct from a shopper
    resubmitting their own review (see submit_review()'s upsert, which
    DOES clear ai_* since the content itself changed) - either path can
    put the same row back into the queue.
    """
    try:
        with get_cursor(commit=True) as cur:
            cur.execute(f"""
                UPDATE product_reviews
                SET status = 'submitted', rejection_reason = NULL, rejection_note = NULL,
                    moderated_at = NULL, moderator_agreed = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING {REVIEW_ROW_COLUMNS}
            """, (review_id,))
            row = cur.fetchone()
    except Exception as e:
        logger.error("Failed to resubmit review=%r: %s", review_id, e)
        return jsonify({"error": "Could not send review back to moderation."}), 500

    if not row:
        return jsonify({"error": "Review not found."}), 404

    return jsonify({"review": _row_to_review(row)}), 200
