#!/usr/bin/env python3
"""
Database migration script to add prop_id columns to file_indexings and CofO tables.
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text
from app.models.database import engine

def add_prop_id_columns():
    """Add prop_id columns to tables that need them"""
    
    migration_statements = [
        # Add prop_id to file_indexings table if it doesn't exist
        """
        IF COL_LENGTH('file_indexings', 'prop_id') IS NULL 
        BEGIN 
            ALTER TABLE file_indexings ADD prop_id NVARCHAR(100) NULL 
            PRINT 'Added prop_id column to file_indexings table'
        END
        ELSE
        BEGIN
            PRINT 'prop_id column already exists in file_indexings table'
        END
        """,
        
        # Add prop_id to CofO table if it doesn't exist
        """
        IF COL_LENGTH('CofO', 'prop_id') IS NULL 
        BEGIN 
            ALTER TABLE CofO ADD prop_id NVARCHAR(100) NULL 
            PRINT 'Added prop_id column to CofO table'
        END
        ELSE
        BEGIN
            PRINT 'prop_id column already exists in CofO table'
        END
        """
    ]
    
    print("Starting database migration to add prop_id columns...")
    print("=" * 60)
    
    with engine.begin() as connection:
        for i, stmt in enumerate(migration_statements, 1):
            try:
                print(f"Executing migration {i}...")
                result = connection.execute(text(stmt))
                
                # Try to fetch any print messages from SQL Server
                try:
                    messages = result.fetchall()
                    for message in messages:
                        print(f"  {message}")
                except:
                    pass
                    
                print(f"✓ Migration {i} completed successfully")
                
            except Exception as e:
                print(f"✗ Migration {i} failed: {e}")
                raise
    
    print("=" * 60)
    print("Migration completed successfully!")
    
    # Verify the columns were added
    print("\nVerifying columns were added...")
    verify_columns()

def verify_columns():
    """Verify that the prop_id columns were added successfully"""
    
    verification_queries = [
        ("file_indexings", "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'file_indexings' AND COLUMN_NAME = 'prop_id'"),
        ("CofO", "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'CofO' AND COLUMN_NAME = 'prop_id'"),
        ("property_records", "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'property_records' AND COLUMN_NAME = 'prop_id'"),
        ("registered_instruments", "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'registered_instruments' AND COLUMN_NAME = 'prop_id'")
    ]
    
    with engine.connect() as conn:
        for table_name, query in verification_queries:
            try:
                result = conn.execute(text(query))
                columns = result.fetchall()
                if columns:
                    print(f"✓ {table_name} table has prop_id column")
                else:
                    print(f"✗ {table_name} table does NOT have prop_id column")
            except Exception as e:
                print(f"✗ Error checking {table_name}: {e}")

if __name__ == "__main__":
    add_prop_id_columns()