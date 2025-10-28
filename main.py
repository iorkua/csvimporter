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

        if not hasattr(app, 'sessions'):
            app.sessions = {}

        app.sessions[session_id] = {
            "filename": file.filename,
            "upload_time": datetime.now(),
            "data": records,
            "multiple_occurrences": multiple_occurrences,
            "total_records": len(records),
            "grouping_preview": grouping_preview
        }

        return {
            "session_id": session_id,
            "filename": file.filename,
            "total_records": len(records),
            "multiple_occurrences_count": len(multiple_occurrences),
            "redirect_url": f"/file-indexing?session_id={session_id}",
            "grouping_preview": grouping_preview
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
        "grouping_preview": session_data.get("grouping_preview", {})
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
            else:
                file_record = FileIndexing(
                    file_number=file_number,
                    tracking_id=tracking_id,
                    status='Indexed',
                    created_at=now,
                    created_by=1,
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
    string_value = str(value).strip()
    return string_value or None


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
        cofo_date=_normalize_string(record.get('cofo_date'))
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
        'cofo_date'
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=5000,
        reload=True
    )