# Architecture Transformation Summary

## Overview of Changes

### Why This Change?
- **Current State**: File Indexing handles customer and entity staging (mixed concerns)
- **Target State**: Each import type (File History, PRA, PIC) handles its own customer/entity staging
- **Benefit**: Clear separation of concerns, reusable staging logic, transaction type linking for `reason_retired`

---

## Database Model Changes

### CustomerStaging Table Enhancement

**Before:**
```python
class CustomerStaging(Base):
    __tablename__ = 'customers_staging'
    id = Column(Integer, primary_key=True)
    customer_name = Column(String(255), nullable=False)
    customer_type = Column(String(50), nullable=False)
    # ... other fields ...
    # NO reason_retired field
```

**After:**
```python
class CustomerStaging(Base):
    __tablename__ = 'customers_staging'
    id = Column(Integer, primary_key=True)
    customer_name = Column(String(255), nullable=False)
    customer_type = Column(String(50), nullable=False)
    # ... other fields ...
    reason_retired = Column(String(100), nullable=True)  # ✅ NEW
    # Valid values: Revoked, Assignment, Power of Attorney, Surrender, Mortgage
```

---

## Data Flow Transformation

### BEFORE: File Indexing Handles Everything

```
┌─────────────────────────────────────────┐
│        FILE INDEXING IMPORT             │
├─────────────────────────────────────────┤
│                                         │
│  1. Parse CSV                           │
│  2. Extract File Indexing Records       │
│  3. Extract Entity & Customer Data ⚠️   │  ← STAGING (MIXED CONCERN)
│     ├─ _extract_entity_name()           │
│     ├─ _classify_customer_type()        │
│     ├─ _extract_customer_name()         │
│     └─ _process_staging_import()        │
│                                         │
│  4. Import to DB                        │
│     ├─ file_indexings table             │
│     ├─ customers_staging table ⚠️       │
│     ├─ entities_staging table ⚠️        │
│     └─ CofO_staging table               │
│                                         │
└─────────────────────────────────────────┘

❌ Problem: File Indexing mixes record indexing with customer/entity staging
❌ Problem: No transaction_type → reason_retired mapping
```

### AFTER: Each Import Type Owns Its Staging

```
┌──────────────────────────────────┐
│   FILE HISTORY IMPORT (NEW)      │
├──────────────────────────────────┤
│                                  │
│  1. Parse CSV                    │
│  2. Process File History Records │
│  3. Extract Staging Data ✅      │
│     ├─ transaction_type → reason_retired
│     └─ perform_staging_import()  │
│  4. Import to DB                 │
│     ├─ customers_staging ✅      │
│     │   └─ reason_retired POPULATED
│     └─ entities_staging ✅       │
│                                  │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│    PRA IMPORT (ENHANCED)         │
├──────────────────────────────────┤
│                                  │
│  1. Parse CSV                    │
│  2. Process PRA Records          │
│  3. Extract Staging Data ✅      │
│     ├─ transaction_type → reason_retired
│     └─ perform_staging_import()  │
│  4. Import to DB                 │
│     ├─ customers_staging ✅      │
│     │   └─ reason_retired POPULATED
│     └─ entities_staging ✅       │
│                                  │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│    PIC IMPORT (ENHANCED)         │
├──────────────────────────────────┤
│                                  │
│  1. Parse CSV                    │
│  2. Process PIC Records          │
│  3. Extract Staging Data ✅      │
│     ├─ transaction_type → reason_retired
│     └─ perform_staging_import()  │
│  4. Import to DB                 │
│     ├─ customers_staging ✅      │
│     │   └─ reason_retired POPULATED
│     └─ entities_staging ✅       │
│                                  │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│   FILE INDEXING IMPORT (CLEANED) │
├──────────────────────────────────┤
│                                  │
│  1. Parse CSV                    │
│  2. Extract File Indexing Records│
│  3. NO Staging Extraction ✅     │
│                                  │
│  4. Import to DB                 │
│     ├─ file_indexings table      │
│     ├─ CofO_staging table        │
│     └─ FileNumber table          │
│                                  │
└──────────────────────────────────┘

✅ Benefit: Clear separation of concerns
✅ Benefit: Reusable staging_handler module
✅ Benefit: Transaction type → reason_retired mapping in each context
```

---

## Code Structure Transformation

### New Module: `app/services/staging_handler.py`

**Provides**:
```python
extract_entity_and_customer_data()
    ↓
    Extracts entities/customers + reason_retired
    ↓
    Returns: (entity_records, customer_records, staging_summary)

build_staging_preview()
    ↓
    Formats for UI display
    ↓
    Returns: {entity_staging_preview, customer_staging_preview, staging_summary}

perform_staging_import()
    ↓
    Inserts to DB with reason_retired
    ↓
    Returns: {success, entity_summary, customer_summary, errors}
```

### Used By

**File History**:
- Calls `extract_entity_and_customer_data(..., transaction_type_field='transaction_type')`
- Calls `perform_staging_import(...)` during import

**PRA**:
- Calls `extract_entity_and_customer_data(..., transaction_type_field='transaction_type')`
- Calls `perform_staging_import(...)` during import

**PIC**:
- Calls `extract_entity_and_customer_data(..., transaction_type_field='transaction_type')`
- Calls `perform_staging_import(...)` during import

**File Indexing**:
- ❌ No longer calls staging_handler
- ✅ Cleaner, focused implementation

---

## API Endpoint Changes

### File Indexing Endpoints

**Upload Endpoint** (`POST /api/upload-csv`):
```diff
Response:
{
  "filename": "...",
  "total_records": 100,
  "qc_summary": {...},
  "property_id_summary": {...},
- "staging_summary": {...},           ❌ REMOVED
- "entity_staging_preview": [...],    ❌ REMOVED
- "customer_staging_preview": [...]   ❌ REMOVED
}
```

**Import Endpoint** (`POST /api/import-file-indexing/{session_id}`):
```diff
Response:
{
  "success": true,
  "imported_count": 100,
  "cofo_records": 50,
- "entities_staging_created": 10,      ❌ REMOVED
- "customers_staging_created": 10,     ❌ REMOVED
- "staging_errors": []                 ❌ REMOVED
}
```

### File History Endpoints

**Upload Endpoint** (`POST /api/upload-file-history`):
```diff
Response:
{
  "filename": "...",
  "total_records": 100,
  "property_records": [...],
  "cofo_records": [...],
  "issues": {...},
+ "staging_summary": {...},           ✅ NEW
+ "entity_staging_preview": [...],    ✅ NEW
+ "customer_staging_preview": [...]   ✅ NEW
}
```

**Import Endpoint** (enhanced):
```diff
Response:
{
  "success": true,
  "imported_count": 100,
  "property_records": 100,
+ "staging_import": {                 ✅ NEW
+   "entities_created": 10,
+   "customers_created": 10,
+   "staging_errors": []
+ }
}
```

### Similar for PRA and PIC

---

## Database Impact

### Queries Before

```sql
-- File Indexing sessions create staging records with NO reason_retired
SELECT COUNT(*) FROM customers_staging;
-- Result: 10,000 records

SELECT DISTINCT reason_retired FROM customers_staging;
-- Result: NULL (empty result set)
```

### Queries After

```sql
-- File History/PRA/PIC sessions create staging records WITH reason_retired
SELECT COUNT(*) FROM customers_staging;
-- Result: 10,000 records (same total)

SELECT DISTINCT reason_retired FROM customers_staging;
-- Result: 
--   Revoked
--   Assignment
--   Power of Attorney
--   Surrender
--   Mortgage
--   NULL (for records without transaction_type)

SELECT COUNT(*), reason_retired 
FROM customers_staging 
GROUP BY reason_retired;
-- Shows distribution of reason_retired values
```

---

## Files Changed Summary

### ✅ Phase 1: Complete

| File | Change | Status |
|------|--------|--------|
| `app/models/database.py` | Add `reason_retired` column to CustomerStaging | ✅ DONE |
| `app/services/file_indexing_service.py` | Update `_process_staging_import()` to populate `reason_retired` | ✅ DONE |
| `app/services/staging_handler.py` | NEW module with reusable staging functions | ✅ DONE |
| `app/routers/file_history.py` | NEW router starter file | ✅ DONE |

### ⏳ Phase 2-4: Pending

| File | Change | Status |
|------|--------|--------|
| `main.py` | Integrate staging_handler into File History upload/import | ⏳ TODO |
| `main.py` | Integrate staging_handler into PRA upload/import | ⏳ TODO |
| `main.py` | Integrate staging_handler into PIC upload/import | ⏳ TODO |
| `app/routers/file_indexing.py` | Remove staging from upload and import | ⏳ TODO |
| `templates/file_indexing.html` | Remove staging UI sections | ⏳ TODO |
| `static/js/file-indexing.js` | Remove staging JS handlers | ⏳ TODO |
| `templates/file_history_import.html` | Add staging preview UI | ⏳ TODO |
| `static/js/file-history-import.js` | Add staging display logic | ⏳ TODO |
| `templates/pra_import.html` | Add staging preview UI | ⏳ TODO |
| `static/js/pra-import.js` | Add staging display logic | ⏳ TODO |
| `templates/property_index_card.html` | Add staging preview UI | ⏳ TODO |
| `static/js/pic.js` | Add staging display logic | ⏳ TODO |

---

## Testing Strategy

### Unit Tests
```python
# Test staging_handler functions independently
test_extract_reason_retired()
test_extract_entity_and_customer_data()
test_perform_staging_import()
```

### Integration Tests
```python
# Test with actual CSV data
test_file_history_with_staging()
test_pra_with_staging()
test_pic_with_staging()
test_file_indexing_without_staging()
```

### Manual Testing
1. Upload File History → Verify reason_retired populated
2. Upload PRA → Verify reason_retired populated
3. Upload PIC → Verify reason_retired populated
4. Upload File Indexing → Verify NO staging created
5. Query database → Verify reason_retired distribution

---

## Migration Checklist

- [ ] Phase 1: Database & Services (COMPLETE)
- [ ] Phase 2: File History Integration
  - [ ] Add staging_handler calls to upload
  - [ ] Add staging_handler calls to import
  - [ ] Update HTML/JS
- [ ] Phase 3: PRA Integration
  - [ ] Add staging_handler calls to upload
  - [ ] Add staging_handler calls to import
  - [ ] Update HTML/JS
- [ ] Phase 4: PIC Integration
  - [ ] Add staging_handler calls to upload
  - [ ] Add staging_handler calls to import
  - [ ] Update HTML/JS
- [ ] Phase 5: File Indexing Cleanup
  - [ ] Remove staging from upload
  - [ ] Remove staging from import
  - [ ] Update HTML/JS
- [ ] Phase 6: Testing
  - [ ] All workflows functional
  - [ ] No errors in logs
  - [ ] Database integrity verified

