"""
CSV Importer FastAPI Application
Clean web application with sidebar navigation
"""

import os
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
import pandas as pd
from app.models.database import CofO, FileNumber, Grouping
from sqlalchemy import func
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
from dateutil import parser as date_parser
import uvicorn

from app.services.file_indexing_service import (
    _build_cofo_record,
    _build_reg_no,
    _collapse_whitespace,
    _combine_location,
    _format_value,
    _has_cofo_payload,
    _normalize_numeric_field,
    _normalize_old_kn_number,
    _normalize_string,
    _strip_all_whitespace,
    _update_cofo,
    _generate_tracking_id,
    _run_qc_validation,
    _classify_customer_type,
)
from app.services.staging_handler import (
    extract_entity_and_customer_data,
    build_staging_preview,
    perform_staging_import,
)
from app.routers.file_indexing import router as file_indexing_router
from app.routers.duplicate_qc import router as duplicate_qc_router
from app.routers.file_number_import import router as file_number_import_router


app = FastAPI(title="CSV Importer")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = (BASE_DIR / "docs").resolve()


app.include_router(file_indexing_router)
app.include_router(duplicate_qc_router)
app.include_router(file_number_import_router)


# ===== Helper Functions =====


def _serve_doc_file(filename: str, media_type: str, download_name: str) -> FileResponse:
    file_path = (DOCS_DIR / filename).resolve()
    if DOCS_DIR not in file_path.parents:
        raise HTTPException(status_code=404, detail="Resource not found")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Resource not found")
    return FileResponse(file_path, media_type=media_type, filename=download_name)


# ========== STAGING TABLE MAPPING ==========
# These staging tables replace property_records in their respective import flows:
STAGING_TABLES = {
    'file_history': 'file_history',      # File History import staging
    'pic': 'pic',                        # Property Index Card staging
    'pra': 'pra'                         # PRA import staging
}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Landing page for the CSV Importer UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/file-number-import", response_class=HTMLResponse)
async def file_number_import_page(request: Request):
    """File Number import guide page."""
    return templates.TemplateResponse("file_number_import.html", {"request": request})


@app.get("/file-number-import/guide")
async def file_number_import_guide():
    """Serve the File Number import guide markdown file."""
    return _serve_doc_file("FILE_NUMBER_IMPORT.md", "text/markdown", "FILE_NUMBER_IMPORT.md")


@app.get("/file-number-import/mapping")
async def file_number_import_mapping():
    """Serve the File Number import mapping markdown file."""
    return _serve_doc_file("FILE_NUMBER_IMPORT_MAPPING.md", "text/markdown", "FILE_NUMBER_IMPORT_MAPPING.md")


@app.get("/file-number-import/sample-csv")
async def file_number_import_sample_csv():
    """Serve the sample File Number CSV template."""
    return _serve_doc_file("filenumbers.csv", "text/csv", "filenumbers.csv")


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
        'deeds_date': ['Deeds Date', 'DeedsDate'],
        'created_by': ['Created By', 'CreatedBy', 'Created_By']
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
    
    # Format date and time columns for UI display
    if 'deeds_date' in standardized_df.columns:
        standardized_df['deeds_date'] = standardized_df['deeds_date'].apply(_format_date_for_ui)
    
    if 'cofo_date' in standardized_df.columns:
        standardized_df['cofo_date'] = standardized_df['cofo_date'].apply(_format_date_for_ui)
        
    if 'deeds_time' in standardized_df.columns:
        standardized_df['deeds_time'] = standardized_df['deeds_time'].apply(_format_time_for_ui)
    
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
        'spacing': []
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
        
    return qc_issues


def _check_padding_issue(file_number: str) -> Optional[Dict[str, str]]:
    """Check if file number has padding issue (leading zeros in final component)"""
    pattern = r'^([A-Z]+(?:-[A-Z]+)*)-(\d{4})-(0+)(\d+)(\([^)]*\))?$'
    match = re.match(pattern, file_number)
    if match:
        prefix, year, leading_zeros, number, suffix = match.groups()
        suffix = suffix or ''
        suggested_fix = f"{prefix}-{year}-{number}{suffix}"
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
        
        suggested_fix = f"{prefix}-{year_4digit}-{number}{suffix}"
        return {'suggested_fix': suggested_fix}
    return None


def _check_spacing_issue(file_number: str) -> Optional[Dict[str, str]]:
    """Check if file number contains spaces"""
    if not re.search(r'\s', file_number):
        return None

    trimmed = str(file_number).strip()
    suffix_text = ''
    base_value = trimmed

    suffix_match = re.search(r'\s*(\([^)]*\))$', trimmed)
    if suffix_match:
        base_value = trimmed[:suffix_match.start()].rstrip('- ')
        suffix_candidate = suffix_match.group(1)
        if suffix_candidate:
            suffix_text = suffix_candidate.strip()

    if not re.search(r'\s', base_value):
        # Allow trailing parenthetical suffixes that do not introduce extra spaces
        return None

    hyphenated = re.sub(r'\s+', '-', base_value.strip())
    hyphenated = re.sub(r'-{2,}', '-', hyphenated).strip('-')

    candidate = hyphenated if hyphenated else _strip_all_whitespace(trimmed)
    if suffix_text:
        candidate = f"{candidate} {suffix_text}".strip()

    return {'suggested_fix': candidate}


SQL_SERVER_MIN_YEAR = 1753
SQL_SERVER_MAX_YEAR = 9999
SQL_DEFAULT_FALLBACK_DATE = '1900-01-01'


def _coerce_sql_date(value: Optional[str]) -> Optional[str]:
    """Normalize incoming date strings to ISO format acceptable by SQL Server.

    Returns None when the input is missing/blank. For invalid or out-of-range
    dates, falls back to SQL_DEFAULT_FALLBACK_DATE.
    """
    normalized = _normalize_string(value)
    if not normalized:
        return None

    try:
        parsed = pd.to_datetime(normalized, errors='coerce', dayfirst=True)
    except Exception:
        parsed = None

    if parsed is not None and not pd.isna(parsed):
        try:
            year = parsed.year
        except AttributeError:
            year = parsed.to_pydatetime().year if hasattr(parsed, 'to_pydatetime') else None

        if year is not None and SQL_SERVER_MIN_YEAR <= year <= SQL_SERVER_MAX_YEAR:
            return parsed.strftime('%Y-%m-%d')
        return SQL_DEFAULT_FALLBACK_DATE

    try:
        parsed_dt = date_parser.parse(normalized, dayfirst=True, fuzzy=True)
        if SQL_SERVER_MIN_YEAR <= parsed_dt.year <= SQL_SERVER_MAX_YEAR:
            return parsed_dt.strftime('%Y-%m-%d')
        return SQL_DEFAULT_FALLBACK_DATE
    except Exception:
        return SQL_DEFAULT_FALLBACK_DATE


def _format_date_for_ui(value: Optional[str]) -> Optional[str]:
    """Format a date-like value as DD-MM-YYYY for UI display.

    Accepts ISO strings or arbitrary raw dates; returns None when parsing fails.
    """
    if not value:
        return None

    normalized = _normalize_string(value)
    if not normalized:
        return None

    try:
        parsed = pd.to_datetime(normalized, errors='coerce', dayfirst=True)
    except Exception:
        parsed = None

    if parsed is not None and not pd.isna(parsed):
        return parsed.strftime('%d-%m-%Y')

    try:
        parsed_dt = date_parser.parse(normalized, dayfirst=True, fuzzy=True)
        return parsed_dt.strftime('%d-%m-%Y')
    except Exception:
        return None


def _format_time_for_ui(value: Optional[str]) -> Optional[str]:
    """Format a time-like value to show AM/PM format for UI display.
    
    Accepts various time formats and returns formatted time with AM/PM.
    """
    if not value:
        return None
        
    normalized = _normalize_string(value)
    if not normalized:
        return None
    
    try:
        # Try parsing as datetime first (in case it includes date)
        parsed_dt = pd.to_datetime(normalized, errors='coerce')
        if parsed_dt is not None and not pd.isna(parsed_dt):
            return parsed_dt.strftime('%I:%M %p')
    except Exception:
        pass
    
    try:
        # Try parsing with dateutil for more flexible time parsing
        parsed_dt = date_parser.parse(normalized, fuzzy=True)
        return parsed_dt.strftime('%I:%M %p')
    except Exception:
        pass
    
    # Try manual parsing for common time formats
    import re
    time_patterns = [
        r'^(\d{1,2}):(\d{2})\s*(AM|PM)$',  # 12:30 PM
        r'^(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)$',  # 12:30:15 PM  
        r'^(\d{1,2}):(\d{2})$',  # 14:30 (24-hour format)
        r'^(\d{4})$',   # 1430 (military time - 4 digits)
    ]
    
    for i, pattern in enumerate(time_patterns):
        match = re.match(pattern, normalized.upper())
        if match:
            try:
                if len(match.groups()) >= 3 and match.group(3) in ['AM', 'PM']:
                    # Already has AM/PM
                    hour = int(match.group(1))
                    minute = int(match.group(2))
                    period = match.group(3)
                    return f"{hour:02d}:{minute:02d} {period}"
                elif i == 3:  # Military time pattern (4 digits)
                    time_str = match.group(1)
                    if len(time_str) == 4:
                        hour = int(time_str[:2])
                        minute = int(time_str[2:])
                        
                        if hour == 0:
                            return f"12:{minute:02d} AM"
                        elif hour < 12:
                            return f"{hour}:{minute:02d} AM"
                        elif hour == 12:
                            return f"12:{minute:02d} PM"
                        else:
                            return f"{hour-12}:{minute:02d} PM"
                else:
                    # Convert 24-hour to 12-hour with AM/PM
                    hour = int(match.group(1))
                    minute = int(match.group(2))
                    
                    if hour == 0:
                        return f"12:{minute:02d} AM"
                    elif hour < 12:
                        return f"{hour}:{minute:02d} AM"
                    elif hour == 12:
                        return f"12:{minute:02d} PM"
                    else:
                        return f"{hour-12}:{minute:02d} PM"
            except (ValueError, IndexError):
                continue
    
    return None
def _apply_ui_date_format_to_session_records(property_records: List[Dict[str, Any]],
                                             cofo_records: Optional[List[Dict[str, Any]]] = None,
                                             file_number_records: Optional[List[Dict[str, Any]]] = None) -> None:
    """Mutate session record lists to format commonly used date fields for UI (DD-MM-YYYY) and time fields (AM/PM).

    This preserves any *_raw fields and replaces the display-ready keys.
    """
    date_fields = [
        'transaction_date', 'reg_date', 'date_created', 'cofo_date', 'deeds_date',
        'assignment_date', 'surrender_date', 'revoked_date', 'date_expired',
        'lease_begins', 'lease_expires', 'date_recommended', 'date_approved'
    ]
    
    time_fields = [
        'deeds_time', 'transaction_time', 'reg_time'
    ]

    def fmt_date(rec: Dict[str, Any], field: str):
        raw = rec.get(field) or rec.get(f"{field}_raw") or rec.get('created_at_override')
        ui = _format_date_for_ui(raw)
        if ui:
            rec[field] = ui
            
    def fmt_time(rec: Dict[str, Any], field: str):
        raw = rec.get(field) or rec.get(f"{field}_raw")
        ui = _format_time_for_ui(raw)
        if ui:
            rec[field] = ui

    for rec in property_records:
        for f in date_fields:
            fmt_date(rec, f)
        for f in time_fields:
            fmt_time(rec, f)

    if cofo_records:
        for rec in cofo_records:
            for f in date_fields:
                fmt_date(rec, f)
            for f in time_fields:
                fmt_time(rec, f)

    if file_number_records:
        for rec in file_number_records:
            for f in date_fields:
                fmt_date(rec, f)
            for f in time_fields:
                fmt_time(rec, f)


def _assign_property_ids(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Assign property IDs to file numbers with duplicate prevention across all tables"""
    property_assignments = []
    property_counter = _get_next_property_id_counter()
    file_number_prop_cache = {}  # Cache prop_ids assigned in this session
    
    for idx, record in enumerate(records):
        file_number = _normalize_string(record.get('file_number'))
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


class FileHistoryClearDataRequest(BaseModel):
    mode: str


# ========== PIC Pydantic Models ==========

class PICRecordUpdate(BaseModel):
    record_type: Literal['records', 'cofo', 'file_numbers']
    index: int
    field: str
    value: Optional[str] = None


class PICRecordDelete(BaseModel):
    index: int
    record_type: Literal['records', 'cofo', 'file_numbers'] = 'records'


class PICClearDataRequest(BaseModel):
    mode: str


class PRAClearDataRequest(BaseModel):
    mode: str


class PRARecordUpdate(BaseModel):
    record_type: Literal['property_records', 'file_numbers', 'cofo']
    record_index: int
    field: str
    value: Optional[str] = None


class PRARecordDelete(BaseModel):
    record_type: Literal['property_records', 'file_numbers', 'cofo'] = 'property_records'
    record_index: int


# ========== FILE HISTORY HELPER FUNCTIONS ==========

def _parse_file_history_date(value: Any) -> Tuple[Optional[str], Optional[str]]:
    """Parse a date value from File History data into ISO format (YYYY-MM-DD)."""
    raw = _normalize_string(value)
    if not raw:
        return None, None

    try:
        parsed = pd.to_datetime(raw, dayfirst=True, errors='coerce')
    except Exception:
        parsed = None

    if parsed is not None and not pd.isna(parsed):
        return parsed.strftime('%Y-%m-%d'), raw

    try:
        parsed_dt = date_parser.parse(raw, dayfirst=True, fuzzy=True)
        return parsed_dt.strftime('%Y-%m-%d'), raw
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


def _is_cofo_indicator(value: Optional[str]) -> bool:
    normalized = _normalize_string(value)
    if not normalized:
        return False

    lowered = normalized.lower()

    if 'certificate of occup' in lowered:
        return True

    if re.search(r"\bc[\W_]*o[\W_]*f[\W_]*o\b", lowered):
        return True

    return False


def _build_file_history_cofo_record(
    *,
    file_number: Optional[str],
    transaction_type: Optional[str],
    assignor: Optional[str],
    assignee: Optional[str],
    mortgagor: Optional[str],
    mortgagee: Optional[str],
    instrument_type: Optional[str],
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
        'instrument_type': instrument_type or transaction_type,
        'Grantor': assignor,
        'Grantee': assignee,
        'Assignor': assignor,
        'Assignee': assignee,
        'Mortgagor': mortgagor,
        'Mortgagee': mortgagee,
        'grantor_assignor': assignor,
        'grantee_assignee': assignee,
        'land_use': land_use,
        'property_description': location,
        'location': location,
        'transaction_date': transaction_date,
        'transaction_date_raw': transaction_date_raw,
        'transaction_time': transaction_time,
        'transaction_time_raw': transaction_time_raw,
        'reg_time': transaction_time,
        'reg_time_raw': transaction_time_raw,
        'serialNo': serial_no,
        'pageNo': page_no,
        'volumeNo': volume_no,
        'regNo': reg_no,
        'created_by': created_by,
        'reg_date': reg_date,
        'reg_date_raw': reg_date_raw,
        'cofo_date': reg_date,
        'source': 'File History',
        'migration_source': 'File History',
        'migrated_by': 'File History Import',
        'prop_id': None,
        'hasIssues': False,
        'is_cofo_record': True,
        'skip_import': False,
        'skip_reason': None
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

        instrument_type_value = (
            _normalize_string(row.get('Instrument Type'))
            or _normalize_string(row.get('Instrument_type'))
            or _normalize_string(row.get('InstrumentType'))
            or _normalize_string(row.get('instrument_type'))
        )

        transaction_type_column_value = (
            _normalize_string(row.get('Transaction Type'))
            or _normalize_string(row.get('TransactionType'))
            or _normalize_string(row.get('transaction_type'))
        )

        transaction_type = transaction_type_column_value or instrument_type_value

        record_type = (
            _normalize_string(row.get('Record Type'))
            or _normalize_string(row.get('RecordType'))
            or _normalize_string(row.get('record_type'))
        )

        title_type = (
            _normalize_string(row.get('Title Type'))
            or _normalize_string(row.get('TitleType'))
            or _normalize_string(row.get('title_type'))
        )

        is_cofo_record = _is_cofo_indicator(transaction_type_column_value)

        assignor = (
            _normalize_string(row.get('Original Holder (Assignor)'))
            or _normalize_string(row.get('Assignor'))
            or _normalize_string(row.get('Grantor'))
            or _normalize_string(row.get('Original Holder'))
        )

        assignee = (
            _normalize_string(row.get('Current Holder (Assignee)'))
            or _normalize_string(row.get('Assignee'))
            or _normalize_string(row.get('Grantee'))
            or _normalize_string(row.get('Assignee (Current Holder)'))
            or _normalize_string(row.get('Current Holder'))
        )

        mortgagor = (
            _normalize_string(row.get('Mortgagor'))
            or _normalize_string(row.get('Mortgagor Name'))
            or _normalize_string(row.get('MortgagorName'))
            or _normalize_string(row.get('Mortgagor/Assignor'))
        )

        mortgagee = (
            _normalize_string(row.get('Mortgagee'))
            or _normalize_string(row.get('Mortgagee Name'))
            or _normalize_string(row.get('MortgageeName'))
            or _normalize_string(row.get('Mortgagee/Assignee'))
        )

        is_mortgage_transaction = False
        for value in (instrument_type_value, transaction_type):
            if value and 'MORTGAGE' in value.upper():
                is_mortgage_transaction = True
                break

        if is_mortgage_transaction:
            if not mortgagor and assignee:
                mortgagor = assignee
            if not mortgagee and assignor:
                mortgagee = assignor
        land_use = _normalize_string(row.get('Landuse'))
        location = _normalize_string(row.get('Location'))

        transaction_date, transaction_date_raw = _parse_file_history_date(row.get('Transaction Date'))
        serial_no = _normalize_numeric_field(row.get('Serial No'))
        page_no = _normalize_numeric_field(row.get('Page No'))
        volume_no = _normalize_numeric_field(row.get('Vol No'))
        reg_time, reg_time_raw = _parse_file_history_time(row.get('Reg Time'))
        reg_date, reg_date_raw = _parse_file_history_date(row.get('Reg Date'))

        # Some extracts provide a combined "Reg Date Reg Time" column; split into discrete values.
        combined_reg_datetime = _normalize_string(row.get('Reg Date Reg Time'))
        if combined_reg_datetime and (not reg_date or not reg_time):
            parsed_combined = None
            try:
                parsed_combined = pd.to_datetime(combined_reg_datetime, dayfirst=True, errors='coerce')
            except Exception:
                parsed_combined = None

            if parsed_combined is not None and not pd.isna(parsed_combined):
                if not reg_date:
                    reg_date = parsed_combined.strftime('%Y-%m-%d')
                if not reg_date_raw:
                    reg_date_raw = combined_reg_datetime
                if not reg_time:
                    reg_time = parsed_combined.strftime('%H:%M')
                if not reg_time_raw:
                    reg_time_raw = combined_reg_datetime
            else:
                try:
                    parsed_dt = date_parser.parse(combined_reg_datetime, dayfirst=True, fuzzy=True)
                except Exception:
                    parsed_dt = None

                if parsed_dt is not None:
                    if not reg_date:
                        reg_date = parsed_dt.strftime('%Y-%m-%d')
                    if not reg_date_raw:
                        reg_date_raw = combined_reg_datetime
                    if not reg_time:
                        reg_time = parsed_dt.strftime('%H:%M')
                    if not reg_time_raw:
                        reg_time_raw = combined_reg_datetime

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
            'instrument_type': instrument_type_value or transaction_type,
            'record_type': record_type,
            'title_type': title_type,
            'Grantor': assignor,
            'Assignor': assignor,
            'grantor_assignor': assignor,
            'Grantee': assignee,
            'Assignee': assignee,
            'grantee_assignee': assignee,
            'Mortgagor': mortgagor,
            'Mortgagee': mortgagee,
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
            'hasIssues': False,
            'is_cofo_record': is_cofo_record
        }

        property_records.append(property_record)

        if is_cofo_record:
            cofo_record = _build_file_history_cofo_record(
                file_number=file_number,
                transaction_type=transaction_type,
                assignor=assignor,
                assignee=assignee,
                mortgagor=mortgagor,
                mortgagee=mortgagee,
                instrument_type=instrument_type_value,
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
            )
        else:
            cofo_record = {
                'mlsFNo': file_number,
                'transaction_type': transaction_type,
                'instrument_type': instrument_type_value or transaction_type,
                'Grantor': assignor,
                'Grantee': assignee,
                'Assignor': assignor,
                'Assignee': assignee,
                'prop_id': None,
                'test_control': None,
                'hasIssues': False,
                'is_cofo_record': False,
                'skip_import': True,
                'skip_reason': 'Transaction Type is not CofO'
            }

        cofo_records.append(cofo_record)

    return property_records, cofo_records


def _run_file_history_qc_validation(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Run File History QC using the File Indexing style buckets."""

    qc_issues = {
        'padding': [],
        'year': [],
        'spacing': [],
        'missing_file_number': []
    }

    for idx, record in enumerate(records):
        record['hasIssues'] = False

        raw_number = (record.get('mlsFNo') or record.get('file_number') or '')
        raw_number = raw_number.replace('\u00A0', ' ')
        compact_number_raw = _strip_all_whitespace(raw_number)

        if not compact_number_raw:
            qc_issues['missing_file_number'].append({
                'record_index': idx,
                'row': idx + 1,
                'issue_type': 'missing_file_number',
                'file_number': '',
                'description': 'File number is missing',
                'message': 'File number is missing',
                'suggested_fix': None,
                'auto_fixable': False,
                'severity': 'High'
            })
            record['hasIssues'] = True
            continue

        display_number = _collapse_whitespace(raw_number)
        base_for_spacing = raw_number.strip()
        compact_number = compact_number_raw.upper()

        padding_issue = _check_padding_issue(compact_number)
        if padding_issue:
            qc_issues['padding'].append({
                'record_index': idx,
                'row': idx + 1,
                'issue_type': 'padding',
                'file_number': display_number,
                'description': 'File number has unnecessary leading zeros',
                'suggested_fix': padding_issue['suggested_fix'],
                'auto_fixable': True,
                'severity': 'Medium'
            })
            record['hasIssues'] = True

        year_issue = _check_year_issue(compact_number)
        if year_issue:
            qc_issues['year'].append({
                'record_index': idx,
                'row': idx + 1,
                'issue_type': 'year',
                'file_number': display_number,
                'description': 'File number has 2-digit year instead of 4-digit',
                'suggested_fix': year_issue['suggested_fix'],
                'auto_fixable': True,
                'severity': 'High'
            })
            record['hasIssues'] = True

        spacing_issue = _check_spacing_issue(base_for_spacing)
        if spacing_issue:
            qc_issues['spacing'].append({
                'record_index': idx,
                'row': idx + 1,
                'issue_type': 'spacing',
                'file_number': display_number,
                'description': 'File number contains unwanted spaces',
                'suggested_fix': spacing_issue['suggested_fix'],
                'auto_fixable': True,
                'severity': 'Medium'
            })
            record['hasIssues'] = True

    return qc_issues


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

    if field in ('Assignor', 'Grantor', 'grantor_assignor'):
        record['Assignor'] = normalized
        record['Grantor'] = normalized
        record['grantor_assignor'] = normalized
        if cofo_record is not None:
            cofo_record['Assignor'] = normalized
            cofo_record['Grantor'] = normalized
            cofo_record['grantor_assignor'] = normalized
        return

    if field in ('Assignee', 'Grantee', 'grantee_assignee'):
        record['Assignee'] = normalized
        record['Grantee'] = normalized
        record['grantee_assignee'] = normalized
        if cofo_record is not None:
            cofo_record['Assignee'] = normalized
            cofo_record['Grantee'] = normalized
            cofo_record['grantee_assignee'] = normalized
        return

    if field == 'Mortgagor':
        record['Mortgagor'] = normalized
        if cofo_record is not None:
            cofo_record['Mortgagor'] = normalized
        return

    if field == 'Mortgagee':
        record['Mortgagee'] = normalized
        if cofo_record is not None:
            cofo_record['Mortgagee'] = normalized
        return

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
        _recalculate_pic_serial_state(record, cofo_record)
    elif field == 'oldKNNo':
        record['oldKNNo'] = normalized
        if cofo_record is not None:
            cofo_record['oldKNNo'] = normalized
        _recalculate_pic_serial_state(record, cofo_record)
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
    elif field == 'reg_time':
        record['reg_time'] = normalized
        record['reg_time_raw'] = normalized
        if cofo_record is not None:
            cofo_record['transaction_time'] = normalized
            cofo_record['transaction_time_raw'] = normalized
            cofo_record['reg_time'] = normalized
            cofo_record['reg_time_raw'] = normalized
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

    if field in ('Assignor', 'Grantor', 'grantor_assignor'):
        cofo_record['Assignor'] = normalized
        cofo_record['Grantor'] = normalized
        cofo_record['grantor_assignor'] = normalized
        if property_record is not None:
            property_record['Assignor'] = normalized
            property_record['Grantor'] = normalized
            property_record['grantor_assignor'] = normalized
        return

    if field in ('Assignee', 'Grantee', 'grantee_assignee'):
        cofo_record['Assignee'] = normalized
        cofo_record['Grantee'] = normalized
        cofo_record['grantee_assignee'] = normalized
        if property_record is not None:
            property_record['Assignee'] = normalized
            property_record['Grantee'] = normalized
            property_record['grantee_assignee'] = normalized
        return

    if field == 'Mortgagor':
        cofo_record['Mortgagor'] = normalized
        if property_record is not None:
            property_record['Mortgagor'] = normalized
        return

    if field == 'Mortgagee':
        cofo_record['Mortgagee'] = normalized
        if property_record is not None:
            property_record['Mortgagee'] = normalized
        return

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
    elif field == 'transaction_date':
        cofo_record['transaction_date'] = normalized
        cofo_record['transaction_date_raw'] = normalized
        if property_record is not None:
            property_record['transaction_date'] = normalized
            property_record['transaction_date_raw'] = normalized
    elif field == 'transaction_time':
        cofo_record['transaction_time'] = normalized
        cofo_record['transaction_time_raw'] = normalized
        cofo_record['reg_time'] = normalized
        cofo_record['reg_time_raw'] = normalized
        if property_record is not None:
            property_record['reg_time'] = normalized
            property_record['reg_time_raw'] = normalized
    elif field == 'serialNo':
        cofo_record['serialNo'] = normalized
        if property_record is not None:
            property_record['serialNo'] = normalized
            property_record['SerialNo'] = normalized
            _recalculate_pic_serial_state(property_record, cofo_record)
    elif field == 'oldKNNo':
        cofo_record['oldKNNo'] = normalized
        if property_record is not None:
            property_record['oldKNNo'] = normalized
            _recalculate_pic_serial_state(property_record, cofo_record)
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
            cofo_entry = cofo_records[idx]
            if cofo_entry and cofo_entry.get('is_cofo_record'):
                cofo_entry['hasIssues'] = has_issue
            elif cofo_entry:
                cofo_entry['hasIssues'] = False
                cofo_entry['skip_import'] = True
                if not cofo_entry.get('skip_reason'):
                    cofo_entry['skip_reason'] = 'Transaction Type is not CofO'

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
        'ready_records': ready_records,
        'test_control': session_data.get('test_control')
    }


# ========== FILE HISTORY IMPORT ENDPOINTS ==========

@app.post("/api/upload-file-history")
async def upload_file_history(test_control: str = Form(...), file: UploadFile = File(...)):
    """Upload File History CSV/Excel file and prepare preview data."""

    try:
        mode = (test_control or '').strip().upper()
        if mode not in {'TEST', 'PRODUCTION'}:
            raise HTTPException(status_code=400, detail="Invalid data mode. Choose TEST or PRODUCTION.")

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

        for record in property_records:
            record['test_control'] = mode

        for record in cofo_records:
            record['test_control'] = mode

        assignment_payload = [{'file_number': record.get('mlsFNo')} for record in property_records]
        assignments = _assign_property_ids(assignment_payload)
        for assignment in assignments:
            idx = assignment['record_index']
            prop_id = assignment['property_id']
            if 0 <= idx < len(property_records):
                property_records[idx]['prop_id'] = prop_id
            if 0 <= idx < len(cofo_records):
                cofo_entry = cofo_records[idx]
                if cofo_entry and cofo_entry.get('is_cofo_record'):
                    cofo_entry['prop_id'] = prop_id

        qc_issues = _run_file_history_qc_validation(property_records)
        duplicates = {"csv": [], "database": []}

        for idx, record in enumerate(property_records):
            has_issues = record.get('hasIssues', False)
            if 0 <= idx < len(cofo_records):
                cofo_entry = cofo_records[idx]
                if cofo_entry and cofo_entry.get('is_cofo_record'):
                    cofo_entry['hasIssues'] = has_issues

        total_records = len(property_records)
        duplicate_count = 0
        validation_issues = sum(len(items) for items in qc_issues.values())
        ready_records = sum(1 for rec in property_records if not rec.get('hasIssues'))

        if not hasattr(app, 'sessions'):
            app.sessions = {}

        # Format dates for UI preview
        _apply_ui_date_format_to_session_records(property_records, cofo_records)

        # ✅ NEW: Extract staging data (entity and customer)
        entity_records, customer_records, staging_summary = extract_entity_and_customer_data(
            property_records,
            file.filename,
            mode,
            transaction_type_field='transaction_type',
            source='file_history'
        )

        app.sessions[session_id] = {
            "filename": file.filename,
            "upload_time": datetime.now(),
            "type": "file-history",
            "test_control": mode,
            "property_records": property_records,
            "cofo_records": cofo_records,
            "qc_issues": qc_issues,
            "duplicates": duplicates,
            # ✅ NEW: Store staging data
            "entity_staging_records": entity_records,
            "customer_staging_records": customer_records,
            "staging_summary": staging_summary
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
            "issues": qc_issues,
            "test_control": mode,
            # ✅ NEW: Include staging in response
            "staging_summary": staging_summary,
            "entity_staging_preview": entity_records,
            "customer_staging_preview": customer_records
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
        "ready_records": summary['ready_records'],
        "test_control": session_data.get('test_control')
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
        "ready_records": summary['ready_records'],
        "test_control": session_data.get('test_control')
    }


@app.post("/api/import-file-history/{session_id}")
async def import_file_history(session_id: str):
    """Commit File History records into file_history and CofO_staging tables."""

    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = app.sessions[session_id]
    if session_data.get('type') != 'file-history':
        raise HTTPException(status_code=400, detail="Invalid session type for File History import")

    db = SessionLocal()
    now = datetime.utcnow()
    property_records_count = 0
    cofo_records_count = 0
    mode = (session_data.get('test_control') or 'PRODUCTION').upper()

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
                'oldKNNo': record.get('oldKNNo'),
                'pageNo': record.get('pageNo'),
                'volumeNo': record.get('volumeNo'),
                'regNo': record.get('regNo'),
                'instrument_type': record.get('instrument_type'),
                'Grantor': record.get('Grantor'),
                'Grantee': record.get('Grantee'),
                'Assignor': record.get('Assignor'),
                'Assignee': record.get('Assignee'),
                'Mortgagor': record.get('Mortgagor'),
                'Mortgagee': record.get('Mortgagee'),
                'Surrenderor': record.get('Surrenderor'),
                'Surrenderee': record.get('Surrenderee'),
                'Lessor': record.get('Lessor'),
                'Lessee': record.get('Lessee'),
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
                'created_at_override': record.get('reg_date') or record.get('date_created'),
                'test_control': mode
            }

            _import_property_record(db, payload, now, allow_update=False, staging_table='file_history')
            property_records_count += 1

        for record in session_data['cofo_records']:
            if record.get('hasIssues'):
                continue
            if not record.get('is_cofo_record'):
                continue
            if record.get('skip_import'):
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
                prop_id=record.get('prop_id'),
                test_control=mode
            )

            existing = db.query(CofO).filter(CofO.mls_fno == cofo_entry.mls_fno).first()
            if existing:
                _update_cofo(existing, cofo_entry)
            else:
                db.add(cofo_entry)

            cofo_records_count += 1

        # Import staging data (entities and customers with reason_retired)
        staging_result = perform_staging_import(
            db,
            session_data.get('property_records', []),
            session_data.get('filename', 'file_history_upload.csv'),
            session_data.get('test_control', 'PRODUCTION'),
            'transaction_type',
            source='file_history',
            precomputed_entities=session_data.get('entity_staging_records'),
            precomputed_customers=session_data.get('customer_staging_records')
        )

        db.commit()

        del app.sessions[session_id]

        return {
            "success": True,
            "imported_count": property_records_count + cofo_records_count,
            "property_records_count": property_records_count,
            "cofo_records_count": cofo_records_count,
            "staging_import": {
                "entity_summary": staging_result.get('entity_summary', {}),
                "customer_summary": staging_result.get('customer_summary', {}),
                "errors": staging_result.get('errors', [])
            },
            "test_control": mode
        }

    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(exc)}")
    finally:
        db.close()

# ========== FILE HISTORY CLEAR DATA ==========


@app.post("/api/file-history/clear-data")
async def clear_file_history_data(request: FileHistoryClearDataRequest):
    mode = (request.mode or '').strip().upper()
    if mode not in {"TEST", "PRODUCTION"}:
        raise HTTPException(status_code=400, detail="Invalid data mode. Choose TEST or PRODUCTION.")

    db = SessionLocal()

    try:
        from sqlalchemy import text

        property_result = db.execute(
            text(
                "DELETE FROM file_history WHERE test_control = :mode AND (source = :source OR migration_source = :source)"
            ),
            {"mode": mode, "source": "File History"}
        )
        property_deleted = property_result.rowcount if property_result is not None else 0

        cofo_deleted = db.query(CofO).filter(
            CofO.test_control == mode,
            CofO.title_type == 'File History'
        ).delete(synchronize_session=False)

        db.commit()
        return {
            "success": True,
            "mode": mode,
            "counts": {
                "file_history": property_deleted,
                "CofO_staging": cofo_deleted,
                "fileNumber": 0
            }
        }
    except Exception as exc:  # pragma: no cover - safeguard against cascading deletes
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to clear {mode} data: {exc}")
    finally:
        db.close()


# ========== PIC IMPORT ENDPOINTS ==========

@app.post("/api/upload-pic")
async def upload_pic(test_control: str = Form(...), file: UploadFile = File(...)):
    """Upload PIC CSV/Excel file and prepare preview data."""

    try:
        mode = (test_control or '').strip().upper()
        if mode not in {"TEST", "PRODUCTION"}:
            raise HTTPException(status_code=400, detail="Invalid data mode. Choose TEST or PRODUCTION.")

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

        property_records, cofo_records, file_number_records = _process_pic_data(dataframe)

        if not property_records:
            raise HTTPException(status_code=400, detail="No valid PIC records found in the uploaded file")

        # Extract staging data (entities and customers with reason_retired)
        entity_records, customer_records, staging_summary = extract_entity_and_customer_data(
            property_records,
            file.filename,
            mode,
            transaction_type_field='transaction_type',
            source='pic'
        )

        # Apply PIC-specific deduplication rules (before property ID assignment)
        # Property Records: kept all, CofO/File Numbers/Entities: deduplicated, Customers: kept all
        property_records, cofo_records, file_number_records, entity_records = _deduplicate_pic_records(
            property_records,
            cofo_records,
            file_number_records,
            entity_records
        )

        assignments = _assign_property_ids(property_records)
        for assignment in assignments:
            idx = assignment['record_index']
            prop_id = assignment['property_id']
            source = assignment.get('status')
            if 0 <= idx < len(property_records):
                property_records[idx]['prop_id_source'] = source
            if 0 <= idx < len(cofo_records):
                cofo_records[idx]['prop_id'] = prop_id
                cofo_records[idx]['prop_id_source'] = source
                cofo_records[idx]['oldKNNo'] = property_records[idx].get('oldKNNo')
            # File number records no longer need prop_id assignment

        qc_issues = _run_pic_qc_validation(property_records)

        for idx, record in enumerate(property_records):
            has_issues = record.get('hasIssues', False)
            if idx < len(cofo_records):
                cofo_records[idx]['hasIssues'] = has_issues
                cofo_records[idx]['oldKNNo'] = record.get('oldKNNo')

        for entry in file_number_records:
            source_index = entry.get('property_index')
            if isinstance(source_index, int) and 0 <= source_index < len(property_records):
                entry['hasIssues'] = property_records[source_index].get('hasIssues', False)

        total_records = len(property_records)
        validation_issues = sum(len(items) for items in qc_issues.values())
        ready_records = sum(1 for rec in property_records if not rec.get('hasIssues'))

        if not hasattr(app, 'sessions'):
            app.sessions = {}

        # Format dates for UI preview
        _apply_ui_date_format_to_session_records(property_records, cofo_records, file_number_records)

        app.sessions[session_id] = {
            "filename": file.filename,
            "upload_time": datetime.now(),
            "type": "pic",
            "test_control": mode,
            "property_records": property_records,
            "cofo_records": cofo_records,
            "file_number_records": file_number_records,
            "qc_issues": qc_issues,
            "property_assignments": assignments,
            "entity_staging_records": entity_records,
            "customer_staging_records": customer_records,
            "staging_summary": staging_summary
        }

        return {
            "session_id": session_id,
            "filename": file.filename,
            "test_control": mode,
            "total_records": total_records,
            "validation_issues": validation_issues,
            "ready_records": ready_records,
            "property_records": property_records,
            "cofo_records": cofo_records,
            "file_number_records": file_number_records,
            "issues": qc_issues,
            "property_assignments": assignments,
            "staging_summary": staging_summary,
            "entity_staging_preview": entity_records,
            "customer_staging_preview": customer_records
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


@app.post("/api/pic/update/{session_id}")
async def update_pic_record(session_id: str, payload: PICRecordUpdate):
    """Update a single field for a PIC preview record."""

    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = app.sessions[session_id]
    if session_data.get('type') != 'pic':
        raise HTTPException(status_code=400, detail="Invalid session type for PIC update")

    _apply_pic_field_update(
        session_data.get('property_records', []),
        session_data.get('cofo_records', []),
        payload.index,
        payload.record_type,
        payload.field,
        payload.value
    )

    summary = _refresh_pic_session_state(session_data)

    return {
        "status": "success",
        "session_id": session_id,
        "property_records": summary['property_records'],
        "cofo_records": summary['cofo_records'],
        "file_number_records": summary['file_number_records'],
        "issues": summary['issues'],
        "total_records": summary['total_records'],
        "validation_issues": summary['validation_issues'],
        "ready_records": summary['ready_records'],
        "test_control": session_data.get('test_control')
    }


@app.post("/api/pic/delete/{session_id}")
async def delete_pic_record(session_id: str, payload: PICRecordDelete):
    """Delete a PIC preview row from the in-memory session."""

    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = app.sessions[session_id]
    if session_data.get('type') != 'pic':
        raise HTTPException(status_code=400, detail="Invalid session type for PIC delete")

    property_records = session_data.get('property_records', [])
    cofo_records = session_data.get('cofo_records', [])
    index = payload.index

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

    summary = _refresh_pic_session_state(session_data)

    return {
        "status": "success",
        "session_id": session_id,
        "property_records": summary['property_records'],
        "cofo_records": summary['cofo_records'],
        "file_number_records": summary['file_number_records'],
        "issues": summary['issues'],
        "total_records": summary['total_records'],
        "validation_issues": summary['validation_issues'],
        "ready_records": summary['ready_records'],
        "test_control": session_data.get('test_control')
    }


@app.post("/api/pic/clear-data")
async def clear_pic_data(request: PICClearDataRequest):
    mode = (request.mode or '').strip().upper()
    if mode not in {"TEST", "PRODUCTION"}:
        raise HTTPException(status_code=400, detail="Invalid data mode. Choose TEST or PRODUCTION.")

    db = SessionLocal()
    try:
        from sqlalchemy import text

        property_result = db.execute(
            text("DELETE FROM pic WHERE test_control = :mode"),
            {"mode": mode}
        )
        cofo_deleted = db.query(CofO).filter(CofO.test_control == mode).delete(synchronize_session=False)
        file_number_deleted = db.query(FileNumber).filter(FileNumber.test_control == mode).delete(synchronize_session=False)

        counts = {
            "pic": property_result.rowcount if property_result is not None else 0,
            "CofO_staging": cofo_deleted,
            "fileNumber": file_number_deleted
        }
        db.commit()
        return {
            "success": True,
            "mode": mode,
            "counts": counts
        }
    except Exception as exc:  # pragma: no cover - defensive rollback
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to clear {mode} data: {exc}")
    finally:
        db.close()


@app.post("/api/import-pic/{session_id}")
async def import_pic(session_id: str):
    """Commit PIC records into pic and CofO_staging tables."""

    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = app.sessions[session_id]
    if session_data.get('type') != 'pic':
        raise HTTPException(status_code=400, detail="Invalid session type for PIC import")

    db = SessionLocal()
    now = datetime.utcnow()
    property_records_count = 0
    cofo_records_count = 0
    test_control = (session_data.get('test_control') or 'PRODUCTION').upper()

    try:
        property_records = session_data.get('property_records', [])
        cofo_records = session_data.get('cofo_records', [])
        file_number_records = session_data.get('file_number_records', [])

        _synchronize_pic_cofo_visibility(property_records, cofo_records)
        file_number_records = _deduplicate_pic_file_numbers(file_number_records)

        for record in property_records:
            if record.get('hasIssues'):
                continue

            payload = {
                'mlsFNo': record.get('mlsFNo'),
                'fileno': record.get('fileno'),
                'transaction_type': record.get('transaction_type'),
                'transaction_date': record.get('transaction_date') or record.get('transaction_date_raw'),
                'serialNo': record.get('serialNo'),
                'oldKNNo': record.get('oldKNNo'),
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
                'created_at_override': record.get('date_created') or record.get('reg_date') or record.get('transaction_date'),
                'test_control': test_control
            }

            _import_property_record(db, payload, now, staging_table='pic')
            property_records_count += 1

        skipped_invalid_cofo = 0
        skipped_duplicate_cofo: List[str] = []

        for record in cofo_records:
            if record.get('hasIssues'):
                continue

            if record.get('skip_cofo_preview'):
                skipped_invalid_cofo += 1
                continue

            file_number = _normalize_string(record.get('mlsFNo'))
            if not file_number:
                skipped_invalid_cofo += 1
                continue

            if _pic_cofo_exists(db, file_number):
                if file_number not in skipped_duplicate_cofo:
                    skipped_duplicate_cofo.append(file_number)
                continue

            cofo_entry = CofO(
                mls_fno=file_number,
                title_type='Property Index Card',
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
                cofo_date=record.get('cofo_date') or record.get('reg_date') or record.get('reg_date_raw'),
                prop_id=record.get('prop_id'),
                test_control=test_control
            )

            db.add(cofo_entry)

            cofo_records_count += 1

        file_number_upserts = 0
        skipped_duplicate_file_numbers: List[str] = []
        for record in file_number_records:
            if record.get('hasIssues'):
                continue
            file_number_value = _normalize_string(record.get('mlsfNo') or record.get('mlsFNo'))
            if not file_number_value:
                continue
            if _pic_file_number_exists(db, file_number_value):
                if file_number_value not in skipped_duplicate_file_numbers:
                    skipped_duplicate_file_numbers.append(file_number_value)
                continue
            if _import_pic_file_number_record(db, record, now, test_control):
                file_number_upserts += 1

        # Import staging data (entities and customers with reason_retired)
        staging_result = perform_staging_import(
            db,
            property_records,
            session_data.get('filename', 'pic_upload.csv'),
            test_control,
            'transaction_type',
            source='pra',
            precomputed_entities=session_data.get('entity_staging_records'),
            precomputed_customers=session_data.get('customer_staging_records')
        )

        db.commit()

        del app.sessions[session_id]

        return {
            "success": True,
            "imported_count": property_records_count + cofo_records_count,
            "property_records_count": property_records_count,
            "cofo_records_count": cofo_records_count,
            "file_number_records_count": file_number_upserts,
            "cofo_skipped_invalid_transaction": skipped_invalid_cofo,
            "cofo_skipped_duplicates": skipped_duplicate_cofo,
            "file_number_skipped_duplicates": skipped_duplicate_file_numbers,
            "staging_import": {
                "entity_summary": staging_result.get('entity_summary', {}),
                "customer_summary": staging_result.get('customer_summary', {}),
                "errors": staging_result.get('errors', [])
            },
            "test_control": test_control
        }

    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(exc)}")
    finally:
        db.close()


# ========== PRA HELPER FUNCTIONS ==========

def _process_pra_data(df):
    """Process PRA CSV data and split into property_records, CofO, and file_numbers data."""
    
    # Normalize column names to handle variations
    df.columns = df.columns.str.strip()
    
    # Create property_records data
    property_records: List[Dict[str, Any]] = []
    cofo_records: List[Dict[str, Any]] = []
    file_numbers: List[Dict[str, Any]] = []
    
    for index, row in df.iterrows():
        # Generate tracking ID
        tracking_id = _generate_tracking_id()

        # Normalize frequently used fields once
        mls_f_no = _normalize_string(row.get('mlsFNo'))
        transaction_type = _normalize_string(row.get('transaction_type'))
        is_cofo_record = _is_cofo_indicator(transaction_type)
        transaction_date_raw = row.get('transaction_date')
        transaction_date = _coerce_sql_date(transaction_date_raw) or _normalize_string(transaction_date_raw)
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
        date_created_raw = row.get('DateCreated')
        date_created = _coerce_sql_date(date_created_raw) or _normalize_string(date_created_raw)

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
            'hasIssues': False,  # Will be set by QC validation
            'is_cofo_record': bool(is_cofo_record)
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
        cofo_records.append(_build_pra_cofo_record(property_record, is_cofo_record=is_cofo_record))
    
    return property_records, cofo_records, file_numbers


def _build_pra_reg_no(serial, page, volume):
    """Build regNo from SerialNo/pageNo/volumeNo"""
    if serial and page and volume:
        return f"{serial}/{page}/{volume}"
    return None


def _build_pra_file_number_qc(
    file_numbers: List[Dict[str, Any]]
) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """Generate QC issues for PRA file numbers using file indexing rules."""
    qc_input = []
    for record in file_numbers:
        raw_value = record.get('mlsfNo')
        if raw_value is None:
            raw_value = ''
        qc_input.append({'file_number': str(raw_value)})

    qc_issues = _run_qc_validation(qc_input)

    qc_rows: List[Dict[str, Any]] = []
    for issue_type, issues in qc_issues.items():
        for issue in issues:
            qc_rows.append({
                'record_index': issue.get('record_index'),
                'row': (issue.get('record_index') or 0) + 1,
                'file_number': issue.get('file_number'),
                'issue_type': issue_type,
                'description': issue.get('description'),
                'suggested_fix': issue.get('suggested_fix'),
                'auto_fixable': issue.get('auto_fixable', False),
                'severity': issue.get('severity')
            })

    qc_rows.sort(key=lambda entry: (entry['issue_type'], entry['record_index'] or 0))

    return qc_issues, qc_rows


def _detect_pra_duplicates(records):
    """Detect duplicate file numbers within CSV and against property_records and fileNumber tables."""
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
                combined_records: List[Dict[str, Any]] = []

                # Check property_records table
                property_result = db.execute(text("""
                    SELECT mlsFNo, Grantee, transaction_type, plot_no, prop_id 
                    FROM property_records 
                    WHERE mlsFNo = :file_number
                """), {'file_number': file_number})

                property_matches = property_result.fetchall()
                if property_matches:
                    for row in property_matches:
                        mapped = dict(row._mapping)
                        combined_records.append({
                            **mapped,
                            'source': 'property_records',
                            'grantee': mapped.get('Grantee'),
                            'transaction_type': mapped.get('transaction_type'),
                            'plot_no': mapped.get('plot_no'),
                            'prop_id': mapped.get('prop_id')
                        })

                # Check fileNumber table
                file_number_result = db.execute(text("""
                    SELECT mlsfNo AS mlsFNo, FileName AS Grantee, type AS transaction_type, plot_no, NULL AS prop_id 
                    FROM fileNumber 
                    WHERE mlsfNo = :file_number
                """), {'file_number': file_number})

                file_number_matches = file_number_result.fetchall()
                if file_number_matches:
                    for row in file_number_matches:
                        mapped = dict(row._mapping)
                        combined_records.append({
                            **mapped,
                            'source': 'fileNumber',
                            'grantee': mapped.get('Grantee'),
                            'transaction_type': mapped.get('transaction_type'),
                            'plot_no': mapped.get('plot_no'),
                            'prop_id': mapped.get('prop_id')
                        })

                if combined_records:
                    duplicates['database'].append({
                        'file_number': file_number,
                        'count': len(combined_records),
                        'records': combined_records
                    })
    except Exception:
        pass  # Ignore database errors for duplicate detection
    finally:
        db.close()
    
    return duplicates


def _detect_cofo_duplicates(cofo_records: List[Dict[str, Any]], test_control: Optional[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Identify CofO duplicates within the upload and against the CofO staging table."""
    duplicates: Dict[str, List[Dict[str, Any]]] = {
        'csv': [],
        'database': []
    }

    if not cofo_records:
        return duplicates

    normalized_mode = (test_control or '').strip().upper() or 'PRODUCTION'
    csv_bucket: Dict[str, List[Dict[str, Any]]] = {}

    for index, record in enumerate(cofo_records):
        if not record.get('is_cofo_record'):
            continue
        file_number = _normalize_string(record.get('mlsFNo'))
        if not file_number:
            continue
        csv_bucket.setdefault(file_number, []).append({
            'record_index': index,
            'mlsFNo': file_number,
            'Grantor': record.get('Grantor'),
            'Grantee': record.get('Grantee'),
            'transaction_type': record.get('transaction_type'),
            'source': 'upload'
        })

    for file_number, occurrences in csv_bucket.items():
        if len(occurrences) > 1:
            duplicates['csv'].append({
                'file_number': file_number,
                'count': len(occurrences),
                'records': occurrences
            })

    db = SessionLocal()
    try:
        if csv_bucket:
            existing_rows = (
                db.query(CofO)
                .filter(CofO.mls_fno.in_(list(csv_bucket.keys())))
                .filter(CofO.test_control == normalized_mode)
                .all()
            )
            if existing_rows:
                for existing in existing_rows:
                    duplicates['database'].append({
                        'file_number': existing.mls_fno,
                        'count': 1,
                        'records': [{
                            'mlsFNo': existing.mls_fno,
                            'transaction_type': existing.transaction_type,
                            'Grantor': existing.grantor,
                            'Grantee': existing.grantee,
                            'cofo_date': existing.cofo_date,
                            'source': 'CofO'
                        }]
                    })
    except Exception:
        pass
    finally:
        db.close()

    return duplicates


def _apply_pra_field_update(
    property_records: List[Dict[str, Any]],
    cofo_records: List[Dict[str, Any]],
    file_numbers: List[Dict[str, Any]],
    record_type: Literal['property_records', 'file_numbers', 'cofo'],
    index: int,
    field: str,
    value: Optional[str]
) -> None:
    if index < 0:
        return

    sanitized = value.strip() if isinstance(value, str) else value

    def update_if_present(record: Optional[Dict[str, Any]], key: str, new_value: Any) -> None:
        if record is not None and key is not None:
            record[key] = new_value

    property_record = property_records[index] if 0 <= index < len(property_records) else None
    cofo_record = cofo_records[index] if 0 <= index < len(cofo_records) else None
    file_number_record = file_numbers[index] if 0 <= index < len(file_numbers) else None

    if record_type == 'property_records':
        if property_record is None:
            return

        update_if_present(property_record, field, sanitized)

        if field in {'mlsFNo', 'fileno'}:
            update_if_present(property_record, 'mlsFNo', sanitized)
            update_if_present(property_record, 'fileno', sanitized)
            update_if_present(file_number_record, 'mlsfNo', sanitized)
            update_if_present(cofo_record, 'mlsFNo', sanitized)
        elif field == 'transaction_type':
            update_if_present(property_record, 'transaction_type', sanitized)
            update_if_present(property_record, 'instrument_type', sanitized)
            update_if_present(file_number_record, 'type', sanitized)
            if cofo_record is not None:
                update_if_present(cofo_record, 'transaction_type', sanitized)
                update_if_present(cofo_record, 'instrument_type', sanitized)
                is_cofo = _is_cofo_indicator(sanitized)
                update_if_present(property_record, 'is_cofo_record', is_cofo)
                update_if_present(cofo_record, 'is_cofo_record', is_cofo)
        elif field == 'transaction_date':
            update_if_present(property_record, 'transaction_date', sanitized)
            update_if_present(property_record, 'transaction_date_raw', sanitized)
            update_if_present(cofo_record, 'transaction_date', sanitized)
            update_if_present(cofo_record, 'transaction_date_raw', sanitized)
        elif field == 'serialNo':
            update_if_present(property_record, 'serialNo', sanitized)
            update_if_present(property_record, 'SerialNo', sanitized)
            update_if_present(cofo_record, 'serialNo', sanitized)
        elif field == 'pageNo':
            update_if_present(property_record, 'pageNo', sanitized)
            update_if_present(cofo_record, 'pageNo', sanitized)
        elif field == 'volumeNo':
            update_if_present(property_record, 'volumeNo', sanitized)
            update_if_present(cofo_record, 'volumeNo', sanitized)
        elif field == 'regNo':
            update_if_present(property_record, 'regNo', sanitized)
            update_if_present(cofo_record, 'regNo', sanitized)
        elif field in {'grantor_assignor', 'Grantor'}:
            update_if_present(property_record, 'grantor_assignor', sanitized)
            update_if_present(property_record, 'Grantor', sanitized)
            update_if_present(cofo_record, 'Grantor', sanitized)
            update_if_present(cofo_record, 'Assignor', sanitized)
        elif field in {'grantee_assignee', 'Grantee', 'Assignee'}:
            update_if_present(property_record, 'grantee_assignee', sanitized)
            update_if_present(property_record, 'Grantee', sanitized)
            update_if_present(property_record, 'Assignee', sanitized)
            update_if_present(cofo_record, 'Grantee', sanitized)
            update_if_present(cofo_record, 'Assignee', sanitized)
            update_if_present(file_number_record, 'FileName', sanitized)
        elif field == 'location':
            update_if_present(property_record, 'location', sanitized)
            update_if_present(property_record, 'property_description', sanitized)
            update_if_present(file_number_record, 'location', sanitized)
            update_if_present(cofo_record, 'location', sanitized)
            update_if_present(cofo_record, 'property_description', sanitized)
        elif field == 'plot_no':
            update_if_present(property_record, 'plot_no', sanitized)
            update_if_present(file_number_record, 'plot_no', sanitized)
        elif field in {'CreatedBy', 'created_by'}:
            update_if_present(property_record, 'CreatedBy', sanitized)
            update_if_present(property_record, 'created_by', sanitized)
            update_if_present(file_number_record, 'created_by', sanitized)
            update_if_present(cofo_record, 'created_by', sanitized)
    elif record_type == 'file_numbers':
        if file_number_record is None:
            return

        update_if_present(file_number_record, field, sanitized)

        if field == 'mlsfNo':
            update_if_present(file_number_record, 'mlsfNo', sanitized)
            update_if_present(property_record, 'mlsFNo', sanitized)
            update_if_present(property_record, 'fileno', sanitized)
            update_if_present(cofo_record, 'mlsFNo', sanitized)
        elif field == 'FileName':
            update_if_present(file_number_record, 'FileName', sanitized)
            update_if_present(property_record, 'Grantee', sanitized)
            update_if_present(property_record, 'grantee_assignee', sanitized)
            update_if_present(property_record, 'Assignee', sanitized)
            update_if_present(cofo_record, 'Grantee', sanitized)
            update_if_present(cofo_record, 'Assignee', sanitized)
        elif field == 'plot_no':
            update_if_present(file_number_record, 'plot_no', sanitized)
            update_if_present(property_record, 'plot_no', sanitized)
        elif field == 'location':
            update_if_present(file_number_record, 'location', sanitized)
            update_if_present(property_record, 'location', sanitized)
            update_if_present(property_record, 'property_description', sanitized)
            update_if_present(cofo_record, 'location', sanitized)
            update_if_present(cofo_record, 'property_description', sanitized)
    elif record_type == 'cofo':
        if cofo_record is None:
            return

        update_if_present(cofo_record, field, sanitized)

        if field == 'mlsFNo':
            update_if_present(cofo_record, 'mlsFNo', sanitized)
            update_if_present(property_record, 'mlsFNo', sanitized)
            update_if_present(property_record, 'fileno', sanitized)
            update_if_present(file_number_record, 'mlsfNo', sanitized)
        elif field == 'transaction_type':
            update_if_present(cofo_record, 'transaction_type', sanitized)
            update_if_present(property_record, 'transaction_type', sanitized)
            update_if_present(property_record, 'instrument_type', sanitized)
            update_if_present(file_number_record, 'type', sanitized)
            is_cofo = _is_cofo_indicator(sanitized)
            update_if_present(property_record, 'is_cofo_record', is_cofo)
            update_if_present(cofo_record, 'is_cofo_record', is_cofo)
        elif field in {'Grantor', 'Assignor'}:
            update_if_present(cofo_record, 'Grantor', sanitized)
            update_if_present(cofo_record, 'Assignor', sanitized)
            update_if_present(property_record, 'grantor_assignor', sanitized)
            update_if_present(property_record, 'Grantor', sanitized)
            update_if_present(property_record, 'Assignor', sanitized)
            _annotate_pic_party_types(property_record)
            update_if_present(cofo_record, 'grantor_type', property_record.get('grantor_type'))
            update_if_present(cofo_record, 'assignor_type', property_record.get('assignor_type'))
        elif field in {'Grantee', 'Assignee'}:
            update_if_present(cofo_record, 'Grantee', sanitized)
            update_if_present(cofo_record, 'Assignee', sanitized)
            update_if_present(property_record, 'grantee_assignee', sanitized)
            update_if_present(property_record, 'Grantee', sanitized)
            update_if_present(property_record, 'Assignee', sanitized)
            update_if_present(file_number_record, 'FileName', sanitized)
            _annotate_pic_party_types(property_record)
            update_if_present(cofo_record, 'grantee_type', property_record.get('grantee_type'))
            update_if_present(cofo_record, 'assignee_type', property_record.get('assignee_type'))
        elif field == 'transaction_date':
            update_if_present(cofo_record, 'transaction_date', sanitized)
            update_if_present(cofo_record, 'transaction_date_raw', sanitized)
            update_if_present(property_record, 'transaction_date', sanitized)
            update_if_present(property_record, 'transaction_date_raw', sanitized)
        elif field == 'serialNo':
            update_if_present(cofo_record, 'serialNo', sanitized)
            update_if_present(property_record, 'serialNo', sanitized)
            update_if_present(property_record, 'SerialNo', sanitized)
        elif field == 'pageNo':
            update_if_present(cofo_record, 'pageNo', sanitized)
            update_if_present(property_record, 'pageNo', sanitized)
        elif field == 'volumeNo':
            update_if_present(cofo_record, 'volumeNo', sanitized)
            update_if_present(property_record, 'volumeNo', sanitized)
        elif field == 'regNo':
            update_if_present(cofo_record, 'regNo', sanitized)
            update_if_present(property_record, 'regNo', sanitized)


def _refresh_pra_session_state(session_data: Dict[str, Any]) -> Dict[str, Any]:
    property_records = session_data.get('property_records', [])
    cofo_records = session_data.get('cofo_records', [])
    file_numbers = session_data.get('file_numbers', [])
    mode = session_data.get('test_control')

    _apply_ui_date_format_to_session_records(property_records, cofo_records, file_numbers)

    for record in property_records:
        record['hasIssues'] = False
    for record in cofo_records:
        record['hasIssues'] = False

    qc_issues_raw, qc_rows = _build_pra_file_number_qc(file_numbers)

    for issue_group in qc_issues_raw.values():
        for issue in issue_group:
            idx = issue.get('record_index')
            if idx is None:
                continue
            if 0 <= idx < len(property_records):
                property_records[idx]['hasIssues'] = True
            if 0 <= idx < len(cofo_records):
                cofo_records[idx]['hasIssues'] = True

    duplicates_property = _detect_pra_duplicates(property_records)
    file_number_probe = [
        {
            'mlsFNo': record.get('mlsfNo'),
            'Grantee': record.get('FileName'),
            'transaction_type': record.get('type'),
            'plot_no': record.get('plot_no')
        }
        for record in file_numbers
    ]
    duplicates_file = _detect_pra_duplicates(file_number_probe)
    cofo_duplicates = _detect_cofo_duplicates(cofo_records, mode)

    existing_cofo_numbers = {entry['file_number'] for entry in cofo_duplicates.get('database', [])}
    for record in cofo_records:
        file_number = _normalize_string(record.get('mlsFNo'))
        if not record.get('is_cofo_record'):
            record['skip_import'] = True
            record['duplicate_in_cofo'] = False
            record['duplicate_reason'] = 'Not a CofO record'
            continue
        if file_number and file_number in existing_cofo_numbers:
            record['duplicate_in_cofo'] = True
            record['skip_import'] = True
            record['duplicate_reason'] = 'Existing CofO record'
            record['hasIssues'] = True
        else:
            record['duplicate_in_cofo'] = False
            record['duplicate_reason'] = None
            record['skip_import'] = False

    total_records = len(property_records)
    ready_records = sum(1 for rec in property_records if not rec.get('hasIssues'))
    validation_issues = len(qc_rows)
    duplicate_count = (
        len(duplicates_property.get('csv', [])) +
        len(duplicates_property.get('database', [])) +
        len(duplicates_file.get('csv', [])) +
        len(duplicates_file.get('database', [])) +
        len(cofo_duplicates.get('csv', [])) +
        len(cofo_duplicates.get('database', []))
    )

    qc_summary = {
        'total_issues': validation_issues,
        'padding_issues': len(qc_issues_raw.get('padding', [])),
        'year_issues': len(qc_issues_raw.get('year', [])),
        'spacing_issues': len(qc_issues_raw.get('spacing', []))
    }

    session_data['property_records'] = property_records
    session_data['cofo_records'] = cofo_records
    session_data['file_numbers'] = file_numbers
    session_data['duplicates'] = {
        'property_records': duplicates_property,
        'file_numbers': duplicates_file
    }
    session_data['cofo_duplicates'] = cofo_duplicates
    session_data['file_number_qc'] = qc_rows
    session_data['qc_summary'] = qc_summary
    session_data['qc_issues_raw'] = qc_issues_raw

    return {
        'property_records': property_records,
        'cofo_records': cofo_records,
        'file_numbers': file_numbers,
        'issues': qc_issues_raw,
        'file_number_qc': qc_rows,
        'duplicates': session_data['duplicates'],
        'cofo_duplicates': cofo_duplicates,
        'cofo_duplicates_ignored': cofo_duplicates.get('database', []),
        'total_records': total_records,
        'duplicate_count': duplicate_count,
        'validation_issues': validation_issues,
        'ready_records': ready_records,
        'qc_summary': qc_summary,
        'staging_summary': session_data.get('staging_summary'),
        'test_control': mode
    }


def _import_property_record(db, record, timestamp, *, allow_update: bool = True, staging_table: str = 'property_records'):
    """Import a single property record to the specified staging table."""
    from sqlalchemy import text
    
    # Validate staging table name to prevent SQL injection
    if staging_table not in ('property_records', 'file_history', 'pic', 'pra'):
        staging_table = 'property_records'
    
    existing = None
    if allow_update:
        # Check if record already exists when updates are permitted
        existing = db.execute(text(f"""
            SELECT id FROM {staging_table} WHERE mlsFNo = :file_number
        """), {'file_number': record['mlsFNo']}).first()
    
    created_at_override = record.get('created_at_override')
    created_at_value = None
    if created_at_override:
        if isinstance(created_at_override, datetime):
            created_at_value = created_at_override
        else:
            coerced_date = _coerce_sql_date(created_at_override)
            if coerced_date:
                try:
                    created_at_value = datetime.fromisoformat(coerced_date)
                except ValueError:
                    created_at_value = None

    params = {k: v for k, v in record.items() if k != 'created_at_override'}
    if 'oldKNNo' not in params:
        params['oldKNNo'] = None

    params['test_control'] = (params.get('test_control') or 'PRODUCTION').upper()

    # Coerce date fields to ISO format acceptable by SQL Server
    params['transaction_date'] = _coerce_sql_date(params.get('transaction_date'))
    params['date_created'] = _coerce_sql_date(params.get('date_created'))

    role_fields: Tuple[Tuple[str, str], ...] = ()
    if staging_table == 'file_history':
        role_fields = (
            ('Assignor', ':Assignor'),
            ('Assignee', ':Assignee'),
            ('Mortgagor', ':Mortgagor'),
            ('Mortgagee', ':Mortgagee'),
            ('Surrenderor', ':Surrenderor'),
            ('Surrenderee', ':Surrenderee'),
            ('Lessor', ':Lessor'),
            ('Lessee', ':Lessee')
        )
        for field, _ in role_fields:
            params.setdefault(field, None)

    update_fields: List[Tuple[str, str]] = [
        ('transaction_type', ':transaction_type'),
        ('transaction_date', ':transaction_date'),
        ('serialNo', ':serialNo'),
        ('oldKNNo', ':oldKNNo'),
        ('pageNo', ':pageNo'),
        ('volumeNo', ':volumeNo'),
        ('regNo', ':regNo'),
        ('instrument_type', ':instrument_type'),
        ('Grantor', ':Grantor'),
        ('Grantee', ':Grantee'),
    ]

    if role_fields:
        update_fields.extend(role_fields)

    update_fields.extend([
        ('property_description', ':property_description'),
        ('location', ':location'),
        ('streetName', ':streetName'),
        ('house_no', ':house_no'),
        ('districtName', ':districtName'),
        ('plot_no', ':plot_no'),
        ('lgsaOrCity', ':lgsaOrCity'),
        ('plot_size', ':plot_size'),
        ('prop_id', ':prop_id'),
        ('test_control', ':test_control'),
        ('updated_at', ':updated_at')
    ])

    set_clause = ",\n                ".join(f"{column} = {placeholder}" for column, placeholder in update_fields)

    insert_columns = [
        'mlsFNo', 'fileno', 'transaction_type', 'transaction_date', 'serialNo', 'oldKNNo', 'pageNo', 'volumeNo', 'regNo',
        'instrument_type', 'Grantor', 'Grantee'
    ]

    if role_fields:
        insert_columns.extend([column for column, _ in role_fields])

    insert_columns.extend([
        'property_description', 'location', 'streetName', 'house_no',
        'districtName', 'plot_no', 'lgsaOrCity', 'source', 'plot_size', 'migrated_by', 'prop_id', 'created_at',
        'created_by', 'date_created', 'migration_source', 'test_control'
    ])

    insert_placeholders = [f":{column}" for column in insert_columns]

    if existing:
        db.execute(text(f"""
            UPDATE {staging_table} SET
                {set_clause}
            WHERE mlsFNo = :mlsFNo
        """), {
            **params,
            'updated_at': timestamp
        })
    else:
        db.execute(text(f"""
            INSERT INTO {staging_table} (
                {', '.join(insert_columns)}
            ) VALUES (
                {', '.join(insert_placeholders)}
            )
        """), {
            **params,
            'created_at': created_at_value or timestamp
        })

# ========== PRA IMPORT ENDPOINTS ==========


@app.post("/api/pra/clear-data")
async def clear_pra_data(request: PRAClearDataRequest):
    mode = (request.mode or '').strip().upper()
    if mode not in {"TEST", "PRODUCTION"}:
        raise HTTPException(status_code=400, detail="Invalid data mode. Choose TEST or PRODUCTION.")

    db = SessionLocal()
    try:
        from sqlalchemy import text

        property_result = db.execute(
            text("DELETE FROM pra WHERE test_control = :mode"),
            {"mode": mode}
        )

        counts = {
            "pra": property_result.rowcount if property_result is not None else 0,
            "fileNumber": 0
        }

        db.commit()
        return {
            "success": True,
            "mode": mode,
            "counts": counts
        }
    except Exception as exc:  # pragma: no cover - defensive rollback
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to clear {mode} data: {exc}")
    finally:
        db.close()


@app.post("/api/upload-pra")
async def upload_pra(test_control: str = Form(...), file: UploadFile = File(...)):
    """Upload and process CSV/Excel file for PRA import preview"""
    
    try:
        mode = (test_control or '').strip().upper()
        if mode not in {"TEST", "PRODUCTION"}:
            raise HTTPException(status_code=400, detail="Invalid data mode. Choose TEST or PRODUCTION.")

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
        property_records, cofo_records, file_numbers = _process_pra_data(dataframe)
        
        # Assign property IDs to both tables
        # Get the next property ID counter that works for all tables
        next_prop_id_counter = _get_next_property_id_counter()
        
        # Assign property IDs to property records
        for i, record in enumerate(property_records):
            prop_id = str(next_prop_id_counter + i)
            record['prop_id'] = prop_id
            record['test_control'] = mode
            if i < len(cofo_records):
                cofo_records[i]['prop_id'] = prop_id
                cofo_records[i]['test_control'] = mode
        
        # Assign property IDs to file numbers (continue counter)
        for i, record in enumerate(file_numbers):
            prop_id = str(next_prop_id_counter + len(property_records) + i)
            record['prop_id'] = prop_id
            record['test_control'] = mode

        # Format dates for UI preview
        _apply_ui_date_format_to_session_records(property_records, cofo_records, file_numbers)
        
        # Build QC rows for file numbers using file indexing rules
        qc_issues_raw, qc_rows = _build_pra_file_number_qc(file_numbers)

        qc_summary = {
            'total_issues': len(qc_rows),
            'padding_issues': len(qc_issues_raw.get('padding', [])),
            'year_issues': len(qc_issues_raw.get('year', [])),
            'spacing_issues': len(qc_issues_raw.get('spacing', []))
        }

        for record in property_records:
            record['hasIssues'] = False
        for record in cofo_records:
            record['hasIssues'] = False

        for issue_list in qc_issues_raw.values():
            for issue in issue_list:
                idx = issue.get('record_index')
                if idx is None:
                    continue
                if 0 <= idx < len(property_records):
                    property_records[idx]['hasIssues'] = True
                if 0 <= idx < len(cofo_records):
                    cofo_records[idx]['hasIssues'] = True

        # Detect duplicates for property and file-number tables
        duplicates_property = _detect_pra_duplicates(property_records)
        file_number_duplicate_probe = [
            {
                'mlsFNo': record.get('mlsfNo'),
                'Grantee': record.get('FileName'),
                'transaction_type': record.get('type'),
                'plot_no': record.get('plot_no')
            }
            for record in file_numbers
        ]
        duplicates_file = _detect_pra_duplicates(file_number_duplicate_probe)
        cofo_duplicates = _detect_cofo_duplicates(cofo_records, mode)

        duplicates = {
            'property_records': duplicates_property,
            'file_numbers': duplicates_file
        }

        duplicate_file_numbers_existing = {entry['file_number'] for entry in cofo_duplicates.get('database', [])}
        for index, record in enumerate(cofo_records):
            file_number = _normalize_string(record.get('mlsFNo'))
            if file_number and file_number in duplicate_file_numbers_existing and record.get('is_cofo_record'):
                record['duplicate_in_cofo'] = True
                record['skip_import'] = True
                record['duplicate_reason'] = 'Existing CofO record'
                record['hasIssues'] = True
            else:
                record['duplicate_in_cofo'] = False
                record['skip_import'] = False
                record['duplicate_reason'] = None

        ready_records = sum(1 for rec in property_records if not rec.get('hasIssues'))

        # Extract staging data (entities and customers with reason_retired)
        entity_records, customer_records, staging_summary = extract_entity_and_customer_data(
            property_records,
            file.filename,
            mode,
            transaction_type_field='transaction_type',
            source='pra'
        )

        if not hasattr(app, 'sessions'):
            app.sessions = {}

        app.sessions[session_id] = {
            "filename": file.filename,
            "upload_time": datetime.now(),
            "type": "pra",
            "test_control": mode,
            "property_records": property_records,
            "cofo_records": cofo_records,
            "file_numbers": file_numbers,
            "duplicates": duplicates,
            "file_number_qc": qc_rows,
            "qc_summary": qc_summary,
            "qc_issues_raw": qc_issues_raw,
            "cofo_duplicates": cofo_duplicates,
            "entity_staging_records": entity_records,
            "customer_staging_records": customer_records,
            "staging_summary": staging_summary
        }

        # Calculate statistics
        total_records = len(property_records)
        duplicate_count = (
            len(duplicates_property.get('csv', [])) +
            len(duplicates_property.get('database', [])) +
            len(duplicates_file.get('csv', [])) +
            len(duplicates_file.get('database', [])) +
            len(cofo_duplicates.get('csv', [])) +
            len(cofo_duplicates.get('database', []))
        )
        validation_issues = qc_summary['total_issues']

        return {
            "session_id": session_id,
            "filename": file.filename,
            "total_records": total_records,
            "duplicate_count": duplicate_count,
            "validation_issues": validation_issues,
            "ready_records": ready_records,
            "property_records": property_records,
            "cofo_records": cofo_records,
            "file_numbers": file_numbers,
            "duplicates": duplicates,
            "file_number_qc": qc_rows,
            "qc_summary": qc_summary,
            "staging_summary": staging_summary,
            "entity_staging_preview": entity_records,
            "customer_staging_preview": customer_records,
            "cofo_duplicates_ignored": cofo_duplicates.get('database', []),
            "test_control": mode
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


@app.post("/api/pra/update/{session_id}")
async def update_pra_record(session_id: str, payload: PRARecordUpdate):
    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = app.sessions[session_id]
    try:
        _apply_pra_field_update(
            session_data.get('property_records', []),
            session_data.get('cofo_records', []),
            session_data.get('file_numbers', []),
            payload.record_type,
            payload.record_index,
            payload.field,
            payload.value
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to update record: {exc}")

    refreshed = _refresh_pra_session_state(session_data)
    refreshed['test_control'] = session_data.get('test_control')
    return refreshed


@app.post("/api/pra/delete/{session_id}")
async def delete_pra_record(session_id: str, payload: PRARecordDelete):
    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = app.sessions[session_id]
    property_records = session_data.get('property_records', [])
    cofo_records = session_data.get('cofo_records', [])
    file_numbers = session_data.get('file_numbers', [])
    index = payload.record_index

    if index < 0 or index >= len(property_records):
        raise HTTPException(status_code=400, detail="Invalid record index")

    # Maintain alignment across arrays regardless of originating tab
    if 0 <= index < len(property_records):
        property_records.pop(index)
    if 0 <= index < len(cofo_records):
        cofo_records.pop(index)
    if 0 <= index < len(file_numbers):
        file_numbers.pop(index)

    refreshed = _refresh_pra_session_state(session_data)
    refreshed['test_control'] = session_data.get('test_control')
    return refreshed


@app.post("/api/import-pra/{session_id}")
async def import_pra(session_id: str):
    """Import PRA data into the PRA staging tables."""
    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = app.sessions[session_id]
    if session_data.get('type') != 'pra':
        raise HTTPException(status_code=400, detail="Invalid session type for PRA import")

    db = SessionLocal()
    property_records_count = 0
    cofo_records_count = 0
    now = datetime.utcnow()
    test_control = (session_data.get('test_control') or 'PRODUCTION').upper()

    try:
        # Import property records to 'pra' staging table
        for record in session_data["property_records"]:
            # Skip records with issues if configured to do so
            if record.get('hasIssues', False):
                continue
            record['test_control'] = test_control
            _import_property_record(db, record, now, staging_table='pra')
            property_records_count += 1

        # Import CofO rows, skipping duplicates flagged during preview
        duplicate_existing: set[str] = set()
        cofo_duplicates = session_data.get('cofo_duplicates') or {}
        for entry in cofo_duplicates.get('database', []):
            file_number = entry.get('file_number')
            if file_number:
                duplicate_existing.add(file_number)

        for record in session_data.get('cofo_records', []):
            if not record.get('is_cofo_record'):
                continue
            file_number = _normalize_string(record.get('mlsFNo'))
            if record.get('skip_import') or (file_number and file_number in duplicate_existing):
                continue

            cofo_entry = CofO(
                mls_fno=record.get('mlsFNo'),
                title_type='PRA',
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
                plot_no=record.get('plot_no'),
                lgsa_or_city=None,
                land_use=None,
                cofo_type=None,
                grantor=record.get('Grantor'),
                grantee=record.get('Grantee'),
                cofo_date=record.get('cofo_date') or record.get('reg_date') or record.get('reg_date_raw'),
                prop_id=record.get('prop_id'),
                test_control=test_control
            )

            existing = db.query(CofO).filter(CofO.mls_fno == cofo_entry.mls_fno, CofO.test_control == test_control).first()
            if existing:
                _update_cofo(existing, cofo_entry)
                existing.test_control = test_control
            else:
                db.add(cofo_entry)
            cofo_records_count += 1

        # Import staging data (entities and customers with reason_retired)
        staging_result = perform_staging_import(
            db,
            session_data.get('property_records', []),
            session_data.get('filename', 'pra_upload.csv'),
            test_control,
            'transaction_type',
            source='pra',
            precomputed_entities=session_data.get('entity_staging_records'),
            precomputed_customers=session_data.get('customer_staging_records')
        )

        db.commit()

        # Clean up session
        del app.sessions[session_id]

        return {
            "success": True,
            "imported_count": property_records_count + cofo_records_count,
            "property_records_count": property_records_count,
            "cofo_records_count": cofo_records_count,
            "staging_import": {
                "entity_summary": staging_result.get('entity_summary', {}),
                "customer_summary": staging_result.get('customer_summary', {}),
                "errors": staging_result.get('errors', [])
            },
            "test_control": test_control
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")
    finally:
        db.close()


def _resolve_pic_transaction_date(
    transaction_type: Optional[str],
    row: pd.Series
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Determine the best transaction date candidate for PIC records."""
    normalized_type = (_normalize_string(transaction_type) or '').lower()
    candidates: List[str] = []

    if 'assign' in normalized_type:
        candidates.extend(['Assignment Date', 'date_approved', 'date_recommended'])
    elif 'surrender' in normalized_type:
        candidates.extend(['Surrender Date', 'date_approved', 'date_recommended'])
    elif 'revoke' in normalized_type or 'revoked' in normalized_type:
        candidates.extend(['Revoked date', 'date_approved', 'date_recommended'])
    else:
        candidates.extend(['date_approved', 'date_recommended', 'Assignment Date'])

    candidates.extend([
        'lease_begins',
        'lease_expires',
        'Date Expired',
        'DateCreated',
        'Surrender Date',
        'Revoked date'
    ])

    seen: set[str] = set()
    for field in candidates:
        if field in seen:
            continue
        seen.add(field)
        if field not in row:
            continue
        iso_value, raw_value = _parse_file_history_date(row.get(field))
        if iso_value or raw_value:
            return iso_value, raw_value, field

    return None, None, None


def _recalculate_pic_serial_state(
    record: Dict[str, Any],
    cofo_record: Optional[Dict[str, Any]] = None
) -> None:
    """Refresh derived serial metadata for PIC rows."""
    register_serial = _normalize_string(record.get('serial_register')) or _normalize_string(record.get('serialNo'))
    card_serial = _normalize_string(record.get('oldKNNo'))

    record['serial_register'] = register_serial
    record['serialNo'] = register_serial
    record['oldKNNo'] = card_serial

    fallback_used = bool(card_serial and not register_serial)
    record['serial_fallback_used'] = fallback_used
    record['serial_missing'] = not bool(register_serial)

    page_value = _normalize_string(record.get('pageNo'))
    volume_value = _normalize_string(record.get('volumeNo'))
    partial_reg_values = bool(register_serial or page_value or volume_value)
    if register_serial and page_value and volume_value:
        record['regNo'] = f"{register_serial}/{page_value}/{volume_value}"
        record['reg_particulars_missing'] = False
    else:
        if not partial_reg_values:
            record['reg_particulars_missing'] = False
        else:
            record['reg_particulars_missing'] = True

    if cofo_record is not None:
        cofo_record['serialNo'] = register_serial
        cofo_record['oldKNNo'] = card_serial
        cofo_record['serial_fallback_used'] = fallback_used
        cofo_record['serial_missing'] = record['serial_missing']
        if register_serial and page_value and volume_value:
            cofo_record['regNo'] = record['regNo']
            cofo_record['reg_particulars_missing'] = False
        else:
            cofo_record['reg_particulars_missing'] = bool(partial_reg_values)


PIC_COFO_TRANSACTION_VALUES = {"cofo", "certificate of occupancy"}


def _is_pic_cofo_transaction(value: Optional[str]) -> bool:
    """Return True when a transaction type should appear in CofO preview/import."""
    normalized = _normalize_string(value)
    if not normalized:
        return False
    return normalized.lower() in PIC_COFO_TRANSACTION_VALUES


def _deduplicate_pic_records(
    property_records: List[Dict[str, Any]],
    cofo_records: List[Dict[str, Any]],
    file_number_records: List[Dict[str, Any]],
    entity_records: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Deduplicate PIC records by their identifiers.
    
    Rules:
    - Property Records: YES duplicates allowed (keep all)
    - CofO: NO duplicates (deduplicate by mlsFNo/oldKNNo)
    - File Numbers: NO duplicates (handled by _deduplicate_pic_file_numbers)
    - Entities: NO duplicates (deduplicate by entity_id/file_number)
    - Customers: YES duplicates allowed (keep all, not deduped here)
    """
    def normalize_key(value: Optional[str]) -> str:
        """Normalize a value for comparison."""
        if not value:
            return ""
        normalized = _normalize_string(value)
        if not normalized:
            return ""
        return _strip_all_whitespace(normalized).upper()
    
    # Property Records: Keep ALL (YES duplicates allowed)
    # No deduplication needed
    
    # CofO: Remove duplicates by mlsFNo or oldKNNo
    cofo_seen = set()
    unique_cofo_records = []
    
    for cofo_record in cofo_records:
        file_number = cofo_record.get('mlsFNo') or cofo_record.get('oldKNNo')
        key = normalize_key(file_number)
        
        if not key:
            # No identifier, include it anyway
            unique_cofo_records.append(cofo_record)
            continue
        
        if key in cofo_seen:
            # Duplicate found, skip it
            continue
        
        cofo_seen.add(key)
        unique_cofo_records.append(cofo_record)
    
    # File Numbers: Remove duplicates (via existing function)
    file_number_records = _deduplicate_pic_file_numbers(file_number_records)
    
    # Entities: Remove duplicates by entity_id or file_number
    entity_seen = set()
    unique_entity_records = []
    
    for entity_record in entity_records:
        entity_id = entity_record.get('entity_id') or entity_record.get('entityId')
        file_number = entity_record.get('file_number') or entity_record.get('fileNumber')
        
        # Use entity_id as primary key, file_number as fallback
        key_value = entity_id or file_number
        key = normalize_key(key_value)
        
        if not key:
            # No identifier, include it anyway
            unique_entity_records.append(entity_record)
            continue
        
        if key in entity_seen:
            # Duplicate found, skip it
            continue
        
        entity_seen.add(key)
        unique_entity_records.append(entity_record)
    
    # Customers: Keep ALL (YES duplicates allowed)
    # No deduplication needed
    
    return property_records, unique_cofo_records, file_number_records, unique_entity_records


def _deduplicate_pic_file_numbers(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate file-number entries (case-insensitive, whitespace-insensitive)."""
    seen = set()
    unique: List[Dict[str, Any]] = []

    for record in records:
        raw_value = record.get('mlsfNo') or record.get('mlsFNo')
        normalized = _normalize_string(raw_value)
        if not normalized:
            unique.append(record)
            continue

        key = _strip_all_whitespace(normalized).upper()
        if key in seen:
            continue

        seen.add(key)
        unique.append(record)

    return unique


def _normalize_file_number_key(value: Optional[str]) -> Optional[str]:
    """Return a canonical comparison key for file numbers."""
    normalized = _normalize_string(value)
    if not normalized:
        return None
    collapsed = _strip_all_whitespace(normalized)
    if not collapsed:
        return None
    return collapsed.upper()


def _pic_file_number_exists(db, file_number: Optional[str]) -> bool:
    """Check if a file number already exists (ignoring whitespace/case)."""
    key = _normalize_file_number_key(file_number)
    if not key:
        return False
    normalized_column = func.upper(func.replace(FileNumber.mlsf_no, ' ', ''))
    return db.query(FileNumber.id).filter(normalized_column == key).first() is not None


def _pic_cofo_exists(db, file_number: Optional[str]) -> bool:
    """Check if a CofO entry already exists for the given file number."""
    key = _normalize_file_number_key(file_number)
    if not key:
        return False
    normalized_column = func.upper(func.replace(CofO.mls_fno, ' ', ''))
    return db.query(CofO.id).filter(normalized_column == key).first() is not None


def _import_pic_file_number_record(
    db,
    record: Dict[str, Any],
    timestamp: datetime,
    test_control: str
) -> bool:
    """Insert a PIC file-number record into the fileNumber table."""
    file_number = _normalize_string(record.get('mlsfNo') or record.get('mlsFNo'))
    if not file_number:
        return False

    created_by_value = _normalize_string(record.get('created_by') or record.get('CreatedBy'))
    file_name_value = _normalize_string(record.get('FileName'))
    location_value = _normalize_string(record.get('location'))
    plot_no_value = _normalize_string(record.get('plot_no'))
    tp_no_value = _normalize_string(record.get('tp_no'))
    tracking_id_value = _normalize_string(record.get('tracking_id')) or _generate_tracking_id()
    source_value = _normalize_string(record.get('SOURCE') or record.get('source')) or 'Property Index Card'
    type_value = _normalize_string(record.get('type')) or 'MLS'

    entry = FileNumber(
        mlsf_no=file_number,
        file_name=file_name_value or file_number,
        created_at=timestamp,
        location=location_value,
        created_by=created_by_value,
        updated_by=created_by_value,
        type=type_value,
        source=source_value,
        plot_no=plot_no_value,
        tp_no=tp_no_value,
        tracking_id=tracking_id_value,
        test_control=test_control
    )
    db.add(entry)
    return True


def _synchronize_pic_cofo_visibility(
    property_records: List[Dict[str, Any]],
    cofo_records: List[Dict[str, Any]]
) -> None:
    """Keep CofO preview flags aligned with property transaction type rules."""
    max_len = max(len(property_records), len(cofo_records))
    for idx in range(max_len):
        property_record = property_records[idx] if idx < len(property_records) else None
        cofo_record = cofo_records[idx] if idx < len(cofo_records) else None

        is_valid = False
        if property_record is not None:
            is_valid = _is_pic_cofo_transaction(property_record.get('transaction_type'))
            property_record['is_valid_cofo_transaction'] = is_valid

        if cofo_record is not None:
            cofo_record['is_valid_cofo_transaction'] = is_valid
            cofo_record['skip_cofo_preview'] = not is_valid


def _annotate_pic_party_types(record: Dict[str, Any]) -> None:
    """Annotate grantor/grantee-style parties with customer type classifications."""
    party_mappings = (
        ('Grantor', 'grantor_type'),
        ('Assignor', 'assignor_type'),
        ('Grantee', 'grantee_type'),
        ('Assignee', 'assignee_type'),
        ('secondary_assignee', 'secondary_assignee_type'),
    )

    for field_name, type_key in party_mappings:
        value = _normalize_string(record.get(field_name))
        if value:
            record[type_key] = _classify_customer_type(value)
        else:
            record.pop(type_key, None)


def _build_pic_property_record(row: pd.Series) -> Optional[Dict[str, Any]]:
    """Convert a PIC CSV row into a property record payload."""
    original_file_number = _normalize_string(
        row.get('MLSFileNo')
        or row.get('MLS File No')
        or row.get('mlsFNo')
        or row.get('mls_file_no')
    )

    transaction_type = _normalize_string(row.get('transaction_type'))
    assignor = _normalize_string(row.get('Grantor'))
    grantee = _normalize_string(row.get('Grantee'))
    assignee = _normalize_string(row.get('Assignee')) or grantee

    # Extract serial numbers: serialNo is the actual Serial No, oldKNNo is the Old KN Number
    # Use _normalize_numeric_field to handle potential numeric values and remove .0
    serial_register = _normalize_numeric_field(row.get('serialNo'))
    serial_card = _normalize_old_kn_number(
        row.get('oldKNNo')
        or row.get('OldKNNo')
        or row.get('old_kn_no')
        or row.get('Old KN No')
    )

    fallback_file_number = serial_register or serial_card
    file_number = original_file_number or fallback_file_number
    file_number_source = 'MLSFileNo' if original_file_number else (
        'serialNo' if serial_register else (
            'oldKNNo' if serial_card else 'none'
        )
    )

    # Allow records even without file_number for PIC
    page_no = _normalize_numeric_field(row.get('pageNo'))
    volume_no = _normalize_numeric_field(row.get('volumeNo'))
    reg_no = _normalize_string(row.get('regNo'))
    period = _normalize_string(row.get('period'))
    period_unit = _normalize_string(row.get('period_unit'))

    assignment_iso, assignment_raw = _parse_file_history_date(row.get('Assignment Date'))
    surrender_iso, surrender_raw = _parse_file_history_date(row.get('Surrender Date'))
    revoked_iso, revoked_raw = _parse_file_history_date(row.get('Revoked date'))
    expired_iso, expired_raw = _parse_file_history_date(row.get('Date Expired'))
    begins_iso, begins_raw = _parse_file_history_date(row.get('lease_begins'))
    expires_iso, expires_raw = _parse_file_history_date(row.get('lease_expires'))
    recommended_iso, recommended_raw = _parse_file_history_date(row.get('date_recommended'))
    approved_iso, approved_raw = _parse_file_history_date(row.get('date_approved'))
    created_iso, created_raw = _parse_file_history_date(row.get('DateCreated'))

    transaction_date_iso, transaction_date_raw, transaction_date_source = _resolve_pic_transaction_date(
        transaction_type,
        row
    )

    location_value = _normalize_string(row.get('location'))
    property_description = _normalize_string(row.get('property_description')) or location_value

    record = {
        'mlsFNo': file_number,
        'fileno': file_number,
        'file_number': file_number,
        'mlsFNo_original': original_file_number,
        'mlsFNo_source': file_number_source,
        'transaction_type': transaction_type,
        'instrument_type': transaction_type,
        'Assignor': assignor,
        'Grantor': assignor,
        'Assignee': assignee,
        'Grantee': assignee or grantee,
        'secondary_assignee': _normalize_string(row.get('Assignee')),
        'grantee_original': grantee,
        'land_use': _normalize_string(row.get('land_use')) or _normalize_string(row.get('Landuse')),
        'property_description': property_description,
        'location': location_value or property_description,
        'streetName': _normalize_string(row.get('streetName')),
        'house_no': _normalize_string(row.get('house_no')),
        'districtName': _normalize_string(row.get('districtName')),
        'plot_no': _normalize_string(row.get('plot_no')),
        'LGA': _normalize_string(row.get('LGA')),
        'lgsaOrCity': _normalize_string(row.get('LGA')),
        'layout': _normalize_string(row.get('layout')),
        'tp_no': _normalize_string(row.get('tp_no')),
        'lpkn_no': _normalize_string(row.get('lpkn_no')),
        'approved_plan_no': _normalize_string(row.get('approved_plan_no')),
        'plot_size': _normalize_string(row.get('plot_size')),
        'period': period,
        'period_unit': period_unit,
        'serial_register': serial_register,
        'serialNo': serial_register,
        'oldKNNo': serial_card,
        'serial_fallback_used': bool(serial_card and not serial_register),
        'serial_missing': not bool(serial_register),
        'pageNo': page_no,
        'volumeNo': volume_no,
        'regNo': reg_no,
        'metric_sheet': _normalize_string(row.get('metric_sheet')),
        'regranted_from': _normalize_string(row.get('regranted from')),
        'comments': _normalize_string(row.get('Comments')),
        'remarks': _normalize_string(row.get('Remarks')),
        'assignment_date': assignment_iso,
        'assignment_date_raw': assignment_raw,
        'surrender_date': surrender_iso,
        'surrender_date_raw': surrender_raw,
        'revoked_date': revoked_iso,
        'revoked_date_raw': revoked_raw,
        'date_expired': expired_iso,
        'date_expired_raw': expired_raw,
        'lease_begins': begins_iso,
        'lease_begins_raw': begins_raw,
        'lease_expires': expires_iso,
        'lease_expires_raw': expires_raw,
        'date_recommended': recommended_iso,
        'date_recommended_raw': recommended_raw,
        'date_approved': approved_iso,
        'date_approved_raw': approved_raw,
        'transaction_date': transaction_date_iso,
        'transaction_date_raw': transaction_date_raw,
        'transaction_date_source': transaction_date_source,
        'created_by': _normalize_string(row.get('CreatedBy')) or 'System',
        'CreatedBy': _normalize_string(row.get('CreatedBy')) or 'System',
        'date_created': created_iso or created_raw,
        'DateCreated': created_raw,
        'reg_date': approved_iso or approved_raw,
        'reg_date_raw': approved_raw or approved_iso,
        'source': _normalize_string(row.get('source')) or 'Property Index Card',
        'migration_source': 'Property Index Card',
        'migrated_by': 'PIC Import',
        'tracking_id': None,
        'prop_id': None,
        'hasIssues': False,
        'is_valid_cofo_transaction': _is_pic_cofo_transaction(transaction_type)
    }

    _annotate_pic_party_types(record)
    _recalculate_pic_serial_state(record)
    return record


def _build_pic_cofo_record(property_record: Dict[str, Any]) -> Dict[str, Any]:
    """Create a CofO preview entry from a PIC property record."""
    is_valid_transaction = _is_pic_cofo_transaction(property_record.get('transaction_type'))
    return {
        'mlsFNo': property_record.get('mlsFNo'),
        'transaction_type': property_record.get('transaction_type'),
        'instrument_type': property_record.get('instrument_type'),
        'Grantor': property_record.get('Grantor'),
        'Grantee': property_record.get('Grantee'),
        'Assignor': property_record.get('Assignor'),
        'Assignee': property_record.get('Assignee'),
        'grantor_type': property_record.get('grantor_type'),
        'assignor_type': property_record.get('assignor_type'),
        'grantee_type': property_record.get('grantee_type'),
        'assignee_type': property_record.get('assignee_type'),
        'secondary_assignee_type': property_record.get('secondary_assignee_type'),
        'land_use': property_record.get('land_use'),
        'property_description': property_record.get('property_description'),
        'location': property_record.get('location'),
        'transaction_date': property_record.get('transaction_date'),
        'transaction_date_raw': property_record.get('transaction_date_raw'),
        'transaction_time': None,
        'transaction_time_raw': None,
        'serialNo': property_record.get('serialNo'),
        'oldKNNo': property_record.get('oldKNNo'),
        'SerialNo': property_record.get('SerialNo'),
        'serial_fallback_used': property_record.get('serial_fallback_used'),
        'pageNo': property_record.get('pageNo'),
        'volumeNo': property_record.get('volumeNo'),
        'regNo': property_record.get('regNo'),
        'created_by': property_record.get('created_by'),
        'reg_date': property_record.get('reg_date'),
        'reg_date_raw': property_record.get('reg_date_raw'),
        'cofo_date': property_record.get('reg_date') or property_record.get('date_approved'),
        'source': property_record.get('source'),
        'migration_source': property_record.get('migration_source'),
        'migrated_by': property_record.get('migrated_by'),
        'prop_id': property_record.get('prop_id'),
        'hasIssues': property_record.get('hasIssues', False),
        'is_valid_cofo_transaction': is_valid_transaction,
        'skip_cofo_preview': not is_valid_transaction
    }


FILE_NUMBER_LABEL_PATTERN = re.compile(r'^[A-Z0-9]{2,}(?:[-/][A-Z0-9]{1,}){1,5}$')


def _looks_like_file_number_label(label: Optional[str], file_number: Optional[str]) -> bool:
    candidate = _normalize_string(label)
    if not candidate:
        return False

    candidate_key = _normalize_file_number_key(candidate)
    if not candidate_key:
        return False

    file_key = _normalize_file_number_key(file_number)
    if file_key and candidate_key == file_key:
        return True

    if FILE_NUMBER_LABEL_PATTERN.fullmatch(candidate_key):
        return True

    if any(char.isdigit() for char in candidate) and any(sep in candidate for sep in {'-', '/'}):
        return True

    return False


def _build_pic_file_number_record(property_record: Dict[str, Any], property_index: int) -> Optional[Dict[str, Any]]:
    """Create a file-number preview entry when the grantee looks valid."""
    file_number = _normalize_string(property_record.get('mlsFNo'))
    grantee_value = property_record.get('Grantee') or property_record.get('grantee')
    grantee = _normalize_string(grantee_value)

    if not grantee:
        return None

    if _looks_like_file_number_label(grantee_value, file_number):
        return None

    entry = {
        'mlsfNo': file_number,
        'grantee': grantee,
        'FileName': grantee,
        'location': property_record.get('location'),
        'created_by': property_record.get('created_by'),
        'SOURCE': property_record.get('source'),
        'plot_no': property_record.get('plot_no'),
        'tp_no': property_record.get('tp_no'),
        'tracking_id': property_record.get('tracking_id'),
        'hasIssues': property_record.get('hasIssues', False),
        'property_index': property_index
    }

    tp_no = _normalize_string(property_record.get('tp_no'))
    if tp_no:
        entry['tp_no'] = tp_no

    return entry


def _process_pic_data(
    df: pd.DataFrame
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Transform PIC dataframe into property, CofO, and file-number payloads."""
    df = df.copy()
    df.columns = df.columns.str.strip()

    property_records: List[Dict[str, Any]] = []
    cofo_records: List[Dict[str, Any]] = []
    file_number_records: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        record = _build_pic_property_record(row)
        if not record:
            continue

        tracking_id = record.get('tracking_id') or _generate_tracking_id()
        record['tracking_id'] = tracking_id

        property_index = len(property_records)
        property_records.append(record)
        cofo_records.append(_build_pic_cofo_record(record.copy()))

        file_number_entry = _build_pic_file_number_record(record.copy(), property_index)
        if file_number_entry:
            file_number_entry['tracking_id'] = tracking_id
            file_number_records.append(file_number_entry)

    _synchronize_pic_cofo_visibility(property_records, cofo_records)
    file_number_records = _deduplicate_pic_file_numbers(file_number_records)
    return property_records, cofo_records, file_number_records


def _build_pra_cofo_record(property_record: Dict[str, Any], *, is_cofo_record: bool) -> Dict[str, Any]:
    """Create a CofO preview payload from a PRA property record."""
    transaction_type = property_record.get('transaction_type')
    grantor = property_record.get('Grantor') or property_record.get('grantor_assignor')
    grantee = property_record.get('Grantee') or property_record.get('grantee_assignee')
    location = property_record.get('location') or property_record.get('property_description')
    transaction_date = property_record.get('transaction_date') or property_record.get('transaction_date_raw')
    reg_date = property_record.get('date_created') or property_record.get('reg_date') or property_record.get('reg_date_raw')

    return {
        'mlsFNo': property_record.get('mlsFNo'),
        'transaction_type': transaction_type,
        'instrument_type': property_record.get('instrument_type') or transaction_type,
        'Grantor': grantor,
        'Grantee': grantee,
        'Assignor': grantor,
        'Assignee': grantee,
        'property_description': location,
        'location': location,
        'plot_no': property_record.get('plot_no'),
        'transaction_date': transaction_date,
        'transaction_date_raw': property_record.get('transaction_date_raw') or transaction_date,
        'transaction_time': None,
        'transaction_time_raw': None,
        'serialNo': property_record.get('serialNo'),
        'pageNo': property_record.get('pageNo'),
        'volumeNo': property_record.get('volumeNo'),
        'regNo': property_record.get('regNo'),
        'created_by': property_record.get('created_by'),
        'cofo_date': reg_date,
        'reg_date': reg_date,
        'reg_date_raw': property_record.get('reg_date_raw') or reg_date,
        'source': 'PRA',
        'migration_source': 'PRA',
        'migrated_by': 'PRA Import',
        'prop_id': property_record.get('prop_id'),
        'test_control': property_record.get('test_control'),
        'hasIssues': property_record.get('hasIssues', False),
        'is_cofo_record': bool(is_cofo_record),
        'skip_import': False,
        'duplicate_in_cofo': False,
        'duplicate_reason': None
    }


def _run_pic_qc_validation(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Run QC checks for PIC records using PRA-style file-number validation only."""
    for record in records:
        record['hasIssues'] = False
        record['serial_missing'] = False
        record['reg_particulars_missing'] = False
        record['serial_fallback_used'] = False

    file_numbers = [{'mlsfNo': record.get('mlsFNo')} for record in records]
    qc_issues, _ = _build_pra_file_number_qc(file_numbers)
    return qc_issues


def _apply_pic_field_update(
    property_records: List[Dict[str, Any]],
    cofo_records: List[Dict[str, Any]],
    index: int,
    record_type: Literal['records', 'cofo'],
    field: str,
    value: Optional[str]
) -> None:
    if record_type == 'records' and 0 <= index < len(property_records):
        record = property_records[index]
        cofo_record = cofo_records[index] if index < len(cofo_records) else None
        normalized = _normalize_string(value)

        if field in {'comments', 'remarks', 'metric_sheet', 'regranted_from', 'period', 'period_unit'}:
            record[field] = normalized
            return

        if field == 'oldKNNo':
            record['oldKNNo'] = normalized
            record['SerialNo'] = normalized or record.get('SerialNo')
            _recalculate_pic_serial_state(record, cofo_record)
            return

        if field == 'serialNo':
            record['serial_register'] = normalized
            record['serialNo'] = normalized
            _recalculate_pic_serial_state(record, cofo_record)
            return

        if field in {'pageNo', 'volumeNo'}:
            record[field] = normalized
            if cofo_record is not None:
                cofo_record[field] = normalized
            _recalculate_pic_serial_state(record, cofo_record)
            return

        if field in {'Grantor', 'Grantee', 'Assignor', 'Assignee'}:
            record[field] = normalized
            type_key = f"{field.lower()}_type"
            if normalized:
                record[type_key] = _classify_customer_type(normalized)
            else:
                record.pop(type_key, None)

            if cofo_record is not None:
                cofo_record[field] = normalized
                if normalized:
                    cofo_record[type_key] = record[type_key]
                else:
                    cofo_record.pop(type_key, None)
            return

        if field in {
            'assignment_date', 'surrender_date', 'revoked_date', 'date_expired',
            'lease_begins', 'lease_expires', 'date_recommended', 'date_approved', 'date_created'
        }:
            record[field] = normalized
            record[f"{field}_raw"] = normalized
            if cofo_record is not None and field in {'date_approved', 'date_created'}:
                cofo_record['reg_date'] = normalized
                cofo_record['reg_date_raw'] = normalized
            return

    if record_type == 'cofo' and 0 <= index < len(cofo_records):
        cofo_record = cofo_records[index]
        property_record = property_records[index] if index < len(property_records) else None
        normalized = _normalize_string(value)

        if field == 'oldKNNo':
            cofo_record['oldKNNo'] = normalized
            if property_record is not None:
                property_record['oldKNNo'] = normalized
                property_record['SerialNo'] = normalized or property_record.get('SerialNo')
                _recalculate_pic_serial_state(property_record, cofo_record)
            return

        if field == 'serialNo':
            cofo_record['serialNo'] = normalized
            if property_record is not None:
                property_record['serial_register'] = normalized
                property_record['serialNo'] = normalized
                _recalculate_pic_serial_state(property_record, cofo_record)
            return

        if field in {'pageNo', 'volumeNo'}:
            cofo_record[field] = normalized
            if property_record is not None:
                property_record[field] = normalized
                _recalculate_pic_serial_state(property_record, cofo_record)
            return

    _apply_file_history_field_update(property_records, cofo_records, index, record_type, field, value)


def _refresh_pic_session_state(session_data: Dict[str, Any]) -> Dict[str, Any]:
    property_records = session_data.get('property_records', [])
    cofo_records = session_data.get('cofo_records', [])
    file_number_records = session_data.get('file_number_records', [])

    _synchronize_pic_cofo_visibility(property_records, cofo_records)
    qc_issues = _run_pic_qc_validation(property_records)
    for idx, record in enumerate(property_records):
        has_issue = record.get('hasIssues', False)
        if not record.get('tracking_id'):
            record['tracking_id'] = _generate_tracking_id()
        if idx < len(cofo_records):
            cofo_records[idx]['hasIssues'] = has_issue
            cofo_records[idx]['oldKNNo'] = record.get('oldKNNo')
            cofo_records[idx]['prop_id'] = record.get('prop_id')
            cofo_records[idx]['prop_id_source'] = record.get('prop_id_source')

    file_number_records: List[Dict[str, Any]] = []
    for idx, rec in enumerate(property_records):
        entry = _build_pic_file_number_record(rec.copy(), idx)
        if not entry:
            continue
        entry['hasIssues'] = rec.get('hasIssues', False)
        entry['tracking_id'] = rec.get('tracking_id')
        file_number_records.append(entry)

    file_number_records = _deduplicate_pic_file_numbers(file_number_records)

    session_data['property_records'] = property_records
    session_data['cofo_records'] = cofo_records
    session_data['file_number_records'] = file_number_records
    session_data['qc_issues'] = qc_issues

    total_records = len(property_records)
    ready_records = sum(1 for rec in property_records if not rec.get('hasIssues'))
    validation_issues = sum(len(items) for items in qc_issues.values())

    return {
        'property_records': property_records,
        'cofo_records': cofo_records,
        'file_number_records': file_number_records,
        'issues': qc_issues,
        'total_records': total_records,
        'validation_issues': validation_issues,
        'ready_records': ready_records,
        'test_control': session_data.get('test_control')
    }












if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=os.getenv("UVICORN_RELOAD", "0") == "1"
    )











