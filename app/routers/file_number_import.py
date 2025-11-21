"""API router for FileNO import workflow."""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core import session_manager
from app.services.file_number_import_service import (
    build_preview_payload,
    build_records,
    import_records,
    read_input_dataframe,
    records_from_session,
)

router = APIRouter(prefix="/api/file-number-import", tags=["file-number-import"])


def _validate_test_control(value: str) -> str:
    normalized = (value or "").strip().upper()
    if normalized not in {"TEST", "PRODUCTION"}:
        raise HTTPException(status_code=400, detail="Invalid test control value. Choose TEST or PRODUCTION.")
    return normalized


@router.post("/upload")
async def upload_file_number_csv(
    file: UploadFile = File(...),
    test_control: str = Form(...),
):
    if not file.filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only CSV or Excel files are supported")

    control = _validate_test_control(test_control)

    try:
        content = await file.read()
        dataframe = await asyncio.to_thread(read_input_dataframe, content, file.filename)
        records = await asyncio.to_thread(build_records, dataframe)
        preview_payload = await asyncio.to_thread(build_preview_payload, records, control)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - generic safeguard
        raise HTTPException(status_code=500, detail=f"Failed to process file: {exc}") from exc

    session_id = session_manager.generate_session_id()
    session_manager.set_session(
        session_id,
        {
            "filename": file.filename,
            "test_control": control,
            "records": [record.to_session_dict() for record in records],
            "summary": preview_payload["summary"],
            "preview_rows": preview_payload["preview_rows"],
        },
    )

    return {
        "session_id": session_id,
        "filename": file.filename,
        "test_control": control,
        "summary": preview_payload["summary"],
        "preview_rows": preview_payload["preview_rows"],
    }


@router.get("/preview/{session_id}")
async def get_file_number_preview(session_id: str):
    session_data: Dict[str, Any] = session_manager.require_session(session_id)
    return {
        "filename": session_data.get("filename"),
        "test_control": session_data.get("test_control"),
        "summary": session_data.get("summary", {}),
        "preview_rows": session_data.get("preview_rows", []),
    }


@router.post("/import/{session_id}")
async def import_file_numbers(session_id: str):
    session_data: Dict[str, Any] = session_manager.require_session(session_id)
    records = records_from_session(session_data.get("records", []))
    control = session_data.get("test_control", "PRODUCTION")
    filename = session_data.get("filename", "upload.csv")

    try:
        summary = await asyncio.to_thread(import_records, records, control, filename)
    except Exception as exc:  # pragma: no cover - surfacing import failure
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}") from exc

    session_manager.delete_session(session_id)
    return {
        "success": True,
        "summary": summary,
    }
