#!/usr/bin/env python3
"""
Test script for grouping functionality without shelf rack integration.
"""

import sys
sys.path.append('.')

from app.services.file_indexing_service import _apply_grouping_updates
from app.models.database import SessionLocal, Grouping
from datetime import datetime

def test_enhanced_grouping_logic():
    """Test the enhanced grouping update logic."""
    print("Testing Enhanced Grouping Logic")
    print("=" * 50)
    
    db = SessionLocal()
    
    try:
        # Test data setup
        test_file_number = "TEST123"
        test_record = {
            'file_number': test_file_number,
            'batch_no': 'BATCH001',
            'registry': 'REG001',
            'shelf_location': 'A1-B2'  # fallback value
        }
        
        # Check if test grouping record exists
        grouping_row = db.query(Grouping).filter(
            Grouping.awaiting_fileno == test_file_number
        ).first()
        
        if not grouping_row:
            print(f"No grouping record found for {test_file_number}")
            print("Creating test data...")
            
            # Create test grouping record
            test_grouping = Grouping(
                awaiting_fileno=test_file_number,
                group='GROUP001',
                sys_batch_no='SYS001',
                indexing_mapping=0,
                tracking_id='TRK-TEST123-0001'
            )
            db.add(test_grouping)
            db.commit()
            print("Test data created.")
        
        # Test the enhanced grouping logic
        print(f"\nTesting grouping updates for file number: {test_file_number}")
        
        result = _apply_grouping_updates(db, test_record, test_file_number, datetime.now(), 'PRODUCTION')

        print(f"Result status: {result['status']}")
        print(f"Shelf location: {result['shelf_location']}")
        print(f"Group: {result['group']}")
        print(f"Sys batch no: {result['sys_batch_no']}")
        print(f"Reason: {result['reason']}")
        
        # Check grouping table updates
        updated_grouping = db.query(Grouping).filter(
            Grouping.awaiting_fileno == test_file_number
        ).first()
        
        if updated_grouping:
            print(f"Grouping mapping status: {updated_grouping.indexing_mapping}")
            print(f"Grouping indexing_mls_fileno: {updated_grouping.indexing_mls_fileno}")
            print(f"Grouping mdc_batch_no: {updated_grouping.mdc_batch_no}")
            print(f"Grouping tracking_id: {updated_grouping.tracking_id}")
        
        print("\n✅ Enhanced grouping logic test completed successfully!")
        
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    test_enhanced_grouping_logic()