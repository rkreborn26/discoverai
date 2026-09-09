"""
DiscoverAI: Intelligent Product Attributes Population V5
========================================================

FINAL VERSION: Properly handles TEXT id column
Loads from product_attributes_extracted.json and inserts
"""

import json
import psycopg2
from dotenv import load_dotenv
import os
import uuid

load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

print("=" * 80)
print("POPULATE PRODUCT ATTRIBUTES - FINAL VERSION")
print("=" * 80)

# Load data
print("\nLoading product_attributes_extracted.json...")
try:
    with open('product_attributes_extracted.json') as f:
        all_attributes = json.load(f)
    print(f"OK: Loaded {len(all_attributes)} products")
except Exception as e:
    print(f"ERROR: {e}")
    exit(1)

print("\nINSERTING INTO DATABASE")
print("=" * 80)

success_count = 0
failed_count = 0

for idx, (product_id, attributes) in enumerate(all_attributes.items()):
    if (idx + 1) % 50 == 0:
        print(f"\n[{idx + 1}/{len(all_attributes)}] Progress...")
    
    print(f"  Product {product_id}...", end=" ", flush=True)
    
    try:
        # Build UPDATE query - only update the attributes we have
        if attributes:
            set_clauses = []
            values = []
            
            for attr_name, attr_value in attributes.items():
                set_clauses.append(f"{attr_name} = %s")
                values.append(attr_value)
            
            values.append(product_id)
            
            set_string = ", ".join(set_clauses)
            query = f"""
                UPDATE product_attributes 
                SET {set_string}
                WHERE product_id = %s
            """
            
            cur.execute(query, tuple(values))
            
            # If no row updated, insert new row with generated id
            if cur.rowcount == 0:
                # Generate unique id (TEXT type)
                next_id = str(uuid.uuid4())
                
                # Build INSERT with id
                cols = ['id', 'product_id'] + list(attributes.keys())
                vals = [next_id, product_id] + list(attributes.values())
                placeholders = ', '.join(['%s'] * len(cols))
                col_string = ', '.join(cols)
                
                insert_query = f"""
                    INSERT INTO product_attributes ({col_string})
                    VALUES ({placeholders})
                """
                
                cur.execute(insert_query, tuple(vals))
            
            conn.commit()
            print("OK")
            success_count += 1
        else:
            print("SKIP")
    
    except Exception as e:
        conn.rollback()
        print(f"FAIL: {str(e)[:50]}")
        failed_count += 1

# Summary
print("\n" + "=" * 80)
print("INSERTION COMPLETE!")
print("=" * 80)
print(f"Success: {success_count}")
print(f"Failed: {failed_count}")
print(f"Total: {len(all_attributes)}")

# Verify
print("\nVERIFICATION:")
try:
    conn.rollback()
    
    cur.execute("""
        SELECT COUNT(*) as total_rows FROM product_attributes;
    """)
    total = cur.fetchone()[0]
    print(f"   Total attribute records: {total}")
    
    cur.execute("""
        SELECT 
            COUNT(DISTINCT product_id) as products_with_attrs,
            COUNT(CASE WHEN pack_size IS NOT NULL THEN 1 END) as with_pack_size,
            COUNT(CASE WHEN size IS NOT NULL THEN 1 END) as with_size,
            COUNT(CASE WHEN color IS NOT NULL THEN 1 END) as with_color,
            COUNT(CASE WHEN storage_gb IS NOT NULL THEN 1 END) as with_storage
        FROM product_attributes;
    """)
    
    products_with_attrs, with_pack, with_size, with_color, with_storage = cur.fetchone()
    print(f"   Products with attributes: {products_with_attrs}")
    print(f"   With pack_size: {with_pack}")
    print(f"   With size: {with_size}")
    print(f"   With color: {with_color}")
    print(f"   With storage_gb: {with_storage}")

except Exception as e:
    print(f"   ERROR: {e}")

cur.close()
conn.close()

print("\nDONE!")
