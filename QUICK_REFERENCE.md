# Quick Reference Guide

## What Has Been Done ✅

### 1. Database Model (app/models/database.py)
```python
# Added reason_retired column to CustomerStaging
reason_retired = Column(String(100), nullable=True)
# Valid values: Revoked, Assignment, Power of Attorney, Surrender, Mortgage
```

### 2. Staging Handler Module (app/services/staging_handler.py)
**New module with 3 main functions:**
- `extract_entity_and_customer_data()` - Extract from records
- `build_staging_preview()` - Format for UI
- `perform_staging_import()` - Insert to database

**Features:**
- Automatically populates `reason_retired` based on transaction_type
- Configurable transaction_type field name
- Centralized extraction logic
- Reusable across File History, PRA, and PIC

### 3. File Indexing Service Enhancement (app/services/file_indexing_service.py)
```python
# Updated _process_staging_import() to extract reason_retired
reason_retired = _extract_reason_retired(record, 'transaction_type')
# Added to CustomerStaging creation
```

---

## What Still Needs to Be Done ⏳

### Phase 2: File History Integration

**1. Update main.py - Upload Endpoint (~line 1205)**
```python
# After processing records, add:
from app.services.staging_handler import extract_entity_and_customer_data

entity_records, customer_records, staging_summary = extract_entity_and_customer_data(
    property_records,
    file.filename,
    mode,  # test_control
    transaction_type_field='transaction_type'
)

# Update session
app.sessions[session_id].update({
    "entity_staging_records": entity_records,
    "customer_staging_records": customer_records,
    "staging_summary": staging_summary
})

# Update response
response.update({
    "staging_summary": staging_summary,
    "entity_staging_preview": entity_records,
    "customer_staging_preview": customer_records
})
```

**2. Update main.py - Import Endpoint (~line 1500)**
```python
# In the import function, add:
from app.services.staging_handler import perform_staging_import

staging_result = perform_staging_import(
    db,
    session_data['property_records'],
    session_data['filename'],
    session_data['test_control'],
    'transaction_type'
)

# Track in results
result['staging_import'] = {
    'entities_created': staging_result['entity_summary']['new'],
    'customers_created': staging_result['customer_summary']['created'],
    'staging_errors': staging_result['errors']
}
```

**3. Update templates/file_history_import.html**
- Add staging summary section with entity/customer counts
- Add customer staging table with reason_retired column
- Add entity count display

**4. Update static/js/file-history-import.js**
- Parse `entity_staging_preview` and `customer_staging_preview` from response
- Display staging summary
- Show reason_retired values in table

### Phase 3: PRA Integration
**Same as Phase 2 but for PRA**
- Update upload endpoint
- Update import endpoint  
- Update HTML/JS for PRA

### Phase 4: PIC Integration
**Same as Phase 2 but for PIC**
- Update upload endpoint
- Update import endpoint
- Update HTML/JS for PIC

### Phase 5: File Indexing Cleanup

**1. Remove from app/routers/file_indexing.py**
- Delete `_prepare_staging_preview()` function
- Remove staging extraction from `_prepare_file_indexing_preview_payload()`
- Remove staging import from `_process_import_data()`
- Remove staging-related imports

**2. Remove from templates/file_indexing.html**
- Delete staging summary cards section
- Delete entity staging table
- Delete customer staging table

**3. Remove from static/js/file-indexing.js**
- Remove `this.customerStagingPreview` property
- Remove staging display functions
- Remove staging event handlers

---

## Mapping Transaction Type to reason_retired

### File History
```
Transaction Type → reason_retired
"Revoked" → "Revoked"
"Assignment" → "Assignment"
"Power of Attorney" → "Power of Attorney"
"Surrender" → "Surrender"
"Mortgage" → "Mortgage"
```

### PRA
```
Use same mapping as File History
```

### PIC
```
Use same mapping as File History
```

---

## Database Queries to Verify

### Check Staging Data
```sql
-- After File History import
SELECT COUNT(*) as total, COUNT(DISTINCT reason_retired) as types
FROM customers_staging;

SELECT reason_retired, COUNT(*) as count
FROM customers_staging
WHERE reason_retired IS NOT NULL
GROUP BY reason_retired;
```

### Check No File Indexing Staging
```sql
-- Verify File Indexing no longer creates staging
SELECT COUNT(*) FROM customers_staging 
WHERE file_number LIKE 'FI-%' OR created_at > GETDATE() - 1;
```

---

## Testing Checklist

- [ ] File Indexing upload works WITHOUT staging data
- [ ] File Indexing import succeeds
- [ ] File History upload extracts staging data
- [ ] File History import creates customers with reason_retired
- [ ] PRA upload extracts staging data
- [ ] PRA import creates customers with reason_retired
- [ ] PIC upload extracts staging data
- [ ] PIC import creates customers with reason_retired
- [ ] reason_retired values are correct (Revoked, Assignment, etc.)
- [ ] No JavaScript errors in browser
- [ ] No Python errors in logs

---

## Code Snippets for Quick Copy-Paste

### Extract and Preview Staging
```python
from app.services.staging_handler import extract_entity_and_customer_data, build_staging_preview

entity_records, customer_records, staging_summary = extract_entity_and_customer_data(
    records_list,
    filename,
    'PRODUCTION',
    transaction_type_field='transaction_type'
)

staging_payload = build_staging_preview(
    entity_records,
    customer_records,
    staging_summary
)
```

### Perform Staging Import
```python
from app.services.staging_handler import perform_staging_import

result = perform_staging_import(
    db,
    records_list,
    filename,
    'PRODUCTION',
    transaction_type_field='transaction_type'
)

# Use result['entity_summary'] and result['customer_summary']
```

### Add to Session and Response
```python
# Session
app.sessions[session_id].update({
    "entity_staging_records": entity_records,
    "customer_staging_records": customer_records,
    "staging_summary": staging_summary
})

# Response
return {
    "staging_summary": staging_summary,
    "entity_staging_preview": entity_records,
    "customer_staging_preview": customer_records,
    # ... other fields ...
}
```

---

## Key Files to Edit

### Main Implementation Files
1. `main.py` - Update File History, PRA, PIC endpoints (3 phases)
2. `app/routers/file_indexing.py` - Remove staging (1 phase)

### Frontend Files
1. `templates/file_history_import.html` - Add staging UI
2. `static/js/file-history-import.js` - Display staging data
3. `templates/pra_import.html` - Add staging UI
4. `static/js/pra-import.js` - Display staging data
5. `templates/property_index_card.html` - Add staging UI
6. `static/js/pic.js` - Display staging data
7. `templates/file_indexing.html` - Remove staging UI
8. `static/js/file-indexing.js` - Remove staging code

### Already Complete
- `app/models/database.py` ✅
- `app/services/file_indexing_service.py` ✅
- `app/services/staging_handler.py` ✅
- `app/routers/file_history.py` ✅

---

## Configuration Notes

### reason_retired Valid Values
Must be one of:
- `Revoked`
- `Assignment`
- `Power of Attorney`
- `Surrender`
- `Mortgage`

Any other value will be NULL (auto-sanitized by staging_handler)

### Transaction Type Field
- File History: `transaction_type`
- PRA: `transaction_type` (or adjust if different)
- PIC: `transaction_type` (or adjust if different)

Pass as `transaction_type_field` parameter:
```python
extract_entity_and_customer_data(
    records,
    filename,
    test_control,
    transaction_type_field='transaction_type'  # Adjust if needed
)
```

---

## Monitoring & Logging

### What to Monitor
1. Staging import success rate
2. reason_retired population rate
3. Error counts per transaction type

### Logs to Check
```python
# After importing, check logs for:
logger.info("Staging preview prepared in %.3fs", ...)
logger.error("Error processing record %d: %s", ...)
logger.info("Created new entity: %s (id=%d)", ...)
```

---

## Troubleshooting

### Issue: reason_retired is NULL
**Cause**: transaction_type field not found or not matching mapping
**Fix**: Verify transaction_type field exists and contains valid values

### Issue: Staging not extracted
**Cause**: staging_handler not called in upload endpoint
**Fix**: Add extract_entity_and_customer_data() call

### Issue: Staging data not in response
**Cause**: Not added to response payload
**Fix**: Include staging_summary, entity_staging_preview, customer_staging_preview

### Issue: JavaScript error on File History page
**Cause**: Staging data not parsed in JS
**Fix**: Update static/js/file-history-import.js to parse staging fields

---

## Success Criteria

✅ **Phase 1**: COMPLETE
- Database model updated
- Staging handler created
- File Indexing service enhanced

✅ **Phase 2-4**: Each integration done when:
- Upload endpoint calls staging_handler
- Import endpoint performs staging import
- HTML displays staging preview
- JS parses and displays staging data
- reason_retired values populate correctly

✅ **Phase 5**: Complete when:
- File Indexing upload response has NO staging fields
- File Indexing import completes without staging
- File Indexing HTML/JS has NO staging UI
- All tests pass

