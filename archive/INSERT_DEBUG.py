import json
import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

with open('product_attributes_extracted.json') as f:
    data = json.load(f)

product_id, attrs = list(data.items())[0]

print(f"Product ID: {product_id}")
print(f"Attributes: {attrs}")

try:
    cols = ['product_id'] + list(attrs.keys())
    vals = [product_id] + list(attrs.values())
    placeholders = ', '.join(['%s'] * len(cols))
    col_string = ', '.join(cols)
    
    query = f"INSERT INTO product_attributes ({col_string}) VALUES ({placeholders})"
    print(f"\nQuery: {query}")
    print(f"Values: {vals}")
    
    cur.execute(query, tuple(vals))
    conn.commit()
    print("\nSUCCESS!")
except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()

cur.close()
conn.close()