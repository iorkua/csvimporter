#!/usr/bin/env python3
"""Check grouping table schema."""

from app.models.database import get_db_connection
from sqlalchemy import text

def check_grouping_schema():
    """Check the grouping table schema for shelf_location field."""
    db = get_db_connection()
    
    try:
        result = db.execute(text("""
            SELECT COLUMN_NAME, DATA_TYPE 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = 'grouping' AND TABLE_SCHEMA = 'dbo'
            ORDER BY ORDINAL_POSITION
        """))
        
        print("grouping table schema:")
        print("=" * 30)
        columns = []
        for row in result.fetchall():
            columns.append(row[0])
            print(f"{row[0]}: {row[1]}")
            
        print(f"\nHas shelf_location field: {'shelf_location' in columns}")
        print(f"Total columns: {len(columns)}")
            
    finally:
        db.close()

if __name__ == "__main__":
    check_grouping_schema()