#!/usr/bin/env python3
"""
DiscoverAI: Popular Searches scoring job
============================================

Implements the algorithm from requirements/auto_suggestion_ai_pm_plan.md:

  1. Aggregate search_events over the last 7 days: search volume (count of
     'search' events), click_rate (product_click count / volume),
     cart_rate (add_to_cart count / volume) - per CANONICAL query, not raw
     query_text. Near-duplicate queries ("oil" / "cooking oil" / "edible
     oil") are merged via query_aliases (see CLUSTER_QUERIES.py) before
     aggregating, so their volume/clicks/carts combine instead of each
     one individually looking weaker than it really is. Any query_text
     with no alias row yet (clustering hasn't run for it) falls back to
     being its own canonical - same behavior as before clustering existed.
  2. Log-scale volume (ln(1+volume)) before normalizing, so one dominant
     query doesn't crush every other query's normalized score toward 0.
  3. Min-max normalize log_volume, click_rate, cart_rate each to 0-1
     across all eligible queries in this run.
  4. popularity_score = average of the 3 normalized values (1/3 weighting
     each).
  5. Eligibility: the 17 seed queries (resolved to their canonical, so two
     seeds that clustered together only count once) are always eligible.
     A non-seed canonical only becomes eligible once its combined 7-day
     volume reaches >=30 - protects against a one-off rare query with a
     tiny, noisy sample size jumping to the top.
  6. Writes the ranked result to popular_queries, keyed by canonical query.
     Seeds with zero recent activity stay in the table (rank continues,
     score 0) so the list never goes empty before real traffic exists.

Run CLUSTER_QUERIES.py first (or at least once) so query_aliases exists -
this script works fine without it too, just without deduplication.

Run this periodically (e.g. daily) once search_events has real data.
Safe to run any time - it's a full recompute, not an incremental update.

Usage:
    python COMPUTE_POPULAR_QUERIES.py            # dry run - prints the plan, writes nothing
    python COMPUTE_POPULAR_QUERIES.py --apply    # recomputes and writes popular_queries
"""

import math
import os
import sys

MIN_VOLUME_FOR_NON_SEED = 30
WINDOW_DAYS = 7


def normalize(values):
    """Min-max normalize a list of floats to 0-1. If every value is the
    same (max == min), returns 0.5 for all rather than dividing by zero."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


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

    # Which queries are marked as seeds, resolved to their canonical query -
    # if clustering merged two seeds together (e.g. "oil" + "cooking oil"),
    # they collapse to one seed entry here.
    cur.execute("SELECT query_text FROM popular_queries WHERE is_seed = true")
    raw_seed_queries = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT query_text, canonical_query FROM query_aliases")
    alias_map = {r[0]: r[1] for r in cur.fetchall()}

    seed_canonicals = {alias_map.get(q, q) for q in raw_seed_queries}
    print(f"Seed queries: {len(raw_seed_queries)} raw -> {len(seed_canonicals)} distinct canonicals "
          f"(after merging any that clustered together)")

    # Aggregate the last WINDOW_DAYS of events, grouped by canonical query
    # (falling back to the raw query_text itself if it has no alias yet).
    cur.execute(f"""
        SELECT
            COALESCE(qa.canonical_query, se.query_text) AS canonical_query,
            COUNT(*) FILTER (WHERE se.event_type = 'search') AS volume,
            COUNT(*) FILTER (WHERE se.event_type = 'product_click') AS clicks,
            COUNT(*) FILTER (WHERE se.event_type = 'add_to_cart') AS carts
        FROM search_events se
        LEFT JOIN query_aliases qa ON qa.query_text = se.query_text
        WHERE se.created_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
        GROUP BY COALESCE(qa.canonical_query, se.query_text)
    """)
    agg_rows = cur.fetchall()
    print(f"Distinct canonical queries with activity in the last {WINDOW_DAYS} days: {len(agg_rows)}")

    stats = {}
    for canonical_query, volume, clicks, carts in agg_rows:
        if volume == 0:
            continue  # no searches at all for this canonical - skip
        is_seed = canonical_query in seed_canonicals
        if not is_seed and volume < MIN_VOLUME_FOR_NON_SEED:
            continue  # not yet eligible - too small a sample to trust
        stats[canonical_query] = {
            "volume": volume,
            "click_rate": clicks / volume,
            "cart_rate": carts / volume,
            "is_seed": is_seed,
        }

    # Seeds with zero activity in the window still need to appear (as
    # fallback, score 0) so the list is never empty before real traffic.
    for canonical_query in seed_canonicals:
        if canonical_query not in stats:
            stats[canonical_query] = {"volume": 0, "click_rate": 0.0, "cart_rate": 0.0, "is_seed": True}

    if not stats:
        print("\nNothing to score (no seeds and no eligible activity) - aborting.")
        cur.close()
        conn.close()
        return

    query_texts = list(stats.keys())
    log_volumes = [math.log(1 + stats[q]["volume"]) for q in query_texts]
    click_rates = [stats[q]["click_rate"] for q in query_texts]
    cart_rates = [stats[q]["cart_rate"] for q in query_texts]

    norm_volume = normalize(log_volumes)
    norm_click = normalize(click_rates)
    norm_cart = normalize(cart_rates)

    scored = []
    for i, query_text in enumerate(query_texts):
        score = (norm_volume[i] + norm_click[i] + norm_cart[i]) / 3.0
        scored.append((query_text, stats[query_text], score))

    # Queries with zero real activity naturally score 0.5 from normalize()'s
    # all-equal fallback when everything is 0 - pin true zero-activity
    # entries to the bottom explicitly so a never-searched seed doesn't
    # outrank a genuinely active query.
    scored.sort(key=lambda row: (row[1]["volume"] > 0, row[2]), reverse=True)

    print(f"\n{len(scored)} canonical queries will be ranked:\n")
    for rank, (query_text, s, score) in enumerate(scored, start=1):
        seed_tag = "[seed]" if s["is_seed"] else "[real]"
        print(f"  {rank:3d}. {seed_tag} {query_text:20s} volume={s['volume']:4d} "
              f"click_rate={s['click_rate']:.3f} cart_rate={s['cart_rate']:.3f} score={score:.4f}")

    if not apply_changes:
        print("\n(dry run - nothing written. Re-run with --apply to commit.)")
        cur.close()
        conn.close()
        return

    for rank, (query_text, s, score) in enumerate(scored, start=1):
        cur.execute(
            """
            INSERT INTO popular_queries (query_text, search_volume, click_rate, cart_rate, popularity_score, is_seed, rank, computed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (query_text) DO UPDATE SET
                search_volume = EXCLUDED.search_volume,
                click_rate = EXCLUDED.click_rate,
                cart_rate = EXCLUDED.cart_rate,
                popularity_score = EXCLUDED.popularity_score,
                is_seed = popular_queries.is_seed OR EXCLUDED.is_seed,
                rank = EXCLUDED.rank,
                computed_at = CURRENT_TIMESTAMP
            """,
            (query_text, s["volume"], s["click_rate"], s["cart_rate"], score, s["is_seed"], rank),
        )

    # Any old popular_queries row for a raw seed query_text that just got
    # merged into a different canonical (e.g. "cooking oil" -> "oil") is
    # now redundant - remove it so the same underlying query doesn't show
    # up twice under two different labels.
    merged_away = [q for q in raw_seed_queries if alias_map.get(q, q) != q]
    if merged_away:
        cur.execute("DELETE FROM popular_queries WHERE query_text = ANY(%s)", (merged_away,))
        print(f"\nRemoved {len(merged_away)} stale row(s) for seeds merged into another canonical: {merged_away}")

    conn.commit()
    print(f"\nDone. Wrote {len(scored)} ranked queries to popular_queries.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
