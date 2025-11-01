"""API router for File Indexing workflows."""
from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core import session_manager
from app.models.database import CofO, FileIndexing, SessionLocal
from app.services.file_indexing_service import (
    analyze_file_number_occurrences,
    process_file_indexing_data,
    _apply_grouping_updates,
    _assign_property_ids,
    _build_cofo_record,
    _build_grouping_preview,
    _generate_tracking_id,
    _has_cofo_payload,
    _normalize_string,
    _combine_location,
    _update_cofo,
    _run_qc_validation,
    _upsert_file_number,
)

router = APIRouter()


class QCFixPayload(BaseModel):
    record_index: int
    new_value: str


class QCFixRequest(BaseModel):
    fixes: List[QCFixPayload]


@router.post("/api/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    """Upload and process CSV/Excel file for file indexing preview."""
    try:
        if not (file.filename.endswith('.csv') or file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

        session_id = session_manager.generate_session_id()
        content = await file.read()

        if file.filename.endswith('.csv'):
            dataframe = None
            last_error: Exception | None = None
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

        qc_issues = _run_qc_validation(records)
        property_id_assignments = _assign_property_ids(records)

        session_manager.set_session(session_id, {
            "filename": file.filename,
            "upload_time": datetime.now(),
            "data": records,
            "multiple_occurrences": multiple_occurrences,
            "total_records": len(records),
            "grouping_preview": grouping_preview,
            "qc_issues": qc_issues,
            "property_assignments": property_id_assignments
        })

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
        "property_assignments": session_data.get("property_assignments", [])
    }


@router.post("/api/import-file-indexing/{session_id}")
async def import_file_indexing(session_id: str):
    """Import file indexing data to database."""
    session_data = session_manager.require_session(session_id)
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
            file_number = record.get('file_number', '').strip()
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

    except Exception as exc:  # pragma: no cover - database safeguard
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(exc)}")
    finally:
        db.close()

    session_manager.delete_session(session_id)

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
