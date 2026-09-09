"""
DiscoverAI Backend: API Routes
================================

The HTTP layer. Each route just parses the request, calls into search.py
(which knows nothing about HTTP), and returns JSON. Keeping this thin is
what makes search.py reusable by something other than this web frontend
later (e.g. a mobile app hitting these same URLs).
"""

import logging
import traceback

from flask import Blueprint, request, jsonify

from search import search_products, SearchError
from db import health_check

logger = logging.getLogger(__name__)

api = Blueprint('api', __name__, url_prefix='/api')


@api.route('/health', methods=['GET'])
def health():
    """Basic liveness + DB connectivity check."""
    db_ok = health_check()
    status_code = 200 if db_ok else 503
    return jsonify({
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "unreachable",
    }), status_code


@api.route('/search', methods=['GET'])
def search():
    """
    GET /api/search?q=<query>&limit=<n>&type=<embedding_column>

    q      - required, the search text
    limit  - optional, defaults to 10, max 50
    type   - optional, one of embedding / embedding_full / embedding_category /
             embedding_name, defaults to embedding_full
    """
    query_text = request.args.get('q', '').strip()
    limit = request.args.get('limit', 10)
    embedding_type = request.args.get('type', 'embedding_full')

    if not query_text:
        return jsonify({"error": "Missing required query parameter 'q'."}), 400

    try:
        results = search_products(query_text, limit=limit, embedding_type=embedding_type)
    except SearchError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        # Unexpected failure (OpenAI down, DB down, etc.) - don't leak internals
        # in the response, but DO log the real traceback so it's visible in
        # the console instead of silently vanishing behind a generic 500.
        logger.error("Search failed for query=%r type=%r: %s", query_text, embedding_type, e)
        traceback.print_exc()
        return jsonify({"error": "Search failed. Please try again in a moment."}), 500

    return jsonify({
        "query": query_text,
        "type": embedding_type,
        "count": len(results),
        "results": results,
    }), 200
