#!/usr/bin/env python3
"""
DiscoverAI: Semantic query clustering
==========================================

Groups near-duplicate search queries ("cooking oil", "oil", "edible oil")
under one canonical query, so COMPUTE_POPULAR_QUERIES.py aggregates their
volume/clicks/carts together instead of scoring them as 3 separate,
individually-weaker entries.

Algorithm:
  1. Collect every distinct query_text worth considering: the 17 seed
     queries (always) + every query_text ever logged in search_events.
  2. Embed each one (text-embedding-3-small, same model used for products),
     caching in query_embeddings so re-running this doesn't re-pay for
     queries already embedded.
  3. Greedy clustering: process seeds first (so the curated, recognizable
     labels become canonicals preferentially), then the rest ordered by
     descending search volume (higher-signal queries become canonicals
     over rare/noisy ones). For each query, compare its embedding to every
     canonical chosen so far; if the best cosine similarity clears
     SIMILARITY_THRESHOLD, alias to that canonical; otherwise it becomes a
     new canonical itself.
  4. Write the query_text -> canonical_query mapping to query_aliases.

SIMILARITY_THRESHOLD is a starting point (0.85), not a validated constant -
short, ambiguous queries ("oil" alone could mean many things) make this
genuinely hard to get perfect. The dry run prints every proposed merge so
it can be sanity-checked by eye before committing, rather than trusting
the threshold blindly.

Usage:
    python CLUSTER_QUERIES.py            # dry run - shows proposed clusters, writes nothing
    python CLUSTER_QUERIES.py --apply    # embeds any new queries + commits query_aliases
"""

import json
import os
import sys

SIMILARITY_THRESHOLD = 0.85
EMBEDDING_MODEL = "text-embedding-3-small"


def cosine_similarity(a, b):
    import numpy as np
    a = np.array(a)
    b = np.array(b)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def main():
    apply_changes = "--apply" in sys.argv

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not database_url:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)
    if not openai_api_key:
        print("ERROR: OPENAI_API_KEY not set.")
        sys.exit(1)

    print("Connecting to Neon...")
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    print("Connected.\n")

    # --- 1. Collect every distinct query_text worth considering ---
    cur.execute("SELECT query_text FROM popular_queries WHERE is_seed = true")
    seed_queries = [r[0] for r in cur.fetchall()]

    cur.execute("""
        SELECT query_text, COUNT(*) AS volume
        FROM search_events
        WHERE event_type = 'search'
        GROUP BY query_text
    """)
    volume_by_query = {r[0]: r[1] for r in cur.fetchall()}

    all_queries = set(seed_queries) | set(volume_by_query.keys())
    print(f"{len(seed_queries)} seed queries, {len(volume_by_query)} distinct queries with search activity, "
          f"{len(all_queries)} total to consider.\n")

    if not all_queries:
        print("Nothing to cluster.")
        cur.close()
        conn.close()
        return

    # --- 2. Embed anything not already cached ---
    cur.execute("SELECT query_text, embedding FROM query_embeddings WHERE query_text = ANY(%s)", (list(all_queries),))
    cached = {}
    for query_text, embedding_str in cur.fetchall():
        cached[query_text] = json.loads(embedding_str) if isinstance(embedding_str, str) else embedding_str

    missing = [q for q in all_queries if q not in cached]
    print(f"{len(cached)} already embedded (cached), {len(missing)} need embedding.")

    if missing:
        from openai import OpenAI
        client = OpenAI(api_key=openai_api_key)
        for i, query_text in enumerate(missing, start=1):
            print(f"  [{i}/{len(missing)}] embedding {query_text!r}...", end=" ", flush=True)
            try:
                response = client.embeddings.create(model=EMBEDDING_MODEL, input=query_text)
                embedding = response.data[0].embedding
                cached[query_text] = embedding
                if apply_changes:
                    cur.execute(
                        """
                        INSERT INTO query_embeddings (query_text, embedding)
                        VALUES (%s, %s::vector)
                        ON CONFLICT (query_text) DO UPDATE SET embedding = EXCLUDED.embedding
                        """,
                        (query_text, json.dumps(embedding)),
                    )
                print("OK")
            except Exception as e:
                print(f"FAILED: {e}")
        if apply_changes:
            conn.commit()

    # --- 3. Greedy clustering ---
    # Seeds first (preferred canonicals), then by descending volume.
    def sort_key(q):
        is_seed = q in seed_queries
        return (0 if is_seed else 1, -volume_by_query.get(q, 0))

    ordered_queries = sorted(all_queries, key=sort_key)

    canonicals = []  # list of (query_text, embedding)
    alias_of = {}     # query_text -> (canonical_query, similarity)

    for query_text in ordered_queries:
        embedding = cached.get(query_text)
        if embedding is None:
            continue  # embedding failed - leave unclustered, handled downstream as self-canonical

        best_canonical, best_similarity = None, -1.0
        for canon_text, canon_embedding in canonicals:
            sim = cosine_similarity(embedding, canon_embedding)
            if sim > best_similarity:
                best_canonical, best_similarity = canon_text, sim

        if best_canonical is not None and best_similarity >= SIMILARITY_THRESHOLD:
            alias_of[query_text] = (best_canonical, best_similarity)
        else:
            canonicals.append((query_text, embedding))
            alias_of[query_text] = (query_text, 1.0)

    # --- Report ---
    clusters = {}
    for query_text, (canonical_query, similarity) in alias_of.items():
        clusters.setdefault(canonical_query, []).append((query_text, similarity))

    merged_clusters = {c: members for c, members in clusters.items() if len(members) > 1}
    print(f"\n{len(canonicals)} canonical queries after clustering ({len(merged_clusters)} have merges):\n")
    for canonical_query, members in sorted(merged_clusters.items()):
        print(f"  '{canonical_query}':")
        for query_text, similarity in sorted(members, key=lambda m: -m[1]):
            if query_text != canonical_query:
                print(f"      <- '{query_text}' (similarity {similarity:.4f})")

    if not merged_clusters:
        print("  (no merges proposed at threshold {:.2f} - every query stood alone)".format(SIMILARITY_THRESHOLD))

    if not apply_changes:
        print("\n(dry run - query_aliases not written. Re-run with --apply to commit.)")
        cur.close()
        conn.close()
        return

    for query_text, (canonical_query, similarity) in alias_of.items():
        cur.execute(
            """
            INSERT INTO query_aliases (query_text, canonical_query, similarity)
            VALUES (%s, %s, %s)
            ON CONFLICT (query_text) DO UPDATE SET
                canonical_query = EXCLUDED.canonical_query,
                similarity = EXCLUDED.similarity,
                computed_at = CURRENT_TIMESTAMP
            """,
            (query_text, canonical_query, similarity),
        )
    conn.commit()
    print(f"\nDone. Wrote {len(alias_of)} query_aliases rows.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
