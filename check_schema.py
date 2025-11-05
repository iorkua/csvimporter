#!/usr/bin/env python3
"""Check database schema for file_indexings table."""

from app.models.database import get_db_connection
from sqlalchemy import text

def check_schema():
    """Check the file_indexings table schema."""
    db = get_db_connection()
    
    try:
        result = db.execute(text("""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = 'file_indexings' 
            AND TABLE_SCHEMA = 'dbo' 
            ORDER BY ORDINAL_POSITION
        """))
        
        print("file_indexings table schema:")
        print("=" * 50)
        for row in result.fetchall():
            print(f"{row[0]}: {row[1]} (nullable: {row[2]}, default: {row[3]})")
            
    finally:
        db.close()

if __name__ == "__main__":
    check_schema()