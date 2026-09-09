#!/usr/bin/env python3
"""
DiscoverAI: Auto Suggestion diagnostic
===========================================

Runs the exact same pipeline as GET /api/auto-suggest for a given query -
ranks precomputed category_suggestion_phrases against the typed text -
and prints the full ranked list (not just the top MAX_SUGGESTIONS) so you
can see what scored just below the cutoff too.

Usage:
    python TEST_AUTO_SUGGEST.py "rice"
    python TEST_AUTO_SUGGEST.py "basmati"
    python TEST_AUTO_SUGGEST.py "india gate rice"
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))


def main():
    if len(sys.argv) < 2:
        print('Usage: python TEST_AUTO_SUGGEST.py "<query text>"')
        sys.exit(1)
    query_text = sys.argv[1]

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)

    from routes import autosuggest_routes as asr

    conn = psycopg2.connect(database_url)
    cur = conn.cursor()

    print("Query: %r" % query_text)
    print("MIN_PHRASE_SIMILARITY = %s, MAX_SUGGESTIONS = %d" % (
        asr.MIN_PHRASE_SIMILARITY, asr.MAX_SUGGESTIONS
    ))

    cur.execute("SELECT COUNT(*) FROM category_suggestion_phrases WHERE is_active = true")
    total_active = cur.fetchone()[0]
    print("Active phrases in table: %d" % total_active)

    print("")
    print("=" * 70)
    print("Top 20 ranked phrases (regardless of threshold)")
    print("=" * 70)
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
        LIMIT 20
        """,
        (query_text, query_text),
    )
    top20 = cur.fetchall()
    for phrase_text, sim in top20:
        picked = sim is not None and sim >= asr.MIN_PHRASE_SIMILARITY
        flag = "  <- IN FINAL RESULT" if picked else ""
        print("    %-40r similarity=%s%s" % (phrase_text, sim, flag))

    print("")
    print("=" * 70)
    print("Actual endpoint result (top %d, threshold %s)" % (asr.MAX_SUGGESTIONS, asr.MIN_PHRASE_SIMILARITY))
    print("=" * 70)
    ranked = asr._rank_phrases(cur, query_text)
    suggestions = [
        phrase_text for phrase_text, sim in ranked
        if sim is not None and sim >= asr.MIN_PHRASE_SIMILARITY
    ]
    print("  FINAL: %d suggestions: %s" % (len(suggestions), suggestions))

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
