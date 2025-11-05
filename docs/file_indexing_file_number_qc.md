# File Indexing – File Number QC Cheatsheet

This note captures how the File Indexing import pipeline evaluates file numbers and builds
QC issues. It is based on the current implementation in:

- `app/services/file_indexing_service.py` – `_run_qc_validation` plus the helper
  checks (`_check_padding_issue`, `_check_year_issue`, `_check_spacing_issue`,
  `_check_temp_issue`, `_normalize_temp_suffix_format`).
- `app/routers/file_indexing.py` – returns QC results from `/api/upload-csv` and
  applies fixes through `/api/qc/apply-fixes/{session_id}`.
- `static/js/file-indexing.js` – renders the QC tab, exposes “Apply fix” and
  bulk “Apply All Auto-Fixes”, and refreshes the preview after an update.

## High-level behaviour

1. Every uploaded record is normalised to produce a `file_number` string.
2. `_run_qc_validation` skips blank numbers, otherwise evaluates four rule sets:
   padding, year, spacing, and TEMP suffix format.
3. Each matching rule appends an object shaped like:

```json
{
  "record_index": 12,
  "file_number": "KN-24-001",
  "issue_type": "year",
  "description": "File number has 2-digit year instead of 4-digit",
  "suggested_fix": "KN-2024-001",
  "auto_fixable": true,
  "severity": "High"
}
```

4. The frontend shows aggregate counts, lets reviewers inspect individual
   issues, and can POST suggested fixes back to the session. All four issue
   types are marked `auto_fixable: true`, so they participate in the “Apply all
   auto-fixes” workflow.

## Rule summary

| Issue key | When it fires | Example input → suggested fix | Severity |
|-----------|---------------|--------------------------------|----------|
| `padding` | Prefix-year-number format contains redundant leading zeros in the numeric tail. | `KNS-2024-0005` → `KNS-2024-5` | Medium |
| `year` | Prefix-year-number format uses a 2-digit year. Years ≥50 become 19XX, otherwise 20XX. | `KNS-24-15` → `KNS-2024-15`<br>`KNS-89-15` → `KNS-1989-15` | High |
| `spacing` | Any internal whitespace beyond the optional ` (TEMP)` suffix. | `KNS - 2024 - 5` → `KNS-2024-5` | Medium |
| `temp` | TEMP markers appear as loose `TEMP`, `T`, or malformed parentheses. | `KNS-2024-5 TEMP` → `KNS-2024-5 (TEMP)`<br>`KNS-2024-5 (T)` → `KNS-2024-5 (TEMP)` | Low |

Notes:

- All rules expect the prefix to be uppercase alpha segments separated by
  hyphens, the year to be numeric, and the identifier tail to be numeric.
- `_normalize_temp_suffix_format` also trims surrounding whitespace and ensures
  the canonical ` (TEMP)` suffix, so spacing and temp issues often share the same suggestion.
- Issue detection uses the raw user input for messaging (`file_number`) but
  suggestions are generated from whitespace-stripped versions (`compact_number`).

## Rule details and examples

### 1. Padding issues (`_check_padding_issue`)
- **Pattern:** `^([A-Z]+(?:-[A-Z]+)*)-(\d{4})-(0+)(\d+)(\([^)]*\))?$`
- **Meaning:** Valid prefix and four-digit year, but the number segment has one or more
  redundant leading zeros.
- **Suggested fix:** Drop the leading zeros, keep any trailing suffix, then normalise the
  TEMP suffix.
- **Example:**
  - Raw: `KN-2023-00045`
  - Suggested: `KN-2023-45`
  - Resulting QC entry reports a medium severity, auto-fixable change.

### 2. Year issues (`_check_year_issue`)
- **Pattern:** `^([A-Z]+(?:-[A-Z]+)*)-(\d{2})-(\d+)(\([^)]*\))?$`
- **Meaning:** Same shape as padding rule, but the year is only two digits.
- **Resolution:** Convert `00–49` → `2000–2049`, `50–99` → `1950–1999`.
- **Example:**
  - Raw: `KNS-07-112`
  - Suggested: `KNS-2007-112`
  - Severity escalated to `High` because the storage year would be wrong.

### 3. Spacing issues (`_check_spacing_issue`)
- **Pattern:** Any whitespace beyond the optional TEMP suffix. If the only
  whitespace sits inside ` (TEMP)` the record is considered compliant.
- **Suggested fix:** Collapse whitespace to single hyphens (preserving existing
  hyphenated segments) and then reapply canonical TEMP formatting.
- **Example:**
  - Raw: `KNS  -  2024  12`
  - Suggested: `KNS-2024-12`
  - Keeps severity at `Medium` and is auto-fixable.

### 4. TEMP notation issues (`_check_temp_issue`)
- **Pattern:** Matches variants such as `TEMP`, `(TEMP`, `(T)`, or trailing `T`
  that do not already match the canonical `… (TEMP)` style.
- **Suggested fix:** `_normalize_temp_suffix_format` rewrites everything to
  `PREFIX-YEAR-NUMBER (TEMP)`.
- **Example:**
  - Raw: `KNS-2024-12 TEMP`
  - Suggested: `KNS-2024-12 (TEMP)`
  - Labeled `Low` severity, still auto-fixable.

## Frontend behaviour quick notes

- The QC tab badge (`#qc-total-issues`) displays the total count returned in the
  upload response (`qc_summary.total_issues`).
- Entries populate `static/js/file-indexing.js`’s `qcIssues` object and render
  inside the QC table; each row offers **Apply Fix** (single record) and supports
  multi-fix submissions via `/api/qc/apply-fixes/{session_id}`.
- The bulk action `applyAllAutoFixes()` gathers every issue with a
  `suggested_fix` and posts them to the same endpoint, letting reviewers normalise the
  entire dataset in a batch.

## Testing ideas

- Build a small CSV with deliberate cases of each issue type, upload it, and
  verify the QC tab shows the correct counts and suggestions.
- Exercise `applyAllAutoFixes()` and confirm the QC lists refresh to zero with
  clean file numbers.
- For padding and year issues, double-check that suggested fixes keep any
  trailing TEMP suffix or other parenthetical content intact.
