"""Service helpers for FileNO import workflow."""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple, Set

import pandas as pd
from sqlalchemy import func

from app.models.database import FileNumber, Grouping, SessionLocal
from app.services.file_indexing_service import (
    _normalize_string,
    _remove_file_number_suffixes,
    _normalize_file_number_for_match,
)


REQUIRED_COLUMNS = {"mlsfno", "currentallottee"}
EXPECTED_COLUMNS = {
    "mlsfno": "mlsf_no",
    "kangisfileno": "kangis_file_no",
    "plotno": "plot_no",
    "tpplanno": "tp_plan_no",
    "currentallottee": "current_allottee",
    "layoutname": "layout_name",
    "districtname": "district_name",
    "lganame": "lga_name",
}

IN_QUERY_CHUNK_SIZE = 900


@dataclass
class FileNumberRecord:
    row_index: int
    file_number: Optional[str]
    clean_number: Optional[str]
    canonical: Optional[str]
    file_name: Optional[str]
    location: Optional[str]
    plot_no: Optional[str]
    tp_no: Optional[str]
    kangis_file_no: Optional[str]
    layout_name: Optional[str]
    district_name: Optional[str]
    lga_name: Optional[str]
    status: str
    status_label: str
    issues: List[str]
    existing_id: Optional[int]
    grouping_id: Optional[int]
    grouping_tracking_id: Optional[str]
    grouping_status: str

    def to_preview_row(self) -> Dict[str, Any]:
        return {
            "index": self.row_index + 1,
            "file_number": self.file_number or "",
            "status": self.status,
            "status_label": self.status_label,
            "file_name": self.file_name or "",
            "location": self.location or "",
            "plot_no": self.plot_no or "",
            "tp_no": self.tp_no or "",
            "kangis_file_no": self.kangis_file_no or "",
            "grouping_status": self.grouping_status,
        }

    def to_session_dict(self) -> Dict[str, Any]:
        return {
            "row_index": self.row_index,
            "file_number": self.file_number,
            "clean_number": self.clean_number,
            "canonical": self.canonical,
            "file_name": self.file_name,
            "location": self.location,
            "plot_no": self.plot_no,
            "tp_no": self.tp_no,
            "kangis_file_no": self.kangis_file_no,
            "layout_name": self.layout_name,
            "district_name": self.district_name,
            "lga_name": self.lga_name,
            "status": self.status,
            "status_label": self.status_label,
            "issues": self.issues,
            "existing_id": self.existing_id,
            "grouping_id": self.grouping_id,
            "grouping_tracking_id": self.grouping_tracking_id,
            "grouping_status": self.grouping_status,
        }


def read_input_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    if filename.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content))

    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(content), encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Unable to decode CSV file with supported encodings")


def _build_location(layout: Optional[str], lga: Optional[str], district: Optional[str]) -> Optional[str]:
    parts: List[str] = []
    for value in (layout, lga, district):
        normalized = _normalize_string(value)
        if normalized:
            parts.append(normalized)
    if not parts:
        return None
    return ", ".join(parts)


def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed: Dict[str, str] = {}
    for column in df.columns:
        key = str(column).strip().lower()
        if key in EXPECTED_COLUMNS:
            renamed[column] = EXPECTED_COLUMNS[key]
    standardized = df.rename(columns=renamed)
    for required in REQUIRED_COLUMNS:
        if required not in {col.strip().lower() for col in df.columns}:
            raise ValueError(f"Missing required column '{required}' in upload")
    return standardized


def _normalize_row_value(row: Any, column: str) -> Optional[str]:
    """Safely extract a column from pandas rows (Series, dict, namedtuple)."""
    value: Any = None
    if hasattr(row, column):
        value = getattr(row, column)
    elif isinstance(row, dict):
        value = row.get(column)
    else:
        try:
            value = row[column]  # type: ignore[index]
        except Exception:
            value = None
    return _normalize_string(value)


def _chunked(values: Iterable[str], size: int = IN_QUERY_CHUNK_SIZE) -> Iterable[List[str]]:
    """Yield successive chunks of strings to keep SQL IN clauses small."""
    chunk: List[str] = []
    for value in values:
        chunk.append(value)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def build_records(dataframe: pd.DataFrame) -> List[FileNumberRecord]:
    df = _standardize_columns(dataframe)
    records: List[FileNumberRecord] = []
    seen_canonicals: Dict[str, int] = {}

    for row in df.itertuples(index=True, name="FileNumberRow"):
        pandas_index = getattr(row, "Index")
        try:
            row_index = int(pandas_index)
        except (TypeError, ValueError):
            row_index = len(records)
        raw_file_number = _normalize_row_value(row, "mlsf_no")
        file_name = _normalize_row_value(row, "current_allottee")

        issues: List[str] = []
        if not raw_file_number:
            issues.append("Missing mlsfNo")
        if not file_name:
            issues.append("Missing currentAllottee")

        clean_value = _remove_file_number_suffixes(raw_file_number) or raw_file_number
        canonical = _normalize_file_number_for_match(raw_file_number)

        layout = _normalize_row_value(row, "layout_name")
        district = _normalize_row_value(row, "district_name")
        lga = _normalize_row_value(row, "lga_name")
        location = _build_location(layout, lga, district)

        kangis_value = _normalize_row_value(row, "kangis_file_no")
        plot_value = _normalize_row_value(row, "plot_no")
        tp_value = _normalize_row_value(row, "tp_plan_no")

        status = "ready" if not issues else "invalid"
        status_label = "Ready"
        if issues:
            status_label = "Invalid"

        if canonical:
            if canonical in seen_canonicals:
                status = "duplicate_upload"
                status_label = "Duplicate in upload"
            else:
                seen_canonicals[canonical] = row_index

        record = FileNumberRecord(
            row_index=row_index,
            file_number=raw_file_number,
            clean_number=clean_value,
            canonical=canonical,
            file_name=file_name,
            location=location,
            plot_no=plot_value,
            tp_no=tp_value,
            kangis_file_no=kangis_value,
            layout_name=layout,
            district_name=district,
            lga_name=lga,
            status=status,
            status_label=status_label,
            issues=issues,
            existing_id=None,
            grouping_id=None,
            grouping_tracking_id=None,
            grouping_status="missing",
        )
        records.append(record)

    return records


def annotate_with_existing(records: List[FileNumberRecord], test_control: str) -> None:
    canonicals = {record.canonical for record in records if record.canonical}
    if not canonicals:
        return

    possible_values: List[str] = []
    seen_values: Set[str] = set()
    for record in records:
        for candidate in (record.file_number, record.clean_number):
            if candidate:
                upper_candidate = candidate.upper()
                if upper_candidate in seen_values:
                    continue
                seen_values.add(upper_candidate)
                possible_values.append(candidate)

    if not possible_values:
        return

    existing_map: Dict[str, int] = {}
    with SessionLocal() as db:
        for chunk in _chunked(possible_values):
            existing_rows = (
                db.query(FileNumber.id, FileNumber.mlsf_no)
                .filter(FileNumber.mlsf_no.isnot(None))
                .filter(FileNumber.mlsf_no.in_(chunk))
                .all()
            )
            for row_id, row_mlsf_no in existing_rows:
                canonical = _normalize_file_number_for_match(row_mlsf_no)
                if not canonical:
                    continue
                existing_map[canonical] = row_id

    for record in records:
        if record.status in {"invalid", "duplicate_upload"}:
            continue
        if record.canonical and record.canonical in existing_map:
            record.status = "duplicate_existing"
            record.status_label = "Already exists in FileNumber"
            record.existing_id = existing_map[record.canonical]
        else:
            record.status = "insert"
            record.status_label = "Will insert"


def annotate_with_grouping(records: List[FileNumberRecord], test_control: str) -> None:
    candidate_values: List[str] = []
    seen_candidates: Set[str] = set()
    for record in records:
        for candidate in (record.file_number, record.clean_number):
            if not candidate:
                continue
            upper_candidate = candidate.upper()
            if upper_candidate in seen_candidates:
                continue
            seen_candidates.add(upper_candidate)
            candidate_values.append(candidate)
    if not candidate_values:
        return

    grouping_map: Dict[str, Tuple[int, Optional[str]]] = {}
    with SessionLocal() as db:
        for chunk in _chunked(candidate_values):
            grouping_rows = (
                db.query(Grouping.id, Grouping.awaiting_fileno, Grouping.tracking_id)
                .filter(Grouping.awaiting_fileno.isnot(None))
                .filter(Grouping.awaiting_fileno.in_(chunk))
                .all()
            )
            for grouping_id, awaiting_value, tracking_id in grouping_rows:
                canonical = _normalize_file_number_for_match(awaiting_value)
                if not canonical:
                    continue
                grouping_map[canonical] = (grouping_id, tracking_id)

    for record in records:
        canonical = record.canonical
        if not canonical:
            continue
        if canonical not in grouping_map:
            continue
        grouping_id, grouping_tracking = grouping_map[canonical]
        record.grouping_id = grouping_id
        record.grouping_tracking_id = _normalize_string(grouping_tracking)
        record.grouping_status = "matched"
        if record.status in {"insert", "update"} and not record.grouping_tracking_id:
            record.grouping_tracking_id = _normalize_string(grouping_tracking)


def summarise_records(records: List[FileNumberRecord]) -> Dict[str, int]:
    summary = {
        "total_rows": len(records),
        "new_records": 0,
        "update_records": 0,
        "duplicates": 0,
        "invalid": 0,
    }
    for record in records:
        if record.status == "insert":
            summary["new_records"] += 1
        elif record.status == "update":
            summary["update_records"] += 1
        elif record.status in {"duplicate_upload", "duplicate_existing"}:
            summary["duplicates"] += 1
        elif record.status == "invalid":
            summary["invalid"] += 1
    summary["ready_for_import"] = summary["new_records"] + summary["update_records"]
    return summary


def build_preview_payload(records: List[FileNumberRecord], test_control: str) -> Dict[str, Any]:
    annotate_with_existing(records, test_control)
    annotate_with_grouping(records, test_control)
    summary = summarise_records(records)
    preview_rows = [record.to_preview_row() for record in records]
    return {
        "summary": summary,
        "preview_rows": preview_rows,
    }


def import_records(records: List[FileNumberRecord], test_control: str, filename: str) -> Dict[str, int]:
    now = datetime.utcnow()
    inserted = 0
    updated = 0
    skipped_duplicates = 0
    skipped_invalid = 0
    grouping_updates = 0

    db = SessionLocal()
    try:
        for record in records:
            if record.status in {"duplicate_upload", "duplicate_existing"}:
                skipped_duplicates += 1
                continue
            if record.status == "invalid":
                skipped_invalid += 1
                continue

            if not record.file_number or not record.file_name:
                skipped_invalid += 1
                continue

            tracking_id = record.grouping_tracking_id
            if not tracking_id and record.grouping_id:
                grouping_row = db.query(Grouping).get(record.grouping_id)
                if grouping_row and grouping_row.tracking_id:
                    tracking_id = _normalize_string(grouping_row.tracking_id)

            existing_entry: Optional[FileNumber] = None
            if record.existing_id:
                existing_entry = db.query(FileNumber).get(record.existing_id)

            if existing_entry:
                existing_entry.file_name = record.file_name
                existing_entry.location = record.location
                existing_entry.plot_no = record.plot_no
                existing_entry.tp_no = record.tp_no
                existing_entry.updated_at = now
                existing_entry.updated_by = "CSV Bulk Importer"
                existing_entry.type = "KANGIS"
                existing_entry.source = "KANGIS GIS"
                existing_entry.test_control = test_control
                if hasattr(existing_entry, "kangis_file_no"):
                    existing_entry.kangis_file_no = record.kangis_file_no
                if hasattr(existing_entry, "new_kangis_file_no"):
                    existing_entry.new_kangis_file_no = None
                if hasattr(existing_entry, "date_migrated"):
                    existing_entry.date_migrated = now
                if hasattr(existing_entry, "migration_source"):
                    existing_entry.migration_source = "KANGIS GIS"
                if hasattr(existing_entry, "migrated_by"):
                    existing_entry.migrated_by = "1"
                if hasattr(existing_entry, "is_deleted"):
                    existing_entry.is_deleted = False
                if tracking_id:
                    existing_entry.tracking_id = tracking_id
                updated += 1
            else:
                entry = FileNumber(
                    mlsf_no=record.file_number,
                    file_name=record.file_name,
                    location=record.location,
                    plot_no=record.plot_no,
                    tp_no=record.tp_no,
                    created_by="CSV Bulk Importer",
                    updated_by="CSV Bulk Importer",
                    created_at=now,
                    updated_at=now,
                    type="KANGIS",
                    source="KANGIS GIS",
                    test_control=test_control,
                    tracking_id=tracking_id,
                )
                if hasattr(entry, "kangis_file_no"):
                    entry.kangis_file_no = record.kangis_file_no
                if hasattr(entry, "new_kangis_file_no"):
                    entry.new_kangis_file_no = None
                if hasattr(entry, "date_migrated"):
                    entry.date_migrated = now
                if hasattr(entry, "migration_source"):
                    entry.migration_source = "KANGIS GIS"
                if hasattr(entry, "migrated_by"):
                    entry.migrated_by = "1"
                if hasattr(entry, "is_deleted"):
                    entry.is_deleted = False
                db.add(entry)
                db.flush()
                record.existing_id = entry.id
                existing_entry = entry
                inserted += 1

            if record.grouping_id:
                grouping_row = db.query(Grouping).get(record.grouping_id)
                if grouping_row:
                    grouping_row.indexing_mapping = 1
                    grouping_row.indexing_mls_fileno = record.file_number
                    grouping_row.test_control = test_control
                    if tracking_id and not grouping_row.tracking_id:
                        grouping_row.tracking_id = tracking_id
                    grouping_updates += 1

        db.commit()
        return {
            "inserted": inserted,
            "updated": updated,
            "skipped_duplicates": skipped_duplicates,
            "skipped_invalid": skipped_invalid,
            "grouping_updates": grouping_updates,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def records_from_session(data: List[Dict[str, Any]]) -> List[FileNumberRecord]:
    records: List[FileNumberRecord] = []
    for item in data:
        records.append(FileNumberRecord(
            row_index=int(item.get("row_index", 0)),
            file_number=item.get("file_number"),
            clean_number=item.get("clean_number"),
            canonical=item.get("canonical"),
            file_name=item.get("file_name"),
            location=item.get("location"),
            plot_no=item.get("plot_no"),
            tp_no=item.get("tp_no"),
            kangis_file_no=item.get("kangis_file_no"),
            layout_name=item.get("layout_name"),
            district_name=item.get("district_name"),
            lga_name=item.get("lga_name"),
            status=item.get("status", "ready"),
            status_label=item.get("status_label", "Ready"),
            issues=item.get("issues", []),
            existing_id=item.get("existing_id"),
            grouping_id=item.get("grouping_id"),
            grouping_tracking_id=item.get("grouping_tracking_id"),
            grouping_status=item.get("grouping_status", "missing"),
        ))
    return records
