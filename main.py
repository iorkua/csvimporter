"""
CSV Importer FastAPI Application
Clean web application with sidebar navigation
"""

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
import pandas as pd
from app.models.database import CofO, FileNumber, Grouping
import numbers
import uuid
import csv
import io
import zipfile
from typing import List, Dict, Any, Optional, Tuple, Literal
from datetime import datetime
from app.models.database import get_db_connection, FileIndexing, SessionLocal
from pydantic import BaseModel
import re

from app.services.file_indexing_service import (
    _build_cofo_record,
    _build_reg_no,
    _collapse_whitespace,
    _combine_location,
    _format_value,
    _has_cofo_payload,
    _normalize_numeric_field,
    _normalize_string,
    _normalize_temp_suffix_format,
    _strip_all_whitespace,
    _update_cofo,
    _generate_tracking_id,
)
from app.routers.file_indexing import router as file_indexing_router


app = FastAPI(title="CSV Importer")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


app.include_router(file_indexing_router)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Landing page for the CSV Importer UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/file-indexing", response_class=HTMLResponse)
async def file_indexing_page(request: Request):
    """File indexing workspace."""
    return templates.TemplateResponse("file_indexing.html", {"request": request})


@app.get("/file-history", response_class=HTMLResponse)
async def file_history_page(request: Request):
    """File history import workspace."""
    return templates.TemplateResponse("file_history_import.html", {"request": request})


@app.get("/pra", response_class=HTMLResponse)
async def pra_page(request: Request):
    """PRA import workspace."""
    return templates.TemplateResponse("pra_import.html", {"request": request})


@app.get("/pic", response_class=HTMLResponse)
async def pic_page(request: Request):
    """Property Index Card workspace."""
    return templates.TemplateResponse("property_index_card.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Placeholder settings page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/help", response_class=HTMLResponse)
async def help_page(request: Request):
    """Placeholder help page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/upload")
async def upload_redirect():
    """Redirect legacy upload link to the file indexing workflow."""
    return RedirectResponse(url="/file-indexing", status_code=307)


def process_file_indexing_data(df):
    """Process CSV/Excel data according to MULTI_TABLE_IMPORT_PLAN.md field mappings"""
    df = df.copy()

    # Normalize column names (strip whitespace, unify spacing)
    df.columns = [col.strip() for col in df.columns]

    normalized_columns = {col.strip().lower(): col for col in df.columns}

    numeric_like_fields = {'registry', 'batch_no', 'lpkn_no', 'serial_no', 'page_no', 'vol_no'}

    # Field mappings from the plan - include exact column names from Excel
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
    
    # Clean and standardize data
    for col in standardized_df.columns:
        if standardized_df[col].dtype == 'object':
            standardized_df[col] = standardized_df[col].astype(str).str.strip()

    # Remove rows where all fields are empty after trimming
    standardized_df.replace('', pd.NA, inplace=True)
    standardized_df.dropna(how='all', inplace=True)
    standardized_df.fillna('', inplace=True)
    standardized_df.reset_index(drop=True, inplace=True)

    # Uppercase file numbers for consistency
    if 'file_number' in standardized_df.columns:
        standardized_df['file_number'] = standardized_df['file_number'].str.upper()
    
    return standardized_df


@app.get("/excel-converter", response_class=HTMLResponse)
async def excel_converter(request: Request):
    """Excel to CSV converter page"""
    return templates.TemplateResponse("excel_converter.html", {"request": request})


@app.get("/api/debug-sessions")
async def list_debug_sessions():
    """List available session IDs (debug only)"""
    if not hasattr(app, 'sessions'):
        return {"sessions": []}
    return {"sessions": list(app.sessions.keys())}


@app.get("/api/debug-session/{session_id}")
async def debug_session(session_id: str):
    """Debug endpoint to see session data"""
    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        return {"error": "Session not found"}
    
    session_data = app.sessions[session_id]
    return {
        "session_exists": True,
        "filename": session_data.get("filename"),
        "total_records": session_data.get("total_records"),
        "data_count": len(session_data.get("data", [])),
        "sample_record": session_data.get("data", [{}])[0] if session_data.get("data") else {},
        "multiple_occurrences_count": len(session_data.get("multiple_occurrences", {}))
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


# ========== QC VALIDATION FUNCTIONS ==========

def _run_qc_validation(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Run quality control validation on file numbers"""
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
            
        # Check for padding issues (leading zeros)
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
        
        # Check for year format issues (2-digit year)
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
        
        # Check for spacing issues
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
        
        # Check for TEMP notation issues
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
    """Check if file number has padding issue (leading zeros in final component)"""
    pattern = r'^([A-Z]+(?:-[A-Z]+)*)-(\d{4})-(0+)(\d+)(\([^)]*\))?$'
    match = re.match(pattern, file_number)
    if match:
        prefix, year, leading_zeros, number, suffix = match.groups()
        suffix = suffix or ''
        suggested_fix = _normalize_temp_suffix_format(f"{prefix}-{year}-{number}{suffix}")
        return {'suggested_fix': suggested_fix}
    return None


def _check_year_issue(file_number: str) -> Optional[Dict[str, str]]:
    """Check if file number has 2-digit year instead of 4-digit"""
    pattern = r'^([A-Z]+(?:-[A-Z]+)*)-(\d{2})-(\d+)(\([^)]*\))?$'
    match = re.match(pattern, file_number)
    if match:
        prefix, year_2digit, number, suffix = match.groups()
        suffix = suffix or ''
        
        # Convert 2-digit to 4-digit year
        year_int = int(year_2digit)
        if year_int >= 50:  # Assuming 50-99 means 1950-1999
            year_4digit = f"19{year_2digit}"
        else:  # 00-49 means 2000-2049
            year_4digit = f"20{year_2digit}"
        
        suggested_fix = _normalize_temp_suffix_format(f"{prefix}-{year_4digit}-{number}{suffix}")
        return {'suggested_fix': suggested_fix}
    return None


def _check_spacing_issue(file_number: str) -> Optional[Dict[str, str]]:
    """Check if file number contains spaces"""
    if not re.search(r'\s', file_number):
        return None

    base_without_temp = re.sub(r'\s*\(TEMP\)\s*$', '', file_number, flags=re.IGNORECASE)
    if not re.search(r'\s', base_without_temp):
        # Only whitespace present is part of a correctly formatted TEMP suffix
        return None

    compact = _strip_all_whitespace(file_number)
    suggested_fix = _normalize_temp_suffix_format(compact)
    return {'suggested_fix': suggested_fix}
    return None


def _check_temp_issue(file_number: str) -> Optional[Dict[str, str]]:
    """Check if file number has improper TEMP notation"""
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
    """Assign property IDs to file numbers with duplicate prevention across all tables"""
    property_assignments = []
    property_counter = _get_next_property_id_counter()
    file_number_prop_cache = {}  # Cache prop_ids assigned in this session
    
    for idx, record in enumerate(records):
        file_number = record.get('file_number', '').strip()
        if not file_number:
            continue
        
        # First check if we've already assigned a prop_id to this file_number in this session
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
        
        # Check if property ID already exists for this file number in database
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
            # Cache this assignment for potential reuse in the same session
            file_number_prop_cache[file_number] = existing_prop_id
        else:
            # Generate new property ID (simple number)
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
            # Cache this assignment for potential reuse in the same session
            file_number_prop_cache[file_number] = new_prop_id
    
    return property_assignments


def _get_next_property_id_counter() -> int:
    """Get the next available property ID counter by finding the highest existing prop_id across all tables"""
    db = SessionLocal()
    try:
        max_prop_id = 0
        
        # Check all tables that have prop_id column
        tables_to_check = [
            (FileIndexing, FileIndexing.prop_id),
            (CofO, CofO.prop_id),
        ]
        
        # Also check property_records and registered_instruments using raw SQL
        # since they're not in our SQLAlchemy models
        from sqlalchemy import text
        
        # Check property_records table
        try:
            result = db.execute(text("SELECT MAX(CAST(prop_id AS INT)) FROM property_records WHERE prop_id IS NOT NULL AND ISNUMERIC(prop_id) = 1"))
            value = result.scalar()
            if value is not None:
                max_prop_id = max(max_prop_id, value)
        except Exception:
            pass  # Table might not exist or prop_id might not be numeric
            
        # Check registered_instruments table
        try:
            result = db.execute(text("SELECT MAX(CAST(prop_id AS INT)) FROM registered_instruments WHERE prop_id IS NOT NULL AND ISNUMERIC(prop_id) = 1"))
            value = result.scalar()
            if value is not None:
                max_prop_id = max(max_prop_id, value)
        except Exception:
            pass  # Table might not exist or prop_id might not be numeric
        
        # Check SQLAlchemy model tables
        for model_class, prop_id_column in tables_to_check:
            try:
                # Query for max numeric prop_id values
                result = db.query(prop_id_column).filter(
                    prop_id_column.isnot(None)
                ).all()
                
                # Convert to integers and find max
                for (prop_id,) in result:
                    if prop_id and str(prop_id).isdigit():
                        max_prop_id = max(max_prop_id, int(prop_id))
            except Exception:
                continue  # Skip if column doesn't exist or other issues
        
        return max_prop_id + 1
        
    finally:
        db.close()


def _find_existing_property_id(file_number: str) -> Optional[str]:
    """Find existing property ID for a file number across all tables"""
    db = SessionLocal()
    try:
        from sqlalchemy import text
        
        # Check in CofO table first
        cofo_record = db.query(CofO).filter(CofO.mls_fno == file_number).first()
        if cofo_record and hasattr(cofo_record, 'prop_id') and cofo_record.prop_id:
            return cofo_record.prop_id
        
        # Check in FileIndexing table
        file_record = db.query(FileIndexing).filter(FileIndexing.file_number == file_number).first()
        if file_record and hasattr(file_record, 'prop_id') and file_record.prop_id:
            return file_record.prop_id
        
        # Check in property_records table using raw SQL
        try:
            result = db.execute(text("""
                SELECT prop_id FROM property_records 
                WHERE mlsFNo = :file_number AND prop_id IS NOT NULL
                ORDER BY created_at DESC
            """), {'file_number': file_number})
            prop_record = result.first()
            if prop_record and prop_record[0]:
                return str(prop_record[0])
        except Exception:
            pass  # Table might not exist or query failed
            
        # Check in registered_instruments table using raw SQL
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
            pass  # Table might not exist or query failed
        
        return None
    finally:
        db.close()


# ========== QC API ENDPOINTS ========== 

class FileHistoryRecordUpdate(BaseModel):
    record_type: Literal['records', 'cofo']
    index: int
    field: str
    value: Optional[str] = None


class FileHistoryRecordDelete(BaseModel):
    index: int


# ========== FILE HISTORY HELPER FUNCTIONS ==========

def _parse_file_history_date(value: Any) -> Tuple[Optional[str], Optional[str]]:
    """Parse a date value from File History data into ISO format (YYYY-MM-DD)."""
    raw = _normalize_string(value)
    if not raw:
        return None, None

    try:
        parsed = pd.to_datetime(raw, dayfirst=True, errors='coerce')
        if pd.isna(parsed):
            return None, raw
        return parsed.strftime('%Y-%m-%d'), raw
    except Exception:
        return None, raw


def _parse_file_history_time(value: Any) -> Tuple[Optional[str], Optional[str]]:
    """Parse time strings such as '2:45 PM' or '14:25' into HH:MM format."""
    raw = _normalize_string(value)
    if not raw:
        return None, None

    try:
        parsed = pd.to_datetime(raw, errors='coerce')
        if pd.isna(parsed):
            return None, raw
        return parsed.strftime('%H:%M'), raw
    except Exception:
        return None, raw


def _build_file_history_cofo_record(
    *,
    file_number: Optional[str],
    transaction_type: Optional[str],
    assignor: Optional[str],
    assignee: Optional[str],
    land_use: Optional[str],
    location: Optional[str],
    transaction_date: Optional[str],
    transaction_date_raw: Optional[str],
    transaction_time: Optional[str],
    transaction_time_raw: Optional[str],
    serial_no: Optional[str],
    page_no: Optional[str],
    volume_no: Optional[str],
    reg_no: Optional[str],
    created_by: Optional[str],
    reg_date: Optional[str],
    reg_date_raw: Optional[str]
) -> Dict[str, Any]:
    return {
        'mlsFNo': file_number,
        'transaction_type': transaction_type,
        'instrument_type': transaction_type,
        'Grantor': assignor,
        'Grantee': assignee,
        'Assignor': assignor,
        'Assignee': assignee,
        'land_use': land_use,
        'property_description': location,
        'location': location,
        'transaction_date': transaction_date,
        'transaction_date_raw': transaction_date_raw,
        'transaction_time': transaction_time,
        'transaction_time_raw': transaction_time_raw,
        'serialNo': serial_no,
        'pageNo': page_no,
        'volumeNo': volume_no,
        'regNo': reg_no,
        'created_by': created_by,
        'reg_date': reg_date,
        'reg_date_raw': reg_date_raw,
        'source': 'File History',
        'migration_source': 'File History',
        'migrated_by': 'File History Import',
        'prop_id': None,
        'hasIssues': False
    }


def _process_file_history_data(df: pd.DataFrame) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Process File History CSV data into property_records and CofO payloads."""
    df.columns = df.columns.str.strip()

    property_records: List[Dict[str, Any]] = []
    cofo_records: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        file_number = _normalize_string(row.get('File Number'))
        if not file_number:
            continue

        transaction_type = _normalize_string(row.get('Transaction Type'))
        assignor = _normalize_string(row.get('Original Holder (Assignor)'))
        assignee = _normalize_string(row.get('Current Holder (Assignee)'))
        land_use = _normalize_string(row.get('Landuse'))
        location = _normalize_string(row.get('Location'))

        transaction_date, transaction_date_raw = _parse_file_history_date(row.get('Transaction Date'))
        serial_no = _normalize_numeric_field(row.get('Serial No'))
        page_no = _normalize_numeric_field(row.get('Page No'))
        volume_no = _normalize_numeric_field(row.get('Vol No'))
        reg_time, reg_time_raw = _parse_file_history_time(row.get('Reg Time'))
        reg_date, reg_date_raw = _parse_file_history_date(row.get('Reg Date'))
        created_by = _normalize_string(row.get('CreatedBy')) or 'System'
        related_file_number = _normalize_string(row.get('Related File Number'))

        reg_no = _build_pra_reg_no(serial_no, page_no, volume_no)

        property_record = {
            'mlsFNo': file_number,
            'fileno': file_number,
            'transaction_type': transaction_type,
            'transaction_date': transaction_date,
            'transaction_date_raw': transaction_date_raw,
            'serialNo': serial_no,
            'SerialNo': serial_no,
            'pageNo': page_no,
            'volumeNo': volume_no,
            'regNo': reg_no,
            'instrument_type': transaction_type,
            'Grantor': assignor,
            'Assignor': assignor,
            'Grantee': assignee,
            'Assignee': assignee,
            'property_description': location,
            'location': location,
            'streetName': None,
            'house_no': None,
            'districtName': None,
            'plot_no': None,
            'LGA': None,
            'lgsaOrCity': None,
            'land_use': land_use,
            'plot_size': None,
            'source': 'File History',
            'migration_source': 'File History',
            'migrated_by': 'File History Import',
            'prop_id': None,
            'created_by': created_by,
            'CreatedBy': created_by,
            'date_created': reg_date,
            'DateCreated': reg_date,
            'reg_date': reg_date,
            'reg_date_raw': reg_date_raw,
            'reg_time': reg_time,
            'reg_time_raw': reg_time_raw,
            'related_file_number': related_file_number,
            'created_at_display': reg_date or reg_date_raw,
            'hasIssues': False
        }

        property_records.append(property_record)

        cofo_records.append(_build_file_history_cofo_record(
            file_number=file_number,
            transaction_type=transaction_type,
            assignor=assignor,
            assignee=assignee,
            land_use=land_use,
            location=location,
            transaction_date=transaction_date,
            transaction_date_raw=transaction_date_raw,
            transaction_time=reg_time,
            transaction_time_raw=reg_time_raw,
            serial_no=serial_no,
            page_no=page_no,
            volume_no=volume_no,
            reg_no=reg_no,
            created_by=created_by,
            reg_date=reg_date,
            reg_date_raw=reg_date_raw
        ))

    return property_records, cofo_records


def _run_file_history_qc_validation(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Run PRA-style QC validation plus File History specific checks."""
    for record in records:
        record['hasIssues'] = False

    qc_results = _run_pra_qc_validation(records)

    additional_issues = {
        'missing_required_fields': [],
        'invalid_dates': [],
        'missing_reg_components': []
    }

    for idx, record in enumerate(records):
        missing_messages = []
        if not _normalize_string(record.get('transaction_type')):
            missing_messages.append('Transaction Type is missing')
        if not _normalize_string(record.get('Grantor')):
            missing_messages.append('Original Holder (Assignor) is missing')
        if not _normalize_string(record.get('Grantee')):
            missing_messages.append('Current Holder (Assignee) is missing')
        if not _normalize_string(record.get('location')):
            missing_messages.append('Location is missing')

        if missing_messages:
            additional_issues['missing_required_fields'].append({
                'row': idx + 1,
                'messages': missing_messages,
                'file_number': record.get('mlsFNo')
            })
            record['hasIssues'] = True

        serial = record.get('serialNo')
        page = record.get('pageNo')
        volume = record.get('volumeNo')
        if not (serial and page and volume):
            additional_issues['missing_reg_components'].append({
                'row': idx + 1,
                'file_number': record.get('mlsFNo'),
                'description': 'Serial, Page, and Volume numbers must all be provided'
            })
            record['hasIssues'] = True

        # Date parsing checks
        raw_txn = record.get('transaction_date_raw')
        txn_iso = record.get('transaction_date')
        if raw_txn and not txn_iso:
            additional_issues['invalid_dates'].append({
                'row': idx + 1,
                'file_number': record.get('mlsFNo'),
                'field': 'transaction_date',
                'value': raw_txn,
                'message': 'Transaction Date could not be parsed'
            })
            record['hasIssues'] = True

        raw_reg_date = record.get('reg_date_raw')
        reg_iso = record.get('reg_date')
        if raw_reg_date and not reg_iso:
            additional_issues['invalid_dates'].append({
                'row': idx + 1,
                'file_number': record.get('mlsFNo'),
                'field': 'reg_date',
                'value': raw_reg_date,
                'message': 'Registration Date could not be parsed'
            })
            record['hasIssues'] = True

    qc_results.update(additional_issues)
    return qc_results


def _detect_file_history_duplicates(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Detect duplicates for File History records (wrapper around PRA duplicate detection)."""
    return _detect_pra_duplicates(records)


def _set_property_record_field(
    record: Dict[str, Any],
    cofo_record: Optional[Dict[str, Any]],
    field: str,
    value: Optional[str]
) -> None:
    normalized = _normalize_string(value)

    if field == 'mlsFNo':
        record['mlsFNo'] = normalized
        record['fileno'] = normalized
        record['file_number'] = normalized
        if cofo_record is not None:
            cofo_record['mlsFNo'] = normalized
    elif field == 'transaction_type':
        record['transaction_type'] = normalized
        record['instrument_type'] = normalized
        if cofo_record is not None:
            cofo_record['transaction_type'] = normalized
            cofo_record['instrument_type'] = normalized
    elif field == 'Assignor':
        record['Assignor'] = normalized
        record['Grantor'] = normalized
        record['grantor_assignor'] = normalized
        if cofo_record is not None:
            cofo_record['Assignor'] = normalized
            cofo_record['Grantor'] = normalized
    elif field == 'Assignee':
        record['Assignee'] = normalized
        record['Grantee'] = normalized
        record['grantee_assignee'] = normalized
        if cofo_record is not None:
            cofo_record['Assignee'] = normalized
            cofo_record['Grantee'] = normalized
    elif field == 'land_use':
        record['land_use'] = normalized
    elif field == 'location':
        record['location'] = normalized
        record['property_description'] = normalized
        if cofo_record is not None:
            cofo_record['location'] = normalized
            cofo_record['property_description'] = normalized
    elif field == 'transaction_date':
        record['transaction_date'] = normalized
        record['transaction_date_raw'] = normalized
        if cofo_record is not None:
            cofo_record['transaction_date'] = normalized
            cofo_record['transaction_date_raw'] = normalized
    elif field == 'serialNo':
        record['serialNo'] = normalized
        record['SerialNo'] = normalized
        if cofo_record is not None:
            cofo_record['serialNo'] = normalized
    elif field == 'pageNo':
        record['pageNo'] = normalized
        if cofo_record is not None:
            cofo_record['pageNo'] = normalized
    elif field == 'volumeNo':
        record['volumeNo'] = normalized
        if cofo_record is not None:
            cofo_record['volumeNo'] = normalized
    elif field == 'reg_date':
        record['reg_date'] = normalized
        record['reg_date_raw'] = normalized
        record['date_created'] = normalized
        if cofo_record is not None:
            cofo_record['reg_date'] = normalized
            cofo_record['reg_date_raw'] = normalized
            cofo_record['cofo_date'] = normalized
    elif field == 'created_by':
        record['created_by'] = normalized
        record['CreatedBy'] = normalized
        if cofo_record is not None:
            cofo_record['created_by'] = normalized


def _set_cofo_record_field(
    cofo_record: Dict[str, Any],
    property_record: Optional[Dict[str, Any]],
    field: str,
    value: Optional[str]
) -> None:
    normalized = _normalize_string(value)

    if field == 'mlsFNo':
        cofo_record['mlsFNo'] = normalized
        if property_record is not None:
            property_record['mlsFNo'] = normalized
            property_record['fileno'] = normalized
            property_record['file_number'] = normalized
    elif field == 'transaction_type':
        cofo_record['transaction_type'] = normalized
        cofo_record['instrument_type'] = normalized
        if property_record is not None:
            property_record['transaction_type'] = normalized
            property_record['instrument_type'] = normalized
    elif field == 'Assignor':
        cofo_record['Assignor'] = normalized
        cofo_record['Grantor'] = normalized
        if property_record is not None:
            property_record['Assignor'] = normalized
            property_record['Grantor'] = normalized
            property_record['grantor_assignor'] = normalized
    elif field == 'Assignee':
        cofo_record['Assignee'] = normalized
        cofo_record['Grantee'] = normalized
        if property_record is not None:
            property_record['Assignee'] = normalized
            property_record['Grantee'] = normalized
            property_record['grantee_assignee'] = normalized
    elif field == 'transaction_date':
        cofo_record['transaction_date'] = normalized
        cofo_record['transaction_date_raw'] = normalized
        if property_record is not None:
            property_record['transaction_date'] = normalized
            property_record['transaction_date_raw'] = normalized
    elif field == 'transaction_time':
        cofo_record['transaction_time'] = normalized
        cofo_record['transaction_time_raw'] = normalized
    elif field == 'serialNo':
        cofo_record['serialNo'] = normalized
        if property_record is not None:
            property_record['serialNo'] = normalized
            property_record['SerialNo'] = normalized
    elif field == 'pageNo':
        cofo_record['pageNo'] = normalized
        if property_record is not None:
            property_record['pageNo'] = normalized
    elif field == 'volumeNo':
        cofo_record['volumeNo'] = normalized
        if property_record is not None:
            property_record['volumeNo'] = normalized
    elif field == 'regNo':
        cofo_record['regNo'] = normalized
        if property_record is not None:
            property_record['regNo'] = normalized
    elif field == 'reg_date':
        cofo_record['reg_date'] = normalized
        cofo_record['reg_date_raw'] = normalized
        cofo_record['cofo_date'] = normalized
        if property_record is not None:
            property_record['reg_date'] = normalized
            property_record['reg_date_raw'] = normalized
            property_record['date_created'] = normalized


def _apply_file_history_field_update(
    property_records: List[Dict[str, Any]],
    cofo_records: List[Dict[str, Any]],
    index: int,
    record_type: Literal['records', 'cofo'],
    field: str,
    value: Optional[str]
) -> None:
    if record_type == 'records':
        if 0 <= index < len(property_records):
            cofo_record = cofo_records[index] if index < len(cofo_records) else None
            _set_property_record_field(property_records[index], cofo_record, field, value)
    else:
        if 0 <= index < len(cofo_records):
            property_record = property_records[index] if index < len(property_records) else None
            _set_cofo_record_field(cofo_records[index], property_record, field, value)


def _refresh_file_history_session_state(session_data: Dict[str, Any]) -> Dict[str, Any]:
    property_records = session_data.get('property_records', [])
    cofo_records = session_data.get('cofo_records', [])

    qc_issues = _run_file_history_qc_validation(property_records)
    duplicates = session_data.get('duplicates') or {'csv': [], 'database': []}

    for idx, record in enumerate(property_records):
        has_issue = record.get('hasIssues', False)
        if idx < len(cofo_records):
            cofo_records[idx]['hasIssues'] = has_issue

    session_data['property_records'] = property_records
    session_data['cofo_records'] = cofo_records
    session_data['qc_issues'] = qc_issues
    session_data['duplicates'] = duplicates

    total_records = len(property_records)
    ready_records = sum(1 for rec in property_records if not rec.get('hasIssues'))
    duplicate_count = len(duplicates.get('csv', [])) + len(duplicates.get('database', []))
    validation_issues = sum(len(items) for items in qc_issues.values())

    return {
        'property_records': property_records,
        'cofo_records': cofo_records,
        'issues': qc_issues,
        'duplicates': duplicates,
        'total_records': total_records,
        'duplicate_count': duplicate_count,
        'validation_issues': validation_issues,
        'ready_records': ready_records
    }


# ========== FILE HISTORY IMPORT ENDPOINTS ==========

@app.post("/api/upload-file-history")
async def upload_file_history(file: UploadFile = File(...)):
    """Upload File History CSV/Excel file and prepare preview data."""

    try:
        if not (file.filename.endswith('.csv') or file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

        session_id = str(uuid.uuid4())
        content = await file.read()

        if file.filename.endswith('.csv'):
            dataframe = pd.read_csv(
                io.BytesIO(content),
                na_values=['', 'NULL', 'null', 'NaN'],
                keep_default_na=False
            )
        else:
            dataframe = pd.read_excel(
                io.BytesIO(content),
                na_values=['', 'NULL', 'null', 'NaN'],
                keep_default_na=False
            )

        dataframe.dropna(how='all', inplace=True)
        dataframe.dropna(axis=1, how='all', inplace=True)

        property_records, cofo_records = _process_file_history_data(dataframe)

        if not property_records:
            raise HTTPException(status_code=400, detail="No valid File History records found in the uploaded file")

        assignment_payload = [{'file_number': record.get('mlsFNo')} for record in property_records]
        assignments = _assign_property_ids(assignment_payload)
        for assignment in assignments:
            idx = assignment['record_index']
            prop_id = assignment['property_id']
            if 0 <= idx < len(property_records):
                property_records[idx]['prop_id'] = prop_id
            if 0 <= idx < len(cofo_records):
                cofo_records[idx]['prop_id'] = prop_id

        qc_issues = _run_file_history_qc_validation(property_records)
        duplicates = {"csv": [], "database": []}

        for idx, record in enumerate(property_records):
            has_issues = record.get('hasIssues', False)
            if 0 <= idx < len(cofo_records):
                cofo_records[idx]['hasIssues'] = has_issues

        total_records = len(property_records)
        duplicate_count = 0
        validation_issues = sum(len(items) for items in qc_issues.values())
        ready_records = sum(1 for rec in property_records if not rec.get('hasIssues'))

        if not hasattr(app, 'sessions'):
            app.sessions = {}

        app.sessions[session_id] = {
            "filename": file.filename,
            "upload_time": datetime.now(),
            "type": "file-history",
            "property_records": property_records,
            "cofo_records": cofo_records,
            "qc_issues": qc_issues,
            "duplicates": duplicates
        }

        return {
            "session_id": session_id,
            "filename": file.filename,
            "total_records": total_records,
            "duplicate_count": duplicate_count,
            "validation_issues": validation_issues,
            "ready_records": ready_records,
            "property_records": property_records,
            "cofo_records": cofo_records,
            "duplicates": duplicates,
            "issues": qc_issues
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


@app.post("/api/file-history/update/{session_id}")
async def update_file_history_record(session_id: str, payload: FileHistoryRecordUpdate):
    """Update a single field for a File History preview record."""

    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = app.sessions[session_id]
    if session_data.get('type') != 'file-history':
        raise HTTPException(status_code=400, detail="Invalid session type for File History update")

    _apply_file_history_field_update(
        session_data.get('property_records', []),
        session_data.get('cofo_records', []),
        payload.record_index,
        payload.record_type,
        payload.field,
        payload.value
    )

    summary = _refresh_file_history_session_state(session_data)

    return {
        "status": "success",
        "session_id": session_id,
        "property_records": summary['property_records'],
        "cofo_records": summary['cofo_records'],
        "issues": summary['issues'],
        "duplicates": summary['duplicates'],
        "total_records": summary['total_records'],
        "duplicate_count": summary['duplicate_count'],
        "validation_issues": summary['validation_issues'],
        "ready_records": summary['ready_records']
    }


@app.post("/api/file-history/delete/{session_id}")
async def delete_file_history_record(session_id: str, payload: FileHistoryRecordDelete):
    """Delete a File History preview row from the in-memory session."""

    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = app.sessions[session_id]
    if session_data.get('type') != 'file-history':
        raise HTTPException(status_code=400, detail="Invalid session type for File History delete")

    property_records = session_data.get('property_records', [])
    cofo_records = session_data.get('cofo_records', [])

    index = payload.record_index

    if payload.record_type == 'records':
        if 0 <= index < len(property_records):
            property_records.pop(index)
        if 0 <= index < len(cofo_records):
            cofo_records.pop(index)
    else:
        if 0 <= index < len(cofo_records):
            cofo_records.pop(index)
        if 0 <= index < len(property_records):
            property_records.pop(index)

    summary = _refresh_file_history_session_state(session_data)

    return {
        "status": "success",
        "session_id": session_id,
        "property_records": summary['property_records'],
        "cofo_records": summary['cofo_records'],
        "issues": summary['issues'],
        "duplicates": summary['duplicates'],
        "total_records": summary['total_records'],
        "duplicate_count": summary['duplicate_count'],
        "validation_issues": summary['validation_issues'],
        "ready_records": summary['ready_records']
    }


@app.post("/api/import-file-history/{session_id}")
async def import_file_history(session_id: str):
    """Commit File History records into property_records and CofO tables."""

    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = app.sessions[session_id]
    if session_data.get('type') != 'file-history':
        raise HTTPException(status_code=400, detail="Invalid session type for File History import")

    db = SessionLocal()
    now = datetime.utcnow()
    property_records_count = 0
    cofo_records_count = 0

    try:
        for record in session_data['property_records']:
            if record.get('hasIssues'):
                continue

            payload = {
                'mlsFNo': record.get('mlsFNo'),
                'fileno': record.get('fileno'),
                'transaction_type': record.get('transaction_type'),
                'transaction_date': record.get('transaction_date') or record.get('transaction_date_raw'),
                'serialNo': record.get('serialNo'),
                'pageNo': record.get('pageNo'),
                'volumeNo': record.get('volumeNo'),
                'regNo': record.get('regNo'),
                'instrument_type': record.get('instrument_type'),
                'Grantor': record.get('Grantor'),
                'Grantee': record.get('Grantee'),
                'property_description': record.get('property_description'),
                'location': record.get('location'),
                'streetName': record.get('streetName'),
                'house_no': record.get('house_no'),
                'districtName': record.get('districtName'),
                'plot_no': record.get('plot_no'),
                'lgsaOrCity': record.get('lgsaOrCity'),
                'source': record.get('source'),
                'plot_size': record.get('plot_size'),
                'migrated_by': record.get('migrated_by'),
                'prop_id': record.get('prop_id'),
                'created_by': record.get('created_by'),
                'date_created': record.get('date_created') or record.get('reg_date'),
                'migration_source': record.get('migration_source'),
                'created_at_override': record.get('reg_date') or record.get('date_created')
            }

            _import_property_record(db, payload, now)
            property_records_count += 1

        for record in session_data['cofo_records']:
            if record.get('hasIssues'):
                continue

            cofo_entry = CofO(
                mls_fno=record.get('mlsFNo'),
                title_type='File History',
                transaction_type=record.get('transaction_type'),
                instrument_type=record.get('instrument_type'),
                transaction_date=record.get('transaction_date') or record.get('transaction_date_raw'),
                transaction_time=record.get('transaction_time') or record.get('transaction_time_raw'),
                serial_no=record.get('serialNo'),
                page_no=record.get('pageNo'),
                volume_no=record.get('volumeNo'),
                reg_no=record.get('regNo'),
                property_description=record.get('property_description'),
                location=record.get('location'),
                plot_no=None,
                lgsa_or_city=None,
                land_use=record.get('land_use'),
                cofo_type=None,
                grantor=record.get('Grantor'),
                grantee=record.get('Grantee'),
                cofo_date=record.get('reg_date') or record.get('reg_date_raw'),
                prop_id=record.get('prop_id')
            )

            existing = db.query(CofO).filter(CofO.mls_fno == cofo_entry.mls_fno).first()
            if existing:
                _update_cofo(existing, cofo_entry)
            else:
                db.add(cofo_entry)

            cofo_records_count += 1

        db.commit()

        del app.sessions[session_id]

        return {
            "success": True,
            "imported_count": property_records_count + cofo_records_count,
            "property_records_count": property_records_count,
            "cofo_records_count": cofo_records_count
        }

    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(exc)}")
    finally:
        db.close()

# ========== PRA HELPER FUNCTIONS ==========

def _process_pra_data(df):
    """Process PRA CSV data and split into property_records and file_numbers data"""
    
    # Normalize column names to handle variations
    df.columns = df.columns.str.strip()
    
    # Create property_records data
    property_records = []
    file_numbers = []
    
    for index, row in df.iterrows():
        # Generate tracking ID
        tracking_id = _generate_tracking_id()

        # Normalize frequently used fields once
        mls_f_no = _normalize_string(row.get('mlsFNo'))
        transaction_type = _normalize_string(row.get('transaction_type'))
        transaction_date = _normalize_string(row.get('transaction_date'))
        serial_no = _normalize_numeric_field(row.get('SerialNo'))
        page_no = _normalize_numeric_field(row.get('pageNo'))
        volume_no = _normalize_numeric_field(row.get('volumeNo'))
        grantor = _normalize_string(row.get('Grantor/Assignor'))
        grantee = _normalize_string(row.get('Grantee/Assignee'))
        street_name = _normalize_string(row.get('streetName'))
        house_no = _normalize_string(row.get('house_no'))
        district_name = _normalize_string(row.get('districtName'))
        plot_no = _normalize_string(row.get('plot_no'))
        lga = _normalize_string(row.get('LGA'))
        plot_size = _normalize_string(row.get('plot_size'))
        created_by = _normalize_string(row.get('CreatedBy')) or 1
        date_created = _normalize_string(row.get('DateCreated'))

        # Build property record
        property_record = {
            'mlsFNo': mls_f_no,
            'fileno': mls_f_no,  # Same as mlsFNo
            'transaction_type': transaction_type,
            'transaction_date': transaction_date,
            'serialNo': serial_no,
            'SerialNo': serial_no,
            'pageNo': page_no,
            'volumeNo': volume_no,
            'regNo': _build_pra_reg_no(serial_no, page_no, volume_no),
            'instrument_type': transaction_type,  # Same as transaction_type
            'Grantor': grantor,
            'grantor_assignor': grantor,
            'Grantee': grantee,
            'grantee_assignee': grantee,
            'property_description': _combine_location(row.get('districtName'), row.get('LGA')),
            'location': _combine_location(row.get('districtName'), row.get('LGA')),
            'streetName': street_name,
            'house_no': house_no,
            'districtName': district_name,
            'plot_no': plot_no,
            'LGA': lga,
            'lgsaOrCity': lga,
            'source': 'PRA',
            'plot_size': plot_size,
            'migrated_by': 1,
            'created_by': created_by,
            'CreatedBy': created_by,
            'date_created': date_created,
            'DateCreated': date_created,
            'migration_source': 'PRA',
            'hasIssues': False  # Will be set by QC validation
        }

        # Build file number record
        file_number_record = {
            'mlsfNo': mls_f_no,
            'FileName': grantee,  # Grantee as filename
            'location': _combine_location(row.get('districtName'), row.get('LGA')),
            'created_by': created_by,
            'CreatedBy': created_by,
            'type': 'MLS',
            'SOURCE': 'PRA',
            'plot_no': plot_no,
            'tracking_id': tracking_id,
            'hasIssues': False  # Will be set by QC validation
        }
        
        property_records.append(property_record)
        file_numbers.append(file_number_record)
    
    return property_records, file_numbers


def _build_pra_reg_no(serial, page, volume):
    """Build regNo from SerialNo/pageNo/volumeNo"""
    if serial and page and volume:
        return f"{serial}/{page}/{volume}"
    return None


def _run_pra_qc_validation(records):
    """Run QC validation on PRA records (same rules as file indexing)"""
    qc_issues = {
        'padding': [],
        'year': [],
        'spacing': [],
        'temp': [],
        'missing_file_number': []
    }
    
    for idx, record in enumerate(records):
        file_number = _normalize_string(record.get('mlsFNo')) or ''
        
        # Check for missing file number
        if not file_number:
            qc_issues['missing_file_number'].append({
                'row': idx + 1,
                'message': 'File number is missing',
                'file_number': ''
            })
            record['hasIssues'] = True
            continue
        
        # Run same QC checks as file indexing
        padding_issue = _check_padding_issue(file_number)
        if padding_issue:
            qc_issues['padding'].append({**padding_issue, 'row': idx + 1})
            record['hasIssues'] = True
            
        year_issue = _check_year_issue(file_number)
        if year_issue:
            qc_issues['year'].append({**year_issue, 'row': idx + 1})
            record['hasIssues'] = True
            
        spacing_issue = _check_spacing_issue(file_number)
        if spacing_issue:
            qc_issues['spacing'].append({**spacing_issue, 'row': idx + 1})
            record['hasIssues'] = True
            
        temp_issue = _check_temp_issue(file_number)
        if temp_issue:
            qc_issues['temp'].append({**temp_issue, 'row': idx + 1})
            record['hasIssues'] = True
    
    return qc_issues


def _detect_pra_duplicates(records):
    """Detect duplicate file numbers within CSV and against database"""
    duplicates = {
        'csv': [],
        'database': []
    }
    
    # Check for CSV duplicates
    file_number_counts = {}
    for record in records:
        file_number = _normalize_string(record.get('mlsFNo'))
        if file_number:
            if file_number not in file_number_counts:
                file_number_counts[file_number] = []
            file_number_counts[file_number].append(record)
    
    # Find CSV duplicates (more than 1 occurrence)
    for file_number, occurrences in file_number_counts.items():
        if len(occurrences) > 1:
            duplicates['csv'].append({
                'file_number': file_number,
                'count': len(occurrences),
                'records': occurrences
            })
    
    # Check for database duplicates
    db = SessionLocal()
    try:
        from sqlalchemy import text
        
        for file_number in file_number_counts.keys():
            if file_number:
                # Check in property_records table
                result = db.execute(text("""
                    SELECT mlsFNo, Grantee, transaction_type, plot_no, prop_id 
                    FROM property_records 
                    WHERE mlsFNo = :file_number
                """), {'file_number': file_number})
                
                existing_records = result.fetchall()
                if existing_records:
                    duplicates['database'].append({
                        'file_number': file_number,
                        'count': len(existing_records),
                        'records': [dict(record._mapping) for record in existing_records]
                    })
    except Exception:
        pass  # Ignore database errors for duplicate detection
    finally:
        db.close()
    
    return duplicates


def _import_property_record(db, record, timestamp):
    """Import a single property record to property_records table"""
    from sqlalchemy import text
    
    # Check if record already exists
    existing = db.execute(text("""
        SELECT id FROM property_records WHERE mlsFNo = :file_number
    """), {'file_number': record['mlsFNo']}).first()
    
    created_at_override = record.get('created_at_override')
    created_at_value = None
    if created_at_override:
        if isinstance(created_at_override, datetime):
            created_at_value = created_at_override
        else:
            try:
                created_at_value = datetime.fromisoformat(created_at_override)
            except ValueError:
                try:
                    parsed = pd.to_datetime(created_at_override, errors='coerce', dayfirst=True)
                    if not pd.isna(parsed):
                        created_at_value = parsed.to_pydatetime()
                except Exception:
                    created_at_value = None

    params = {k: v for k, v in record.items() if k != 'created_at_override'}

    if existing:
        # Update existing record
        db.execute(text("""
            UPDATE property_records SET
                transaction_type = :transaction_type,
                transaction_date = :transaction_date,
                serialNo = :serialNo,
                pageNo = :pageNo,
                volumeNo = :volumeNo,
                regNo = :regNo,
                instrument_type = :instrument_type,
                Grantor = :Grantor,
                Grantee = :Grantee,
                property_description = :property_description,
                location = :location,
                streetName = :streetName,
                house_no = :house_no,
                districtName = :districtName,
                plot_no = :plot_no,
                lgsaOrCity = :lgsaOrCity,
                plot_size = :plot_size,
                prop_id = :prop_id,
                updated_at = :updated_at
            WHERE mlsFNo = :mlsFNo
        """), {
            **params,
            'updated_at': timestamp
        })
    else:
        # Insert new record
        db.execute(text("""
            INSERT INTO property_records (
                mlsFNo, fileno, transaction_type, transaction_date, serialNo, pageNo, volumeNo, regNo,
                instrument_type, Grantor, Grantee, property_description, location, streetName, house_no,
                districtName, plot_no, lgsaOrCity, source, plot_size, migrated_by, prop_id, created_at,
                created_by, date_created, migration_source
            ) VALUES (
                :mlsFNo, :fileno, :transaction_type, :transaction_date, :serialNo, :pageNo, :volumeNo, :regNo,
                :instrument_type, :Grantor, :Grantee, :property_description, :location, :streetName, :house_no,
                :districtName, :plot_no, :lgsaOrCity, :source, :plot_size, :migrated_by, :prop_id, :created_at,
                :created_by, :date_created, :migration_source
            )
        """), {
            **params,
            'created_at': created_at_value or timestamp
        })


def _import_file_number_record(db, record, timestamp):
    """Import a single file number record to fileNumber table"""
    from sqlalchemy import text
    
    # Check if record already exists
    existing = db.execute(text("""
        SELECT id FROM fileNumber WHERE mlsfNo = :file_number
    """), {'file_number': record['mlsfNo']}).first()
    
    if existing:
        # Update existing record
        db.execute(text("""
            UPDATE fileNumber SET
                FileName = :FileName,
                location = :location,
                plot_no = :plot_no,
                updated_at = :updated_at
            WHERE mlsfNo = :mlsfNo
        """), {
            **record,
            'updated_at': timestamp
        })
    else:
        # Insert new record
        db.execute(text("""
            INSERT INTO fileNumber (
                mlsfNo, FileName, created_at, location, created_by, type, SOURCE, plot_no, tracking_id
            ) VALUES (
                :mlsfNo, :FileName, :created_at, :location, :created_by, :type, :SOURCE, :plot_no, :tracking_id
            )
        """), {
            **record,
            'created_at': timestamp
        })


# ========== PRA IMPORT ENDPOINTS ==========

@app.post("/api/upload-pra")
async def upload_pra(file: UploadFile = File(...)):
    """Upload and process CSV/Excel file for PRA import preview"""
    
    try:
        if not (file.filename.endswith('.csv') or file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

        session_id = str(uuid.uuid4())
        content = await file.read()

        if file.filename.endswith('.csv'):
            dataframe = pd.read_csv(
                io.BytesIO(content),
                na_values=['', 'NULL', 'null', 'NaN'],
                keep_default_na=False
            )
        else:
            dataframe = pd.read_excel(
                io.BytesIO(content),
                na_values=['', 'NULL', 'null', 'NaN'],
                keep_default_na=False
            )

        # Process PRA data
        property_records, file_numbers = _process_pra_data(dataframe)
        
        # Assign property IDs to both tables
        # Get the next property ID counter that works for all tables
        next_prop_id_counter = _get_next_property_id_counter()
        
        # Assign property IDs to property records
        for i, record in enumerate(property_records):
            prop_id = str(next_prop_id_counter + i)
            record['prop_id'] = prop_id
        
        # Assign property IDs to file numbers (continue counter)
        for i, record in enumerate(file_numbers):
            prop_id = str(next_prop_id_counter + len(property_records) + i)
            record['prop_id'] = prop_id
        
        # Run QC validation on both record types
        qc_property_records = _run_pra_qc_validation(property_records)
        qc_file_numbers = _run_pra_qc_validation(file_numbers)
        
        # Combine QC results
        qc_issues = {
            'property_records': qc_property_records,
            'file_numbers': qc_file_numbers
        }
        
        # Detect duplicates for both record types
        duplicates_property = _detect_pra_duplicates(property_records)
        duplicates_file = _detect_pra_duplicates(file_numbers)
        
        # Combine duplicate results
        duplicates = {
            'property_records': duplicates_property,
            'file_numbers': duplicates_file
        }

        if not hasattr(app, 'sessions'):
            app.sessions = {}

        app.sessions[session_id] = {
            "filename": file.filename,
            "upload_time": datetime.now(),
            "type": "pra",
            "property_records": property_records,
            "file_numbers": file_numbers,
            "qc_issues": qc_issues,
            "duplicates": duplicates
        }

        # Calculate statistics
        total_records = len(property_records)
        duplicate_count = len(duplicates.get('csv', [])) + len(duplicates.get('database', []))
        validation_issues = sum(len(issues) for issues in qc_issues.values())
        ready_records = total_records - validation_issues

        return {
            "session_id": session_id,
            "filename": file.filename,
            "total_records": total_records,
            "duplicate_count": duplicate_count,
            "validation_issues": validation_issues,
            "ready_records": ready_records,
            "property_records": property_records,
            "file_numbers": file_numbers,
            "duplicates": duplicates,
            "issues": qc_issues
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


@app.post("/api/import-pra/{session_id}")
async def import_pra(session_id: str):
    """Import PRA data to property_records and fileNumber tables"""
    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = app.sessions[session_id]
    if session_data.get('type') != 'pra':
        raise HTTPException(status_code=400, detail="Invalid session type for PRA import")

    db = SessionLocal()
    property_records_count = 0
    file_numbers_count = 0
    now = datetime.utcnow()

    try:
        # Import property records
        for record in session_data["property_records"]:
            # Skip records with issues if configured to do so
            if record.get('hasIssues', False):
                continue
                
            _import_property_record(db, record, now)
            property_records_count += 1

        # Import file numbers
        for record in session_data["file_numbers"]:
            # Skip records with issues if configured to do so
            if record.get('hasIssues', False):
                continue
                
            _import_file_number_record(db, record, now)
            file_numbers_count += 1

        db.commit()

        # Clean up session
        del app.sessions[session_id]

        return {
            "success": True,
            "imported_count": property_records_count + file_numbers_count,
            "property_records_count": property_records_count,
            "file_numbers_count": file_numbers_count
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=5000,
        reload=True
    )