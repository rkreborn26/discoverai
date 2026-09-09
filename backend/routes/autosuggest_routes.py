"""
DiscoverAI Backend: Auto Suggestion API
============================================

The as-you-type suggestion endpoint (see
requirements/auto_suggestion_ai_pm_plan.md, "Auto Suggestion - Third
Iteration"). Ranks precomputed, category-aware suggestion phrases
(category_suggestion_phrases, built offline by
GENERATE_CATEGORY_SUGGESTION_PHRASES.py) directly against the customer's
typed text - no live product-table joins, no facet decomposition/
recomposition.

This replaces an earlier design that recognized category/brand facets
independently via trigram matching, then reassembled them with one
generic formatting function. That approach broke in several ways found
through live testing - case sensitivity, word_similarity()'s directional
argument order (different shapes needed for "oil" -> "Cooking Oil & Ghee"
vs. "nandini milk" -> "Nandini"), one brand's whole set of pack-size/
variety combinations crowding out every other option, and - most
fundamentally - a query that didn't fuzzy-match ANY category or brand
falling through to an unfiltered scan of the ENTIRE catalog (jewelry,
electronics, clothing - anything). All of those were symptoms of
decomposing a query into generic facets and recombining them with logic
that didn't know Rice should read differently from Fragrances.

Precomputed phrases sidestep this: each phrase is already a complete,
natural suggestion string built with per-category domain knowledge (see
GENERATE_CATEGORY_SUGGESTION_PHRASES.py's recipes), so matching becomes a
single flat trigram ranking of "which precomputed phrases best fit what
was typed" - no fallback into unrelated categories is possible, because
a phrase from an unrelated category simply won't score well against the
typed text.

  GET /api/auto-suggest?q=<partial text>
"""

import logging

from flask import Blueprint, request, jsonify

from db import get_cursor

logger = logging.getLogger(__name__)

autosuggest = Blueprint('autosuggest', __name__, url_prefix='/api')

MIN_QUERY_LENGTH = 2
MAX_SUGGESTIONS = 8
# Phrases are natural multi-word strings (not single facet terms), so
# scores here behave more predictably than the old facet-vs-query
# matching did - still a floor to avoid surfacing near-nonsense matches
# when nothing typed is close to anything in the catalog.
MIN_PHRASE_SIMILARITY = 0.25


def _rank_phrases(cur, query_text):
    """Trigram-rank active phrases against query_text. GREATEST() of both
    argument orders is kept from the earlier design for the same reason:
    word_similarity(a, b) is directional (finds the best-matching
    continuous substring of b for a), and a short query against a longer
    phrase needs the opposite order from a longer query against a short
    phrase - neither fixed order handles both shapes."""
    cur.execute(
        """
        SELECT phrase_text,
               GREATEST(
                   word_similarity(lower(%s), lower(phrase_text)),
                   word_similarity(lower(phrase_text), lower(%s))
               ) AS sim
        FROM category_suggestion_phrases
        WHERE is_active = true
        ORDER BY sim DESC
        LIMIT %s
        """,
        (query_text, query_text, MAX_SUGGESTIONS),
    )
    return cur.fetchall()


@autosuggest.route('/auto-suggest', methods=['GET'])
def auto_suggest():
    query_text = request.args.get('q', '').strip()
    if len(query_text) < MIN_QUERY_LENGTH:
        return jsonify({"query": query_text, "suggestions": []}), 200

    try:
        with get_cursor() as cur:
            ranked = _rank_phrases(cur, query_text)
    except Exception as e:
        logger.error("Auto-suggest failed for query=%r: %s", query_text, e)
        return jsonify({"error": "Auto-suggest failed."}), 500

    suggestions = [
        phrase_text for phrase_text, sim in ranked
        if sim is not None and sim >= MIN_PHRASE_SIMILARITY
    ]

    return jsonify({"query": query_text, "suggestions": suggestions}), 200
