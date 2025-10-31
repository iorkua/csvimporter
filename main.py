"""
CSV Importer FastAPI Application
Clean web application with sidebar navigation
"""

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import pandas as pd
from app.models.database import CofO, FileNumber, Grouping
import numbers
import uuid
import csv
import io
import zipfile
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.models.database import get_db_connection, FileIndexing, SessionLocal
from pydantic import BaseModel
import re

GROUPING_SKIP_PATTERNS = ['(TEMP)', ' T,', 'AND EXTENSION']
TRACKING_ID_PREFIX = 'TRK'
DEFAULT_CREATED_BY = 'MDC Import'

# Initialize FastAPI application
app = FastAPI(
    title="CSV Importer",
    description="Multi-table CSV import system",
    version="1.0.0"
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with sidebar navigation"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/file-indexing", response_class=HTMLResponse)
async def file_indexing(request: Request):
    """File indexing page with upload and preview functionality"""
    return templates.TemplateResponse("file_indexing.html", {"request": request})


@app.get("/pra", response_class=HTMLResponse)
async def pra_import(request: Request):
    """Property Records Assistance (PRA) import page"""
    return templates.TemplateResponse("pra_import.html", {"request": request})


@app.post("/api/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    """Upload and process CSV/Excel file for file indexing preview"""

    try:
        if not (file.filename.endswith('.csv') or file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

        session_id = str(uuid.uuid4())
        content = await file.read()

        if file.filename.endswith('.csv'):
            dataframe = None
            last_error = None
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    dataframe = pd.read_csv(
                        io.BytesIO(content),
                        encoding=encoding,
                        na_values=['', 'NULL', 'null', 'NaN'],
                        keep_default_na=False
                    )
                    break
                except UnicodeDecodeError as exc:
                    last_error = exc
            if dataframe is None:
                raise HTTPException(status_code=400, detail=f"Unable to decode CSV file with available encodings: {last_error}")
        else:
            dataframe = pd.read_excel(
                io.BytesIO(content),
                na_values=['', 'NULL', 'null', 'NaN'],
                keep_default_na=False
            )

        processed_df = process_file_indexing_data(dataframe)
        records = processed_df.to_dict('records')
        multiple_occurrences = analyze_file_number_occurrences(processed_df)
        grouping_preview = _build_grouping_preview(records)
        
        # Run QC validation on file numbers
        qc_issues = _run_qc_validation(records)
        
        # Generate/assign property IDs
        property_id_assignments = _assign_property_ids(records)

        if not hasattr(app, 'sessions'):
            app.sessions = {}

        app.sessions[session_id] = {
            "filename": file.filename,
            "upload_time": datetime.now(),
            "data": records,
            "multiple_occurrences": multiple_occurrences,
            "total_records": len(records),
            "grouping_preview": grouping_preview,
            "qc_issues": qc_issues,
            "property_assignments": property_id_assignments
        }

        return {
            "session_id": session_id,
            "filename": file.filename,
            "total_records": len(records),
            "multiple_occurrences_count": len(multiple_occurrences),
            "redirect_url": f"/file-indexing?session_id={session_id}",
            "grouping_preview": grouping_preview,
            "qc_summary": {
                "total_issues": sum(len(issues) for issues in qc_issues.values()),
                "padding_issues": len(qc_issues.get('padding', [])),
                "year_issues": len(qc_issues.get('year', [])),
                "spacing_issues": len(qc_issues.get('spacing', [])),
                "temp_issues": len(qc_issues.get('temp', []))
            },
            "property_id_summary": {
                "new_assignments": len([p for p in property_id_assignments if p['status'] == 'new']),
                "existing_found": len([p for p in property_id_assignments if p['status'] == 'existing'])
            }
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


@app.get("/api/preview-data/{session_id}")
async def get_preview_data(session_id: str):
    """Get preview data for file indexing"""
    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session_data = app.sessions[session_id]
    return {
        "data": session_data["data"],
        "multiple_occurrences": session_data["multiple_occurrences"],
        "total_records": session_data["total_records"],
        "filename": session_data["filename"],
        "grouping_preview": session_data.get("grouping_preview", {}),
        "qc_issues": session_data.get("qc_issues", {}),
        "property_assignments": session_data.get("property_assignments", [])
    }


@app.post("/api/import-file-indexing/{session_id}")
async def import_file_indexing(session_id: str):
    """Import file indexing data to database"""
    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session_data = app.sessions[session_id]
    db = SessionLocal()
    imported_count = 0
    cofo_count = 0
    file_number_count = 0
    grouping_summary = {'matched': 0, 'missing': 0, 'skipped': 0}
    unmatched_grouping: List[Dict[str, Any]] = []
    now = datetime.utcnow()
    source_filename = session_data.get('filename', '')

    try:
        for record in session_data["data"]:
            file_number = _normalize_string(record.get('file_number'))
            if not file_number:
                continue

            existing_indexing = db.query(FileIndexing).filter(FileIndexing.file_number == file_number).first()

            if existing_indexing and existing_indexing.tracking_id:
                tracking_id = existing_indexing.tracking_id
            else:
                tracking_id = record.get('tracking_id') or _generate_tracking_id()

            record['tracking_id'] = tracking_id

            grouping_result = _apply_grouping_updates(db, record, file_number, now)
            status = grouping_result['status']
            grouping_summary[status] = grouping_summary.get(status, 0) + 1
            if status == 'missing':
                unmatched_grouping.append({
                    'file_number': file_number,
                    'reason': grouping_result.get('reason')
                })

            record['shelf_location'] = grouping_result.get('shelf_location')

            payload = {
                'registry': _normalize_string(record.get('registry')) or '',
                'batch_no': _normalize_string(record.get('batch_no')) or '',
                'file_title': _normalize_string(record.get('file_title')) or '',
                'land_use_type': _normalize_string(record.get('land_use_type')) or '',
                'plot_number': _normalize_string(record.get('plot_number')) or '',
                'lpkn_no': _normalize_string(record.get('lpkn_no')) or '',
                'tp_no': _normalize_string(record.get('tp_no')) or '',
                'district': _normalize_string(record.get('district')) or '',
                'lga': _normalize_string(record.get('lga')) or '',
                'location': _normalize_string(record.get('location')) or _combine_location(record.get('district'), record.get('lga')) or '',
                'shelf_location': _normalize_string(record.get('shelf_location')) or '',
                'serial_no': _normalize_string(record.get('serial_no')) or ''
            }

            if existing_indexing:
                for field, value in payload.items():
                    setattr(existing_indexing, field, value)
                existing_indexing.tracking_id = tracking_id
                existing_indexing.updated_at = now
                existing_indexing.updated_by = 1
                # Assign prop_id if not already set
                if not existing_indexing.prop_id:
                    existing_indexing.prop_id = record.get('prop_id')
            else:
                file_record = FileIndexing(
                    file_number=file_number,
                    tracking_id=tracking_id,
                    status='Indexed',
                    created_at=now,
                    created_by=1,
                    prop_id=record.get('prop_id'),
                    **payload
                )
                db.add(file_record)
            imported_count += 1

            if _has_cofo_payload(record):
                cofo_record = _build_cofo_record(record)
                if cofo_record.mls_fno:
                    existing_cofo = db.query(CofO).filter(CofO.mls_fno == cofo_record.mls_fno).first()
                    if existing_cofo:
                        _update_cofo(existing_cofo, cofo_record)
                    else:
                        db.add(cofo_record)
                    cofo_count += 1

            _upsert_file_number(db, file_number, record, tracking_id, source_filename, now)
            file_number_count += 1

        db.commit()

    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(exc)}")
    finally:
        db.close()

    del app.sessions[session_id]

    return {
        "success": True,
        "imported_count": imported_count,
        "cofo_records": cofo_count,
        "file_number_records": file_number_count,
        "grouping_summary": grouping_summary,
        "unmatched_grouping": unmatched_grouping,
        "message": (
            f"Successfully imported {imported_count} file indexing records"
            + (f" and processed {cofo_count} CofO records" if cofo_count else '')
        )
    }


def _format_value(value, numeric=False):
    """Format a value for display, removing unwanted .0 for numeric-like fields."""
    if pd.isna(value):
        return ''

    # Handle pandas Timestamp objects gracefully
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime('%Y-%m-%d')

    if numeric:
        # Convert floats that are whole numbers to integers to avoid trailing .0
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            # Remove trailing zeros but keep decimal part if necessary
            return str(value).rstrip('0').rstrip('.')
        if isinstance(value, numbers.Integral):
            return str(value)

        # Strings may still carry a trailing .0 if they came from Excel export
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.endswith('.0') and stripped.replace('.', '', 1).isdigit():
                return stripped[:-2]
            return stripped

    # Default string conversion
    return str(value).strip()


def _normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None

    try:
        # Handle pandas/NumPy NaN values
        if pd.isna(value):
            return None
    except Exception:
        # pd.isna may raise if pandas isn't available for this type
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
    """Normalize numeric fields, removing unnecessary .0 for whole numbers"""
    if value is None or pd.isna(value):
        return None
    
    # Convert to string first
    string_value = str(value).strip()
    
    if not string_value:
        return None
    
    # Try to convert to float and back to see if it's a whole number
    try:
        float_value = float(string_value)
        # If it's a whole number, return as integer string
        if float_value.is_integer():
            return str(int(float_value))
        else:
            return str(float_value)
    except (ValueError, TypeError):
        # If it's not a number, return as is
        return string_value


def _collapse_whitespace(value: str) -> str:
    """Convert any whitespace runs (including non-breaking spaces) to a single space."""
    if value is None:
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def _strip_all_whitespace(value: str) -> str:
    """Remove all whitespace characters from a string."""
    if value is None:
        return ''
    return re.sub(r'\s+', '', str(value))


def _normalize_temp_suffix_format(value: str) -> str:
    """Ensure TEMP suffix uses canonical " (TEMP)" formatting if present."""
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


def _combine_location(district: str, lga: str) -> str:
    parts = [_normalize_string(district), _normalize_string(lga)]
    parts = [part for part in parts if part]
    return ', '.join(parts) if parts else None


def _build_reg_no(record: Dict[str, Any]) -> str:
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


def _should_skip_grouping(file_number: Optional[str]) -> bool:
    if not file_number:
        return True
    upper_value = file_number.upper()
    return any(pattern in upper_value for pattern in GROUPING_SKIP_PATTERNS)


def _grouping_match_info(db, file_number: Optional[str]):
    if not file_number:
        return None, 'missing', 'File number is blank'
    if _should_skip_grouping(file_number):
        return None, 'skipped', 'File number skipped by pattern rule'

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


def analyze_file_number_occurrences(df):
    """Analyze file numbers for multiple occurrences (not calling them duplicates)"""
    if 'file_number' not in df.columns:
        return {}
    
    file_number_counts = df['file_number'].value_counts()
    
    # Find file numbers that appear more than twice
    multiple_occurrences = {}
    for file_number, count in file_number_counts.items():
        if count > 2 and file_number and file_number.strip():
            indices = df[df['file_number'] == file_number].index.tolist()
            multiple_occurrences[file_number] = {
                'count': count,
                'indices': indices
            }
    
    return multiple_occurrences


@app.post("/api/upload-excel")
async def upload_excel(file: UploadFile = File(...)):
    """Upload Excel file and analyze sheets for conversion to CSV"""
    
    try:
        # Validate file type
        if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            raise HTTPException(status_code=400, detail="Only Excel files are supported")
        
        # Generate session ID
        session_id = str(uuid.uuid4())
        
        # Read Excel file
        content = await file.read()
        
        try:
            # Read all sheets
            excel_file = pd.ExcelFile(pd.io.common.BytesIO(content))
            sheet_names = excel_file.sheet_names
            
            sheets_info = []
            all_sheets_data = {}
            
            for sheet_name in sheet_names:
                df = pd.read_excel(
                    pd.io.common.BytesIO(content),
                    sheet_name=sheet_name,
                    na_values=['', 'NULL', 'null', 'NaN'],
                    keep_default_na=False
                )
                
                # Process data for this sheet
                processed_df = process_file_indexing_data(df)
                all_sheets_data[sheet_name] = processed_df.to_dict('records')
                
                sheets_info.append({
                    'name': sheet_name,
                    'rows': len(df),
                    'columns': len(df.columns),
                    'column_names': list(df.columns)
                })
            
            # Store in session
            if not hasattr(app, 'sessions'):
                app.sessions = {}
            
            app.sessions[session_id] = {
                "filename": file.filename,
                "upload_time": datetime.now(),
                "type": "excel",
                "sheets_info": sheets_info,
                "sheets_data": all_sheets_data
            }
            
            return {
                "session_id": session_id,
                "filename": file.filename,
                "sheets": sheets_info,
                "total_sheets": len(sheet_names)
            }
            
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error reading Excel file: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/api/export-sheet-csv/{session_id}/{sheet_name}")
async def export_sheet_to_csv(session_id: str, sheet_name: str):
    """Export a specific Excel sheet to CSV format"""
    from fastapi.responses import StreamingResponse
    
    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session_data = app.sessions[session_id]
    
    if session_data.get("type") != "excel":
        raise HTTPException(status_code=400, detail="Session is not for Excel file")
    
    if sheet_name not in session_data["sheets_data"]:
        raise HTTPException(status_code=404, detail="Sheet not found")
    
    try:
        # Get sheet data
        sheet_data = session_data["sheets_data"][sheet_name]
        df = pd.DataFrame(sheet_data)
        
        # Convert to CSV
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_content = csv_buffer.getvalue()
        
        # Create filename
        safe_sheet_name = "".join(c for c in sheet_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        filename = f"{safe_sheet_name}.csv"
        
        # Return as download
        return StreamingResponse(
            io.StringIO(csv_content),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting CSV: {str(e)}")


@app.post("/api/export-all-sheets-csv/{session_id}")
async def export_all_sheets_to_csv(session_id: str):
    """Export all Excel sheets to separate CSV files in a ZIP archive"""
    import zipfile
    from fastapi.responses import StreamingResponse
    
    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session_data = app.sessions[session_id]
    
    if session_data.get("type") != "excel":
        raise HTTPException(status_code=400, detail="Session is not for Excel file")
    
    try:
        # Create ZIP file in memory
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for sheet_name, sheet_data in session_data["sheets_data"].items():
                # Convert sheet to CSV
                df = pd.DataFrame(sheet_data)
                csv_buffer = io.StringIO()
                df.to_csv(csv_buffer, index=False)
                csv_content = csv_buffer.getvalue()
                
                # Add to ZIP with safe filename
                safe_sheet_name = "".join(c for c in sheet_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                csv_filename = f"{safe_sheet_name}.csv"
                zip_file.writestr(csv_filename, csv_content)
        
        zip_buffer.seek(0)
        
        # Create download filename
        base_filename = session_data["filename"].replace('.xlsx', '').replace('.xls', '')
        zip_filename = f"{base_filename}_sheets.zip"
        
        return StreamingResponse(
            io.BytesIO(zip_buffer.read()),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating ZIP: {str(e)}")


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

class QCFixPayload(BaseModel):
    record_index: int
    new_value: str


class QCFixRequest(BaseModel):
    fixes: List[QCFixPayload]


@app.post("/api/qc/apply-fixes/{session_id}")
async def apply_qc_fixes(session_id: str, payload: QCFixRequest):
    """Apply QC fixes to session data"""
    if not hasattr(app, 'sessions') or session_id not in app.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session_data = app.sessions[session_id]
    applied_fixes = []
    
    for fix in payload.fixes:
        record_index = fix.record_index
        new_value = fix.new_value
        
        if 0 <= record_index < len(session_data['data']):
            old_value = session_data['data'][record_index]['file_number']
            session_data['data'][record_index]['file_number'] = new_value
            
            applied_fixes.append({
                'record_index': record_index,
                'old_value': old_value,
                'new_value': new_value,
                'timestamp': datetime.now().isoformat()
            })
    
    # Re-run QC validation after fixes
    session_data['qc_issues'] = _run_qc_validation(session_data['data'])
    
    # Recalculate grouping preview after fixes
    session_data['grouping_preview'] = _build_grouping_preview(session_data['data'])
    
    return {
        'success': True,
        'applied_fixes': applied_fixes,
        'updated_qc_issues': session_data['qc_issues'],
        'updated_grouping_preview': session_data['grouping_preview']
    }


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
            **record,
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
            **record,
            'created_at': timestamp
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