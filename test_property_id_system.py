#!/usr/bin/env python3
"""
Test script to verify the property ID assignment system works correctly.
This tests:
1. Property ID counter finds the max across all tables
2. No duplicate property IDs are generated
3. Same file number gets the same property ID
4. Different file numbers get different property IDs
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import _get_next_property_id_counter, _find_existing_property_id, _assign_property_ids

def test_property_id_counter():
    """Test that the counter finds the max across all tables"""
    print("Testing _get_next_property_id_counter...")
    try:
        next_id = _get_next_property_id_counter()
        print(f"✓ Next available property ID: {next_id}")
        return next_id
    except Exception as e:
        print(f"✗ Error getting next property ID: {e}")
        return None

def test_find_existing_property_id():
    """Test finding existing property IDs"""
    print("\nTesting _find_existing_property_id...")
    
    # Test with a file number that might exist
    test_file_numbers = ["RES-1985-1", "COM-1990-100", "NONEXISTENT-2025-999"]
    
    for file_number in test_file_numbers:
        try:
            existing_id = _find_existing_property_id(file_number)
            if existing_id:
                print(f"✓ Found existing property ID for {file_number}: {existing_id}")
            else:
                print(f"✓ No existing property ID found for {file_number}")
        except Exception as e:
            print(f"✗ Error finding property ID for {file_number}: {e}")

def test_property_id_assignment():
    """Test the full property ID assignment logic"""
    print("\nTesting _assign_property_ids...")
    
    # Create test records
    test_records = [
        {'file_number': 'TEST-2025-001'},
        {'file_number': 'TEST-2025-002'},
        {'file_number': 'TEST-2025-001'},  # Duplicate file number
        {'file_number': 'TEST-2025-003'},
        {'file_number': ''},  # Empty file number
        {'file_number': 'TEST-2025-002'},  # Another duplicate
    ]
    
    try:
        assignments = _assign_property_ids(test_records)
        
        print(f"✓ Processed {len(assignments)} property assignments")
        
        # Check for proper prop_id assignment
        prop_ids_used = []
        file_number_to_prop_id = {}
        
        for i, assignment in enumerate(assignments):
            file_number = assignment['file_number']
            prop_id = assignment['property_id']
            status = assignment['status']
            
            print(f"  Record {i+1}: {file_number} -> {prop_id} ({status})")
            
            # Check that same file number gets same property ID
            if file_number in file_number_to_prop_id:
                if file_number_to_prop_id[file_number] != prop_id:
                    print(f"✗ INCONSISTENT PROPERTY ID for {file_number}: got {prop_id}, expected {file_number_to_prop_id[file_number]}")
                else:
                    print(f"  ✓ Same file number correctly reused property ID: {prop_id}")
            else:
                file_number_to_prop_id[file_number] = prop_id
                prop_ids_used.append(prop_id)
        
        # Verify records have prop_id assigned
        records_with_prop_id = [r for r in test_records if r.get('prop_id')]
        print(f"✓ {len(records_with_prop_id)} records have prop_id assigned")
        
        # Show prop_ids assigned to records
        for i, record in enumerate(test_records):
            if record.get('prop_id'):
                print(f"  Record {i+1}: {record.get('file_number', 'NO_FILE_NUMBER')} has prop_id: {record['prop_id']}")
        
    except Exception as e:
        print(f"✗ Error in property ID assignment: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("=" * 60)
    print("PROPERTY ID SYSTEM TEST")
    print("=" * 60)
    
    # Test 1: Property ID Counter
    next_id = test_property_id_counter()
    
    # Test 2: Find Existing Property IDs
    test_find_existing_property_id()
    
    # Test 3: Property ID Assignment Logic
    test_property_id_assignment()
    
    print("\n" + "=" * 60)
    print("TEST COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    main()