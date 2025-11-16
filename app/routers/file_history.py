"""
API router for File History import with entity and customer staging.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import io
import uuid

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.database import SessionLocal
from app.services.staging_handler import (
    extract_entity_and_customer_data,
    build_staging_preview,
    perform_staging_import
)

router = APIRouter()


# Import file history processing from main.py (will be enhanced)
def _prepare_file_history_staging_preview(
    property_records: List[Dict[str, Any]],
    cofo_records: List[Dict[str, Any]],
    filename: str,
    test_control: str = 'PRODUCTION'
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Prepare file history staging data with entity and customer extraction.
    
    Returns: (staging_data, response_payload)
    """
    # Extract entity and customer data using transaction_type field
    entity_records, customer_records, staging_summary = extract_entity_and_customer_data(
        property_records,
        filename,
        test_control,
        transaction_type_field='transaction_type',
        source='file_history'
    )
    
    staging_payload = build_staging_preview(
        entity_records,
        customer_records,
        staging_summary
    )
    
    return staging_payload, staging_summary
