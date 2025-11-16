# Visual Implementation Guide

## Current Status: Phase 1 ✅ COMPLETE

```
Phase 1: Core Services & Database
├─ ✅ app/models/database.py
│  └─ Added reason_retired column to CustomerStaging
│
├─ ✅ app/services/staging_handler.py (NEW)
│  ├─ extract_entity_and_customer_data()
│  ├─ build_staging_preview()
│  └─ perform_staging_import()
│
├─ ✅ app/services/file_indexing_service.py
│  └─ Updated _process_staging_import() with reason_retired
│
└─ ✅ app/routers/file_history.py (NEW - starter)
```

---

## Phase 2: File History Integration ⏳ TODO

### Step-by-Step Flow

```
1. USER UPLOADS FILE HISTORY CSV
   │
   ├─ endpoint: POST /api/upload-file-history
   │
   ├─ Process:
   │  ├─ Read CSV → property_records
   │  ├─ Read CSV → cofo_records
   │  │
   │  ├─ NEW: Call staging_handler
   │  │  ├─ extract_entity_and_customer_data()
   │  │  │  ├─ Iterate each property_record
   │  │  │  ├─ Extract transaction_type
   │  │  │  │  └─ Map to reason_retired
   │  │  │  ├─ Extract entity_name
   │  │  │  ├─ Extract customer_name
   │  │  │  └─ Return staging data
   │  │  │
   │  │  └─ build_staging_preview()
   │  │     └─ Format for UI
   │  │
   │  ├─ Build response
   │  └─ Store in session
   │
   └─ RESPONSE INCLUDES:
      ├─ property_records
      ├─ cofo_records
      ├─ ✅ staging_summary
      ├─ ✅ entity_staging_preview
      ├─ ✅ customer_staging_preview
      └─ test_control

2. USER REVIEWS DATA & CLICKS IMPORT
   │
   ├─ endpoint: POST /api/file-history/import/{session_id}
   │
   ├─ Process:
   │  ├─ Get session data
   │  ├─ Begin transaction
   │  │
   │  ├─ Import property_records
   │  ├─ Import cofo_records
   │  │
   │  ├─ NEW: Call perform_staging_import()
   │  │  ├─ Iterate each property_record
   │  │  ├─ Create EntityStaging records
   │  │  ├─ Create CustomerStaging records
   │  │  │  └─ POPULATE reason_retired
   │  │  └─ Commit to DB
   │  │
   │  ├─ Commit transaction
   │  └─ Clear session
   │
   └─ RESPONSE INCLUDES:
      ├─ success: true
      ├─ imported_count: 100
      ├─ ✅ staging_import
      │  ├─ entities_created: 10
      │  ├─ customers_created: 10
      │  └─ staging_errors: []
      └─ message: "..."
```

### Code Changes Needed (main.py)

```python
# CHANGE 1: Import at top of file
from app.services.staging_handler import (
    extract_entity_and_customer_data,
    build_staging_preview,
    perform_staging_import
)

# CHANGE 2: In upload endpoint (after processing records)
@app.post("/api/upload-file-history")
async def upload_file_history(...):
    # ... existing code ...
    property_records, cofo_records = _process_file_history_data(dataframe)
    
    # ✅ NEW CODE HERE
    entity_records, customer_records, staging_summary = extract_entity_and_customer_data(
        property_records,
        file.filename,
        mode,
        transaction_type_field='transaction_type'
    )
    
    # ... update session ...
    app.sessions[session_id].update({
        "entity_staging_records": entity_records,
        "customer_staging_records": customer_records,
        "staging_summary": staging_summary
    })
    
    # ... update response ...
    return {
        # ... existing fields ...
        "staging_summary": staging_summary,
        "entity_staging_preview": entity_records,
        "customer_staging_preview": customer_records
    }

# CHANGE 3: In import endpoint
@app.post("/api/file-history/import/{session_id}")
async def import_file_history(session_id: str):
    # ... existing code ...
    db = SessionLocal()
    
    # ✅ NEW CODE HERE
    staging_result = perform_staging_import(
        db,
        session_data['property_records'],
        session_data['filename'],
        session_data['test_control'],
        'transaction_type'
    )
    
    # ... existing import code ...
    
    return {
        "success": True,
        # ... existing fields ...
        "staging_import": {
            "entities_created": staging_result['entity_summary']['new'],
            "customers_created": staging_result['customer_summary']['created'],
            "staging_errors": staging_result['errors']
        }
    }
```

### UI Changes (templates/file_history_import.html)

```html
<!-- ADD AFTER COFO SECTION -->

<!-- Staging Preview Section -->
<div id="stagingPreviewContainer" style="display:none;">
    <div class="card mt-4">
        <div class="card-header bg-info text-white">
            <h5 class="mb-0">
                <i class="fas fa-users me-2"></i>
                Entity & Customer Staging
            </h5>
        </div>
        <div class="card-body">
            <!-- Staging Summary Stats -->
            <div class="row mb-3">
                <div class="col-md-3">
                    <div class="badge bg-primary p-2">
                        Entities: <span id="stagingEntityCount">0</span>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="badge bg-success p-2">
                        Customers: <span id="stagingCustomerCount">0</span>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="badge bg-warning p-2">
                        With Reason: <span id="stagingReasonCount">0</span>
                    </div>
                </div>
            </div>
            
            <!-- Customer Staging Table -->
            <table class="table table-sm table-hover">
                <thead>
                    <tr>
                        <th>Customer Name</th>
                        <th>Type</th>
                        <th>Reason Retired</th>
                        <th>File Number</th>
                    </tr>
                </thead>
                <tbody id="stagingTableBody">
                    <!-- Populated by JS -->
                </tbody>
            </table>
        </div>
    </div>
</div>
```

### JS Changes (static/js/file-history-import.js)

```javascript
// ADD TO FILE-HISTORY-IMPORT.JS

class FileHistoryImporter {
    // ... existing code ...
    
    displayStagingPreview(stagingData) {
        // Show container
        document.getElementById('stagingPreviewContainer').style.display = 'block';
        
        // Update counts
        document.getElementById('stagingEntityCount').textContent = 
            stagingData.staging_summary.entity_count;
        document.getElementById('stagingCustomerCount').textContent = 
            stagingData.staging_summary.customer_count;
        document.getElementById('stagingReasonCount').textContent = 
            stagingData.staging_summary.reason_retired_populated;
        
        // Populate table
        const tbody = document.getElementById('stagingTableBody');
        tbody.innerHTML = '';
        
        for (const customer of stagingData.customer_staging_preview) {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${customer.customer_name}</td>
                <td><span class="badge bg-secondary">${customer.customer_type}</span></td>
                <td>${customer.reason_retired || '-'}</td>
                <td>${customer.file_number || '-'}</td>
            `;
            tbody.appendChild(row);
        }
    }
    
    async handleUpload(formData) {
        // ... existing code ...
        const result = await fetch(...).then(r => r.json());
        
        // ✅ NEW: Display staging preview
        this.displayStagingPreview(result);
        
        // ... rest of handling ...
    }
}
```

---

## Phase 3 & 4: PRA & PIC Integration

### Same Pattern as File History

```
PRA Integration:
├─ Add staging_handler calls to /api/upload-pra
├─ Add staging_handler calls to /api/pra/import/{session_id}
├─ Update templates/pra_import.html
└─ Update static/js/pra-import.js

PIC Integration:
├─ Add staging_handler calls to /api/upload-pic
├─ Add staging_handler calls to /api/pic/import/{session_id}
├─ Update templates/property_index_card.html
└─ Update static/js/pic.js
```

---

## Phase 5: File Indexing Cleanup

### Removal Checklist

```
app/routers/file_indexing.py:
├─ Remove import: _prepare_staging_preview
├─ Remove import: _classify_customer_type
├─ Remove import: _extract_entity_name
├─ Remove import: _extract_customer_name
├─ Remove import: _extract_customer_address
├─ Remove import: _extract_photos
├─ Remove import: _generate_customer_code
├─ Remove import: _generate_import_batch_id
├─ Remove import: _get_or_create_entity
├─ Remove import: _process_staging_import
│
├─ Remove function: _prepare_staging_preview()
│
├─ Remove from _prepare_file_indexing_preview_payload():
│  ├─ staging_start = datetime.utcnow()
│  ├─ entity_staging_preview, customer_staging_preview, staging_summary = ...
│  ├─ "entity_staging_records": entity_staging_preview
│  ├─ "customer_staging_records": customer_staging_preview
│  ├─ "staging_summary": staging_summary
│  └─ (all related lines)
│
└─ Remove from _process_import_data():
   ├─ entities_created = 0
   ├─ customers_created = 0
   ├─ staging_errors: List[Dict[str, Any]] = []
   ├─ staging_result = _process_staging_import(...)
   ├─ "entities_staging_created": entities_created
   ├─ "customers_staging_created": customers_created
   ├─ "staging_errors": staging_errors
   └─ (all related lines)

templates/file_indexing.html:
├─ Remove: Staging summary cards section
├─ Remove: Entity staging table
├─ Remove: Customer staging table
└─ Remove: Staging-related modals/tabs

static/js/file-indexing.js:
├─ Remove: this.customerStagingPreview property
├─ Remove: displayStagingPreview() function
├─ Remove: updateStagingTable() function
├─ Remove: Staging event handlers
└─ Remove: Staging-related code blocks
```

---

## Database State Verification

### Before File History Integration
```sql
SELECT COUNT(*), source FROM customers_staging GROUP BY source;
-- May have older test records

SELECT COUNT(*), COUNT(DISTINCT reason_retired) FROM customers_staging;
-- reason_retired mostly NULL
```

### After File History Integration
```sql
SELECT COUNT(*), source FROM customers_staging GROUP BY source;
-- New records from file_history

SELECT DISTINCT reason_retired FROM customers_staging ORDER BY reason_retired;
-- Results:
-- Assignment
-- Mortgage
-- Power of Attorney
-- Revoked
-- Surrender
-- NULL
```

### After PRA Integration
```sql
SELECT COUNT(*), source FROM customers_staging GROUP BY source;
-- Records from file_history AND pra
```

### After PIC Integration
```sql
SELECT COUNT(*), source FROM customers_staging GROUP BY source;
-- Records from file_history AND pra AND pic
```

### After File Indexing Cleanup
```sql
SELECT COUNT(*), source FROM customers_staging GROUP BY source;
-- NO records from file_indexing
-- Only from file_history, pra, pic
```

---

## Timeline & Dependencies

```
Phase 1: DATABASE & SERVICES (COMPLETE) ✅
         ↓
         └─ Ready for all following phases

Phase 2: FILE HISTORY INTEGRATION (INDEPENDENT)
         └─ Can start anytime
         ├─ Creates test cases for Phase 5

Phase 3: PRA INTEGRATION (INDEPENDENT)
         └─ Can start after Phase 2 or in parallel

Phase 4: PIC INTEGRATION (INDEPENDENT)
         └─ Can start after Phase 2-3 or in parallel

Phase 5: FILE INDEXING CLEANUP (DEPENDENT)
         └─ MUST come after Phase 2-4
         └─ Allows safe removal without breaking staging

DEPLOYMENT:
Phase 1-2 → Test → Deploy
Phase 3-4 → Test → Deploy
Phase 5 → Test → Deploy
```

---

## Risk Assessment

### Low Risk ✅
- Adding `reason_retired` column (nullable, no constraint)
- Creating new staging_handler module (unused until integrated)
- Enhancing _process_staging_import() (backward compatible)

### Medium Risk ⚠️
- Updating File History upload/import (may need debug)
- Adding JS to parse staging data (check browser console)

### Higher Risk (Mitigated)
- Removing staging from File Indexing
  - MITIGATION: Only after all other features confirmed working
  - MITIGATION: Keep git branch for quick rollback
  - MITIGATION: Test File Indexing thoroughly before cleanup

---

