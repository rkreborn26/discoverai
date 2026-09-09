#!/usr/bin/env python3
"""
Script to import missing categories from CSV to NEON Database
Usage: python import_missing_categories.py
"""

import csv
import sys
from src.db_connection import get_connection

def import_categories_from_csv(csv_file_path):
    """
    Import categories from CSV file to NEON database
    
    CSV Format:
    id,name,parent_id,description
    """
    
    try:
        # Connect to database
        conn = get_connection()
        cur = conn.cursor()
        
        # Track statistics
        success_count = 0
        error_count = 0
        skipped_count = 0
        errors = []
        
        print("\n" + "="*70)
        print("IMPORTING MISSING CATEGORIES FROM CSV")
        print("="*70)
        print(f"CSV File: {csv_file_path}\n")
        
        # Open and read CSV
        with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            # Validate headers (new format with category_code and level)
            expected_headers = ['id', 'category_code', 'name', 'parent_id', 'level', 'description']
            if not reader.fieldnames or reader.fieldnames != expected_headers:
                print("❌ ERROR: CSV headers don't match expected format!")
                print(f"Expected: {expected_headers}")
                print(f"Got: {list(reader.fieldnames)}")
                return False
            
            for row_num, row in enumerate(reader, start=2):  # start=2 because row 1 is header
                try:
                    category_id = row['id'].strip()
                    category_code = row['category_code'].strip()
                    name = row['name'].strip()
                    parent_id = row['parent_id'].strip() if row['parent_id'].strip() else None
                    level = int(row['level'].strip()) if row['level'].strip() else 1
                    description = row['description'].strip()
                    
                    # Validate required fields
                    if not category_id or not category_code or not name:
                        error_msg = f"Row {row_num}: Missing id, category_code, or name"
                        errors.append(error_msg)
                        error_count += 1
                        print(f"⚠️  {error_msg}")
                        continue
                    
                    # Check if category already exists
                    cur.execute("SELECT id FROM categories WHERE id = %s", (category_id,))
                    if cur.fetchone():
                        skipped_count += 1
                        print(f"⏭️  Row {row_num}: Category '{category_id}' already exists (SKIPPED)")
                        continue
                    
                    # If parent_id is provided, verify it exists
                    if parent_id:
                        cur.execute("SELECT id FROM categories WHERE id = %s", (parent_id,))
                        if not cur.fetchone():
                            error_msg = f"Row {row_num}: Parent category '{parent_id}' not found"
                            errors.append(error_msg)
                            error_count += 1
                            print(f"❌ {error_msg}")
                            continue
                    
                    # Insert category with all required columns
                    cur.execute(
                        """
                        INSERT INTO categories (id, category_code, name, parent_id, level, description)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (category_id, category_code, name, parent_id, level, description)
                    )
                    
                    success_count += 1
                    print(f"✅ Row {row_num}: '{category_id}' - '{name}' imported successfully")
                    
                except Exception as e:
                    error_msg = f"Row {row_num}: {str(e)}"
                    errors.append(error_msg)
                    error_count += 1
                    print(f"❌ {error_msg}")
        
        # Commit all changes
        conn.commit()
        
        # Print summary
        print("\n" + "="*70)
        print("IMPORT SUMMARY")
        print("="*70)
        print(f"✅ Successfully imported: {success_count} categories")
        print(f"⏭️  Skipped (already exist): {skipped_count} categories")
        print(f"❌ Errors: {error_count}")
        print("="*70)
        
        if errors:
            print("\nErrors encountered:")
            for error in errors:
                print(f"  - {error}")
        
        # Verify import
        cur.execute("SELECT COUNT(*) FROM categories")
        total_categories = cur.fetchone()[0]
        print(f"\nTotal categories in database now: {total_categories}")
        
        # Close connection
        cur.close()
        conn.close()
        
        return error_count == 0
        
    except FileNotFoundError:
        print(f"❌ ERROR: CSV file not found: {csv_file_path}")
        return False
    
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        return False

def main():
    """Main function"""
    
    # CSV file path
    csv_file = 'MISSING_CATEGORIES.csv'
    
    print("\n" + "#"*70)
    print("# MISSING CATEGORIES IMPORT TOOL")
    print("#"*70)
    
    # Check if file exists
    try:
        with open(csv_file, 'r') as f:
            pass
    except FileNotFoundError:
        print(f"\n❌ ERROR: File '{csv_file}' not found!")
        print(f"Make sure MISSING_CATEGORIES.csv is in your project directory")
        print(f"Current directory: {os.getcwd()}")
        sys.exit(1)
    
    # Run import
    success = import_categories_from_csv(csv_file)
    
    if success:
        print("\n✅ All categories imported successfully!")
        sys.exit(0)
    else:
        print("\n⚠️  Import completed with some errors. Please review above.")
        sys.exit(1)

if __name__ == "__main__":
    import os
    main()
