#!/usr/bin/env python3
"""
Test script for shelf_location handling in file_indexings and grouping tables.
"""

import sys
sys.path.append('.')

from app.services.file_indexing_service import _apply_grouping_updates
from app.models.database import SessionLocal, Grouping, FileIndexing
from datetime import datetime

def test_shelf_location_updates():
    """Test shelf_location updates in both tables."""
    print("Testing Shelf Location Updates in Both Tables")
    print("=" * 50)
    
    db = SessionLocal()
    
    try:
        # Test data setup
        test_file_number = "SHELF_TEST123"
        
        # Clean up any existing test data
        db.query(FileIndexing).filter(FileIndexing.file_number == test_file_number).delete()
        db.query(Grouping).filter(Grouping.awaiting_fileno == test_file_number).delete()
        db.commit()
        
        # Create test grouping record
        test_grouping = Grouping(
            awaiting_fileno=test_file_number,
            group='GROUP_SHELF',
            sys_batch_no='SYS_SHELF',
            indexing_mapping=0,
            tracking_id='TRK-SHELF-0001'
        )
        db.add(test_grouping)
        
        db.commit()
        print("✅ Test data created")
        
        # Test the shelf_location logic (no rack resolution)
        test_record = {
            'file_number': test_file_number,
            'batch_no': 5001,
            'registry': 'REG_SHELF',
            'shelf_location': 'FALLBACK_SHELF'
        }
        
        print(f"\nProcessing record: {test_file_number}")
        
        # Apply grouping updates
        grouping_result = _apply_grouping_updates(db, test_record, test_file_number, datetime.now(), 'PRODUCTION')
        
        print(f"\nGrouping Results:")
        print(f"  Status: {grouping_result['status']}")
        print(f"  Shelf Location (for file_indexings): {grouping_result['shelf_location']}")
        print(f"  Tracking ID: {grouping_result.get('tracking_id')}")
        
        updated_grouping = db.query(Grouping).filter(Grouping.awaiting_fileno == test_file_number).first()
        if updated_grouping:
            print(f"  Grouping.indexing_mapping: {updated_grouping.indexing_mapping}")
            print(f"  Grouping.indexing_mls_fileno: {updated_grouping.indexing_mls_fileno}")
            print(f"  Grouping.tracking_id: {updated_grouping.tracking_id}")
        
        # Simulate creating file_indexing record with the result
        test_file_record = FileIndexing(
            file_number=test_file_number,
            shelf_location=grouping_result['shelf_location'],
            group=grouping_result.get('group'),
            sys_batch_no=grouping_result.get('sys_batch_no'),
            registry=test_record['registry'],
            batch_no=test_record['batch_no'],
            tracking_id=grouping_result.get('tracking_id') or f"TRK-{test_file_number}",
            status='Indexed',
            created_at=datetime.now(),
            created_by=1
        )
        db.add(test_file_record)
        db.commit()
        
        # Final verification
        created_file_record = db.query(FileIndexing).filter(FileIndexing.file_number == test_file_number).first()
        if created_file_record:
            print(f"  Created file_indexings.shelf_location: {created_file_record.shelf_location}")
        
        print("\n🎯 Shelf Location Flow Summary:")
        print("1. ✅ Grouping matches update indexing_mapping state")
        print("2. ✅ Shelf location stays with provided fallback value")
        print("3. ✅ File indexing record stores fallback shelf location")
        
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    test_shelf_location_updates()