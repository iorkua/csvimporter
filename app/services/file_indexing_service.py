"""Business logic for file indexing workflows.

The helpers here were extracted from the FastAPI entrypoint to make them
importable by routers and other modules.
"""
from __future__ import annotations

import numbers
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import text

from app.models.database import CofO, FileIndexing, FileNumber, Grouping, SessionLocal
TRACKING_ID_PREFIX = 'TRK'
DEFAULT_CREATED_BY = 'MDC Import'


def _format_value(value, numeric: bool = False):
    """Format a value for display, removing unwanted .0 for numeric-like fields."""
    if pd.isna(value):
        return ''

    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime('%Y-%m-%d')

    if numeric:
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            return str(value).rstrip('0').rstrip('.')
        if isinstance(value, numbers.Integral):
            return str(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.endswith('.0') and stripped.replace('.', '', 1).isdigit():
                return stripped[:-2]
            return stripped

    return str(value).strip()


def _normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, str):
        string_value = value.strip()
        if not string_value:
            return None
        if string_value.lower() in {"nan", "none", "null", "undefined", "n/a"}:
            return None
        return string_value

    string_value = str(value).strip()
    if not string_value:
        return None
    if string_value.lower() in {"nan", "none", "null", "undefined", "n/a"}:
        return None
    return string_value


def _normalize_numeric_field(value: Any) -> Optional[str]:
    """Normalize numeric fields, removing unnecessary .0 for whole numbers."""
    if value is None or pd.isna(value):
        return None

    string_value = str(value).strip()
    if not string_value:
        return None

    try:
        float_value = float(string_value)
        if float_value.is_integer():
            return str(int(float_value))
        return str(float_value)
    except (ValueError, TypeError):
        return string_value


def _collapse_whitespace(value: str) -> str:
    if value is None:
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def _strip_all_whitespace(value: str) -> str:
    if value is None:
        return ''
    return re.sub(r'\s+', '', str(value))


def _normalize_temp_suffix_format(value: str) -> str:
    if not value:
        return value

    trimmed = str(value).strip()

    temp_patterns = [
        r'\(T\)\s*$',
        r'\(TEMP\)\s*$',
        r'TEMP\s*$',
        r'T\s*$',
    ]

    for pattern in temp_patterns:
        match = re.search(pattern, trimmed, flags=re.IGNORECASE)
        if match:
            base = trimmed[:match.start()].rstrip()
            return f"{base} (TEMP)"

    return trimmed


def _combine_location(district: str, lga: str) -> Optional[str]:
    parts = [_normalize_string(district), _normalize_string(lga)]
    parts = [part for part in parts if part]
    return ', '.join(parts) if parts else None


def _build_reg_no(record: Dict[str, Any]) -> Optional[str]:
    serial = _normalize_string(record.get('serial_no'))
    page = _normalize_string(record.get('page_no'))
    volume = _normalize_string(record.get('vol_no'))
    if serial and page and volume:
        return f"{serial}/{page}/{volume}"
    return None


def _has_cofo_payload(record: Dict[str, Any]) -> bool:
    cofo_fields = ['cofo_date', 'serial_no', 'page_no', 'vol_no', 'deeds_time', 'deeds_date']
    return any(_normalize_string(record.get(field)) for field in cofo_fields)


def _build_cofo_record(record: Dict[str, Any]) -> CofO:
    location = _combine_location(record.get('district'), record.get('lga'))
    reg_no = _build_reg_no(record)

    return CofO(
        mls_fno=_normalize_string(record.get('file_number')),
        title_type='COFO',
        transaction_type='Certificate of Occupancy',
        instrument_type='Certificate of Occupancy',
        transaction_date=_normalize_string(record.get('deeds_date') or record.get('transaction_date')),
        transaction_time=_normalize_string(record.get('deeds_time') or record.get('transaction_time')),
        serial_no=_normalize_string(record.get('serial_no')),
        page_no=_normalize_string(record.get('page_no')),
        volume_no=_normalize_string(record.get('vol_no')),
        reg_no=_normalize_string(reg_no),
        property_description=location,
        location=location,
        plot_no=_normalize_string(record.get('plot_number')),
        lgsa_or_city=_normalize_string(record.get('lga')),
        land_use=_normalize_string(record.get('land_use_type')),
        cofo_type='Legacy CofO',
        grantor='Kano State Government',
        grantee=_normalize_string(record.get('file_title')),
        cofo_date=_normalize_string(record.get('cofo_date')),
        prop_id=record.get('prop_id')
    )


def _update_cofo(target: CofO, source: CofO) -> None:
    fields_to_sync = [
        'title_type',
        'transaction_type',
        'instrument_type',
        'transaction_date',
        'transaction_time',
        'serial_no',
        'page_no',
        'volume_no',
        'reg_no',
        'property_description',
        'location',
        'plot_no',
        'lgsa_or_city',
        'land_use',
        'cofo_type',
        'grantor',
        'grantee',
        'cofo_date',
        'prop_id'
    ]

    for field in fields_to_sync:
        new_value = getattr(source, field)
        if new_value:
            setattr(target, field, new_value)


def _generate_tracking_id() -> str:
    token = uuid.uuid4().hex.upper()
    return f"{TRACKING_ID_PREFIX}-{token[:8]}-{token[8:13]}"


def _grouping_match_info(db, file_number: Optional[str]):
    if not file_number:
        return None, 'missing', 'File number is blank'

    grouping_row = db.query(Grouping).filter(Grouping.awaiting_fileno == file_number).first()
    if grouping_row:
        return grouping_row, 'matched', ''
    return None, 'missing', 'Awaiting file number not found in grouping table'


def _build_grouping_preview(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {'matched': 0, 'missing': 0, 'skipped': 0}
    rows = []

    with SessionLocal() as db:
        for record in records:
            file_number = record.get('file_number')
            grouping_row, status, reason = _grouping_match_info(db, file_number)
            summary.setdefault(status, 0)
            summary[status] += 1

            rows.append({
                'file_number': file_number,
                'status': status,
                'reason': reason,
                'shelf_rack': grouping_row.shelf_rack if grouping_row else None,
                'grouping_registry': grouping_row.registry if grouping_row else None,
                'grouping_number': grouping_row.number if grouping_row else None,
                'awaiting_fileno': grouping_row.awaiting_fileno if grouping_row else None
            })

    return {
        'rows': rows,
        'summary': summary
    }


def _apply_grouping_updates(db, record: Dict[str, Any], file_number: Optional[str], timestamp: datetime) -> Dict[str, Any]:
    shelf_location = record.get('shelf_location')
    grouping_row, status, reason = _grouping_match_info(db, file_number)

    result = {
        'status': status,
        'reason': reason,
        'shelf_location': shelf_location
    }

    if status != 'matched' or not grouping_row:
        return result

    grouping_row.mls_fileno = file_number
    grouping_row.mapping = 1
    grouping_row.date_index = timestamp
    grouping_row.indexed_by = DEFAULT_CREATED_BY

    batch_no = record.get('batch_no')
    if batch_no:
        grouping_row.mdc_batch_no = batch_no

    registry = record.get('registry')
    if registry:
        grouping_row.registry = registry

    resolved_shelf = grouping_row.shelf_rack or shelf_location
    result['shelf_location'] = resolved_shelf
    result['reason'] = ''
    return result


def _upsert_file_number(
    db,
    file_number: str,
    record: Dict[str, Any],
    tracking_id: str,
    import_filename: str,
    timestamp: datetime
) -> None:
    location = _combine_location(record.get('district'), record.get('lga')) or _normalize_string(record.get('location'))
    plot_no = _normalize_string(record.get('plot_number'))
    tp_no = _normalize_string(record.get('tp_no'))
    file_title = _normalize_string(record.get('file_title'))

    file_number_entry = db.query(FileNumber).filter(FileNumber.mlsf_no == file_number).first()

    if file_number_entry:
        if file_title:
            file_number_entry.file_name = file_title
        elif not file_number_entry.file_name and import_filename:
            file_number_entry.file_name = import_filename
        file_number_entry.location = location
        file_number_entry.plot_no = plot_no
        file_number_entry.tp_no = tp_no
        file_number_entry.tracking_id = tracking_id
        file_number_entry.type = 'MlsFileNO'
        file_number_entry.source = 'Indexing'
        file_number_entry.updated_at = timestamp
        file_number_entry.updated_by = DEFAULT_CREATED_BY
        if not file_number_entry.created_by:
            file_number_entry.created_by = DEFAULT_CREATED_BY
    else:
        file_number_entry = FileNumber(
            mlsf_no=file_number,
            file_name=file_title or import_filename or file_number,
            created_at=timestamp,
            location=location,
            created_by=DEFAULT_CREATED_BY,
            type='MlsFileNO',
            source='Indexing',
            plot_no=plot_no,
            tp_no=tp_no,
            tracking_id=tracking_id
        )
        db.add(file_number_entry)


def process_file_indexing_data(df: pd.DataFrame) -> pd.DataFrame:
    """Process CSV/Excel data according to field mappings."""
    df = df.copy()
    df.columns = [col.strip() for col in df.columns]
    normalized_columns = {col.strip().lower(): col for col in df.columns}
    numeric_like_fields = {'registry', 'batch_no', 'lpkn_no', 'serial_no', 'page_no', 'vol_no'}

    field_mappings = {
        'registry': ['Registry'],
        'batch_no': ['Batch No', 'BatchNo'],
        'file_number': ['File Number', 'FileNumber', 'Number Related File', 'Num#', 'Related File'],
        'file_title': ['File Title'],
        'land_use_type': ['Landuse', 'Land Use Type', 'Land Use'],
        'plot_number': ['Plot Number', 'PlotNumber', 'Plot Num'],
        'lpkn_no': ['LPKN No', 'LPKNNo'],
        'tp_no': ['TP No', 'TPNo'],
        'district': ['District'],
        'lga': ['LGA'],
        'location': ['Location'],
        'shelf_location': ['Shelf Location', 'ShelfLocation'],
        'cofo_date': ['CoFO Date', 'COFO Date', 'Cofo Date'],
        'serial_no': ['Serial No', 'SerialNo', 'Serial Number'],
        'page_no': ['Page No', 'PageNo', 'Page Number'],
        'vol_no': ['Vol No', 'VolNo', 'Volume No', 'Volume Number'],
        'deeds_time': ['Deeds Time', 'DeedsTime'],
        'deeds_date': ['Deeds Date', 'DeedsDate']
    }

    standardized_df = pd.DataFrame()

    for standard_field, possible_names in field_mappings.items():
        matched_column = None
        for possible_name in possible_names:
            normalized_name = possible_name.strip().lower()
            if normalized_name in normalized_columns:
                matched_column = normalized_columns[normalized_name]
                break

        if matched_column:
            treat_as_numeric = standard_field in numeric_like_fields
            standardized_df[standard_field] = df[matched_column].apply(
                lambda val: _format_value(val, numeric=treat_as_numeric)
            )
        else:
            standardized_df[standard_field] = ''

    for col in standardized_df.columns:
        if standardized_df[col].dtype == 'object':
            standardized_df[col] = standardized_df[col].astype(str).str.strip()

    standardized_df.replace('', pd.NA, inplace=True)
    standardized_df.dropna(how='all', inplace=True)
    standardized_df.fillna('', inplace=True)
    standardized_df.reset_index(drop=True, inplace=True)

    if 'file_number' in standardized_df.columns:
        standardized_df['file_number'] = standardized_df['file_number'].str.upper()

    return standardized_df


def analyze_file_number_occurrences(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    if 'file_number' not in df.columns:
        return {}

    file_number_counts = df['file_number'].value_counts()
    multiple_occurrences: Dict[str, Dict[str, Any]] = {}

    for file_number, count in file_number_counts.items():
        if count > 2 and file_number and file_number.strip():
            indices = df[df['file_number'] == file_number].index.tolist()
            multiple_occurrences[file_number] = {
                'count': count,
                'indices': indices
            }

    return multiple_occurrences


def _run_qc_validation(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    qc_issues = {
        'padding': [],
        'year': [],
        'spacing': [],
        'temp': []
    }

    for idx, record in enumerate(records):
        raw_number = (record.get('file_number') or '').replace('\u00A0', ' ')
        compact_number = _strip_all_whitespace(raw_number)

        if not compact_number:
            continue
        display_number = _collapse_whitespace(raw_number)
        base_for_spacing = raw_number.strip()

        padding_issue = _check_padding_issue(compact_number)
        if padding_issue:
            qc_issues['padding'].append({
                'record_index': idx,
                'file_number': display_number,
                'issue_type': 'padding',
                'description': 'File number has unnecessary leading zeros',
                'suggested_fix': padding_issue['suggested_fix'],
                'auto_fixable': True,
                'severity': 'Medium'
            })

        year_issue = _check_year_issue(compact_number)
        if year_issue:
            qc_issues['year'].append({
                'record_index': idx,
                'file_number': display_number,
                'issue_type': 'year',
                'description': 'File number has 2-digit year instead of 4-digit',
                'suggested_fix': year_issue['suggested_fix'],
                'auto_fixable': True,
                'severity': 'High'
            })

        spacing_issue = _check_spacing_issue(base_for_spacing)
        if spacing_issue:
            qc_issues['spacing'].append({
                'record_index': idx,
                'file_number': display_number,
                'issue_type': 'spacing',
                'description': 'File number contains unwanted spaces',
                'suggested_fix': spacing_issue['suggested_fix'],
                'auto_fixable': True,
                'severity': 'Medium'
            })

        temp_issue = _check_temp_issue(base_for_spacing)
        if temp_issue:
            qc_issues['temp'].append({
                'record_index': idx,
                'file_number': display_number,
                'issue_type': 'temp',
                'description': 'File number has improper TEMP notation format',
                'suggested_fix': temp_issue['suggested_fix'],
                'auto_fixable': True,
                'severity': 'Low'
            })

    return qc_issues


def _check_padding_issue(file_number: str) -> Optional[Dict[str, str]]:
    pattern = r'^([A-Z]+(?:-[A-Z]+)*)-(\d{4})-(0+)(\d+)(\([^)]*\))?$'
    match = re.match(pattern, file_number)
    if match:
        prefix, year, leading_zeros, number, suffix = match.groups()
        suffix = suffix or ''
        suggested_fix = _normalize_temp_suffix_format(f"{prefix}-{year}-{number}{suffix}")
        return {'suggested_fix': suggested_fix}
    return None


def _check_year_issue(file_number: str) -> Optional[Dict[str, str]]:
    pattern = r'^([A-Z]+(?:-[A-Z]+)*)-(\d{2})-(\d+)(\([^)]*\))?$'
    match = re.match(pattern, file_number)
    if match:
        prefix, year_2digit, number, suffix = match.groups()
        suffix = suffix or ''

        year_int = int(year_2digit)
        if year_int >= 50:
            year_4digit = f"19{year_2digit}"
        else:
            year_4digit = f"20{year_2digit}"

        suggested_fix = _normalize_temp_suffix_format(f"{prefix}-{year_4digit}-{number}{suffix}")
        return {'suggested_fix': suggested_fix}
    return None


def _check_spacing_issue(file_number: str) -> Optional[Dict[str, str]]:
    if not re.search(r'\s', file_number):
        return None

    base_without_temp = re.sub(r'\s*\(TEMP\)\s*$', '', file_number, flags=re.IGNORECASE)
    if not re.search(r'\s', base_without_temp):
        return None

    compact = _strip_all_whitespace(file_number)
    suggested_fix = _normalize_temp_suffix_format(compact)
    return {'suggested_fix': suggested_fix}


def _check_temp_issue(file_number: str) -> Optional[Dict[str, str]]:
    normalized = _normalize_temp_suffix_format(file_number)
    if not normalized:
        return None

    cleaned = file_number.strip()
    if cleaned == normalized:
        return None

    if re.search(r'(TEMP|\(TEMP\)|\(T\)|\bT)$', cleaned, flags=re.IGNORECASE):
        return {'suggested_fix': normalized}

    return None


def _assign_property_ids(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    property_assignments: List[Dict[str, Any]] = []
    property_counter = _get_next_property_id_counter()
    file_number_prop_cache: Dict[str, str] = {}

    for idx, record in enumerate(records):
        file_number = record.get('file_number', '').strip()
        if not file_number:
            continue

        if file_number in file_number_prop_cache:
            existing_session_prop_id = file_number_prop_cache[file_number]
            property_assignments.append({
                'record_index': idx,
                'file_number': file_number,
                'property_id': existing_session_prop_id,
                'status': 'session_reused',
                'source_table': 'current_session'
            })
            record['prop_id'] = existing_session_prop_id
            continue

        existing_prop_id = _find_existing_property_id(file_number)

        if existing_prop_id:
            property_assignments.append({
                'record_index': idx,
                'file_number': file_number,
                'property_id': existing_prop_id,
                'status': 'existing',
                'source_table': 'existing_lookup'
            })
            record['prop_id'] = existing_prop_id
            file_number_prop_cache[file_number] = existing_prop_id
        else:
            new_prop_id = str(property_counter)
            property_counter += 1

            property_assignments.append({
                'record_index': idx,
                'file_number': file_number,
                'property_id': new_prop_id,
                'status': 'new',
                'source_table': 'file_indexings'
            })
            record['prop_id'] = new_prop_id
            file_number_prop_cache[file_number] = new_prop_id

    return property_assignments


def _get_next_property_id_counter() -> int:
    db = SessionLocal()
    try:
        max_prop_id = 0

        tables_to_check = [
            (FileIndexing, FileIndexing.prop_id),
            (CofO, CofO.prop_id),
        ]

        try:
            result = db.execute(text("SELECT MAX(CAST(prop_id AS INT)) FROM property_records WHERE prop_id IS NOT NULL AND ISNUMERIC(prop_id) = 1"))
            value = result.scalar()
            if value is not None:
                max_prop_id = max(max_prop_id, value)
        except Exception:
            pass

        try:
            result = db.execute(text("SELECT MAX(CAST(prop_id AS INT)) FROM registered_instruments WHERE prop_id IS NOT NULL AND ISNUMERIC(prop_id) = 1"))
            value = result.scalar()
            if value is not None:
                max_prop_id = max(max_prop_id, value)
        except Exception:
            pass

        for model_class, prop_id_column in tables_to_check:
            try:
                max_value = db.query(prop_id_column).order_by(prop_id_column.desc()).first()
                if max_value and max_value[0] is not None:
                    try:
                        numeric_value = int(max_value[0])
                        max_prop_id = max(max_prop_id, numeric_value)
                    except (TypeError, ValueError):
                        continue
            except Exception:
                continue

        return max_prop_id + 1
    finally:
        db.close()


def _find_existing_property_id(file_number: str) -> Optional[str]:
    db = SessionLocal()
    try:
        record = db.query(FileIndexing).filter(FileIndexing.file_number == file_number, FileIndexing.prop_id.isnot(None)).first()
        if record and record.prop_id:
            return str(record.prop_id)

        record = db.query(CofO).filter(CofO.mls_fno == file_number, CofO.prop_id.isnot(None)).first()
        if record and record.prop_id:
            return str(record.prop_id)

        try:
            result = db.execute(text("""
                SELECT TOP 1 prop_id FROM property_records 
                WHERE file_number = :file_number AND prop_id IS NOT NULL
                ORDER BY created_at DESC
            """), {'file_number': file_number})
            existing_record = result.first()
            if existing_record and existing_record[0]:
                return str(existing_record[0])
        except Exception:
            pass

        try:
            result = db.execute(text("""
                SELECT prop_id FROM registered_instruments 
                WHERE MLSFileNo = :file_number AND prop_id IS NOT NULL
                ORDER BY created_at DESC
            """), {'file_number': file_number})
            reg_record = result.first()
            if reg_record and reg_record[0]:
                return str(reg_record[0])
        except Exception:
            pass

        return None
    finally:
        db.close()


__all__ = [
    'TRACKING_ID_PREFIX',
    'DEFAULT_CREATED_BY',
    '_format_value',
    '_normalize_string',
    '_normalize_numeric_field',
    '_collapse_whitespace',
    '_strip_all_whitespace',
    '_normalize_temp_suffix_format',
    '_combine_location',
    '_build_reg_no',
    '_has_cofo_payload',
    '_build_cofo_record',
    '_update_cofo',
    '_generate_tracking_id',
    '_grouping_match_info',
    '_build_grouping_preview',
    '_apply_grouping_updates',
    '_upsert_file_number',
    'process_file_indexing_data',
    'analyze_file_number_occurrences',
    '_run_qc_validation',
    '_check_padding_issue',
    '_check_year_issue',
    '_check_spacing_issue',
    '_check_temp_issue',
    '_assign_property_ids',
    '_get_next_property_id_counter',
    '_find_existing_property_id',
]
