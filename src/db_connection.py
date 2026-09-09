"""
Database Connection Module
Connects Python to NEON PostgreSQL database
"""

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv
import os

# Load environment variables from .env
load_dotenv()

# Get database URL from .env
DATABASE_URL = os.getenv('DATABASE_URL')

def get_connection():
    """
    Create and return a connection to NEON database
    
    Returns:
        psycopg2.connection: Active database connection
        
    Raises:
        Exception: If connection fails
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        raise

def test_connection():
    """
    Test if connection to NEON works
    Run simple SELECT query
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Test query 1: Count categories
        cur.execute("SELECT COUNT(*) FROM public.categories")
        category_count = cur.fetchone()[0]
        print(f"✅ Categories in database: {category_count}")
        
        # Test query 2: Count products
        cur.execute("SELECT COUNT(*) FROM public.products")
        product_count = cur.fetchone()[0]
        print(f"✅ Products in database: {product_count}")
        
        # Test query 3: Get all product names and prices
        cur.execute("SELECT id, name, price FROM public.products")
        products = cur.fetchall()
        print(f"\n✅ Products:")
        for product in products:
            print(f"   - {product[1]} (₹{product[2]})")
        
        cur.close()
        conn.close()
        
        print(f"\n✅ CONNECTION SUCCESSFUL! 🎉")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

def get_categories():
    """
    Get all categories from database
    
    Returns:
        list: List of tuples (id, name)
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM public.categories")
        categories = cur.fetchall()
        cur.close()
        conn.close()
        return categories
    except Exception as e:
        print(f"❌ Error fetching categories: {e}")
        return []

def get_products():
    """
    Get all products from database
    
    Returns:
        list: List of tuples (id, name, price)
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, name, price FROM public.products")
        products = cur.fetchall()
        cur.close()
        conn.close()
        return products
    except Exception as e:
        print(f"❌ Error fetching products: {e}")
        return []

def get_product_by_id(product_id):
    """
    Get a specific product by ID
    
    Args:
        product_id: Product ID to fetch
        
    Returns:
        tuple: (id, name, price) or None if not found
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, price FROM public.products WHERE id = %s",
            (product_id,)
        )
        product = cur.fetchone()
        cur.close()
        conn.close()
        return product
    except Exception as e:
        print(f"❌ Error fetching product: {e}")
        return None

# When this file is run directly, test the connection
if __name__ == "__main__":
    print("Testing NEON Database Connection...")
    print("=" * 50)
    test_connection()