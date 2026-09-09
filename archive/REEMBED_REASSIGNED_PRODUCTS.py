#!/usr/bin/env python3
"""
DiscoverAI: Re-embed products reassigned by a category split
==================================================================

Third step of the leaf-category split work. SPLIT_COMPOUND_CATEGORIES.py
moves products to a new, more specific leaf category (e.g. "Onions &
Shallots" -> "Onions") and appends every moved product to
data/exports/products_needing_reembedding.csv. That product's category
PATH is baked directly into its embedding_full text (see search.py's
_reconstruct_embedded_text and FINAL_PRODUCTION_EMBEDDINGS_GENERATOR.py's
build_embedding_texts) - so after a category change, its stored
embeddings are stale until this script re-generates them.

This does NOT use FINAL_PRODUCTION_EMBEDDINGS_GENERATOR.py's own
"products missing an embedding" query, on purpose - a reassigned
product already HAS embeddings (from before the move), just stale
ones, so it would never be picked up by a NULL-check. This script
instead re-embeds exactly the product ids listed in the CSV,
regardless of whether they currently have embeddings.

Embedding text formula is copied verbatim from
FINAL_PRODUCTION_EMBEDDINGS_GENERATOR.py's build_embedding_texts (and
matches search.py's _reconstruct_embedded_text, which is what the
Explain panel shows customers) - keeping this identical is what keeps
"why this result?" honest after a re-embed.

Usage:
    python REEMBED_REASSIGNED_PRODUCTS.py            # dry run - shows which products, calls no API, writes nothing
    python REEMBED_REASSIGNED_PRODUCTS.py --apply    # calls OpenAI + writes new embeddings
"""

import csv
import os
import sys
import time
from pathlib import Path

REEMBED_CSV = Path("data/exports/products_needing_reembedding.csv")
EMBEDDING_MODEL = "text-embedding-3-small"


def build_embedding_texts(name, description, brand, price, category_path,
                           pack_size, color, size, material, storage_gb, ram_gb, processor):
    """Identical formula to FINAL_PRODUCTION_EMBEDDINGS_GENERATOR.py's
    build_embedding_texts() / search.py's _reconstruct_embedded_text() -
    do not let this drift from those, or the Explain panel's "exact text
    that was embedded" claim stops being true."""
    full_text = f"{name} {description} {brand} {category_path} {price}"
    if pack_size:
        full_text += f" {pack_size}"
    if color:
        full_text += f" {color}"
    if size:
        full_text += f" {size}"
    if material:
        full_text += f" {material}"
    if storage_gb:
        full_text += f" {storage_gb}GB"
    if ram_gb:
        full_text += f" {ram_gb}GB RAM"
    if processor:
        full_text += f" {processor}"

    return {
        "full": full_text,
        "category": category_path or "Unknown",
        "name": name or "Product",
    }


def load_product_ids_from_csv():
    if not REEMBED_CSV.exists():
        print(f"ERROR: {REEMBED_CSV} not found.")
        print("Run SPLIT_COMPOUND_CATEGORIES.py --apply first - it writes this file.")
        sys.exit(1)

    ids = []
    seen = set()
    with open(REEMBED_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pid = row["product_id"]
            if pid not in seen:
                seen.add(pid)
                ids.append(pid)
    return ids


def main():
    apply_changes = "--apply" in sys.argv

    product_ids = load_product_ids_from_csv()
    if not product_ids:
        print(f"{REEMBED_CSV} has no rows - nothing to re-embed.")
        return
    print(f"Found {len(product_ids)} distinct product id(s) in {REEMBED_CSV}.\n")

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

    cur.execute("""
        SELECT p.id, p.name, p.description, p.brand, p.price, c.path AS category_path,
               pa.pack_size, pa.color, pa.size, pa.material, pa.storage_gb, pa.ram_gb, pa.processor
        FROM products p
        LEFT JOIN categories c ON p.category = c.id
        LEFT JOIN product_attributes pa ON pa.product_id = p.id
        WHERE p.id = ANY(%s)
    """, (product_ids,))
    rows = cur.fetchall()
    found_ids = {r[0] for r in rows}

    missing = [pid for pid in product_ids if pid not in found_ids]
    if missing:
        print(f"WARNING: {len(missing)} id(s) from the CSV no longer exist in products - skipping them:")
        print(f"  {missing[:20]}{' ...' if len(missing) > 20 else ''}\n")

    print(f"Will re-embed {len(rows)} product(s):")
    for r in rows[:20]:
        print(f"  {r[0]}  {r[1]!r}  (category: {r[5]!r})")
    if len(rows) > 20:
        print(f"  ... and {len(rows) - 20} more")

    if not apply_changes:
        print("\n(dry run - no API calls made, nothing written. Re-run with --apply to actually re-embed.)")
        cur.close()
        conn.close()
        return

    from openai import OpenAI
    client = OpenAI(api_key=openai_api_key)

    def embed(text):
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
        return response.data[0].embedding

    print("\nGenerating and writing new embeddings...\n")
    success, failed = 0, []
    for idx, row in enumerate(rows, start=1):
        (product_id, name, description, brand, price, category_path,
         pack_size, color, size, material, storage_gb, ram_gb, processor) = row

        texts = build_embedding_texts(
            name, description, brand, price, category_path,
            pack_size, color, size, material, storage_gb, ram_gb, processor,
        )
        print(f"  [{idx}/{len(rows)}] {name[:40]!r}...", end=" ", flush=True)

        try:
            embedding_full = embed(texts["full"])
            embedding_category = embed(texts["category"])
            embedding_name = embed(texts["name"])
        except Exception as e:
            print(f"FAIL (embedding API): {str(e)[:60]}")
            failed.append(product_id)
            continue

        try:
            cur.execute(
                """UPDATE products
                   SET embedding = %s, embedding_full = %s, embedding_category = %s,
                       embedding_name = %s, updated_at = CURRENT_TIMESTAMP
                   WHERE id = %s""",
                (embedding_full, embedding_full, embedding_category, embedding_name, product_id),
            )
            conn.commit()
            print("OK")
            success += 1
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            print(f"connection dropped ({str(e)[:40]}), reconnecting...", end=" ")
            try:
                conn.close()
            except Exception:
                pass
            conn = psycopg2.connect(database_url)
            cur = conn.cursor()
            try:
                cur.execute(
                    """UPDATE products
                       SET embedding = %s, embedding_full = %s, embedding_category = %s,
                           embedding_name = %s, updated_at = CURRENT_TIMESTAMP
                       WHERE id = %s""",
                    (embedding_full, embedding_full, embedding_category, embedding_name, product_id),
                )
                conn.commit()
                print("OK (after reconnect)")
                success += 1
            except Exception as e2:
                print(f"FAIL (after reconnect): {str(e2)[:60]}")
                failed.append(product_id)
        except Exception as e:
            conn.rollback()
            print(f"FAIL: {str(e)[:60]}")
            failed.append(product_id)

        time.sleep(0.05)  # gentle rate limit, matches FINAL_PRODUCTION_EMBEDDINGS_GENERATOR.py

    print(f"\nDone. Re-embedded {success}/{len(rows)}.")
    if failed:
        print(f"Failed ({len(failed)}): {failed}")
        print("Re-run this script (--apply) to retry - already-succeeded rows are just re-written, which is fine.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
