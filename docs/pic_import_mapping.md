# Property Index Card (PIC) Import Mapping

This document captures how the **`docs/Index Card_All.csv`** columns translate into the
in-memory payloads that flow through the PIC import preview (property records,
CofO preview, duplicate/QC scans) and eventually into the MLS persistence layer.
It augments the multi-table plan with the PIC-specific fields that are not
present in the File History workflow.

---

## 1. Source Columns

The CSV currently ships with the following header sequence:

```
SN, MLSFileNo, Comments, oldKNNo, transaction_type, serialNo, pageNo, volumeNo,
regNo, period, period_unit, Grantor, Grantee, Assignee, property_description,
location, Assignment Date, streetName, house_no, districtName, plot_no, LGA,
layout, source, tp_no, lpkn_no, approved_plan_no, plot_size, date_recommended,
date_approved, lease_begins, lease_expires, Surrender Date, Revoked date,
metric_sheet, regranted from, Date Expired, Remarks, CreatedBy, DateCreated
```

Key nuances identified during inspection:

- `oldKNNo` is now provided directly in the CSV and maps straight into the
  persistent `oldKNNo` column while also powering the dedicated card-serial
  column in the UI.
- `SerialNo` (camel case S) remains present on legacy extracts and is still
  read to backfill `oldKNNo` when the dedicated column is missing, but it no
  longer influences the register-facing `serialNo` field.
- `serialNo` (lower camel) captures the **register serial number** used in File
  History. When the column is blank we flag a QC error instead of falling back
  to `oldKNNo`. The preview now shows register and card serials side by side.
- `MLSFileNo` already contains the full normalized file number e.g.
  `RES-RC-1982-378`; values are uppercase but still pass through
  `_normalize_string` for consistency.
- Date columns present mixed formats (`13-8-1968`, `1-6-1975`, empty). They will
  be parsed via the shared `_parse_file_history_date` helper and surfaced both as
  normalized ISO and raw strings so the UI can show the original value.
- `Assignment Date`, `Surrender Date`, `Revoked date`, and `Date Expired` may be
  blank for many rows but should stay aligned with the related transaction type
  (e.g. Assignment rows usually contain `Assignment Date`).

---

## 2. Property Records Payload Mapping

The PIC preview will emit `property_records` entries similar to the File History
flow, enriched with PIC-only attributes. All keys are optional strings unless
otherwise noted.

| Property Record Key          | Source Column / Rule                              | Notes |
|------------------------------|---------------------------------------------------|-------|
| `mlsFNo`, `fileno`           | `MLSFileNo`                                       | Normalized to uppercase; drives prop-id reuse. |
| `transaction_type`           | `transaction_type`                                | Mirrors existing QC buckets. |
| `Assignor`, `Grantor`        | `Grantor`                                         | Assignor + grantor stay in sync to match File History schema. |
| `Assignee`, `Grantee`        | `Grantee` / `Assignee`                            | `Assignee` column (if present) wins; fallback to `Grantee`. |
| `secondary_assignee`         | `Assignee`                                        | Lets UI display the third party separately without breaking existing bindings. |
| `comments`                   | `Comments`                                        | New free-text display column. |
| `remarks`                    | `Remarks`                                         | Separate card remark field. |
| `property_description`       | `property_description`                            | Falls back to `location` when empty. |
| `location`                   | `location`                                        | Rendered in table and CofO preview. |
| `streetName`                 | `streetName`                                      | Downstream editing uses this key. |
| `house_no`                   | `house_no`                                        | — |
| `districtName`               | `districtName`                                    | — |
| `plot_no`                    | `plot_no`                                         | — |
| `layout`                     | `layout`                                          | Stored for richer land description. |
| `LGA`, `lgsaOrCity`          | `LGA`                                             | Keep both keys aligned for CofO compatibility. |
| `tp_no`                      | `tp_no`                                           | — |
| `lpkn_no`                    | `lpkn_no`                                         | — |
| `approved_plan_no`           | `approved_plan_no`                                | — |
| `plot_size`                  | `plot_size`                                       | As-is; no unit conversion yet. |
| `period`, `period_unit`      | `period`, `period_unit`                           | Used for lease duration summary badges. |
| `assignment_date`            | `Assignment Date`                                 | Parsed date + raw copy (`assignment_date_raw`). |
| `lease_begins`, `lease_begins_raw` | `lease_begins`                               | Normalized + preserved original. |
| `lease_expires`, `lease_expires_raw` | `lease_expires`                           | — |
| `surrender_date`, `surrender_date_raw` | `Surrender Date`                        | — |
| `revoked_date`, `revoked_date_raw`   | `Revoked date`                           | — |
| `date_expired`, `date_expired_raw`   | `Date Expired`                            | — |
| `date_recommended`, `date_recommended_raw` | `date_recommended`                  | — |
| `date_approved`, `date_approved_raw` | `date_approved`                           | — |
| `serialNo`                   | `serialNo` (register serial)                      | Register-issued value; blank entries remain blank and trigger QC. |
| `oldKNNo`                    | `oldKNNo` column                                  | Card serial stored separately; falls back to legacy `SerialNo` only when the dedicated column is blank. |
| `serial_fallback_used` (bool)| `True` when `serialNo` is empty but `oldKNNo` still carries a value. | UI surfaces card-only serials without auto-filling the register column. |
| `pageNo`                     | `pageNo`                                          | Numeric normalization applied. |
| `volumeNo`                   | `volumeNo`                                        | — |
| `regNo`                      | `regNo` (recomposed as `serial/page/volume` when all three are present) | Automatically rebuilt when register serial, page, and volume are filled; otherwise retains the uploaded value for reference. |
| `metric_sheet`               | `metric_sheet`                                    | — |
| `regranted_from`             | `regranted from`                                  | Trimmed + normalized key name. |
| `source`                     | `source` (defaults to `Property Index Card`)      | Stored alongside `migration_source`. |
| `migration_source`           | literal `Property Index Card`                     | Keeps downstream audit consistent. |
| `created_by`, `CreatedBy`    | `CreatedBy` (fallback `System`)                   | Dual casing for legacy consumers. |
| `date_created`, `DateCreated`| `DateCreated`                                     | Parsed + raw copy. |
| `hasIssues`                  | defaults `False`, set during QC                   | Mirrors File History. |
| `prop_id`                    | assigned via `_assign_property_ids`               | Maintains reuse against File Indexing/File History tables. |

All raw values retain their original string representation to power inline
editing while the normalized versions are used for QC checks.

---

## 3. CofO Preview Mapping

The CofO payload mirrors the File History structure with minor adjustments. We
produce a record when at least one of `serialNo`, `pageNo`, `volumeNo`, or
`regNo` carries data.

| CofO Key             | Source Column / Rule                           |
|----------------------|-----------------------------------------------|
| `mlsFNo`             | `MLSFileNo`                                   |
| `transaction_type`   | `transaction_type`                            |
| `instrument_type`    | `transaction_type`                            |
| `Grantor`            | `Grantor`                                     |
| `Grantee`            | `Grantee`                                     |
| `Assignee`           | `Assignee`                                    |
| `location`           | `location` (fallback: `property_description`) |
| `property_description` | `property_description`                      |
| `transaction_date`, `transaction_date_raw` | `Assignment Date` for assignment rows; otherwise `date_approved` or `date_recommended` when available. |
| `transaction_time`, `transaction_time_raw` | Not populated (PIC data has no time component). |
| `serialNo`           | `serialNo` (register serial)                        | Remains empty when the register column is blank. |
| `oldKNNo`            | `oldKNNo` column (fallback to `SerialNo` when the dedicated column is empty). | Card serial reference only; no longer backfills `serialNo`. |
| `pageNo`             | `pageNo`                                     |
| `volumeNo`           | `volumeNo`                                   |
| `regNo`              | `regNo`                                      |
| `created_by`         | `CreatedBy` (fallback `System`)              |
| `prop_id`            | Filled after `_assign_property_ids`.         |
| `source`             | `Property Index Card`                        |

Rows with an empty register serial but a populated card serial inherit
`serial_fallback_used=True`, allowing frontend badges to draw attention without
mutating the register-facing `serialNo` field.

---

## 4. File Number Preview Mapping

Each property row now renders a companion entry in the **File Numbers** preview
tab. The payload mirrors the `fileNumber` table contract while preserving the
per-row tracking ID so uploads can be correlated later.

| File Number Key   | Source Column / Rule                           | Notes |
|-------------------|-----------------------------------------------|-------|
| `mlsfNo`          | `MLSFileNo`                                    | Matches the persisted primary key. |
| `FileName`        | `Grantee` column from property record          | Uses grantee name as the file name. |
| `location`        | `location` (fallback: `property_description`)  | Mirrors the property preview. |
| `type`            | `transaction_type`                             | Stored exactly as seen in the CSV. |
| `SOURCE`          | Resolved `source` string (defaults to `Property Index Card`) | Surfaces the ingest origin. |
| `plot_no`         | `plot_no`                                      | Provided for quick cross checks. |
| `tp_no`           | `tp_no`                                        | Included for downstream land-plan lookups. |
| `created_by`      | `CreatedBy` (defaults to `System`)             | Matches audit columns in the database. |
| `tracking_id`     | Generated via `_generate_tracking_id()` per row | Shared with the property & CofO entries for correlation. |
| `hasIssues`       | Mirrors the originating property row           | The table highlights rows needing review.

The frontend renders these columns alongside a status badge and a placeholder
`Delete` column to keep parity with the other preview tables while avoiding
duplicate delete paths. Note that file number records are not assigned property
IDs as they serve purely informational purposes in the preview.

---

## 5. Duplicate Detection & QC

- Duplicates are keyed off normalized `MLSFileNo` just like File History, with
  the duplicate summaries including the `oldKNNo` when available so operators
  can see whether conflicting cards map to the same KN identifier.
- QC reuses `_run_pra_qc_validation` for file-number patterns and adds a
  `missing_serial` bucket that flags rows where the register `serialNo` column
  is empty. When the card serial is present the same row also lands in the
  `serial_fallback` bucket so reviewers can see the alternate value.
- Rows that contain *some* registration particulars (`serialNo`, `pageNo`,
  `volumeNo`) but not the full trio now fall into a
  `missing_reg_particulars` bucket. The UI surfaces these as "Reg Particulars
  Missing" so operators can complete the page/volume pairing before import.
- Additional date validation reuses `_run_file_history_qc_validation` helpers to
  avoid divergent logic. Any PIC-only required-field checks (`Grantor`,
  `Grantee`, `transaction_type`, `location`) stay aligned with File History so
  the JS renderer can remain generic.

---

## 6. Prop-ID Reuse & Tracking IDs

The PIC flow calls `_assign_property_ids` after merging property + CofO payloads
so property IDs stay consistent across File Indexing, File History, and PIC
sessions. New records trigger the same sequential counter, while existing file
numbers reuse the previous prop-id (sourced from `file_indexings`,
`property_records`, `registered_instruments`, or current session cache).

Each upload batch receives a shared `tracking_id` produced by
`_generate_tracking_id()`. The ID is stamped on every property record and CofO
entry so we can correlate PIC imports with File History/PRA data when persisting
in the future.

---

## 7. Frontend Display Hints

To keep the UI in sync with the backend mapping:

- Show paired **Register Serial** (`serialNo`) and **Old KN No** (`oldKNNo`)
  columns, keeping **Old KN No** immediately to the right of the Comments
  column so card-serial context stays close to the operator notes. When
  `serial_fallback_used` is true, highlight the row/badge so operators know
  only the card serial is currently available.
- Surface the **File Numbers** tab immediately after CofO preview so operators
  can verify the generated tracking ID, file name, and plot details in one
  glance. The table is read-only, mirroring the property row count for easy
  reconciliation.
- Surface `comments`, `remarks`, and expanded date fields in the property-record
  table via expandable rows or additional columns (mirroring File History badge
  patterns).
- Continue to rely on `hasIssues` for row-level highlighting; PIC-specific QC
  just toggles the same flag while adding the `missing_serial` card to the
  summary panel.

---

_Last updated: 2025-11-24_
