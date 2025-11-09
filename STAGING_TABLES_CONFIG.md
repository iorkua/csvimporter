# Staging Tables Configuration

## Overview
The CSV Importer now uses dedicated staging tables for each import flow instead of writing to shared `property_records` and `CofO` tables.

## Table Mappings

### Property Records Staging Tables
- **File History Import**: `file_history` table
- **PIC Import**: `pic` table
- **PRA Import**: `pra` table

### Certificate of Occupancy Staging Table
- **All Imports**: `CofO_staging` table (renamed from `CofO`)

## Code Changes

### Database Model (`app/models/database.py`)
- `CofO` class now maps to `CofO_staging` table instead of `CofO`

### Backend Persistence (`main.py`)

#### Configuration
- Added `STAGING_TABLES` dictionary mapping flow names to table names

#### Import Endpoints
1. **File History Import** (`/api/import-file-history/{session_id}`)
   - Writes records to `file_history` table
   - Writes CofO entries to `CofO_staging` table

2. **PIC Import** (`/api/import-pic/{session_id}`)
   - Writes records to `pic` table
   - Writes CofO entries to `CofO_staging` table

3. **PRA Import** (`/api/import-pra/{session_id}`)
   - Writes records to `pra` table

#### Clear Data Endpoints
1. **File History** (`/api/file-history/clear-data`)
   - Deletes from `file_history` table
   - Returns counts with keys: `file_history`, `CofO_staging`, `fileNumber`

2. **PIC** (`/api/pic/clear-data`)
   - Deletes from `pic` table
   - Returns counts with keys: `pic`, `CofO_staging`, `fileNumber`

3. **PRA** (`/api/pra/clear-data`)
   - Deletes from `pra` table
   - Returns counts with keys: `pra`, `fileNumber`

### Helper Functions

#### `_import_property_record(db, record, timestamp, *, allow_update=True, staging_table='property_records')`
- Now accepts `staging_table` parameter
- Supports: `'property_records'`, `'file_history'`, `'pic'`, `'pra'`
- Default: `'property_records'` for backward compatibility
- Validated to prevent SQL injection

## API Response Changes

### Clear Data Responses

**Before:**
```json
{
  "counts": {
    "property_records": 10,
    "CofO": 5,
    "fileNumber": 3
  }
}
```

**After (File History):**
```json
{
  "counts": {
    "file_history": 10,
    "CofO_staging": 5,
    "fileNumber": 3
  }
}
```

**After (PIC):**
```json
{
  "counts": {
    "pic": 10,
    "CofO_staging": 5,
    "fileNumber": 3
  }
}
```

**After (PRA):**
```json
{
  "counts": {
    "pra": 10,
    "fileNumber": 3
  }
}
```

## Database Schema Requirements

The following tables must exist with appropriate schemas:
- `file_history` - for File History import staging
- `pic` - for PIC import staging
- `pra` - for PRA import staging
- `CofO_staging` - for all import CofO staging (renamed from `CofO`)

All tables should have the same columns as the original `property_records` and `CofO` tables respectively.

## Migration Notes

1. **No Code Logic Changes**: All business logic remains identical
2. **Backward Compatible**: Default table parameter is `property_records`
3. **SQL Injection Protected**: Table names are validated against whitelist
4. **Session Cleanup**: Sessions are cleaned up after successful imports
