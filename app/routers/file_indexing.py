"""API router for File Indexing workflows."""
from __future__ import annotations

import asyncio
import logging
import io
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Tuple

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core import session_manager
from app.models.database import CofO, FileIndexing, FileNumber, Grouping, SessionLocal
from app.services.file_indexing_service import (
    analyze_file_number_occurrences,
    process_file_indexing_data,
    _apply_grouping_updates,
    _assign_property_ids,
    _build_cofo_record,
    _build_grouping_preview,
    _has_cofo_payload,
    _normalize_cofo_date,
    _normalize_time_field,
    _normalize_string,
    _normalize_registry,
    _combine_location,
    _update_cofo,
    _run_qc_validation,
    _upsert_file_number,
)

router = APIRouter()
logger = logging.getLogger(__name__)

GROUPING_PREVIEW_MAX_RECORDS = 5000


class QCFixPayload(BaseModel):
    record_index: int
    new_value: str


class QCFixRequest(BaseModel):
    fixes: List[QCFixPayload]


class ClearDataRequest(BaseModel):
    mode: str


def _read_csv_stream(data: bytes, encoding: str) -> pd.DataFrame:
    return pd.read_csv(
        io.BytesIO(data),
        encoding=encoding,
        na_values=['', 'NULL', 'null', 'NaN'],
        keep_default_na=False
    )


def _read_excel_stream(data: bytes) -> pd.DataFrame:
    return pd.read_excel(
        io.BytesIO(data),
        na_values=['', 'NULL', 'null', 'NaN'],
        keep_default_na=False
    )


def _prepare_file_indexing_preview_payload(
    dataframe: pd.DataFrame,
    filename: str,
    test_control_value: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    start_time = datetime.utcnow()
    logger.info("Starting preview payload build for %s (%d rows)", filename, len(dataframe))
    processed_df = process_file_indexing_data(dataframe)
    records = processed_df.to_dict('records')
    multiple_occurrences = analyze_file_number_occurrences(processed_df)
    logger.info("Post-processed dataframe for %s in %.3fs", filename, (datetime.utcnow() - start_time).total_seconds())
    
    # Skip grouping preview for large datasets to improve performance
    # Only build grouping preview for smaller uploads (< 1000 records)
    record_count = len(records)

    if record_count <= GROUPING_PREVIEW_MAX_RECORDS:
        grouping_start = datetime.utcnow()
        grouping_preview = _build_grouping_preview(records)
        logger.info("Grouping preview built in %.3fs", (datetime.utcnow() - grouping_start).total_seconds())
    else:
        grouping_preview = {
            'rows': [],
            'summary': {'matched': 0, 'missing': 0, 'skipped': record_count},
            'note': (
                'Grouping preview skipped because this upload contains '
                f'{record_count} records. Preview is available for up to '
                f'{GROUPING_PREVIEW_MAX_RECORDS:,} records and will run automatically '
                'during import.'
            )
        }

    # For large datasets, skip intensive QC processing during preview
    if record_count < 2000:
        qc_start = datetime.utcnow()
        qc_issues = _run_qc_validation(records)
        logger.info("QC validation completed in %.3fs", (datetime.utcnow() - qc_start).total_seconds())
    else:
        qc_issues = {
            'padding': [],
            'year': [],
            'spacing': [],
            'note': f'QC validation skipped for large dataset ({len(records)} records). QC will run during import.'
        }
        
    prop_start = datetime.utcnow()
    property_id_assignments = _assign_property_ids(records)
    logger.info("Property ID assignment completed in %.3fs", (datetime.utcnow() - prop_start).total_seconds())

    session_payload = {
        "filename": filename,
        "upload_time": datetime.now(),
        "data": records,
        "multiple_occurrences": multiple_occurrences,
        "total_records": len(records),
        "grouping_preview": grouping_preview,
        "qc_issues": qc_issues,
        "property_assignments": property_id_assignments,
        "test_control": test_control_value
    }

    total_issue_count = sum(
        len(issue_list)
        for issue_list in qc_issues.values()
        if isinstance(issue_list, list)
    )

    qc_summary = {
        "total_issues": total_issue_count,
        "padding_issues": len(qc_issues.get('padding', [])),
        "year_issues": len(qc_issues.get('year', [])),
        "spacing_issues": len(qc_issues.get('spacing', []))
    }

    property_id_summary = {
        "new_assignments": len([p for p in property_id_assignments if p['status'] == 'new']),
        "existing_found": len([p for p in property_id_assignments if p['status'] == 'existing'])
    }

    response_payload = {
        "filename": filename,
        "total_records": len(records),
        "multiple_occurrences_count": len(multiple_occurrences),
        "grouping_preview": grouping_preview,
        "qc_summary": qc_summary,
        "property_id_summary": property_id_summary,
        "test_control": test_control_value
    }

    logger.info(
        "Preview payload completed for %s in %.3fs",
        filename,
        (datetime.utcnow() - start_time).total_seconds()
    )

    return session_payload, response_payload


@router.post("/api/upload-csv")
async def upload_csv(
    file: UploadFile = File(...),
    test_control: str = Form(...)
):
    """Upload and process CSV/Excel file for file indexing preview."""
    try:
        if not (file.filename.endswith('.csv') or file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

        test_control_value = (test_control or '').strip().upper()
        if test_control_value not in {'TEST', 'PRODUCTION'}:
            raise HTTPException(status_code=400, detail="Invalid test control value. Choose TEST or PRODUCTION.")

        session_id = session_manager.generate_session_id()
        content = await file.read()

        if file.filename.endswith('.csv'):
            dataframe = None
            last_error: Exception | None = None
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    dataframe = await asyncio.to_thread(
                        _read_csv_stream,
                        content,
                        encoding
                    )
                    break
                except UnicodeDecodeError as exc:
                    last_error = exc
            if dataframe is None:
                raise HTTPException(status_code=400, detail=f"Unable to decode CSV file with available encodings: {last_error}")
        else:
            dataframe = await asyncio.to_thread(_read_excel_stream, content)

        session_payload, response_payload = await asyncio.to_thread(
            _prepare_file_indexing_preview_payload,
            dataframe,
            file.filename,
            test_control_value
        )

        session_manager.set_session(session_id, session_payload)

        response_payload.update({
            "session_id": session_id,
            "redirect_url": f"/file-indexing?session_id={session_id}"
        })

        return response_payload

    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - generic safety net
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


@router.get("/api/preview-data/{session_id}")
async def get_preview_data(session_id: str):
    """Get preview data for file indexing."""
    session_data = session_manager.require_session(session_id)
    return {
        "data": session_data["data"],
        "multiple_occurrences": session_data["multiple_occurrences"],
        "total_records": session_data["total_records"],
        "filename": session_data["filename"],
        "grouping_preview": session_data.get("grouping_preview", {}),
        "qc_issues": session_data.get("qc_issues", {}),
        "property_assignments": session_data.get("property_assignments", []),
        "test_control": session_data.get("test_control", 'PRODUCTION')
    }


@router.post("/api/import-file-indexing/{session_id}")
async def import_file_indexing(session_id: str):
    """Start file indexing import as a background task."""
    session_data = session_manager.require_session(session_id)
    
    # Initialize progress tracking
    progress_key = f"import_progress_{session_id}"
    session_manager.set_session(progress_key, {
        "status": "starting",
        "progress": 0,
        "total": len(session_data["data"]),
        "current_batch": 0,
        "message": "Starting import...",
        "start_time": datetime.utcnow().isoformat()
    })
    
    # Start background task
    asyncio.create_task(_background_import_task(session_data, session_id, progress_key))
    
    return {
        "success": True,
        "message": "Import started in background",
        "progress_url": f"/api/import-progress/{session_id}",
        "session_id": session_id
    }


async def _background_import_task(session_data: Dict[str, Any], session_id: str, progress_key: str):
    """Run import in background and update progress."""
    try:
        result = await asyncio.to_thread(_process_import_data, session_data, progress_key)
        
        # Update final progress
        session_manager.set_session(progress_key, {
            "status": "completed",
            "progress": 100,
            "total": len(session_data["data"]),
            "message": "Import completed successfully!",
            "result": result,
            "end_time": datetime.utcnow().isoformat()
        })
        
        session_manager.delete_session(session_id)
        
    except Exception as exc:
        logger.error("Background import failed for session %s: %s", session_id, exc)
        session_manager.set_session(progress_key, {
            "status": "error",
            "progress": 0,
            "message": f"Import failed: {str(exc)}",
            "error": str(exc),
            "end_time": datetime.utcnow().isoformat()
        })


@router.get("/api/import-progress/{session_id}")
async def get_import_progress(session_id: str):
    """Get current import progress."""
    progress_key = f"import_progress_{session_id}"
    try:
        progress_data = session_manager.require_session(progress_key)
        return progress_data
    except:
        return {"status": "not_found", "message": "Import progress not found"}


def _process_import_data(session_data: Dict[str, Any], progress_key: str = None) -> Dict[str, Any]:
    """Process import data in a separate thread to avoid blocking."""
    db = SessionLocal()
    imported_count = 0
    cofo_count = 0
    file_number_count = 0
    grouping_summary = {'matched': 0, 'missing': 0, 'skipped': 0}
    unmatched_grouping: List[Dict[str, Any]] = []
    now = datetime.utcnow()
    source_filename = session_data.get('filename', '')
    test_control = (session_data.get('test_control') or 'PRODUCTION').upper()

    def update_progress(current: int, total: int, message: str, batch_num: int = 0):
        if progress_key:
            try:
                session_manager.set_session(progress_key, {
                    "status": "processing",
                    "progress": round((current / total) * 100, 1),
                    "current": current,
                    "total": total,
                    "current_batch": batch_num,
                    "message": message
                })
            except:
                pass  # Don't fail import if progress update fails

    try:
        # Process records in batches to avoid timeouts
        batch_size = 50
        total_records = len(session_data["data"])
        
        update_progress(0, total_records, "Starting import...", 0)
        
        for i, record in enumerate(session_data["data"]):
            file_number = record.get('file_number', '').strip()
            if not file_number:
                continue

            record['test_control'] = test_control
            existing_indexing = db.query(FileIndexing).filter(FileIndexing.file_number == file_number).first()

            existing_tracking_id = None
            if existing_indexing and existing_indexing.tracking_id:
                existing_tracking_id = existing_indexing.tracking_id
            elif record.get('tracking_id'):
                existing_tracking_id = record['tracking_id']

            record['tracking_id'] = existing_tracking_id

            grouping_result = _apply_grouping_updates(db, record, file_number, now, test_control)
            status = grouping_result['status']
            grouping_summary[status] = grouping_summary.get(status, 0) + 1
            if status == 'missing':
                unmatched_grouping.append({
                    'file_number': file_number,
                    'reason': grouping_result.get('reason')
                })

            grouping_row = grouping_result.pop('grouping_record', None)

            tracking_id = grouping_result.get('tracking_id') or existing_tracking_id
            if grouping_row and grouping_row.tracking_id and not tracking_id:
                tracking_id = grouping_row.tracking_id

            if not tracking_id:
                if status == 'matched':
                    grouping_summary['matched'] = max(0, grouping_summary.get('matched', 0) - 1)
                    grouping_summary['skipped'] = grouping_summary.get('skipped', 0) + 1
                    unmatched_grouping.append({
                        'file_number': file_number,
                        'reason': 'Matched grouping record is missing tracking_id'
                    })
                logger.warning("Skipping import for %s because tracking_id is unavailable", file_number)
                continue

            record['tracking_id'] = tracking_id

            if grouping_row and status == 'matched' and not grouping_row.tracking_id:
                grouping_row.tracking_id = tracking_id

            # Update record with grouping results
            record['shelf_location'] = grouping_result.get('shelf_location')
            record['group'] = grouping_result.get('group')
            record['sys_batch_no'] = grouping_result.get('sys_batch_no')

            # Helper function to safely convert batch_no to integer
            def safe_int_conversion(value):
                if value is None or value == '':
                    return None
                try:
                    return int(str(value).strip())
                except (ValueError, TypeError):
                    return None

            created_by_raw = record.get('created_by')
            created_by_value = safe_int_conversion(created_by_raw)
            normalized_created_by = _normalize_string(created_by_raw)
            if created_by_value is None and not normalized_created_by:
                logger.warning("Created By missing for file number %s; preserving existing values where possible", file_number)
            record['created_by'] = (
                str(created_by_value) if created_by_value is not None else (normalized_created_by or '')
            )

            normalized_cofo_date = _normalize_cofo_date(record.get('cofo_date'))
            record['cofo_date'] = normalized_cofo_date or ''

            normalized_deeds_time = _normalize_time_field(record.get('deeds_time') or record.get('transaction_time'))
            record['deeds_time'] = normalized_deeds_time or ''

            payload = {
                'registry': _normalize_registry(record.get('registry')) or '',
                'batch_no': safe_int_conversion(record.get('batch_no')),
                'file_title': _normalize_string(record.get('file_title')) or '',
                'land_use_type': _normalize_string(record.get('land_use_type')) or '',
                'plot_number': _normalize_string(record.get('plot_number')) or '',
                'lpkn_no': _normalize_string(record.get('lpkn_no')) or '',
                'tp_no': _normalize_string(record.get('tp_no')) or '',
                'district': _normalize_string(record.get('district')) or '',
                'lga': _normalize_string(record.get('lga')) or '',
                'location': _normalize_string(record.get('location')) or _combine_location(record.get('district'), record.get('lga')) or '',
                'shelf_location': _normalize_string(record.get('shelf_location')) or '',
                'serial_no': _normalize_string(record.get('serial_no')) or '',
                'group': _normalize_string(record.get('group')) or '',  # Copy group from grouping table
                'sys_batch_no': _normalize_string(record.get('sys_batch_no')) or ''  # Copy sys_batch_no from grouping table
            }

            if existing_indexing:
                for field, value in payload.items():
                    setattr(existing_indexing, field, value)
                existing_indexing.tracking_id = tracking_id
                existing_indexing.updated_at = now
                if created_by_value is not None:
                    existing_indexing.updated_by = created_by_value
                    if existing_indexing.created_by is None:
                        existing_indexing.created_by = created_by_value
                existing_indexing.test_control = test_control
            else:
                file_record = FileIndexing(
                    file_number=file_number,
                    tracking_id=tracking_id,
                    status='Indexed',
                    created_at=now,
                    created_by=created_by_value if created_by_value is not None else None,
                    updated_by=created_by_value if created_by_value is not None else None,
                    test_control=test_control,
                    **payload
                )
                db.add(file_record)
            imported_count += 1

            if _has_cofo_payload(record):
                cofo_record = _build_cofo_record(record, test_control)
                if cofo_record.mls_fno:
                    existing_cofo = db.query(CofO).filter(CofO.mls_fno == cofo_record.mls_fno).first()
                    if existing_cofo:
                        _update_cofo(existing_cofo, cofo_record)
                        existing_cofo.test_control = test_control
                    else:
                        db.add(cofo_record)
                    cofo_count += 1

            _upsert_file_number(db, file_number, record, tracking_id, source_filename, now, test_control)
            file_number_count += 1

            # Update progress for each individual record
            progress_msg = f"Processing record {i + 1} of {total_records}"
            update_progress(i + 1, total_records, progress_msg, 0)
            
            # Commit in batches to avoid timeouts
            if (i + 1) % batch_size == 0 or (i + 1) == total_records:
                batch_num = ((i + 1) // batch_size) + (1 if (i + 1) % batch_size > 0 else 0)
                batch_start = max(1, i + 2 - batch_size)
                logger.info("Committing batch %d-%d of %d records", 
                           batch_start, i + 1, total_records)
                db.commit()

        # Final commit (may be redundant but ensures everything is saved)
        db.commit()

    except Exception as exc:  # pragma: no cover - database safeguard
        db.rollback()
        raise exc  # Re-raise as regular exception, not HTTPException
    finally:
        db.close()

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


@router.post("/api/file-indexing/clear-data")
async def clear_file_indexing_data(request: ClearDataRequest):
    mode = (request.mode or '').strip().upper()
    if mode not in {"TEST", "PRODUCTION"}:
        raise HTTPException(status_code=400, detail="Invalid data mode. Choose TEST or PRODUCTION.")

    db = SessionLocal()

    try:
        grouping_update_fields = {
            Grouping.indexing_mls_fileno: None,
            Grouping.indexing_mapping: 0,
            Grouping.date_index: None,
            Grouping.indexed_by: None,
            Grouping.mdc_batch_no: None,
            Grouping.test_control: None
        }

        grouping_query = db.query(Grouping).filter(Grouping.test_control == mode)
        grouping_rows_affected = grouping_query.update(grouping_update_fields, synchronize_session=False)

        counts = {
            "file_indexings": db.query(FileIndexing).filter(FileIndexing.test_control == mode).delete(synchronize_session=False),
            "CofO": db.query(CofO).filter(CofO.test_control == mode).delete(synchronize_session=False),
            "fileNumber": db.query(FileNumber).filter(FileNumber.test_control == mode).delete(synchronize_session=False),
            "grouping": grouping_rows_affected
        }
        db.commit()
        return {
            "success": True,
            "mode": mode,
            "counts": counts
        }
    except Exception as exc:  # pragma: no cover - safeguards against cascading delete errors
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to clear {mode} data: {exc}")
    finally:
        db.close()


router.add_api_route(
    "/api/file-indexing/clear-data/",
    clear_file_indexing_data,
    methods=["POST"],
    include_in_schema=False
)


@router.post("/api/upload-excel")
async def upload_excel(file: UploadFile = File(...)):
    """Upload Excel file and analyze sheets for conversion to CSV."""
    try:
        if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            raise HTTPException(status_code=400, detail="Only Excel files are supported")

        session_id = session_manager.generate_session_id()
        content = await file.read()

        try:
            excel_file = pd.ExcelFile(pd.io.common.BytesIO(content))
            sheet_names = excel_file.sheet_names

            sheets_info: List[Dict[str, Any]] = []
            all_sheets_data: Dict[str, List[Dict[str, Any]]] = {}

            for sheet_name in sheet_names:
                df = pd.read_excel(
                    pd.io.common.BytesIO(content),
                    sheet_name=sheet_name,
                    na_values=['', 'NULL', 'null', 'NaN'],
                    keep_default_na=False
                )

                processed_df = process_file_indexing_data(df)
                all_sheets_data[sheet_name] = processed_df.to_dict('records')

                sheets_info.append({
                    'name': sheet_name,
                    'rows': len(df),
                    'columns': len(df.columns),
                    'column_names': list(df.columns)
                })

            session_manager.set_session(session_id, {
                "filename": file.filename,
                "upload_time": datetime.now(),
                "type": "excel",
                "sheets_info": sheets_info,
                "sheets_data": all_sheets_data
            })

            return {
                "session_id": session_id,
                "filename": file.filename,
                "sheets": sheets_info,
                "total_sheets": len(sheet_names)
            }

        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Error reading Excel file: {str(exc)}")

    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


@router.get("/api/export-sheet-csv/{session_id}/{sheet_name}")
async def export_sheet_to_csv(session_id: str, sheet_name: str):
    """Export a specific Excel sheet to CSV format."""
    session_data = session_manager.require_session(session_id)

    if session_data.get("type") != "excel":
        raise HTTPException(status_code=400, detail="Session is not for Excel file")

    if sheet_name not in session_data["sheets_data"]:
        raise HTTPException(status_code=404, detail="Sheet not found")

    try:
        sheet_data = session_data["sheets_data"][sheet_name]
        df = pd.DataFrame(sheet_data)

        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_content = csv_buffer.getvalue()

        safe_sheet_name = "".join(c for c in sheet_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        filename = f"{safe_sheet_name}.csv"

        return StreamingResponse(
            io.StringIO(csv_content),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Error exporting CSV: {str(exc)}")


@router.post("/api/export-all-sheets-csv/{session_id}")
async def export_all_sheets_to_csv(session_id: str):
    """Export all Excel sheets to separate CSV files in a ZIP archive."""
    session_data = session_manager.require_session(session_id)

    if session_data.get("type") != "excel":
        raise HTTPException(status_code=400, detail="Session is not for Excel file")

    try:
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for sheet_name, sheet_data in session_data["sheets_data"].items():
                df = pd.DataFrame(sheet_data)
                csv_buffer = io.StringIO()
                df.to_csv(csv_buffer, index=False)
                csv_content = csv_buffer.getvalue()

                safe_sheet_name = "".join(c for c in sheet_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                csv_filename = f"{safe_sheet_name}.csv"
                zip_file.writestr(csv_filename, csv_content)

        zip_buffer.seek(0)

        base_filename = session_data["filename"].replace('.xlsx', '').replace('.xls', '')
        zip_filename = f"{base_filename}_sheets.zip"

        return StreamingResponse(
            io.BytesIO(zip_buffer.read()),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
        )

    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Error creating ZIP: {str(exc)}")


@router.get("/api/debug-sessions")
async def list_debug_sessions():
    """List available session IDs (debug only)."""
    return {"sessions": list(session_manager.list_sessions())}


@router.get("/api/debug-session/{session_id}")
async def debug_session(session_id: str):
    """Debug endpoint to see session data."""
    session_data = session_manager.get_session(session_id)
    if session_data is None:
        return {"error": "Session not found"}

    return {
        "session_exists": True,
        "filename": session_data.get("filename"),
        "total_records": session_data.get("total_records"),
        "data_count": len(session_data.get("data", [])),
        "sample_record": session_data.get("data", [{}])[0] if session_data.get("data") else {},
        "multiple_occurrences_count": len(session_data.get("multiple_occurrences", {}))
    }


@router.post("/api/qc/apply-fixes/{session_id}")
async def apply_qc_fixes(session_id: str, payload: QCFixRequest):
    """Apply QC fixes to session data."""
    session_data = session_manager.require_session(session_id)
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

    session_data['qc_issues'] = _run_qc_validation(session_data['data'])
    session_data['grouping_preview'] = _build_grouping_preview(session_data['data'])

    return {
        'success': True,
        'applied_fixes': applied_fixes,
        'updated_qc_issues': session_data['qc_issues'],
        'updated_grouping_preview': session_data['grouping_preview']
    }
