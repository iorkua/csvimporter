from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models.database import CofO, FileIndexing, FileNumber, SessionLocal


@dataclass
class DuplicateGroup:
    table: str
    group_key: str
    display_value: str
    records: List[Dict[str, Any]]
    keep_id: int


_TABLE_MAP = {
    "file_indexing": {
        "model": FileIndexing,
        "number_attr": "file_number",
        "display_name": "File Indexing",
    },
    "cofo": {
        "model": CofO,
        "number_attr": "mls_fno",
        "display_name": "CofO Staging",
    },
    "file_number": {
        "model": FileNumber,
        "number_attr": "mlsf_no",
        "display_name": "File Number",
    },
}


def _normalize(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = "".join(text.upper().split())
    normalized = normalized.replace("-", "")
    return normalized or None


def _format_timestamp(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _choose_keep(records: Sequence[Dict[str, Any]], test_control: Optional[str]) -> int:
    def weight(item: Dict[str, Any]) -> Tuple[int, int, int, str]:
        control_score = 1 if (test_control and item.get("test_control") == test_control) else 0
        tracking_score = 1 if item.get("tracking_id") else 0
        prop_score = 1 if item.get("prop_id") else 0
        timestamp = item.get("updated_at") or item.get("created_at") or ""
        return (control_score, tracking_score, prop_score, timestamp)

    best = max(records, key=weight)
    return int(best["id"])  # type: ignore[arg-type]


def _serialize_record(obj: Any, number_attr: str, table_key: str) -> Dict[str, Any]:
    data = {
        "id": getattr(obj, "id"),
        "file_number": getattr(obj, number_attr, None),
        "created_at": _format_timestamp(getattr(obj, "created_at", None)),
        "updated_at": _format_timestamp(getattr(obj, "updated_at", None)),
        "test_control": getattr(obj, "test_control", None),
        "tracking_id": getattr(obj, "tracking_id", None),
        "prop_id": getattr(obj, "prop_id", None),
    }
    if table_key == "file_indexing":
        data["file_title"] = getattr(obj, "file_title", None)
        data["file_name"] = getattr(obj, "file_title", None) or getattr(obj, "file_name", None)
        batch_value = getattr(obj, "batch_no", None)
        if batch_value is not None:
            try:
                data["batch_no"] = int(batch_value)
            except (TypeError, ValueError):
                data["batch_no"] = str(batch_value)
        else:
            data["batch_no"] = None
        data["registry"] = getattr(obj, "registry", None)
        data["created_by"] = getattr(obj, "created_by", None)
    elif table_key == "file_number":
        data["file_name"] = getattr(obj, "file_name", None)
    elif table_key == "cofo":
        grantor_value = getattr(obj, "grantor", None) or getattr(obj, "Grantor", None)
        grantee_value = getattr(obj, "grantee", None) or getattr(obj, "Grantee", None)
        data["grantor"] = grantor_value
        data["grantee"] = grantee_value
        data["Grantor"] = grantor_value
        data["Grantee"] = grantee_value
        data["created_by"] = getattr(obj, "created_by", None)
    return data


def _gather_groups(
    session: Session,
    table_key: str,
    test_control: Optional[str] = None,
) -> List[DuplicateGroup]:
    config = _TABLE_MAP[table_key]
    model = config["model"]
    number_attr = config["number_attr"]

    query = session.query(model)
    if test_control and hasattr(model, "test_control"):
        query = query.filter(getattr(model, "test_control") == test_control)

    items = query.all()

    buckets: Dict[str, List[Any]] = defaultdict(list)
    for item in items:
        number_value = getattr(item, number_attr, None)
        normalized = _normalize(number_value)
        if not normalized:
            continue
        buckets[normalized].append(item)

    groups: List[DuplicateGroup] = []
    for normalized_key, objects in buckets.items():
        if len(objects) < 2:
            continue
        serialized = [_serialize_record(obj, number_attr, table_key) for obj in objects]
        keep_id = _choose_keep(serialized, test_control)
        display_values = {record.get("file_number") or "" for record in serialized}
        display_value = ", ".join(sorted(filter(None, display_values))) or normalized_key
        for record in serialized:
            record["locked"] = record["id"] == keep_id
        groups.append(
            DuplicateGroup(
                table=table_key,
                group_key=normalized_key,
                display_value=display_value,
                records=serialized,
                keep_id=keep_id,
            )
        )

    groups.sort(key=lambda group: group.display_value)
    return groups


def get_duplicate_groups(
    table: str,
    test_control: Optional[str],
    page: int,
    page_size: int,
) -> Dict[str, Any]:
    if table not in _TABLE_MAP:
        raise ValueError("Unknown table")

    session = SessionLocal()
    try:
        groups = _gather_groups(session, table, test_control)
        total = len(groups)
        start = max(page - 1, 0) * page_size
        end = start + page_size
        page_items = groups[start:end]
        return {
            "table": table,
            "table_label": _TABLE_MAP[table]["display_name"],
            "page": page,
            "page_size": page_size,
            "total_groups": total,
            "groups": [
                {
                    "group_key": group.group_key,
                    "display_value": group.display_value,
                    "keep_id": group.keep_id,
                    "records": group.records,
                }
                for group in page_items
            ],
        }
    finally:
        session.close()


def delete_duplicates(
    table: str,
    operations: Iterable[Dict[str, Any]],
    test_control: Optional[str] = None,
) -> Dict[str, Any]:
    if table not in _TABLE_MAP:
        raise ValueError("Unknown table")

    config = _TABLE_MAP[table]
    model = config["model"]
    number_attr = config["number_attr"]

    session = SessionLocal()
    deleted_total = 0
    try:
        for op in operations:
            keep_id = op.get("keep_id")
            delete_ids: List[int] = [int(x) for x in op.get("delete_ids", [])]
            if not delete_ids:
                continue
            if keep_id in delete_ids:
                raise ValueError("keep_id cannot be deleted")

            query = session.query(model).filter(model.id.in_(delete_ids))
            if test_control and hasattr(model, "test_control"):
                query = query.filter(getattr(model, "test_control") == test_control)

            rows = query.all()
            for row in rows:
                number_value = getattr(row, number_attr, None)
                normalized = _normalize(number_value)
                if normalized != op.get("group_key"):
                    raise ValueError("Mismatch between group key and record")
                session.delete(row)
                deleted_total += 1

        session.commit()
        return {"deleted": deleted_total}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
