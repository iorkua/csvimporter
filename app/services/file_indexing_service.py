"""Business logic for file indexing workflows.

The helpers here were extracted from the FastAPI entrypoint to make them
importable by routers and other modules.
"""
from __future__ import annotations

import calendar
import logging
import numbers
import re
import uuid
import warnings
import time
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import pandas as pd
from sqlalchemy import func, text
from sqlalchemy.sql import bindparam

from app.models.database import CofO, FileIndexing, FileNumber, Grouping, SessionLocal

TRACKING_ID_PREFIX = 'TRK'

logger = logging.getLogger(__name__)

_COFO_DATE_WARNING_CACHE: Set[str] = set()
_MAX_COFO_DATE_WARNINGS = 25
_COFO_DATE_CAP_LOGGED = False

REASON_RETIRED_ALIAS_MAP = {
    'assignment': 'Assignment',
    'deed of assignment': 'Assignment',
    'withdrawn': 'Withdrawn',
    'withdraw': 'Withdrawn',
    'withdrawal': 'Withdrawn',
    'sub division': 'Sub Division',
    'subdivision': 'Sub Division',
    'subdivided': 'Sub Division',
    'sub divide': 'Sub Division',
    'menger': 'Menger',
    'surrender': 'Surrender',
    'revocation': 'Revocation',
    'revoked': 'Revocation',
}


def _format_value(value, numeric: bool = False):
    """Format a value for display, removing unwanted .0 for numeric-like fields."""
    if pd.isna(value):
        return ''

    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime('%Y-%m-%d')

    if numeric:
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            return str(value).rstrip('0').rstrip('.')
        if isinstance(value, numbers.Integral):
            return str(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.endswith('.0') and stripped.replace('.', '', 1).isdigit():
                return stripped[:-2]
            return stripped

    return str(value).strip()


def _normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
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
    """Normalize numeric fields, removing unnecessary .0 for whole numbers."""
    if value is None or pd.isna(value):
        return None

    string_value = str(value).strip()
    if not string_value:
        return None

    try:
        float_value = float(string_value)
        if float_value.is_integer():
            return str(int(float_value))
        return str(float_value)
    except (ValueError, TypeError):
        return string_value


def _normalize_old_kn_number(value: Any) -> Optional[str]:
    """Normalize Old KN Number by replacing hyphens with spaces.
    Example: KN-101 -> KN 101, KN-102 -> KN 102"""
    if value is None or pd.isna(value):
        return None
    
    string_value = str(value).strip()
    if not string_value:
        return None
    
    # Replace hyphens with spaces
    return string_value.replace('-', ' ')


def _normalize_reason_retired_key(value: str) -> str:
    """Normalize transaction text for reason_retired comparisons."""
    lowered = value.lower()
    lowered = lowered.replace('_', ' ')
    lowered = lowered.replace('-', ' ')
    cleaned = re.sub(r'[^a-z0-9\s]', ' ', lowered)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()


def _canonical_reason_retired(value: Optional[str]) -> Optional[str]:
    """Return canonical reason_retired if value matches allowed transaction types."""
    if not value:
        return None

    normalized_key = _normalize_reason_retired_key(value)
    if not normalized_key:
        return None

    tokens = normalized_key.split()

    for alias, canonical in REASON_RETIRED_ALIAS_MAP.items():
        alias_tokens = alias.split()
        if normalized_key == alias:
            return canonical
        if normalized_key.startswith(f"{alias} "):
            return canonical
        if alias in normalized_key:
            return canonical
        if len(alias_tokens) == 1 and alias_tokens[0] in tokens:
            return canonical
        if len(alias_tokens) > 1:
            window = len(alias_tokens)
            for idx in range(len(tokens) - window + 1):
                if tokens[idx: idx + window] == alias_tokens:
                    return canonical

    return None


def _collapse_whitespace(value: str) -> str:
    if value is None:
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def _strip_all_whitespace(value: str) -> str:
    if value is None:
        return ''
    return re.sub(r'\s+', '', str(value))


def _remove_file_number_suffixes(value: Any) -> Optional[str]:
    """Strip trailing suffixes like 'AND EXTENSION' for canonical comparisons."""
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    suffix_patterns = (
        r'\s+(?:AND\s+EXTENSION)\s*$',
        r'\s*&\s*EXTENSION\s*$',
    )

    while True:
        updated = text
        for pattern in suffix_patterns:
            updated = re.sub(pattern, '', updated, flags=re.IGNORECASE).strip()
        if updated == text:
            break
        text = updated

    return text if text else None


def _normalize_file_number_for_match(value: Any) -> Optional[str]:
    normalized = _normalize_string(value)
    if not normalized:
        return None

    normalized = _remove_file_number_suffixes(normalized) or normalized
    normalized = normalized.upper()
    normalized = re.sub(r'\s+', '', normalized)
    normalized = normalized.replace('-', '')
    return normalized if normalized else None


@lru_cache(maxsize=2048)
def _parse_cofo_date_value(normalized: str) -> Optional[str]:
    if not normalized:
        return None

    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        for day_first in (True, False):
            parsed = pd.to_datetime(normalized, errors='coerce', dayfirst=day_first)
            if not pd.isna(parsed):
                return parsed.strftime('%d-%m-%Y')
    return None


def _record_cofo_date_warning(value: str) -> None:
    global _COFO_DATE_CAP_LOGGED

    if not value:
        return

    if value in _COFO_DATE_WARNING_CACHE:
        return

    if len(_COFO_DATE_WARNING_CACHE) >= _MAX_COFO_DATE_WARNINGS:
        if not _COFO_DATE_CAP_LOGGED:
            logger.warning(
                "Additional cofo_date parse warnings suppressed after %s unique values",
                _MAX_COFO_DATE_WARNINGS
            )
            _COFO_DATE_CAP_LOGGED = True
        return

    _COFO_DATE_WARNING_CACHE.add(value)
    logger.debug("Unable to parse cofo_date '%s'", value)

    if len(_COFO_DATE_WARNING_CACHE) >= _MAX_COFO_DATE_WARNINGS and not _COFO_DATE_CAP_LOGGED:
        logger.debug(
            "Additional cofo_date parse warnings suppressed after %s unique values",
            _MAX_COFO_DATE_WARNINGS
        )
        _COFO_DATE_CAP_LOGGED = True


def _coerce_cofo_date_components(parts: List[str]) -> Optional[str]:
    if len(parts) != 3:
        return None

    cleaned: List[Optional[int]] = []
    for part in parts:
        digits = re.sub(r'\D', '', part or '')
        if digits == '':
            cleaned.append(None)
            continue
        cleaned.append(int(digits))

    day, month, year = cleaned

    if year is None:
        return None

    # Normalize common year entry issues (two-digit years, missing 9 in 1980s, etc.)
    if year < 100:
        year += 2000 if year < 30 else 1900
    elif 100 <= year <= 999:
        year += 1900
    elif 1000 <= year <= 1099:
        year += 900

    if month is None or month == 0:
        return None

    if not 1 <= month <= 12:
        return None

    if day is None or day == 0:
        return None

    day = max(1, min(31, day))

    try:
        last_day = calendar.monthrange(year, month)[1]
    except calendar.IllegalMonthError:
        return None

    day = min(day, last_day)

    return f"{day:02d}-{month:02d}-{year:04d}"


def _normalize_cofo_date(value: Any) -> Optional[str]:
    normalized = _normalize_string(value)
    if not normalized:
        return None

    original_normalized = normalized.strip()
    normalized = original_normalized.replace('/', '-').replace('.', '-').replace('\\', '-')
    normalized = re.sub(r'\s+', '-', normalized)
    normalized = re.sub(r'-{2,}', '-', normalized).strip('-')

    sanitized = re.sub(r'[^0-9-]', '-', normalized)
    sanitized = re.sub(r'-{2,}', '-', sanitized).strip('-')

    candidates = []
    if sanitized:
        candidates.append(sanitized)
    if normalized and normalized != sanitized:
        candidates.append(normalized)
    if original_normalized and original_normalized not in candidates:
        candidates.append(original_normalized)

    # Attempt to coerce obvious numeric component issues before parsing
    numeric_parts = [part for part in (sanitized or '').split('-') if part]
    coerced_candidate = _coerce_cofo_date_components(numeric_parts)
    if coerced_candidate:
        candidates.insert(0, coerced_candidate)

    for candidate in candidates:
        parsed = _parse_cofo_date_value(candidate)
        if parsed:
            return parsed

    digits = re.sub(r'\D', '', sanitized or original_normalized)
    if len(digits) < 6:
        return original_normalized

    _record_cofo_date_warning(original_normalized)
    return original_normalized


def _normalize_time_field(value: Any) -> Optional[str]:
    normalized = _normalize_string(value)
    if not normalized:
        return None

    working = normalized.replace('.', ':')
    working = re.sub(r'\s+', ' ', working).strip().upper()

    am_pm = ''
    match = re.search(r'(AM|PM)$', working)
    if match:
        am_pm = match.group(1)
        working = working[:match.start()].strip()

    working = working.replace(' ', '')

    if ':' not in working:
        digits_only = re.sub(r'[^0-9]', '', working)
        if digits_only.isdigit() and len(digits_only) >= 3:
            split_index = len(digits_only) - 2
            working = f"{digits_only[:split_index]}:{digits_only[split_index:]}"
        else:
            working = digits_only or working

    segments = [segment for segment in working.split(':') if segment != '']
    for index, segment in enumerate(segments):
        if segment.isdigit():
            segments[index] = segment.zfill(2)
    working = ':'.join(segments)

    formatted = working
    if am_pm:
        formatted = f"{working} {am_pm}"

    validation_formats = [
        "%I:%M %p",
        "%H:%M",
        "%I:%M:%S %p",
        "%H:%M:%S",
        "%I %M %p",
        "%H%M"
    ]

    for fmt in validation_formats:
        try:
            datetime.strptime(formatted, fmt)
            return formatted
        except ValueError:
            continue

    return formatted


def _normalize_registry(value: Any) -> Optional[str]:
    """Normalize registry values so different user inputs map to just the number (1, 2, 3)."""
    normalized = _normalize_string(value)
    if not normalized:
        return None

    candidate = normalized.strip().lower()

    # If it's already just a digit, return it (removing leading zeros)
    exact_digit = re.fullmatch(r'\d+', candidate)
    if exact_digit:
        number = exact_digit.group(0).lstrip('0') or '0'
        return number

    # Extract number from "registry N" or "reg N" format
    suffix_match = re.fullmatch(r'(?:registry|reg)\s*(\d+)', candidate)
    if suffix_match:
        number = suffix_match.group(1).lstrip('0') or '0'
        return number

    # If it contains "registry" but doesn't match the pattern above, 
    # try to extract any trailing number
    if 'registry' in candidate:
        number_match = re.search(r'(\d+)$', candidate)
        if number_match:
            number = number_match.group(1).lstrip('0') or '0'
            return number

    return normalized


def _standardize_file_number(value: Any) -> Optional[str]:
    normalized = _normalize_string(value)
    if not normalized:
        return None
    normalized = _remove_file_number_suffixes(normalized) or normalized
    return normalized.upper()


def _chunk_list(values: List[str], size: int) -> Iterable[List[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _combine_location(district: str, lga: str) -> Optional[str]:
    parts = [_normalize_string(district), _normalize_string(lga)]
    parts = [part for part in parts if part]
    return ', '.join(parts) if parts else None


def _build_reg_no(record: Dict[str, Any]) -> Optional[str]:
    serial = _normalize_string(record.get('serial_no'))
    page = _normalize_string(record.get('page_no'))
    volume = _normalize_string(record.get('vol_no'))
    if serial and page and volume:
        return f"{serial}/{page}/{volume}"
    return None


def _has_cofo_payload(record: Dict[str, Any]) -> bool:
    cofo_fields = ['cofo_date', 'serial_no', 'page_no', 'vol_no', 'deeds_time', 'deeds_date']
    return any(_normalize_string(record.get(field)) for field in cofo_fields)


def _build_cofo_record(record: Dict[str, Any], test_control: str) -> CofO:
    location = _combine_location(record.get('district'), record.get('lga'))
    reg_no = _build_reg_no(record)

    return CofO(
        mls_fno=_normalize_string(record.get('file_number')),
        title_type='COFO',
        transaction_type='Certificate of Occupancy',
        instrument_type='Certificate of Occupancy',
    transaction_date=_normalize_string(record.get('deeds_date') or record.get('transaction_date')),
    transaction_time=_normalize_time_field(record.get('deeds_time') or record.get('transaction_time')),
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
        cofo_date=_normalize_cofo_date(record.get('cofo_date')),
        prop_id=record.get('prop_id'),
        test_control=test_control
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
        'prop_id',
        'test_control'
    ]

    for field in fields_to_sync:
        new_value = getattr(source, field)
        if new_value:
            setattr(target, field, new_value)


def _generate_tracking_id() -> str:
    token = uuid.uuid4().hex.upper()
    return f"{TRACKING_ID_PREFIX}-{token[:8]}-{token[8:13]}"


def _grouping_match_info(db, file_number: Optional[str]):
    canonical_input = _normalize_file_number_for_match(file_number)
    if not canonical_input:
        return None, 'missing', 'File number is blank'

    normalized_input = _normalize_string(file_number)
    grouping_row = None
    base_input = _remove_file_number_suffixes(normalized_input) if normalized_input else None

    if normalized_input:
        grouping_row = db.query(Grouping).filter(Grouping.awaiting_fileno == normalized_input).first()

    if not grouping_row:
        candidate_value = base_input or normalized_input
        if candidate_value:
            grouping_row = db.query(Grouping).filter(Grouping.awaiting_fileno == candidate_value).first()

    if not grouping_row and base_input:
        grouping_row = (
            db.query(Grouping)
            .filter(func.upper(Grouping.awaiting_fileno) == base_input.upper())
            .first()
        )

    if not grouping_row and base_input:
        candidates = (
            db.query(Grouping)
            .filter(func.upper(Grouping.awaiting_fileno).like(f"{base_input.upper()}%"))
            .all()
        )
        for candidate in candidates:
            candidate_canonical = _normalize_file_number_for_match(candidate.awaiting_fileno)
            if candidate_canonical and candidate_canonical == canonical_input:
                grouping_row = candidate
                break

    if not grouping_row:
        grouping_row = (
            db.query(Grouping)
            .filter(
                func.replace(
                    func.replace(func.upper(Grouping.awaiting_fileno), '-', ''),
                    ' ',
                    ''
                ) == canonical_input
            )
            .first()
        )

    if grouping_row:
        return grouping_row, 'matched', ''
    return None, 'missing', 'Awaiting file number not found in grouping table'

def _build_grouping_preview(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Assemble grouping preview data with optimized database queries for large grouping tables."""
    summary = {'matched': 0, 'missing': 0, 'skipped': 0}
    rows: List[Dict[str, Any]] = []

    standardized_numbers: List[Optional[str]] = []
    unique_numbers: List[str] = []
    seen_numbers: Set[str] = set()

    # Process input records first
    for record in records:
        standardized = _standardize_file_number(record.get('file_number'))
        standardized_numbers.append(standardized)
        if standardized and standardized not in seen_numbers:
            seen_numbers.add(standardized)
            unique_numbers.append(standardized)

    grouping_map: Dict[str, Grouping] = {}
    if unique_numbers:
        with SessionLocal() as db:
            # Strategy 1: Direct exact matches first (fastest)
            for chunk in _chunk_list(unique_numbers, 1000):
                if not chunk:
                    continue
                
                # Try exact matches first
                exact_matches = (
                    db.query(Grouping)
                    .filter(Grouping.awaiting_fileno.in_(chunk))
                    .all()
                )
                for grouping_row in exact_matches:
                    key = _standardize_file_number(grouping_row.awaiting_fileno)
                    if key and key not in grouping_map:
                        grouping_map[key] = grouping_row

                # For unmatched items, try case-insensitive matches
                matched_keys = set(grouping_map.keys())
                unmatched = [num for num in chunk if num not in matched_keys]
                
                if unmatched:
                    case_insensitive_matches = (
                        db.query(Grouping)
                        .filter(func.upper(Grouping.awaiting_fileno).in_([fn.upper() for fn in unmatched]))
                        .all()
                    )
                    for grouping_row in case_insensitive_matches:
                        key = _standardize_file_number(grouping_row.awaiting_fileno)
                        if key and key not in grouping_map:
                            grouping_map[key] = grouping_row

    for index, record in enumerate(records):
        raw_number = record.get('file_number')
        standardized = standardized_numbers[index]

        registry_value = _normalize_registry(record.get('registry')) or ''
        registry_batch_value = _normalize_string(record.get('registry_batch_no')) or ''
        csv_batch_value = _normalize_string(record.get('batch_no')) or ''

        if not standardized:
            summary['missing'] += 1
            rows.append({
                'file_number': raw_number,
                'normalized_file_number': None,
                'registry': registry_value,
                'registry_batch_no': registry_batch_value,
                'csv_batch_no': csv_batch_value,
                'status': 'missing',
                'reason': 'File number is blank',
                'grouping_registry': None,
                'grouping_number': None,
                'awaiting_fileno': None,
                'group': None,
                'sys_batch_no': None,
                'mdc_batch_no': None,
                'awaiting_normalized': None
            })
            continue

        grouping_row = grouping_map.get(standardized)
        if grouping_row:
            grouping_registry_batch = _normalize_string(getattr(grouping_row, 'registry_batch_no', None)) or ''
            summary['matched'] += 1
            rows.append({
                'file_number': raw_number,
                'normalized_file_number': standardized,
                'registry': registry_value,
                'registry_batch_no': registry_batch_value or grouping_registry_batch,
                'csv_batch_no': csv_batch_value,
                'status': 'matched',
                'reason': '',
                'grouping_registry': grouping_row.registry,
                'grouping_number': grouping_row.number,
                'awaiting_fileno': grouping_row.awaiting_fileno,
                'awaiting_normalized': _standardize_file_number(grouping_row.awaiting_fileno),
                'group': grouping_row.group,
                'sys_batch_no': grouping_row.sys_batch_no,
                'mdc_batch_no': _normalize_string(getattr(grouping_row, 'mdc_batch_no', None)) or ''
            })
        else:
            summary['missing'] += 1
            rows.append({
                'file_number': raw_number,
                'normalized_file_number': standardized,
                'registry': registry_value,
                'registry_batch_no': registry_batch_value,
                'csv_batch_no': csv_batch_value,
                'status': 'missing',
                'reason': 'Awaiting file number not found in grouping table',
                'grouping_registry': None,
                'grouping_number': None,
                'awaiting_fileno': None,
                'awaiting_normalized': None,
                'group': None,
                'sys_batch_no': None,
                'mdc_batch_no': None
            })

    return {
        'rows': rows,
        'summary': summary
    }


def _bulk_lookup_existing_property_ids(file_numbers: List[Optional[str]]) -> Dict[str, str]:
    """Resolve existing prop_ids for the provided file numbers using batched lookups."""
    lookup: Dict[str, str] = {}
    normalized_unique = [fn for fn in dict.fromkeys(file_numbers or []) if fn]
    if not normalized_unique:
        return lookup

    with SessionLocal() as db:
        for chunk in _chunk_list(normalized_unique, 500):
            if not chunk:
                continue

            file_indexing_rows = (
                db.query(FileIndexing.file_number, FileIndexing.prop_id)
                .filter(
                    FileIndexing.file_number.in_(chunk),
                    FileIndexing.prop_id.isnot(None)
                )
                .all()
            )
            for file_number, prop_id in file_indexing_rows:
                key = _standardize_file_number(file_number)
                value = _normalize_string(prop_id)
                if not key or not value:
                    continue
                lookup.setdefault(key, value)

            cofo_rows = (
                db.query(CofO.mls_fno, CofO.prop_id)
                .filter(
                    CofO.mls_fno.in_(chunk),
                    CofO.prop_id.isnot(None)
                )
                .all()
            )
            for file_number, prop_id in cofo_rows:
                key = _standardize_file_number(file_number)
                value = _normalize_string(prop_id)
                if not key or not value:
                    continue
                lookup.setdefault(key, value)

            try:
                property_rows = db.execute(
                    text(
                        "SELECT file_number, prop_id "
                        "FROM property_records "
                        "WHERE file_number IN :file_numbers "
                        "AND prop_id IS NOT NULL "
                        "ORDER BY created_at DESC"
                    ).bindparams(bindparam("file_numbers", expanding=True)),
                    {"file_numbers": chunk}
                )
                for file_number, prop_id in property_rows:
                    key = _standardize_file_number(file_number)
                    value = _normalize_string(prop_id)
                    if not key or not value:
                        continue
                    lookup.setdefault(key, value)
            except Exception:
                pass

            try:
                registered_rows = db.execute(
                    text(
                        "SELECT MLSFileNo, prop_id "
                        "FROM registered_instruments "
                        "WHERE MLSFileNo IN :file_numbers "
                        "AND prop_id IS NOT NULL "
                        "ORDER BY created_at DESC"
                    ).bindparams(bindparam("file_numbers", expanding=True)),
                    {"file_numbers": chunk}
                )
                for file_number, prop_id in registered_rows:
                    key = _standardize_file_number(file_number)
                    value = _normalize_string(prop_id)
                    if not key or not value:
                        continue
                    lookup.setdefault(key, value)
            except Exception:
                pass

    return lookup


def _lookup_existing_file_number_sources(
    file_numbers: List[Optional[str]],
    test_control: str
) -> Dict[str, List[str]]:
    control = (test_control or 'PRODUCTION').upper()
    normalized_unique: List[str] = []
    for candidate in dict.fromkeys(file_numbers or []):
        normalized_candidate = _normalize_string(candidate)
        if not normalized_candidate:
            continue
        normalized_unique.append(normalized_candidate.upper())

    if not normalized_unique:
        return {}

    detected: Dict[str, Set[str]] = {}

    with SessionLocal() as db:
        for chunk in _chunk_list(normalized_unique, 500):
            if not chunk:
                continue

            indexing_rows = (
                db.query(FileIndexing.file_number)
                .filter(FileIndexing.file_number.in_(chunk))
                .filter(FileIndexing.test_control == control)
                .all()
            )
            for (value,) in indexing_rows:
                normalized_value = (_normalize_string(value) or '').upper()
                if not normalized_value:
                    continue
                detected.setdefault(normalized_value, set()).add('File Indexings')

            cofo_rows = (
                db.query(CofO.mls_fno)
                .filter(CofO.mls_fno.in_(chunk))
                .filter(CofO.test_control == control)
                .all()
            )
            for (value,) in cofo_rows:
                normalized_value = (_normalize_string(value) or '').upper()
                if not normalized_value:
                    continue
                detected.setdefault(normalized_value, set()).add('CofO staging')

            filenumber_rows = (
                db.query(FileNumber.mlsf_no)
                .filter(FileNumber.mlsf_no.in_(chunk))
                .filter(FileNumber.test_control == control)
                .all()
            )
            for (value,) in filenumber_rows:
                normalized_value = (_normalize_string(value) or '').upper()
                if not normalized_value:
                    continue
                detected.setdefault(normalized_value, set()).add('File Number staging')

    return {
        key: sorted(sources)
        for key, sources in detected.items()
    }


def _filter_existing_file_numbers_for_preview(
    dataframe: pd.DataFrame,
    test_control: str
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    if dataframe.empty or 'file_number' not in dataframe.columns:
        return dataframe, []

    normalized_numbers: List[Optional[str]] = []
    for value in dataframe['file_number'].tolist():
        normalized_numbers.append((_normalize_string(value) or '').upper())

    existing_sources = _lookup_existing_file_number_sources(normalized_numbers, test_control)
    if not existing_sources:
        return dataframe, []

    keep_mask: List[bool] = []
    suppressed: List[Dict[str, Any]] = []

    for original_index, normalized_number in enumerate(normalized_numbers):
        if normalized_number and normalized_number in existing_sources:
            suppressed.append({
                'original_index': original_index,
                'file_number': dataframe.iloc[original_index]['file_number'],
                'sources': existing_sources[normalized_number]
            })
            keep_mask.append(False)
        else:
            keep_mask.append(True)

    filtered_df = dataframe.loc[keep_mask].reset_index(drop=True)
    return filtered_df, suppressed


def _apply_grouping_updates(
    db,
    record: Dict[str, Any],
    file_number: Optional[str],
    timestamp: datetime,
    test_control: str = 'PRODUCTION'
) -> Dict[str, Any]:
    shelf_location = record.get('shelf_location')
    grouping_row, status, reason = _grouping_match_info(db, file_number)

    incoming_file_number = record.get('file_number', file_number)
    cleaned_file_number = _remove_file_number_suffixes(incoming_file_number)
    grouping_storage_value = (cleaned_file_number or incoming_file_number or '').upper()

    result = {
        'status': status,
        'reason': reason,
        'shelf_location': shelf_location,
        'group': None,
        'sys_batch_no': None,
        'registry_batch_no': None,
        'tracking_id': record.get('tracking_id'),
        'grouping_record': grouping_row
    }

    if status != 'matched' or not grouping_row:
        return result

    canonical_input = _normalize_file_number_for_match(file_number)
    canonical_awaiting = _normalize_file_number_for_match(grouping_row.awaiting_fileno)

    if canonical_input and canonical_awaiting and canonical_input == canonical_awaiting:
        # Update grouping table
        grouping_row.indexing_mls_fileno = grouping_storage_value
        grouping_row.indexing_mapping = 1  # Set mapping to 1 when exact match
        grouping_row.date_index = timestamp

        created_by_source = _normalize_string(record.get('created_by'))
        if created_by_source:
            grouping_row.indexed_by = created_by_source

        # Copy batch_no from indexing record to mdc_batch_no in grouping
        batch_no = record.get('batch_no')
        if batch_no:
            # Convert to string for mdc_batch_no (assuming it's string field in grouping table)
            grouping_row.mdc_batch_no = str(batch_no)

        # Update registry if available
        registry = _normalize_registry(record.get('registry'))
        if registry:
            grouping_row.registry = registry
        if test_control:
            grouping_row.test_control = test_control

        # Copy group field from grouping to result (for file indexing)
        if grouping_row.group:
            result['group'] = grouping_row.group

        # Copy sys_batch_no from grouping to result (for file indexing)  
        if grouping_row.sys_batch_no:
            result['sys_batch_no'] = grouping_row.sys_batch_no

        if grouping_row.registry_batch_no:
            result['registry_batch_no'] = grouping_row.registry_batch_no

        # Adopt tracking id from grouping when available; otherwise cascade from record
        if grouping_row.tracking_id:
            result['tracking_id'] = grouping_row.tracking_id
        elif record.get('tracking_id'):
            grouping_row.tracking_id = record['tracking_id']
            result['tracking_id'] = record['tracking_id']

        result['shelf_location'] = shelf_location
        result['reason'] = ''
    else:
        # No exact match, don't update mapping
        result['reason'] = f'File number {file_number} does not exactly match awaiting_fileno {grouping_row.awaiting_fileno}'

    return result


def _upsert_file_number(
    db,
    file_number: str,
    record: Dict[str, Any],
    tracking_id: str,
    import_filename: str,
    timestamp: datetime,
    test_control: str = 'PRODUCTION'
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
        created_by_source = _normalize_string(record.get('created_by'))
        if created_by_source:
            file_number_entry.updated_by = created_by_source
            if not file_number_entry.created_by:
                file_number_entry.created_by = created_by_source
        elif not created_by_source and not record.get('_created_by_warning_emitted'):
            logger.warning("Created By missing for file number %s; keeping existing user metadata", file_number)
            record['_created_by_warning_emitted'] = True
        file_number_entry.test_control = test_control
    else:
        created_by_source = _normalize_string(record.get('created_by'))
        if not created_by_source and not record.get('_created_by_warning_emitted'):
            logger.warning("Created By missing for file number %s; inserting record without user metadata", file_number)
            record['_created_by_warning_emitted'] = True
        file_number_entry = FileNumber(
            mlsf_no=file_number,
            file_name=file_title or import_filename or file_number,
            created_at=timestamp,
            location=location,
            created_by=created_by_source,
            type='MlsFileNO',
            source='Indexing',
            plot_no=plot_no,
            tp_no=tp_no,
            tracking_id=tracking_id,
            updated_by=created_by_source,
            test_control=test_control
        )
        db.add(file_number_entry)


def process_file_indexing_data(df: pd.DataFrame) -> pd.DataFrame:
    """Process CSV/Excel data according to field mappings."""
    df = df.copy()
    df.columns = [col.strip() for col in df.columns]
    normalized_columns = {col.strip().lower(): col for col in df.columns}
    numeric_like_fields = {'registry', 'batch_no', 'lpkn_no', 'serial_no', 'page_no', 'vol_no', 'created_by'}

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
    'created_by': ['Created By', 'CreatedBy'],
        'group': ['Group'],
        'sys_batch_no': ['Sys Batch No', 'SysBatchNo', 'System Batch No'],
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

    for col in standardized_df.columns:
        if standardized_df[col].dtype == 'object':
            standardized_df[col] = standardized_df[col].astype(str).str.strip()

    if 'registry' in standardized_df.columns:
        standardized_df['registry'] = standardized_df['registry'].apply(_normalize_registry)

    standardized_df.replace('', pd.NA, inplace=True)
    standardized_df.dropna(how='all', inplace=True)
    standardized_df.fillna('', inplace=True)
    standardized_df.reset_index(drop=True, inplace=True)

    if 'file_number' in standardized_df.columns:
        standardized_df['file_number'] = standardized_df['file_number'].str.upper()

    if 'cofo_date' in standardized_df.columns:
        def _normalize_cofo_for_preview(value: Any) -> str:
            normalized_date = _normalize_cofo_date(value)
            if normalized_date:
                return normalized_date
            normalized_string = _normalize_string(value)
            return normalized_string or ''

        standardized_df['cofo_date'] = standardized_df['cofo_date'].apply(_normalize_cofo_for_preview)

    if 'deeds_time' in standardized_df.columns:
        def _normalize_time_for_preview(value: Any) -> str:
            normalized_time = _normalize_time_field(value)
            if normalized_time:
                return normalized_time
            normalized_string = _normalize_string(value)
            return normalized_string or ''

        standardized_df['deeds_time'] = standardized_df['deeds_time'].apply(_normalize_time_for_preview)

    return standardized_df


def analyze_file_number_occurrences(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    if 'file_number' not in df.columns:
        return {}

    file_number_counts = df['file_number'].value_counts()
    multiple_occurrences: Dict[str, Dict[str, Any]] = {}

    for file_number, count in file_number_counts.items():
        if count > 2 and file_number and file_number.strip():
            indices = df[df['file_number'] == file_number].index.tolist()
            multiple_occurrences[file_number] = {
                'count': count,
                'indices': indices
            }

    return multiple_occurrences


def _run_qc_validation(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
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
    pattern = r'^([A-Z]+(?:-[A-Z]+)*)-(\d{4})-(0+)(\d+)(\([^)]*\))?$'
    match = re.match(pattern, file_number)
    if match:
        prefix, year, leading_zeros, number, suffix = match.groups()
        suffix = suffix or ''
        suggested_fix = f"{prefix}-{year}-{number}{suffix}"
        return {'suggested_fix': suggested_fix}
    return None


def _check_year_issue(file_number: str) -> Optional[Dict[str, str]]:
    pattern = r'^([A-Z]+(?:-[A-Z]+)*)-(\d{2})-(\d+)(\([^)]*\))?$'
    match = re.match(pattern, file_number)
    if match:
        prefix, year_2digit, number, suffix = match.groups()
        suffix = suffix or ''

        year_int = int(year_2digit)
        if year_int >= 50:
            year_4digit = f"19{year_2digit}"
        else:
            year_4digit = f"20{year_2digit}"

        suggested_fix = f"{prefix}-{year_4digit}-{number}{suffix}"
        return {'suggested_fix': suggested_fix}
    return None


def _check_spacing_issue(file_number: str) -> Optional[Dict[str, str]]:
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
        return None

    hyphenated = re.sub(r'\s+', '-', base_value.strip())
    hyphenated = re.sub(r'-{2,}', '-', hyphenated).strip('-')

    candidate = hyphenated if hyphenated else _strip_all_whitespace(trimmed)
    if suffix_text:
        candidate = f"{candidate} {suffix_text}".strip()

    return {'suggested_fix': candidate}


def _assign_property_ids(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    property_assignments: List[Dict[str, Any]] = []
    property_counter = _get_next_property_id_counter()
    file_number_prop_cache: Dict[str, str] = {}

    standardized_numbers = [_standardize_file_number(record.get('file_number')) for record in records]
    existing_props = _bulk_lookup_existing_property_ids(standardized_numbers)

    for idx, record in enumerate(records):
        file_number = standardized_numbers[idx]
        if not file_number:
            continue

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

        existing_prop_id = existing_props.get(file_number)

        if existing_prop_id:
            property_assignments.append({
                'record_index': idx,
                'file_number': file_number,
                'property_id': existing_prop_id,
                'status': 'existing',
                'source_table': 'existing_lookup'
            })
            record['prop_id'] = existing_prop_id
            file_number_prop_cache[file_number] = existing_prop_id
        else:
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
            file_number_prop_cache[file_number] = new_prop_id

    return property_assignments


@lru_cache(maxsize=1)
def _log_timing(message: str, start_time: float) -> None:
    elapsed = time.perf_counter() - start_time
    logger.info("%s (%.3fs)", message, elapsed)


def _fetch_max_numeric_prop_id(db, table_identifier: str, column_name: str = 'prop_id') -> Optional[int]:
    sql = text(
        f"""
            SELECT TOP 1 prop_id_value
            FROM (
                SELECT TRY_CAST({column_name} AS BIGINT) AS prop_id_value
                FROM {table_identifier} WITH (NOLOCK)
            ) AS numeric_props
            WHERE prop_id_value IS NOT NULL
            ORDER BY prop_id_value DESC
        """
    )
    try:
        value = db.execute(sql).scalar()
        if value is not None:
            return int(value)
    except Exception as exc:
        logger.debug("Failed to fetch max prop_id from %s: %s", table_identifier, exc)
    return None


def _get_cached_property_id_counter() -> int:
    """Cache the property ID counter to avoid repeated database queries."""
    start_time = time.perf_counter()
    db = SessionLocal()
    try:
        candidates: List[int] = []

        primary_tables = [
            ('file_indexings', 'prop_id'),
            ('[CofO]', 'prop_id')
        ]

        for table_name, column_name in primary_tables:
            value = _fetch_max_numeric_prop_id(db, table_name, column_name)
            if value is not None:
                candidates.append(value)

        if candidates:
            _log_timing("Resolved max prop_id via primary tables", start_time)
            return max(candidates) + 1

        extended_tables = [
            ('property_records', 'prop_id'),
            ('registered_instruments', 'prop_id')
        ]

        for table_name, column_name in extended_tables:
            value = _fetch_max_numeric_prop_id(db, table_name, column_name)
            if value is not None:
                candidates.append(value)

        if candidates:
            _log_timing("Resolved max prop_id via extended tables", start_time)
            return max(candidates) + 1

        _log_timing("No existing prop_id found; defaulting to 1", start_time)
        return 1
    finally:
        _log_timing("Property ID counter resolution complete", start_time)
        db.close()


def _get_next_property_id_counter() -> int:
    """Get the next property ID counter, using cached value for performance."""
    return _get_cached_property_id_counter()


def _clear_property_id_cache() -> None:
    """Clear the property ID cache to force refresh on next access."""
    _get_cached_property_id_counter.cache_clear()


def _find_existing_property_id(file_number: str) -> Optional[str]:
    db = SessionLocal()
    try:
        record = db.query(FileIndexing).filter(FileIndexing.file_number == file_number, FileIndexing.prop_id.isnot(None)).first()
        if record and record.prop_id:
            return str(record.prop_id)

        record = db.query(CofO).filter(CofO.mls_fno == file_number, CofO.prop_id.isnot(None)).first()
        if record and record.prop_id:
            return str(record.prop_id)

        try:
            result = db.execute(text("""
                SELECT TOP 1 prop_id FROM property_records 
                WHERE file_number = :file_number AND prop_id IS NOT NULL
                ORDER BY created_at DESC
            """), {'file_number': file_number})
            existing_record = result.first()
            if existing_record and existing_record[0]:
                return str(existing_record[0])
        except Exception:
            pass

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
            pass

        return None
    finally:
        db.close()


# ============================================================================
# STAGING IMPORT FUNCTIONS (Customer & Entity Staging)
# ============================================================================

# Heuristic keyword sets for customer classification.
CORPORATE_TOKEN_KEYWORDS = {
    'ASSOCIATES', 'AUTO', 'AUTOS', 'AUTOMOBILE', 'AUTOMOBILES', 'BANK', 'BANKS',
    'BROS', 'BROTHERS', 'CARDS', 'CATERING', 'CHEMICAL', 'CHEMICALS', 'COMPANY',
    'COMPUTERS', 'CONSTRUCTION', 'CONSTRUCTIONS', 'CONSULT', 'CONSULTANTS',
    'CONSULTING', 'CORP', 'CORPORATION', 'DEVELOPERS', 'DEVELOPMENT', 'ENTERPRISE',
    'ENTERPRISES', 'ENTERPRIES', 'ESTATE', 'ESTATES', 'EXPORT', 'EXPORTS', 'FIBER',
    'FIBRE', 'FIBRES', 'FOUNDATION', 'GLOBAL', 'GROUP', 'GROUPS', 'HOLDING',
    'HOLDINGS', 'HOSPITAL', 'HOSPITALS', 'IMPORT', 'IMPORTS', 'INDUSTRIAL',
    'INDUSTRIES', 'INDUSTRY', 'INSURANCE', 'INTERNATIONAL', 'INVESTMENT',
    'INVESTMENTS', 'INVESTORS', 'LIMITED', 'LOGISTIC', 'LOGISTICS', 'LTD', 'MEDICAL',
    'MERCHANT', 'MERCHANTS', 'MINING', 'MOTORS', 'MKT', 'NIG', 'NIGERIA', 'OIL',
    'PETROLEUM', 'PHARMACY', 'PHARMACEUTICAL', 'PHARMACEUTICALS', 'PLC', 'POWER',
    'PRESS', 'PROPERTIES', 'PROPERTY', 'REALTY', 'RESOURCES', 'SERVICE', 'SERVICES',
    'SON', 'SONS', 'DAUGHTER', 'DAUGHTERS', 'FAMILY', 'FAMILIES',
    'STATION', 'STATIONS', 'STEEL', 'TECH', 'TECHNOLOGIES', 'TECHNOLOGY',
    'TELECOM', 'TELECOMS', 'TRANSPORT', 'TRANSPORTS', 'TRADING', 'TRAVELS',
    'VENTURE', 'VENTURES', 'WORKS'
}

CORPORATE_PHRASES = (
    ' CO.', ' & CO', ' AND CO', ' & SONS', ' AND SONS', ' & BROTHERS',
    ' AND BROTHERS', ' BROTHERS LTD', ' HOLDINGS LTD', ' GLOBAL LTD',
    ' GROUP LTD', ' NIG. LTD', ' NIG LTD', ' CAR HIRE', ' CAR SALES',
    ' AUTO LTD', ' AUTO NIG', ' MOTORS LTD', ' MEDICAL CENTRE', ' MEDICAL CENTER',
    ' MEDICAL HOSPITAL', ' HOSPITAL LTD', ' INTL LTD', ' INT\'L LTD'
)

MULTIPLE_TOKEN_KEYWORDS = {'OTHERS', 'ET', 'AL', 'ETAL', 'ET-AL', 'ET.', 'AL.'}

MULTIPLE_PHRASES = (
    ' AND ', ' WITH ', ' AKA ', ' A/K/A ', ' A.K.A ', ' + ', ' / ',
    ' AKA', ' OTHERS', ' & OR ', ' AND/OR '
)


def _classify_customer_type(descriptor: Optional[str]) -> str:
    """
    Classify customer/entity type using heuristics on the provided descriptor.

    The descriptor can be a file title, entity name, or filename. We prioritise
    detecting corporate entities first (keywords like LTD, PLC, COMPANY, etc.).
    If we see clear signs of multiple distinct people (comma or "and" delimited
    list) we classify as "Multiple". Otherwise we fall back to "Individual".
    """
    if not descriptor:
        return 'Individual'

    text = descriptor.strip()
    if not text:
        return 'Individual'

    lowered = text.lower()
    uppercase = text.upper()
    normalized_tokens = re.findall(r"[A-Z0-9']+", uppercase)
    token_set = set(normalized_tokens)

    if any(phrase in uppercase for phrase in CORPORATE_PHRASES):
        return 'Corporate'

    if token_set & CORPORATE_TOKEN_KEYWORDS:
        return 'Corporate'

    if token_set & MULTIPLE_TOKEN_KEYWORDS:
        return 'Multiple'

    if '&' in uppercase:
        if re.search(r'&\s*(SON|SONS|DAUGHTER|DAUGHTERS|BROTHER|BROTHERS|BROS\.?|FAMILY)\b', uppercase):
            return 'Corporate'
        return 'Multiple'

    if any(phrase in uppercase for phrase in MULTIPLE_PHRASES):
        return 'Multiple'

    # Detect multiple individual names (comma separated, ampersand, or "and")
    if re.search(r',', text) or re.search(r'\band\b', lowered) or re.search(r'\s&\s', text):
        segments = re.split(r',|\band\b|\s&\s', text, flags=re.IGNORECASE)
        non_empty_segments = [segment.strip() for segment in segments if segment and segment.strip()]
        if len(non_empty_segments) >= 2:
            return 'Multiple'

    return 'Individual'


def _extract_entity_name(record: Dict[str, Any]) -> Optional[str]:
    """
    Extract entity name with intelligent fallback chain.
    
    Priority: file_title → district+lga → file_number → None
    """
    # Priority 1: file_title (most specific)
    file_title = _normalize_string(record.get('file_title'))
    if file_title:
        return file_title
    
    # Priority 2: Combine district + lga
    district = _normalize_string(record.get('district'))
    lga = _normalize_string(record.get('lga'))
    combined = _combine_location(district, lga)
    if combined:
        return combined
    
    # Priority 3: file_number (include alternate field names used by other imports)
    file_number = _normalize_string(
        record.get('file_number')
        or record.get('mlsFNo')
        or record.get('fileno')
        or record.get('fileNumber')
    )
    if file_number:
        return f"File: {file_number}"
    
    # Priority 4: Cannot proceed
    return None


def _extract_customer_name(record: Dict[str, Any], entity_name: Optional[str] = None) -> Optional[str]:
    """
    Extract customer name from record.
    
    Priority: file_title → entity_name → created_by → generated reference
    """
    # Priority 1: Use file_title
    file_title = _normalize_string(record.get('file_title'))
    if file_title:
        return file_title
    
    # Priority 2: Use entity_name if provided
    if entity_name:
        return entity_name
    
    # Priority 3: Use created_by if it looks like a name
    created_by = _normalize_string(record.get('created_by'))
    if created_by and len(created_by) > 2:
        return created_by
    
    # Priority 4: Generate reference from file_number
    file_number = _normalize_string(
        record.get('file_number')
        or record.get('mlsFNo')
        or record.get('fileno')
        or record.get('fileNumber')
    )
    if file_number:
        return f"Customer-{file_number}"
    
    return None


def _extract_customer_address(record: Dict[str, Any]) -> Optional[str]:
    """
    Extract property address from record.
    
    Priority: location → plot_number+lga combination
    """
    # Priority 1: location field
    location = _normalize_string(record.get('location'))
    if location:
        return location
    
    # Priority 2: Combine plot_number + lga
    plot_number = _normalize_string(record.get('plot_number'))
    lga = _normalize_string(record.get('lga'))
    
    if plot_number and lga:
        return f"{plot_number}, {lga}"
    elif plot_number:
        return plot_number
    elif lga:
        return lga
    
    return None


def _is_valid_url(url_string: Optional[str]) -> bool:
    """Check if a string is a valid URL."""
    if not url_string:
        return False
    
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # or IP
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)?$', re.IGNORECASE)
    
    return bool(url_pattern.match(url_string))


def _is_valid_email(email: Optional[str]) -> bool:
    """Check if a string is a valid email address."""
    if not email:
        return False
    
    email_pattern = re.compile(
        r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    )
    return bool(email_pattern.match(email))


# Placeholder image URLs
PLACEHOLDER_PASSPORT_PHOTO = "https://via.placeholder.com/150x200?text=Passport+Photo"
PLACEHOLDER_COMPANY_LOGO = "https://via.placeholder.com/200x100?text=Company+Logo"


def _extract_photos(
    record: Dict[str, Any],
    customer_type: str,
    include_placeholders: bool = True
) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract passport_photo and company_logo URLs.
    
    Since CSV doesn't contain image data, use placeholder images for preview.
    Photos are ONLY included for Corporate or Multiple types.
    Individual types will have NULL photos.
    """
    passport_photo = None
    company_logo = None
    
    # Only extract photos for non-Individual types
    if customer_type in ['Corporate', 'Multiple']:
        # Try to get from record (unlikely in FileIndexing)
        passport_photo = _normalize_string(record.get('passport_photo'))
        company_logo = _normalize_string(record.get('company_logo'))
        
        # Validate URLs if present
        if passport_photo and not _is_valid_url(passport_photo):
            logger.warning("Invalid passport_photo URL in record: %s", passport_photo)
            passport_photo = None
        
        if company_logo and not _is_valid_url(company_logo):
            logger.warning("Invalid company_logo URL in record: %s", company_logo)
            company_logo = None
        
        # Use placeholders for preview if no actual URLs found
        if include_placeholders:
            if not passport_photo:
                passport_photo = PLACEHOLDER_PASSPORT_PHOTO
            if not company_logo:
                company_logo = PLACEHOLDER_COMPANY_LOGO
    
    return passport_photo, company_logo


def _generate_customer_code() -> str:
    """Generate auto-generated customer code in format: CUST-{YYYYMMDD}-{UUID:8}"""
    timestamp = datetime.utcnow().strftime('%Y%m%d')
    uuid_part = str(uuid.uuid4()).replace('-', '')[:8].upper()
    return f"CUST-{timestamp}-{uuid_part}"


def _generate_import_batch_id() -> str:
    """Generate import batch ID in format: IMP-{YYYYMMDD}-{UUID:8}"""
    timestamp = datetime.utcnow().strftime('%Y%m%d')
    uuid_part = str(uuid.uuid4()).replace('-', '')[:8].upper()
    return f"IMP-{timestamp}-{uuid_part}"


def _get_or_create_entity(
    db,
    entity_name: str,
    customer_type: str,
    file_number: Optional[str] = None,
    passport_photo: Optional[str] = None,
    company_logo: Optional[str] = None,
    test_control: str = 'PRODUCTION'
):
    """
    Get existing entity or create new one.
    
    Entity lookup: entity_name + entity_type (unique index)
    """
    from app.models.database import EntityStaging
    
    # Normalize name
    normalized_name = _normalize_string(entity_name)
    if not normalized_name:
        raise ValueError("Cannot create entity with empty name")
    
    # Try to find existing entity with same name and type
    existing_entity = db.query(EntityStaging).filter(
        EntityStaging.entity_name == normalized_name,
        EntityStaging.entity_type == customer_type,
        EntityStaging.test_control == test_control
    ).first()
    
    if existing_entity:
        logger.info(
            "Reusing existing entity: %s (id=%d)",
            normalized_name,
            existing_entity.id
        )
        return existing_entity
    
    # Create new entity
    new_entity = EntityStaging(
        entity_name=normalized_name,
        entity_type=customer_type,
        passport_photo=passport_photo,
        company_logo=company_logo,
        file_number=file_number,
        created_at=datetime.utcnow(),
        test_control=test_control
    )
    
    db.add(new_entity)
    db.flush()  # Get the ID before commit
    
    logger.info(
        "Created new entity: %s (id=%d)",
        normalized_name,
        new_entity.id
    )
    
    return new_entity


def _process_staging_import(
    db,
    records: List[Dict[str, Any]],
    filename: str,
    test_control: str = 'PRODUCTION'
) -> Dict[str, Any]:
    """
    Process staging import for entities and customers.
    """
    from app.models.database import EntityStaging, CustomerStaging
    
    entity_summary = {
        'new': 0,
        'reused': 0,
        'failed': 0
    }
    
    customer_summary = {
        'created': 0,
        'failed': 0
    }
    
    entity_cache: Dict[str, EntityStaging] = {}
    errors: List[Dict[str, Any]] = []

    def safe_int_conversion(value: Any) -> Optional[int]:
        """Convert possible numeric values to int, otherwise None."""
        if value is None:
            return None
        if isinstance(value, int):
            return value
        try:
            str_value = str(value).strip()
            if not str_value:
                return None
            return int(str_value)
        except (ValueError, TypeError):
            return None
    
    for idx, record in enumerate(records):
        try:
            # Step 1: Extract entity data
            entity_name = _extract_entity_name(record)
            if not entity_name:
                errors.append({
                    'record_index': idx,
                    'type': 'missing_entity_name',
                    'file_number': record.get('file_number')
                })
                continue
            
            descriptor = (
                _normalize_string(record.get('file_title'))
                or entity_name
                or _normalize_string(record.get('customer_name'))
                or filename
            )
            customer_type = _classify_customer_type(descriptor)

            # Step 2: Extract photos (nullable)
            passport_photo, company_logo = _extract_photos(
                record,
                customer_type
            )
            
            file_number_value = _normalize_string(record.get('file_number'))

            # Step 3: Get or create entity
            cache_key = f"{entity_name}:{customer_type}"
            if cache_key in entity_cache:
                entity = entity_cache[cache_key]
                entity_summary['reused'] += 1
            else:
                entity = _get_or_create_entity(
                    db,
                    entity_name,
                    customer_type,
                    file_number_value,
                    passport_photo,
                    company_logo,
                    test_control
                )
                entity_cache[cache_key] = entity
                entity_summary['new'] += 1
            
            # Step 4: Extract customer data
            customer_name = _extract_customer_name(record, entity_name)
            customer_code = _generate_customer_code()
            property_address = _extract_customer_address(record)

            created_by_value = safe_int_conversion(record.get('created_by'))
            
            # Step 4b: Extract reason_retired from transaction_type
            transaction_type = _normalize_string(record.get('transaction_type'))
            reason_retired = _canonical_reason_retired(transaction_type)
            
            # Step 5: Create customer staging record
            customer = CustomerStaging(
                customer_name=customer_name,
                customer_type=customer_type,
                customer_code=customer_code,
                property_address=property_address,
                entity_id=entity.id,
                created_by=created_by_value,
                created_at=datetime.utcnow(),
                test_control=test_control,
                file_number=file_number_value,
                account_no=file_number_value,
                reason_retired=reason_retired
            )
            
            db.add(customer)
            customer_summary['created'] += 1
            
        except Exception as e:
            logger.error("Error processing record %d: %s", idx, str(e))
            entity_summary['failed'] += 1
            errors.append({
                'record_index': idx,
                'type': 'processing_error',
                'error': str(e)
            })
    
    db.commit()
    
    return {
        'success': len(errors) == 0,
        'entity_summary': entity_summary,
        'customer_summary': customer_summary,
        'errors': errors
    }


__all__ = [
    'TRACKING_ID_PREFIX',
    '_format_value',
    '_normalize_string',
    '_normalize_numeric_field',
    '_collapse_whitespace',
    '_strip_all_whitespace',
    '_normalize_registry',
    '_normalize_time_field',
    '_combine_location',
    '_build_reg_no',
    '_has_cofo_payload',
    '_build_cofo_record',
    '_update_cofo',
    '_generate_tracking_id',
    '_grouping_match_info',
    '_build_grouping_preview',
    '_apply_grouping_updates',
    '_upsert_file_number',
    'process_file_indexing_data',
    'analyze_file_number_occurrences',
    '_run_qc_validation',
    '_check_padding_issue',
    '_check_year_issue',
    '_check_spacing_issue',
    '_assign_property_ids',
    '_filter_existing_file_numbers_for_preview',
    '_lookup_existing_file_number_sources',
    '_get_next_property_id_counter',
    '_find_existing_property_id',
    # Staging functions
    '_classify_customer_type',
    '_extract_entity_name',
    '_extract_customer_name',
    '_extract_customer_address',
    '_is_valid_url',
    '_is_valid_email',
    '_extract_photos',
    '_generate_customer_code',
    '_generate_import_batch_id',
    '_get_or_create_entity',
    '_process_staging_import',
]
