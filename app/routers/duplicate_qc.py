from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from app.services.duplicate_qc_service import delete_duplicates, get_duplicate_groups

router = APIRouter()

templates = Jinja2Templates(directory="templates")


@router.get("/duplicate-qc")
async def duplicate_qc_page(request: Request):
    return templates.TemplateResponse("duplicate_qc.html", {"request": request})


@router.get("/api/duplicate-qc/groups")
async def duplicate_qc_groups(
    table: str = Query(..., regex="^(file_indexing|cofo|file_number)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    test_control: str | None = Query(None, regex="^(TEST|PRODUCTION)$"),
):
    try:
        payload = get_duplicate_groups(table=table, test_control=test_control, page=page, page_size=page_size)
        return JSONResponse(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/duplicate-qc/delete")
async def duplicate_qc_delete(payload: dict):
    table = payload.get("table")
    operations = payload.get("groups", [])
    test_control = payload.get("test_control")

    if table not in {"file_indexing", "cofo", "file_number"}:
        raise HTTPException(status_code=400, detail="Unknown table")

    if test_control not in {None, "TEST", "PRODUCTION"}:
        raise HTTPException(status_code=400, detail="Invalid test control")

    if not isinstance(operations, list) or not operations:
        raise HTTPException(status_code=400, detail="No duplicate groups supplied")

    try:
        result = delete_duplicates(table=table, operations=operations, test_control=test_control)
        return JSONResponse({"status": "success", **result})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover - defensive safety net
        raise HTTPException(status_code=500, detail=str(exc))
