# Staging Tables Migration Strategy

## Overview
**Goal**: Safely remove `customers_staging` and `entities_staging` from File Indexing workflow and redistribute the entity/customer extraction logic to File History, PRA, and PIC imports.

**New Column Added**: `reason_retired` column added to `CustomerStaging` with valid values:
- Revoked
- Assignment
- Power of Attorney
- Surrender
- Mortgage

---

## Current Architecture

### File Indexing Current Flow
```
File Indexing Upload
├── Parse CSV/Excel
├── Process File Indexing Records
├── Extract Entity & Customer Data (STAGING)
│   ├── _prepare_staging_preview()
│   ├── _extract_entity_name()
│   ├── _extract_customer_name()
│   └── _classify_customer_type()
├── Create Preview (UI shows staging tables)
└── Import
    └── _process_staging_import()
```

### Target Architecture
```
File Indexing Upload
├── Parse CSV/Excel
├── Process File Indexing Records
└── No staging extraction (REMOVED)

File History Upload (ENHANCED)
├── Parse CSV/Excel
├── Extract Entity & Customer Data (MOVED HERE)
└── Import entities_staging & customers_staging

PRA Upload (ENHANCED)
├── Parse CSV/Excel
├── Extract Entity & Customer Data (MOVED HERE)
└── Import entities_staging & customers_staging

PIC Upload (ENHANCED)
├── Parse CSV/Excel
├── Extract Entity & Customer Data (MOVED HERE)
└── Import entities_staging & customers_staging
```

---

## Implementation Plan

### Phase 1: Create Staging Module
- [ ] Create `app/services/staging_handler.py` with reusable staging functions:
  - `extract_entity_and_customer_data(records, filename, test_control)`
  - `build_staging_preview(entity_records, customer_records)`
  - `perform_staging_import(db, entity_records, customer_records, test_control)`
  - Handle `reason_retired` field for customer records

### Phase 2: Update File History
- [ ] Create staging extraction in File History router
- [ ] Add `reason_retired` field to File History preview/import
- [ ] Link File History `transaction_type` to determine `reason_retired` value
- [ ] Update File History HTML/JS to show staging preview

### Phase 3: Update PRA
- [ ] Create staging extraction in PRA router
- [ ] Add `reason_retired` field to PRA preview/import
- [ ] Link PRA transaction data to `reason_retired`
- [ ] Update PRA HTML/JS to show staging preview

### Phase 4: Update PIC
- [ ] Create staging extraction in PIC router
- [ ] Add `reason_retired` field to PIC preview/import
- [ ] Link PIC transaction data to `reason_retired`
- [ ] Update PIC HTML/JS to show staging preview

### Phase 5: Remove from File Indexing
- [ ] Remove staging preview from File Indexing upload response
- [ ] Remove staging import from File Indexing import logic
- [ ] Remove staging-related HTML elements from file_indexing.html
- [ ] Remove staging-related JS from file-indexing.js
- [ ] Update File Indexing tests

### Phase 6: Testing & Validation
- [ ] Test File History staging import
- [ ] Test PRA staging import
- [ ] Test PIC staging import
- [ ] Verify File Indexing no longer processes staging data
- [ ] Verify `reason_retired` values are correctly populated

---

## Key Functions to Reuse

All existing staging functions from `file_indexing_service.py` will be moved/reused:

```python
# Core extraction functions
_classify_customer_type(descriptor)
_extract_entity_name(record)
_extract_customer_name(record, entity_name)
_extract_customer_address(record)
_extract_photos(record, customer_type, include_placeholders)
_generate_customer_code()
_get_or_create_entity(db, entity_name, customer_type, ...)
_process_staging_import(db, records, filename, test_control)
```

---

## reason_retired Field Mapping

### File History
- Transaction Type → reason_retired:
  - `Revoked` → `Revoked`
  - `Assignment` → `Assignment`
  - `Power of Attorney` → `Power of Attorney`
  - `Surrender` → `Surrender`
  - `Mortgage` → `Mortgage`

### PRA
- Similar mapping based on transaction type field

### PIC
- Similar mapping based on transaction type field

---

## Database Impact

### New/Modified Tables
- `customers_staging`: Adding `reason_retired` column (DONE ✓)
- `entities_staging`: No changes needed (remains as-is)

### Clear Data Endpoint
- Existing `/api/file-indexing/clear-data` already deletes staging tables
- Ensure File History, PRA, PIC clear endpoints also handle staging cleanup

---

## Frontend Changes Summary

### File Indexing
- **Remove**: Staging preview section
- **Remove**: Staging summary cards
- **Remove**: Entity/Customer tables

### File History
- **Add**: Staging preview section
- **Add**: Staging summary cards
- **Add**: reason_retired field display

### PRA
- **Add**: Staging preview section
- **Add**: Staging summary cards
- **Add**: reason_retired field display

### PIC
- **Add**: Staging preview section
- **Add**: Staging summary cards
- **Add**: reason_retired field display

---

## Rollback Plan

If needed, restore staging functionality to File Indexing:
1. Restore `_prepare_staging_preview()` call in router
2. Restore staging preview response payload
3. Restore staging import in `_process_import_data()`
4. Restore HTML/JS staging UI elements

---

## Testing Checklist

- [ ] File Indexing imports without staging data
- [ ] File History extracts and imports entities/customers correctly
- [ ] PRA extracts and imports entities/customers correctly
- [ ] PIC extracts and imports entities/customers correctly
- [ ] reason_retired values are populated correctly
- [ ] Clear data endpoints delete staging records
- [ ] No errors in browser console
- [ ] All QC validations still work

