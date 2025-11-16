"""
Centralized staging handler for entity and customer extraction.

This module provides reusable functions for extracting, previewing, and importing
customer and entity staging data across File History, PRA, and PIC imports.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.models.database import CustomerStaging, EntityStaging, SessionLocal
from app.services.file_indexing_service import (
    _classify_customer_type,
    _extract_entity_name,
    _extract_customer_name,
    _extract_customer_address,
    _extract_photos,
    _combine_location,
    _generate_customer_code,
    _get_or_create_entity,
    _normalize_string,
)

logger = logging.getLogger(__name__)


def _extract_reason_retired(
    record: Dict[str, Any],
    transaction_type_field: str = 'transaction_type'
) -> Optional[str]:
    """
    Extract reason_retired from record based on transaction_type.
    
    Valid values: Revoked, Assignment, Power of Attorney, Surrender, Mortgage
    
    Args:
        record: Record dictionary
        transaction_type_field: Field name containing transaction type
    
    Returns:
        reason_retired value or None
    """
    transaction_type = _normalize_string(record.get(transaction_type_field))
    if not transaction_type:
        return None
    
    # Map transaction types to reason_retired
    mapping = {
        'Revoked': 'Revoked',
        'Assignment': 'Assignment',
        'Power of Attorney': 'Power of Attorney',
        'Surrender': 'Surrender',
        'Mortgage': 'Mortgage',
    }
    
    # Try exact match first
    for key, value in mapping.items():
        if transaction_type.lower() == key.lower():
            return value
    
    # Try partial match
    lower_type = transaction_type.lower()
    for key, value in mapping.items():
        if key.lower() in lower_type:
            return value
    
    # Return original if no match (will be validated at DB level)
    return transaction_type if transaction_type in mapping.values() else None


def _resolve_file_history_holder(record: Dict[str, Any], role: str) -> Optional[str]:
    """Resolve assignor/assignee style values that appear under multiple headers."""
    if role == 'assignor':
        candidate_fields = (
            'Assignor', 'Grantor', 'Original Holder (Assignor)',
            'Original Holder', 'original_holder_assignor', 'grantor_assignor'
        )
    else:
        candidate_fields = (
            'Assignee', 'Grantee', 'Current Holder (Assignee)',
            'Current Holder', 'current_holder_assignee', 'grantee_assignee'
        )

    for field in candidate_fields:
        resolved = _normalize_string(record.get(field))
        if resolved:
            return resolved
    return None


def _compose_reason_retired_detail(base_reason: Optional[str], assignee: Optional[str]) -> Optional[str]:
    """Build a human-friendly reason_retired description that references the assignee when present."""
    if base_reason and assignee:
        return f"{base_reason} -> {assignee}"
    if assignee:
        return assignee
    return base_reason


def extract_entity_and_customer_data(
    records: List[Dict[str, Any]],
    filename: str,
    test_control: str = 'PRODUCTION',
    transaction_type_field: str = 'transaction_type',
    source: str = 'default'
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Extract entity and customer staging data from records.

    Returns: (entity_records, customer_records, summary)
    """

    entity_records: List[Dict[str, Any]] = []
    customer_records: List[Dict[str, Any]] = []
    entity_cache: Dict[str, int] = {}
    type_counter: Dict[str, int] = {}

    normalized_source = (source or 'default').strip().lower()
    is_file_history = normalized_source == 'file_history'
    is_pic = normalized_source == 'pic'
    is_pra = normalized_source == 'pra'
    is_pic = normalized_source == 'pic'
    is_pra = normalized_source == 'pra'

    for idx, record in enumerate(records):
        try:
            assignor = _resolve_file_history_holder(record, 'assignor') if is_file_history else None
            assignee = _resolve_file_history_holder(record, 'assignee') if is_file_history else None
            pic_grantor = _normalize_string(record.get('Grantor')) if is_pic else None
            pic_grantee = _normalize_string(record.get('grantee_original') or record.get('Grantee')) if is_pic else None
            pic_property_address = _normalize_string(record.get('property_description')) if is_pic else None
            pra_grantee = _normalize_string(record.get('grantee_assignee') or record.get('Grantee')) if is_pra else None
            pra_grantor = _normalize_string(record.get('grantor_assignor') or record.get('Grantor')) if is_pra else None
            transaction_label = _normalize_string(record.get(transaction_type_field)) if transaction_type_field else None
            location_value = _normalize_string(record.get('location'))
            district_value = record.get('districtName') or record.get('district')
            lga_value = record.get('LGA') or record.get('lga')
            pra_combined_location = _combine_location(district_value, lga_value) if is_pra else None

            # Determine base entity name using file-history specific mapping when requested
            entity_name = assignor if assignor else _extract_entity_name(record)
            if is_pra and pra_grantee:
                entity_name = pra_grantee
            if not entity_name:
                logger.warning("No entity name for record %d", idx)
                continue

            descriptor = (
                pra_grantee
                or assignor
                or _normalize_string(record.get('file_title'))
                or entity_name
                or _normalize_string(record.get('customer_name'))
                or filename
            )
            customer_type = _classify_customer_type(descriptor)
            type_counter[customer_type] = type_counter.get(customer_type, 0) + 1

            passport_photo, company_logo = _extract_photos(
                record,
                customer_type,
                include_placeholders=True
            )

            file_number_value = _normalize_string(
                record.get('file_number')
                or record.get('mlsFNo')
                or record.get('fileno')
                or record.get('fileNumber')
                or record.get('MLSFileNo')
            )

            cache_key = f"{entity_name}:{customer_type}"
            if cache_key not in entity_cache:
                next_entity_id = len(entity_records) + 1
                entity_data = {
                    'entity_id': next_entity_id,
                    'entity_name': entity_name,
                    'name': entity_name,
                    'entity_type': customer_type,
                    'passport_photo': passport_photo,
                    'company_logo': company_logo,
                    'file_number': file_number_value,
                    'status': 'new',
                    'test_control': test_control
                }
                entity_records.append(entity_data)
                entity_cache[cache_key] = len(entity_records) - 1
            else:
                existing_entity = entity_records[entity_cache[cache_key]]
                existing_entity['status'] = 'reused'
                if file_number_value and not existing_entity.get('file_number'):
                    existing_entity['file_number'] = file_number_value

            entity_index = entity_cache[cache_key]
            entity_id_value = entity_records[entity_index].get('entity_id')

            if is_file_history and assignor:
                customer_name = assignor
            elif is_pic and pic_grantee:
                customer_name = pic_grantee
            elif is_pra and pra_grantee:
                customer_name = pra_grantee
            else:
                customer_name = _extract_customer_name(record, entity_name)
            customer_code = _generate_customer_code()

            if is_file_history:
                property_address = location_value or _extract_customer_address(record)
            elif is_pic:
                combined_location = _combine_location(district_value, lga_value)
                property_address = combined_location or pic_property_address or _extract_customer_address(record)
            elif is_pra:
                property_address = pra_combined_location or _extract_customer_address(record)
            else:
                property_address = _extract_customer_address(record)

            if is_file_history:
                reason_retired_value = transaction_label
                reason_by_value = assignee
                notes_value = None
            elif is_pic:
                reason_retired_value = transaction_label
                reason_by_value = pic_grantor
                notes_value = None
            elif is_pra:
                reason_retired_value = transaction_label
                reason_by_value = pra_grantor
                notes_value = None
            else:
                reason_retired_value = _extract_reason_retired(record, transaction_type_field)
                reason_by_value = None
                notes_value = None

            customer_data = {
                'customer_name': customer_name,
                'customer_type': customer_type,
                'status': 'pending',
                'customer_code': customer_code,
                'email': _normalize_string(record.get('email')),
                'phone': _normalize_string(record.get('phone')),
                'property_address': property_address,
                'residential_address': _normalize_string(record.get('residential_address')),
                'notes': notes_value,
                'entity_name': entity_name,
                'entity_id': entity_id_value,
                'file_number': file_number_value,
                'account_no': file_number_value,
                'reason_retired': reason_retired_value,
                'reason_by': reason_by_value,
                'has_issues': False,
                'test_control': test_control
            }
            customer_data['name'] = customer_name
            customer_data['transaction_type'] = transaction_label
            customer_records.append(customer_data)

        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Error extracting staging data for record %d: %s", idx, str(exc))
            continue

    if not type_counter:
        summary_customer_type = _classify_customer_type(filename)
    elif len(type_counter) == 1:
        summary_customer_type = next(iter(type_counter))
    else:
        summary_customer_type = 'Mixed'

    staging_summary = {
        'customer_type': summary_customer_type,
        'customer_type_breakdown': type_counter,
        'entity_count': len(entity_records),
        'customer_count': len(customer_records),
        'new_entities': len([e for e in entity_records if e['status'] == 'new']),
        'existing_entities': len([e for e in entity_records if e['status'] == 'reused']),
        'duplicates_flagged': 0,
        'reason_retired_populated': len([c for c in customer_records if c.get('reason_retired')])
    }

    return entity_records, customer_records, staging_summary


def build_staging_preview(
    entity_records: List[Dict[str, Any]],
    customer_records: List[Dict[str, Any]],
    staging_summary: Dict[str, Any]
) -> Dict[str, Any]:
    """Build staging preview payload for response."""
    return {
        'entity_staging_preview': entity_records,
        'customer_staging_preview': customer_records,
        'staging_summary': staging_summary
    }


def perform_staging_import(
    db,
    records: List[Dict[str, Any]],
    filename: str,
    test_control: str = 'PRODUCTION',
    transaction_type_field: str = 'transaction_type',
    source: str = 'default'
) -> Dict[str, Any]:
    """
    Perform actual staging import to database.
    
    Returns: {success, entity_summary, customer_summary, errors}
    """
    entity_summary = {
        'new': 0,
        'reused': 0,
        'failed': 0
    }
    
    customer_summary = {
        'created': 0,
        'failed': 0
    }
    
    entity_cache: Dict[str, EntityStaging] = {}
    errors: List[Dict[str, Any]] = []

    normalized_source = (source or 'default').strip().lower()
    is_file_history = normalized_source == 'file_history'
    
    def safe_int_conversion(value: Any) -> Optional[int]:
        """Convert possible numeric values to int, otherwise None."""
        if value is None:
            return None
        if isinstance(value, int):
            return value
        try:
            str_value = str(value).strip()
            if not str_value:
                return None
            return int(str_value)
        except (ValueError, TypeError):
            return None
    
    try:
        for idx, record in enumerate(records):
            try:
                transaction_label = _normalize_string(record.get(transaction_type_field)) if transaction_type_field else None
                pra_grantee = _normalize_string(record.get('grantee_assignee') or record.get('Grantee')) if is_pra else None
                pra_grantor = _normalize_string(record.get('grantor_assignor') or record.get('Grantor')) if is_pra else None
                district_value = record.get('districtName') or record.get('district')
                lga_value = record.get('LGA') or record.get('lga')

                # Extract entity data
                entity_name = _extract_entity_name(record)
                if is_pra and pra_grantee:
                    entity_name = pra_grantee
                if not entity_name:
                    errors.append({
                        'record_index': idx,
                        'type': 'missing_entity_name',
                        'file_number': record.get('file_number')
                    })
                    continue
                
                descriptor = (
                    pra_grantee
                    or _normalize_string(record.get('file_title'))
                    or entity_name
                    or _normalize_string(record.get('customer_name'))
                    or filename
                )
                customer_type = _classify_customer_type(descriptor)
                
                # Extract photos
                passport_photo, company_logo = _extract_photos(record, customer_type)
                
                file_number_value = _normalize_string(
                    record.get('file_number')
                    or record.get('mlsFNo')
                    or record.get('fileno')
                    or record.get('fileNumber')
                    or record.get('MLSFileNo')
                )
                
                # Get or create entity
                cache_key = f"{entity_name}:{customer_type}"
                if cache_key in entity_cache:
                    entity = entity_cache[cache_key]
                    entity_summary['reused'] += 1
                else:
                    entity = _get_or_create_entity(
                        db,
                        entity_name,
                        customer_type,
                        file_number_value,
                        passport_photo,
                        company_logo,
                        test_control
                    )
                    entity_cache[cache_key] = entity
                    entity_summary['new'] += 1
                
                # Extract customer data
                assignor = _resolve_file_history_holder(record, 'assignor') if is_file_history else None
                assignee = _resolve_file_history_holder(record, 'assignee') if is_file_history else None
                pic_grantor = _normalize_string(record.get('Grantor')) if is_pic else None
                pic_grantee = _normalize_string(record.get('grantee_original') or record.get('Grantee')) if is_pic else None

                if is_file_history and assignor:
                    customer_name = assignor
                elif is_pic and pic_grantee:
                    customer_name = pic_grantee
                elif is_pra and pra_grantee:
                    customer_name = pra_grantee
                else:
                    customer_name = _extract_customer_name(record, entity_name)
                customer_code = _generate_customer_code()
                if is_file_history:
                    property_address = _normalize_string(record.get('location')) or _extract_customer_address(record)
                    reason_retired = transaction_label
                    notes_value = assignee
                elif is_pic:
                    combined_location = _combine_location(district_value, lga_value)
                    property_address = combined_location or _normalize_string(record.get('property_description')) or _extract_customer_address(record)
                    reason_retired = transaction_label
                    notes_value = None
                elif is_pra:
                    combined_location = _combine_location(district_value, lga_value)
                    property_address = combined_location or _extract_customer_address(record)
                    reason_retired = transaction_label
                    notes_value = pra_grantor
                else:
                    property_address = _extract_customer_address(record)
                    reason_retired = _extract_reason_retired(record, transaction_type_field)
                    notes_value = None
                
                created_by_value = safe_int_conversion(record.get('created_by'))
                
                # Create customer staging record
                customer = CustomerStaging(
                    customer_name=customer_name,
                    customer_type=customer_type,
                    customer_code=customer_code,
                    property_address=property_address,
                    notes=notes_value,
                    entity_id=entity.id,
                    created_by=created_by_value,
                    created_at=datetime.utcnow(),
                    test_control=test_control,
                    file_number=file_number_value,
                    account_no=file_number_value,
                    reason_retired=reason_retired
                )
                
                db.add(customer)
                customer_summary['created'] += 1
                
            except Exception as e:
                logger.error("Error processing record %d: %s", idx, str(e))
                entity_summary['failed'] += 1
                errors.append({
                    'record_index': idx,
                    'type': 'processing_error',
                    'error': str(e)
                })
        
        db.commit()
        
        return {
            'success': len(errors) == 0,
            'entity_summary': entity_summary,
            'customer_summary': customer_summary,
            'errors': errors
        }
        
    except Exception as e:
        db.rollback()
        logger.error("Staging import failed: %s", str(e))
        raise
