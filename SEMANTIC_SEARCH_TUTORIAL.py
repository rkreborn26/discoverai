"""
DiscoverAI: Semantic Search Tutorial
====================================

Learn how semantic search works step-by-step!

Features:
1. Enter a query
2. See the embedding generated
3. Watch products ranked by similarity
4. Understand why they matched
"""

import os
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv
import json

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
NEON_CONNECTION_STRING = os.getenv('DATABASE_URL')

if not OPENAI_API_KEY or not NEON_CONNECTION_STRING:
    print("ERROR: Missing credentials in .env")
    exit(1)

client = OpenAI(api_key=OPENAI_API_KEY)

print("Connecting to NEON...")
try:
    conn = psycopg2.connect(NEON_CONNECTION_STRING)
    cur = conn.cursor()
    print("OK: Database connected!\n")
except Exception as e:
    print(f"ERROR: {e}")
    exit(1)

# ==========================================
# GENERATE EMBEDDING FOR QUERY
# ==========================================

def generate_query_embedding(query_text):
    """Generate embedding for user query"""
    print(f"[STEP 1] Generating embedding for query: '{query_text}'")
    print("-" * 80)
    
    try:
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=query_text
        )
        
        embedding = response.data[0].embedding
        print(f"OK: Generated 1536-dimensional vector")
        print(f"    First 10 dimensions: {[round(x, 4) for x in embedding[:10]]}")
        print(f"    Last 10 dimensions:  {[round(x, 4) for x in embedding[-10:]]}")
        print()
        
        return embedding
        
    except Exception as e:
        print(f"ERROR: {e}")
        return None

# ==========================================
# SEARCH SIMILAR PRODUCTS
# ==========================================

def search_similar_products(query_embedding, embedding_type='embedding_full', limit=10):
    """Search for similar products"""
    print(f"[STEP 2] Searching for similar products (using {embedding_type})")
    print("-" * 80)
    
    try:
        # Convert embedding to PostgreSQL format
        embedding_str = json.dumps(query_embedding)
        
        query = f"""
        SELECT 
            p.id,
            p.name,
            p.brand,
            p.price,
            c.path as category,
            -- Calculate distance (1 - cosine similarity)
            ROUND((1 - ({embedding_type} <=> %s::vector))::numeric * 100, 2) as similarity_score,
            -- Raw distance for debugging
            ROUND(({embedding_type} <=> %s::vector)::numeric, 6) as distance
        FROM products p
        LEFT JOIN categories c ON p.category = c.id
        WHERE p.{embedding_type} IS NOT NULL
        ORDER BY {embedding_type} <=> %s::vector
        LIMIT {limit};
        """
        
        cur.execute(query, (embedding_str, embedding_str, embedding_str))
        results = cur.fetchall()
        
        print(f"OK: Found {len(results)} matching products\n")
        return results
        
    except Exception as e:
        print(f"ERROR: {e}")
        return []

# ==========================================
# DISPLAY RESULTS
# ==========================================

def display_results(results):
    """Display search results with explanation"""
    print("[STEP 3] Results ranked by similarity")
    print("-" * 80)
    
    print(f"\n{'Rank':<6} {'Product':<40} {'Brand':<12} {'Price':<10} {'Similarity':<12}")
    print("-" * 80)
    
    for idx, (product_id, name, brand, price, category, similarity, distance) in enumerate(results):
        rank = idx + 1
        name_short = name[:38] if name else "Unknown"
        brand_short = brand[:10] if brand else "N/A"
        
        print(f"{rank:<6} {name_short:<40} {brand_short:<12} ₹{price:<8} {similarity}%")
    
    print("\n[STEP 4] Understanding the results")
    print("-" * 80)
    
    if results:
        top_result = results[0]
        print(f"\nTop Match: {top_result[1]}")
        print(f"  Category: {top_result[4]}")
        print(f"  Brand: {top_result[2]}")
        print(f"  Price: ₹{top_result[3]}")
        print(f"  Similarity Score: {top_result[5]}%")
        print(f"  Vector Distance: {top_result[6]}")
        print(f"\nExplanation:")
        print(f"  - Your query was converted to a 1536-dimensional vector")
        print(f"  - Each product also has a 1536-dimensional vector (embedding)")
        print(f"  - PostgreSQL calculated the distance between query and each product")
        print(f"  - Smaller distance = More similar (better match)")
        print(f"  - Similarity = (1 - distance) × 100%")
        print(f"  - {top_result[1]} is the closest match!")

# ==========================================
# DETAILED EXPLANATION
# ==========================================

def show_explanation():
    """Show detailed explanation of how it works"""
    print("\n" + "=" * 80)
    print("HOW SEMANTIC SEARCH WORKS - DETAILED EXPLANATION")
    print("=" * 80)
    
    explanation = """
1. TEXT TO VECTOR (Embedding Generation)
   Input:  "blue jeans for men"
   Process: OpenAI text-embedding-3-small model
   Output: [0.123, -0.456, 0.789, ..., 0.234]  (1536 dimensions)
   
   Each dimension captures different semantic meanings:
   - Some dimensions capture "clothing"
   - Some capture "blue color"
   - Some capture "men's fashion"
   - Some capture "casual wear"

2. COMPARE QUERY VS PRODUCTS
   For each product in database:
     - Get product's embedding (already stored)
     - Calculate distance between query embedding and product embedding
     - Store distance with product
   
   Distance Formula (Cosine Distance):
     distance = 1 - cosine_similarity
     
   Cosine Similarity: Measures angle between two vectors
     - 1.0 = identical vectors (distance = 0)
     - 0.0 = perpendicular vectors (distance = 1)

3. RANK BY DISTANCE
   Sort all products by distance (smallest first)
   Smaller distance = Better match
   
4. RETURN TOP RESULTS
   Return top 10 (or N) closest matches
   Show similarity score = (1 - distance) × 100%

WHY IT WORKS:
- Products with similar descriptions/names have similar embeddings
- "blue jeans" query is close to actual blue jeans in vector space
- "red jeans" is also close, but not as close as blue ones
- "blue shirt" is close because it has "blue" but not "jeans"
- Vector distance naturally captures semantic similarity!

SPEED OPTIMIZATION:
- PostgreSQL IVFFlat index pre-clusters embeddings
- Query skips most products, only checks nearby clusters
- 497 products searched in milliseconds!
"""
    
    print(explanation)

# ==========================================
# INTERACTIVE LOOP
# ==========================================

def main():
    print("=" * 80)
    print("SEMANTIC SEARCH TUTORIAL - INTERACTIVE MODE")
    print("=" * 80)
    print("\nEnter a search query and we'll show you:")
    print("  1. How the query is converted to an embedding")
    print("  2. How products are matched and ranked")
    print("  3. Why they matched (similarity scores)")
    print("\nCommands:")
    print("  Type a query and press Enter to search")
    print("  Type 'help' to see explanation")
    print("  Type 'quit' to exit")
    print("\n" + "=" * 80 + "\n")
    
    while True:
        try:
            query = input("Enter search query (or 'help'/'quit'): ").strip()
            
            if not query:
                continue
            
            if query.lower() == 'quit':
                print("\nGoodbye!")
                break
            
            if query.lower() == 'help':
                show_explanation()
                continue
            
            # Perform search
            print("\n" + "=" * 80)
            embedding = generate_query_embedding(query)
            
            if embedding:
                print()
                results = search_similar_products(embedding, 'embedding_full', limit=10)
                
                if results:
                    print()
                    display_results(results)
                else:
                    print("No results found")
            
            print("\n" + "=" * 80 + "\n")
            
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"ERROR: {e}\n")

if __name__ == "__main__":
    main()
    cur.close()
    conn.close()
