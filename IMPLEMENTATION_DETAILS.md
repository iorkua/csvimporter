# Implementation Guide: Moving Staging Tables from File Indexing

## Summary of Changes

This document provides step-by-step instructions for safely removing `customers_staging` and `entities_staging` extraction from File Indexing and moving it to File History, PRA, and PIC.

---

## PART 1: Database Model Changes ✅ DONE

### CustomerStaging Model Enhancement
- **File**: `app/models/database.py`
- **Change**: Added `reason_retired` column
- **Valid Values**: Revoked, Assignment, Power of Attorney, Surrender, Mortgage
- **Status**: ✅ COMPLETED

---

## PART 2: Core Services Updates

### 2.1 Staging Handler Module ✅ DONE
- **File**: `app/services/staging_handler.py` (NEW)
- **Purpose**: Centralized staging extraction for all import workflows
- **Functions**:
  - `extract_entity_and_customer_data()` - Extract from records with reason_retired
  - `build_staging_preview()` - Format staging data for UI
  - `perform_staging_import()` - Database insert with reason_retired
- **Status**: ✅ COMPLETED

### 2.2 File Indexing Service Enhancement ✅ DONE
- **File**: `app/services/file_indexing_service.py`
- **Change**: Updated `_process_staging_import()` to include `reason_retired` extraction
- **Logic**: Maps transaction_type to reason_retired values
- **Status**: ✅ COMPLETED

---

## PART 3: Router/Endpoint Updates

### 3.1 File History Router Enhancement
- **File**: `app/routers/file_history.py` (NEW - STARTER CREATED)
- **Next Steps**:
  1. In `main.py`, locate `/api/upload-file-history` endpoint (line ~1205)
  2. After processing property_records and cofo_records, call:
     ```python
     from app.services.staging_handler import extract_entity_and_customer_data, build_staging_preview
     
     entity_records, customer_records, staging_summary = extract_entity_and_customer_data(
         property_records,
         file.filename,
         mode,  # test_control
         transaction_type_field='transaction_type'
     )
     ```
  3. Add to session and response:
     ```python
     app.sessions[session_id].update({
         "entity_staging_records": entity_records,
         "customer_staging_records": customer_records,
         "staging_summary": staging_summary
     })
     ```
  4. Add to return payload:
     ```python
     "staging_summary": staging_summary,
     "entity_staging_preview": entity_records,
     "customer_staging_preview": customer_records
     ```

### 3.2 File History Import Endpoint
- **Location**: `main.py` line ~1500 (@app.post("/api/file-history/import/{session_id}"))
- **Add**: Call `perform_staging_import()` before committing file history data
- **Code**:
  ```python
  from app.services.staging_handler import perform_staging_import
  
  staging_result = perform_staging_import(
      db,
      session_data['property_records'],
      session_data['filename'],
      session_data['test_control'],
      'transaction_type'
  )
  
  # Track staging results in response
  result['staging_import'] = {
      'entities_created': staging_result['entity_summary']['new'],
      'customers_created': staging_result['customer_summary']['created'],
      'staging_errors': staging_result['errors']
  }
  ```

### 3.3 PRA Import Updates (SIMILAR TO FILE HISTORY)
- **Files**: `main.py` and `app/routers/pra.py` (if exists)
- **Steps**: Same as File History
- **Field**: Map PRA transaction_type to reason_retired

### 3.4 PIC Import Updates (SIMILAR TO FILE HISTORY)
- **Files**: `main.py` and `app/routers/pic.py` (if exists)
- **Steps**: Same as File History
- **Field**: Map PIC transaction_type to reason_retired

---

## PART 4: File Indexing Cleanup

### 4.1 Remove Staging from Upload Preview
- **File**: `app/routers/file_indexing.py`
- **Location**: `_prepare_file_indexing_preview_payload()` function (line ~180)
- **Remove**: These lines:
  ```python
  # Remove entire staging preview section:
  staging_start = datetime.utcnow()
  entity_staging_preview, customer_staging_preview, staging_summary = _prepare_staging_preview(
      records, 
      filename,
      test_control_value
  )
  logger.info("Staging preview prepared in %.3fs", (datetime.utcnow() - staging_start).total_seconds())
  ```
- **Remove from session_payload**: 
  ```python
  "entity_staging_records": entity_staging_preview,
  "customer_staging_records": customer_staging_preview,
  "staging_summary": staging_summary
  ```
- **Remove from response_payload**:
  ```python
  "staging_summary": staging_summary,
  "entity_staging_preview": entity_staging_preview,
  "customer_staging_preview": customer_staging_preview
  ```

### 4.2 Remove Staging from Import Logic
- **File**: `app/routers/file_indexing.py`
- **Location**: `_process_import_data()` function (line ~470)
- **Remove**: Entire staging import section:
  ```python
  # Staging import tracking (NEW)
  entities_created = 0
  customers_created = 0
  staging_errors: List[Dict[str, Any]] = []
  
  # ... and later ...
  
  staging_result = _process_staging_import(
      db,
      session_data["data"],
      source_filename,
      test_control
  )
  entities_created = staging_result.get('entity_summary', {}).get('new', 0)
  customers_created = staging_result.get('customer_summary', {}).get('created', 0)
  staging_errors = list(staging_result.get('errors', []))
  ```
- **Remove from return payload**:
  ```python
  "entities_staging_created": entities_created,
  "customers_staging_created": customers_created,
  "staging_errors": staging_errors,
  ```

### 4.3 Remove Staging Functions from File Indexing Router
- **File**: `app/routers/file_indexing.py`
- **Remove imports**:
  ```python
  _prepare_staging_preview,
  _classify_customer_type,
  _extract_entity_name,
  _extract_customer_name,
  _extract_customer_address,
  _extract_photos,
  _generate_customer_code,
  _generate_import_batch_id,
  _get_or_create_entity,
  _process_staging_import,
  ```
- **Remove function**: `_prepare_staging_preview()` (entire function)

### 4.4 Remove Staging from Upload Endpoint
- **File**: `app/routers/file_indexing.py`
- **Location**: `/api/upload-csv` endpoint
- **Remove**: The section that calls `_prepare_staging_preview()`

---

## PART 5: Frontend Changes

### 5.1 File Indexing HTML Cleanup
- **File**: `templates/file_indexing.html`
- **Remove Sections**:
  - Staging summary cards section
  - Entity staging table section
  - Customer staging table section
  - Any staging-related modals or tabs

### 5.2 File Indexing JavaScript Cleanup
- **File**: `static/js/file-indexing.js`
- **Remove**:
  - `this.customerStagingPreview` property initialization
  - Any functions related to staging display
  - Staging tab rendering
  - Staging data event handlers

### 5.3 File History HTML Enhancement
- **File**: `templates/file_history_import.html`
- **Add**:
  - Staging summary section (copy from existing File Indexing design)
  - Entity staging table (optional, minimal display)
  - Customer staging table with reason_retired column
  - Staging status badges

### 5.4 File History JavaScript Enhancement
- **File**: `static/js/file-history-import.js`
- **Add**:
  - Parse staging_preview from upload response
  - Display staging summary with counts
  - Show reason_retired values for customers
  - Handle staging import completion status

### 5.5 PRA HTML/JS Enhancement
- **Similar to File History**
- Add staging preview display
- Map PRA transaction types to reason_retired

### 5.6 PIC HTML/JS Enhancement
- **Similar to File History**
- Add staging preview display
- Map PIC transaction types to reason_retired

---

## PART 6: Validation & Testing

### Test Checklist
- [ ] File Indexing upload succeeds WITHOUT staging data
- [ ] File Indexing import completes normally
- [ ] File History upload extracts staging data correctly
- [ ] File History import creates entities and customers with reason_retired
- [ ] PRA upload extracts staging data correctly
- [ ] PRA import creates entities and customers with reason_retired
- [ ] PIC upload extracts staging data correctly
- [ ] PIC import creates entities and customers with reason_retired
- [ ] reason_retired values are correctly populated (Revoked, Assignment, etc.)
- [ ] Clear data endpoints delete staging records for all features
- [ ] No JavaScript errors in browser console
- [ ] All QC validation still functions

### Database Queries to Verify
```sql
-- Check staging tables after File History import
SELECT COUNT(*), customer_type FROM customers_staging GROUP BY customer_type;
SELECT COUNT(*), COUNT(DISTINCT reason_retired) FROM customers_staging;
SELECT DISTINCT reason_retired FROM customers_staging WHERE reason_retired IS NOT NULL;

-- Verify no staging records from File Indexing (should be empty or minimal)
SELECT COUNT(*) FROM customers_staging WHERE file_number LIKE 'FILE-IDX%';
```

---

## PART 7: Rollback Plan

If needed to restore File Indexing staging:

1. Restore `_prepare_staging_preview()` function in `app/routers/file_indexing.py`
2. Restore staging extraction call in `_prepare_file_indexing_preview_payload()`
3. Restore staging import call in `_process_import_data()`
4. Restore HTML sections in `templates/file_indexing.html`
5. Restore JS functions in `static/js/file-indexing.js`
6. Restore import statements in `app/routers/file_indexing.py`

---

## Key Functions Reference

### Staging Handler Functions (app/services/staging_handler.py)
```python
extract_entity_and_customer_data(
    records: List[Dict[str, Any]],
    filename: str,
    test_control: str = 'PRODUCTION',
    transaction_type_field: str = 'transaction_type'
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]

build_staging_preview(
    entity_records: List[Dict[str, Any]],
    customer_records: List[Dict[str, Any]],
    staging_summary: Dict[str, Any]
) -> Dict[str, Any]

perform_staging_import(
    db,
    records: List[Dict[str, Any]],
    filename: str,
    test_control: str = 'PRODUCTION',
    transaction_type_field: str = 'transaction_type'
) -> Dict[str, Any]
```

### File Indexing Service Functions (app/services/file_indexing_service.py)
```python
_extract_reason_retired(record, transaction_type_field)
_process_staging_import(db, records, filename, test_control)  # ENHANCED
```

---

## Implementation Sequence

**Recommended Order**:

1. ✅ Phase 1: Database & Services (DONE)
   - Add reason_retired column
   - Create staging_handler.py
   - Update _process_staging_import()

2. ⏳ Phase 2: File History Integration
   - Integrate staging_handler with File History upload
   - Integrate staging import with File History import
   - Update File History HTML/JS

3. ⏳ Phase 3: PRA & PIC Integration
   - Apply same pattern to PRA
   - Apply same pattern to PIC

4. ⏳ Phase 4: File Indexing Cleanup
   - Remove staging from upload preview
   - Remove staging from import logic
   - Update File Indexing HTML/JS

5. ⏳ Phase 5: Testing & Validation
   - Verify all workflows
   - Check database integrity
   - Run full test suite

---

