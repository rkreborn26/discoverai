"""
Debug script: Extract attributes for ONE product
Prints detailed error logs to file (Fixed encoding)
"""

import os
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import json
import traceback

# Load environment
env_path = Path('.env')
if env_path.exists():
    load_dotenv(env_path)

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
NEON_CONNECTION_STRING = os.getenv('DATABASE_URL')

print("Initializing...")
print(f"OpenAI API Key: {OPENAI_API_KEY[:20]}..." if OPENAI_API_KEY else "ERROR: No API Key!")
print(f"Database URL: {NEON_CONNECTION_STRING[:50]}..." if NEON_CONNECTION_STRING else "ERROR: No DB URL!")

if not OPENAI_API_KEY or not NEON_CONNECTION_STRING:
    print("ERROR: Missing OPENAI_API_KEY or DATABASE_URL in .env")
    exit(1)

print("Connecting to NEON...")
try:
    conn = psycopg2.connect(NEON_CONNECTION_STRING)
    cur = conn.cursor()
    print("OK: Database connected!")
except Exception as e:
    print(f"ERROR: Connection failed: {e}")
    exit(1)

# Log file - FIXED ENCODING
LOG_FILE = "debug_log.txt"
log_file = open(LOG_FILE, 'w', encoding='utf-8')

def log(msg):
    """Print and log message"""
    print(msg)
    log_file.write(msg + "\n")
    log_file.flush()

log("=" * 80)
log("DEBUG: Extract Attributes for ONE Product")
log("=" * 80)

# FETCH ONE PRODUCT
log("\n[STEP 1] Fetching one product...")
try:
    cur.execute("""
        SELECT 
            p.id,
            p.name,
            p.description,
            p.brand,
            p.price,
            c.path as category_path
        FROM products p
        LEFT JOIN categories c ON p.category = c.id
        LIMIT 1;
    """)
    
    result = cur.fetchone()
    if result:
        product_id, name, description, brand, price, category_path = result
        log(f"OK: Found product: {product_id}")
        log(f"   Name: {name}")
        log(f"   Brand: {brand}")
        log(f"   Price: {price}")
        log(f"   Category: {category_path}")
    else:
        log("ERROR: No products found")
        exit(1)
        
except Exception as e:
    log(f"ERROR: {e}")
    traceback.print_exc(file=log_file)
    exit(1)

# TEST OPENAI API
log("\n[STEP 2] Testing OpenAI API...")
log(f"API Key (first 50 chars): {OPENAI_API_KEY[:50]}")
log(f"Model: gpt-4o-mini")

try:
    client = OpenAI(api_key=OPENAI_API_KEY)
    log("OK: OpenAI client created")
    
    # Build prompt
    prompt = f"""Extract product attributes. Return ONLY valid JSON.

Name: {name}
Brand: {brand}
Price: {price}
Description: {description}
Category: {category_path}

Return JSON:
{{
  "color": "value or null",
  "size": "value or null",
  "material": "value or null"
}}
"""
    
    log(f"\n[STEP 3] Prompt being sent:\n{prompt}\n")
    
    log("[STEP 4] Calling OpenAI API...")
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=150
    )
    
    log("OK: API call successful!")
    response_text = response.choices[0].message.content.strip()
    log(f"\n[STEP 5] API Response:\n{response_text}\n")
    
    # Parse JSON
    try:
        attrs = json.loads(response_text)
        log(f"OK: JSON parsed successfully!")
        log(f"   Attributes: {attrs}")
    except json.JSONDecodeError as e:
        log(f"ERROR: JSON parse error: {e}")
        
except Exception as e:
    log(f"\nERROR: OpenAI API error!")
    log(f"   Error type: {type(e).__name__}")
    log(f"   Error message: {str(e)}")
    log(f"\nFull traceback:")
    traceback.print_exc(file=log_file)

log("\n" + "=" * 80)
log(f"DEBUG COMPLETE! Check {LOG_FILE} for full details")
log("=" * 80)

log_file.close()
cur.close()
conn.close()

print(f"\nLog saved to: {LOG_FILE}")
