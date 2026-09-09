"""
DiscoverAI Phase 2: Embeddings & Semantic Search Setup
======================================================

This script:
1. Generates embeddings for all 500 products
2. Stores embeddings in NEON database
3. Enables semantic search functionality
4. Tests search with sample queries

Author: Ra Ko
Date: June 20, 2026
"""

import os
import json
import psycopg2
from psycopg2.extras import execute_values
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import time

# Load environment variables from .env file
env_path = Path('.env')
if env_path.exists():
    load_dotenv(env_path)
else:
    print("⚠️  .env file not found in current directory")

# ==========================================
# CONFIGURATION
# ==========================================

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
NEON_CONNECTION_STRING = os.getenv('DATABASE_URL')

# Debug: Check if variables loaded
if not OPENAI_API_KEY:
    print("❌ ERROR: OPENAI_API_KEY not found in .env")
    print(f"   Current directory: {os.getcwd()}")
    exit(1)

if not NEON_CONNECTION_STRING:
    print("❌ ERROR: DATABASE_URL not found in .env")
    print(f"   Current directory: {os.getcwd()}")
    exit(1)

EMBEDDING_MODEL = 'text-embedding-3-small'
EMBEDDING_DIMENSION = 1536
BATCH_SIZE = 50  # OpenAI allows up to 2000 per request, use 50 for safety

# ==========================================
# INITIALIZE CLIENTS
# ==========================================

print("🚀 Initializing OpenAI Client...")
client = OpenAI(api_key=OPENAI_API_KEY)

print("📊 Connecting to NEON Database...")
try:
    conn = psycopg2.connect(NEON_CONNECTION_STRING)
    cur = conn.cursor()
    print("✅ Database connected!")
except Exception as e:
    print(f"❌ Database connection failed: {e}")
    exit(1)

# ==========================================
# STEP 1: ENABLE PGVECTOR EXTENSION
# ==========================================

def enable_pgvector():
    """Enable pgvector extension in PostgreSQL"""
    print("\n📦 Checking pgvector extension...")
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.commit()
        print("✅ pgvector extension enabled!")
    except Exception as e:
        if "already exists" in str(e):
            print("✅ pgvector already enabled")
            conn.commit()
        else:
            print(f"⚠️  pgvector warning: {e}")

# ==========================================
# STEP 2: CREATE EMBEDDING COLUMN
# ==========================================

def create_embedding_column():
    """Add embedding column to products table"""
    print("\n🔧 Setting up embedding column...")
    try:
        cur.execute("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS embedding vector(1536);
        """)
        conn.commit()
        print("✅ Embedding column created/verified!")
    except Exception as e:
        if "already exists" in str(e):
            print("✅ Embedding column already exists")
            conn.commit()
        else:
            print(f"⚠️  Column setup warning: {e}")

# ==========================================
# STEP 3: CREATE INDEX FOR FAST SEARCH
# ==========================================

def create_embedding_index():
    """Create index for faster semantic search"""
    print("\n⚡ Creating embedding index...")
    try:
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_products_embedding
            ON products USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        """)
        conn.commit()
        print("✅ Embedding index created!")
    except Exception as e:
        if "already exists" in str(e):
            print("✅ Index already exists")
            conn.commit()
        else:
            print(f"⚠️  Index warning: {e}")

# ==========================================
# STEP 4: FETCH PRODUCTS
# ==========================================

def fetch_products_without_embeddings():
    """Get all products that don't have embeddings yet"""
    print("\n📥 Fetching products without embeddings...")
    try:
        cur.execute("""
            SELECT id, name, description, category, brand, price
            FROM products
            WHERE embedding IS NULL
            ORDER BY CAST(id AS INTEGER)
            LIMIT 500;
        """)
        products = cur.fetchall()
        print(f"✅ Found {len(products)} products to process")
        return products
    except Exception as e:
        print(f"❌ Error fetching products: {e}")
        conn.rollback()  # Reset transaction
        return []

# ==========================================
# STEP 5: GENERATE EMBEDDINGS
# ==========================================

def generate_embeddings(products):
    """
    Generate embeddings for products using OpenAI API

    Input text format: "name | description | brand | category"
    This gives context about what the product is, what it does, and its category
    """
    print(f"\n🤖 Generating embeddings for {len(products)} products...")
    print(f"   Using model: {EMBEDDING_MODEL} ({EMBEDDING_DIMENSION} dimensions)")

    embeddings_data = []
    total_cost = 0

    # Process in batches
    for batch_start in range(0, len(products), BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, len(products))
        batch = products[batch_start:batch_end]

        # Prepare texts for embedding
        texts = []
        for product in batch:
            product_id, name, description, category, brand, price = product

            # Combine fields for rich embedding context
            embedding_text = f"{name} | {description} | {brand or 'Generic'} | {category} | ₹{price}"
            texts.append(embedding_text)

        try:
            # Call OpenAI Embeddings API
            print(f"   Processing batch {batch_start//BATCH_SIZE + 1}...", end=" ", flush=True)
            response = client.embeddings.create(
                input=texts,
                model=EMBEDDING_MODEL
            )

            # Extract embeddings and pair with products
            for i, item in enumerate(response.data):
                product_id = batch[i][0]
                embedding = item.embedding
                embeddings_data.append((product_id, embedding))

            # Cost calculation: $0.00002 per 1K tokens for text-embedding-3-small
            # Average product text: ~100 tokens
            batch_cost = len(texts) * 100 * 0.00002 / 1000
            total_cost += batch_cost

            print(f"✅ ({len(embeddings_data)}/{len(products)} total)")

            # Rate limiting (OpenAI free tier limit)
            time.sleep(0.5)

        except Exception as e:
            print(f"❌ Error generating embeddings: {e}")
            return None, total_cost

    print(f"\n✅ Embeddings generated!")
    print(f"💰 Estimated cost: ${total_cost:.4f}")

    return embeddings_data, total_cost

# ==========================================
# STEP 6: STORE EMBEDDINGS IN DATABASE
# ==========================================

def store_embeddings(embeddings_data):
    """Store generated embeddings in NEON database"""
    print(f"\n💾 Storing {len(embeddings_data)} embeddings in NEON...")

    if not embeddings_data:
        print("❌ No embeddings to store")
        return False

    try:
        # Prepare data for batch insert
        insert_data = [
            (product_id, json.dumps(embedding))
            for product_id, embedding in embeddings_data
        ]

        # Batch update embeddings
        update_query = """
            UPDATE products
            SET embedding = %s::vector
            WHERE id = %s;
        """

        for product_id, embedding_json in insert_data:
            cur.execute(
                "UPDATE products SET embedding = %s::vector WHERE id = %s",
                (embedding_json, product_id)
            )

        conn.commit()
        print(f"✅ Successfully stored {len(embeddings_data)} embeddings!")
        return True

    except Exception as e:
        print(f"❌ Error storing embeddings: {e}")
        conn.rollback()
        return False

# ==========================================
# STEP 7: TEST SEMANTIC SEARCH
# ==========================================

def semantic_search(query, top_k=5):
    """
    Perform semantic search using embeddings

    Process:
    1. Generate embedding for query
    2. Find products with similar embeddings (cosine similarity)
    3. Return top-k most similar products
    """
    print(f"\n🔍 Semantic Search Test: '{query}'")

    try:
        # Generate embedding for query
        query_response = client.embeddings.create(
            input=query,
            model=EMBEDDING_MODEL
        )
        query_embedding = query_response.data[0].embedding

        # Find similar products using cosine similarity
        cur.execute(f"""
            SELECT
                id, name, category, brand, price,
                description,
                1 - (embedding <=> %s::vector) as similarity_score
            FROM products
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT {top_k};
        """, (json.dumps(query_embedding), json.dumps(query_embedding)))

        results = cur.fetchall()

        print(f"\n   Top {top_k} Results:")
        print(f"   {'─' * 80}")

        for i, result in enumerate(results, 1):
            product_id, name, category, brand, price, description, similarity = result
            print(f"\n   {i}. {name}")
            print(f"      Brand: {brand or 'Generic'}")
            print(f"      Price: ₹{price}")
            print(f"      Category: {category}")
            print(f"      Similarity: {similarity:.2%}")
            print(f"      Description: {description[:60]}...")

        return results

    except Exception as e:
        print(f"❌ Search error: {e}")
        return []

# ==========================================
# STEP 8: VERIFY EMBEDDINGS
# ==========================================

def verify_embeddings():
    """Check embedding statistics"""
    print(f"\n📊 Embedding Statistics:")

    try:
        # Rollback any failed transaction first
        conn.rollback()

        cur.execute("""
            SELECT
                COUNT(*) as total_products,
                COUNT(CASE WHEN embedding IS NOT NULL THEN 1 END) as with_embeddings,
                COUNT(CASE WHEN embedding IS NULL THEN 1 END) as without_embeddings
            FROM products;
        """)

        total, with_emb, without_emb = cur.fetchone()

        print(f"   Total products: {total}")
        print(f"   ✅ With embeddings: {with_emb}")
        print(f"   ❌ Without embeddings: {without_emb}")

        if with_emb == total:
            print(f"\n   🎉 ALL PRODUCTS HAVE EMBEDDINGS!")

        return with_emb, without_emb

    except Exception as e:
        print(f"❌ Verification error: {e}")
        conn.rollback()
        return None, None

# ==========================================
# MAIN EXECUTION
# ==========================================

def main():
    """Main execution flow"""

    print("="*80)
    print("🚀 DISCOVERAI PHASE 2: EMBEDDINGS SETUP")
    print("="*80)
    print(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"OpenAI Model: {EMBEDDING_MODEL}")
    print(f"Database: NEON PostgreSQL")
    print(f"Product Count Target: 500")
    print("="*80)

    # Step 1: Setup database
    enable_pgvector()
    create_embedding_column()
    create_embedding_index()

    # Step 2: Fetch products
    products = fetch_products_without_embeddings()
    if not products:
        print("\n✅ All products already have embeddings!")
        with_emb, without_emb = verify_embeddings()
        return

    # Step 3: Generate embeddings
    embeddings_data, cost = generate_embeddings(products)
    if embeddings_data is None:
        print("❌ Failed to generate embeddings")
        return

    # Step 4: Store embeddings
    if store_embeddings(embeddings_data):
        print("\n✅ Phase 2 Setup Complete!")
    else:
        print("\n❌ Failed to store embeddings")
        return

    # Step 5: Verify
    with_emb, without_emb = verify_embeddings()

    # Step 6: Test semantic search with sample queries
    print("\n" + "="*80)
    print("🧪 TESTING SEMANTIC SEARCH")
    print("="*80)

    test_queries = [
        "best smartphone for photography",
        "affordable jeans for men",
        "luxury perfume for men",
        "frozen vegetables for cooking",
        "women sports shoes"
    ]

    for query in test_queries:
        semantic_search(query, top_k=3)
        print()

    # Final summary
    print("\n" + "="*80)
    print("✅ PHASE 2 COMPLETE!")
    print("="*80)
    print(f"Embeddings Generated: {len(embeddings_data)}")
    print(f"Estimated Cost: ${cost:.4f}")
    print(f"Next: Phase 2 Task 3 - Build Recommendation Engine")
    print("="*80)

    # Cleanup
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
