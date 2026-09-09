"""
DiscoverAI: Final Production Embeddings Generator V2
====================================================

TWO-STEP PROCESS:
1. Extract: Generate embeddings, save to JSON file
2. Insert: Load from file, insert to database

Usage:
    python FINAL_PRODUCTION_EMBEDDINGS_GENERATOR_V2.py extract
    python FINAL_PRODUCTION_EMBEDDINGS_GENERATOR_V2.py insert
"""

import os
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import json
import sys
import time

# Load environment
env_path = Path('.env')
if env_path.exists():
    load_dotenv(env_path)

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
NEON_CONNECTION_STRING = os.getenv('DATABASE_URL')

if not OPENAI_API_KEY or not NEON_CONNECTION_STRING:
    print("ERROR: Missing OPENAI_API_KEY or DATABASE_URL in .env")
    exit(1)

client = OpenAI(api_key=OPENAI_API_KEY)

# File to save embeddings
EMBEDDINGS_FILE = "embeddings_extracted.json"

print("Connecting to NEON...")
try:
    conn = psycopg2.connect(NEON_CONNECTION_STRING)
    cur = conn.cursor()
    print("OK: Database connected!")
except Exception as e:
    print(f"ERROR: {e}")
    exit(1)

# ==========================================
# FETCH ALL PRODUCTS WITH ATTRIBUTES
# ==========================================

def fetch_products_with_attributes():
    """Fetch active products that are still missing at least one embedding,
    with their category paths and attributes.

    NOTE: this used to have `LIMIT 497` (tuned for the original ~500-product
    catalog) and no embedding filter, which would silently truncate results
    and re-embed (and re-pay for) products that already had embeddings once
    the catalog grew past 497 rows. Both are fixed here: no limit, and only
    rows missing an embedding are fetched - safe to re-run any time new
    products are added.
    """
    print("\nFetching products with attributes...")

    try:
        cur.execute("""
            SELECT
                p.id,
                p.name,
                p.description,
                p.brand,
                p.price,
                c.path as category_path,
                pa.pack_size,
                pa.color,
                pa.size,
                pa.material,
                pa.fit_type,
                pa.organic,
                pa.storage_gb,
                pa.ram_gb,
                pa.processor,
                pa.display_size_inch,
                pa.connectivity_5g
            FROM products p
            LEFT JOIN categories c ON p.category = c.id
            LEFT JOIN product_attributes pa ON p.id = pa.product_id
            WHERE p.is_active = true
              AND (p.embedding_full IS NULL OR p.embedding_category IS NULL OR p.embedding_name IS NULL)
            ORDER BY p.id;
        """)

        products = cur.fetchall()
        print(f"OK: Found {len(products)} products needing embeddings")
        return products

    except Exception as e:
        print(f"ERROR: {e}")
        return []

# ==========================================
# BUILD EMBEDDING TEXT
# ==========================================

def build_embedding_texts(product_id, name, description, brand, price, category_path, 
                          pack_size, color, size, material, fit_type, organic, 
                          storage_gb, ram_gb, processor, display_size_inch, connectivity_5g):
    """Build text for embeddings"""
    
    # FULL embedding: everything
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
    
    # CATEGORY embedding: just category hierarchy
    category_text = category_path or "Unknown"
    
    # NAME embedding: just product name
    name_text = name or "Product"
    
    return {
        'full': full_text,
        'category': category_text,
        'name': name_text
    }

# ==========================================
# GENERATE EMBEDDINGS
# ==========================================

def generate_embeddings(text, embedding_type="full"):
    """Call OpenAI to generate embedding"""
    try:
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"\nERROR generating embedding: {e}")
        return None

# ==========================================
# MODE 1: EXTRACT EMBEDDINGS
# ==========================================

def mode_extract():
    """Extract embeddings and save to file"""
    print("\n" + "=" * 80)
    print("MODE 1: EXTRACT EMBEDDINGS (Generate & Save to File)")
    print("=" * 80)
    
    products = fetch_products_with_attributes()
    if not products:
        print("ERROR: No products found")
        return
    
    print("\nGENERATING EMBEDDINGS")
    print("=" * 80)
    
    all_embeddings = {}
    success_count = 0
    
    for idx, product in enumerate(products):
        product_id, name, description, brand, price, category_path, pack_size, color, size, material, fit_type, organic, storage_gb, ram_gb, processor, display_size_inch, connectivity_5g = product
        
        if (idx + 1) % 50 == 0:
            print(f"\n[{idx + 1}/{len(products)}] Generating embeddings...")
        
        print(f"  {name[:40]}...", end=" ", flush=True)
        
        # Build embedding texts
        texts = build_embedding_texts(
            product_id, name, description, brand, price, category_path,
            pack_size, color, size, material, fit_type, organic,
            storage_gb, ram_gb, processor, display_size_inch, connectivity_5g
        )
        
        # Generate embeddings
        embedding_full = generate_embeddings(texts['full'], 'full')
        embedding_category = generate_embeddings(texts['category'], 'category')
        embedding_name = generate_embeddings(texts['name'], 'name')
        
        if embedding_full and embedding_category and embedding_name:
            all_embeddings[product_id] = {
                'embedding_full': embedding_full,
                'embedding_category': embedding_category,
                'embedding_name': embedding_name
            }
            print("OK")
            success_count += 1
        else:
            print("FAIL")
        
        time.sleep(0.05)  # Rate limit
    
    # Save to file
    print("\n" + "=" * 80)
    print("SAVING EMBEDDINGS TO FILE")
    print("=" * 80)
    
    try:
        with open(EMBEDDINGS_FILE, 'w') as f:
            json.dump(all_embeddings, f)
        print(f"OK: Saved {len(all_embeddings)} products to {EMBEDDINGS_FILE}")
        print(f"\nNext step: python FINAL_PRODUCTION_EMBEDDINGS_GENERATOR_V2.py insert")
    except Exception as e:
        print(f"ERROR: {e}")

# ==========================================
# MODE 2: INSERT EMBEDDINGS FROM FILE
# ==========================================

def mode_insert():
    """Load embeddings from file and insert to database.

    Neon (especially on lower tiers) can drop an idle/long-lived connection
    mid-batch ("server closed the connection unexpectedly") - with 800+
    sequential UPDATE+commit round trips this is a real risk, not an edge
    case. Rather than crashing and losing progress, this reconnects and
    retries the current row a few times before giving up on it and moving
    on, so one dropped connection doesn't kill the whole run.
    """
    global conn, cur

    print("\n" + "=" * 80)
    print("MODE 2: INSERT EMBEDDINGS FROM FILE")
    print("=" * 80)

    # Check if file exists
    if not os.path.exists(EMBEDDINGS_FILE):
        print(f"ERROR: File not found: {EMBEDDINGS_FILE}")
        print(f"Run: python FINAL_PRODUCTION_EMBEDDINGS_GENERATOR_V2.py extract")
        return

    # Load from file
    print(f"\nLoading {EMBEDDINGS_FILE}...")
    try:
        with open(EMBEDDINGS_FILE, 'r') as f:
            all_embeddings = json.load(f)
        print(f"OK: Loaded {len(all_embeddings)} products")
    except Exception as e:
        print(f"ERROR: {e}")
        return

    # Insert into database
    print("\nINSERTING INTO DATABASE")
    print("=" * 80)

    success_count = 0
    failed_count = 0
    failed_ids = []
    MAX_RETRIES = 5

    query = """
        UPDATE products
        SET embedding = %s,
            embedding_full = %s,
            embedding_category = %s,
            embedding_name = %s
        WHERE id = %s
    """

    for idx, (product_id, embeddings) in enumerate(all_embeddings.items()):
        if (idx + 1) % 50 == 0:
            print(f"\n[{idx + 1}/{len(all_embeddings)}] Inserting...")

        print(f"  {product_id}...", end=" ", flush=True)

        params = (
            embeddings['embedding_full'],
            embeddings['embedding_full'],
            embeddings['embedding_category'],
            embeddings['embedding_name'],
            product_id
        )

        attempt = 0
        while True:
            attempt += 1
            try:
                cur.execute(query, params)
                conn.commit()
                print("OK" if attempt == 1 else f"OK (after reconnect, attempt {attempt})")
                success_count += 1
                break
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                # Connection dropped mid-batch - reconnect and retry this
                # same row rather than losing the rest of the run.
                try:
                    conn.close()
                except Exception:
                    pass
                if attempt > MAX_RETRIES:
                    print(f"FAIL (connection kept dropping): {str(e)[:60]}")
                    failed_count += 1
                    failed_ids.append(product_id)
                    break
                print(f"connection dropped, reconnecting (attempt {attempt}/{MAX_RETRIES})...", end=" ", flush=True)
                try:
                    conn = psycopg2.connect(NEON_CONNECTION_STRING)
                    cur = conn.cursor()
                except Exception as reconnect_error:
                    print(f"reconnect failed: {str(reconnect_error)[:60]}")
                    time.sleep(2)
                    continue
            except Exception as e:
                conn.rollback()
                print(f"FAIL: {str(e)[:40]}")
                failed_count += 1
                failed_ids.append(product_id)
                break
    
    # Summary
    print("\n" + "=" * 80)
    print("INSERTION COMPLETE!")
    print("=" * 80)
    print(f"Success: {success_count}")
    print(f"Failed: {failed_count}")
    if failed_ids:
        print(f"Failed product ids ({len(failed_ids)}): {failed_ids}")
        print("Re-run 'insert' again to retry just these - it's safe, already-set rows are just re-written.")

    # Verify
    print("\nVERIFICATION:")
    try:
        conn.rollback()
        
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(embedding_full) as with_full,
                COUNT(embedding_category) as with_category,
                COUNT(embedding_name) as with_name
            FROM products;
        """)
        
        total, with_full, with_category, with_name = cur.fetchone()
        print(f"   Total products: {total}")
        print(f"   With embedding_full: {with_full}")
        print(f"   With embedding_category: {with_category}")
        print(f"   With embedding_name: {with_name}")
    except Exception as e:
        print(f"   ERROR: {e}")

# ==========================================
# MAIN
# ==========================================

def main():
    if len(sys.argv) < 2:
        print("=" * 80)
        print("FINAL PRODUCTION EMBEDDINGS GENERATOR V2")
        print("=" * 80)
        print("\nUsage:")
        print("  python FINAL_PRODUCTION_EMBEDDINGS_GENERATOR_V2.py extract")
        print("  python FINAL_PRODUCTION_EMBEDDINGS_GENERATOR_V2.py insert")
        print("\nWorkflow:")
        print("  1. extract - Generate embeddings, save to file")
        print("  2. insert  - Load file, insert to database")
        return
    
    mode = sys.argv[1].lower()
    
    if mode == 'extract':
        mode_extract()
    elif mode == 'insert':
        mode_insert()
    else:
        print(f"ERROR: Unknown mode: {mode}")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
