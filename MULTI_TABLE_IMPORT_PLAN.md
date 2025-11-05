# Multi-Table Import Plan# Multi-Table Import Plan



## Overview## Overview

This document outlines the strategy for importing CSV data from Excel files into multiple database tables within the MLS system, handling file indexing, Certificate of Occupancy records, file numbers, and grouping table updates.This document outlines the strategy for importing CSV data into multiple database tables within the MLS (Multiple Listing Service) system.



## CSV Structure (Excel Headers)## Database Schema Structure

```

SN, Registry, Batch No, File Number, File Title, Landuse, Plot Number, ### Primary Table: `file_indexings`

LPKN No, TP No, District, LGA, CofO Date, Serial No, Page No, Vol No, - **Purpose**: Main file tracking and indexing information

Deeds Time, Deeds Date- **Key Fields**:

```  - `file_number` (unique identifier)

  - `registry`, `batch_no`, `file_title`

## Target Database Tables  - `land_use_type`, `plot_number`, `lpkn_no`, `tp_no`

  - `district`, `lga`, `location`

### 1. `file_indexings` (Primary File Records)  - `shelf_location`, `batch_id`, `tracking_id`

**Purpose**: Main file tracking and indexing information  - Status and audit fields



**Field Mappings**:### Supporting Table: `Rack_Shelf_Labels`

- `registry` ← `Registry`- **Purpose**: Physical storage location management

- `batch_no` ← `Batch No`- **Key Fields**:

- `file_number` ← `File Number`  - `rack`, `shelf`, `full_label`

- `file_title` ← `File Title` (applicant name)  - `is_used`, `reserved_by`, `reserved_at`

- `land_use_type` ← `Landuse`

- `plot_number` ← `Plot Number`### Batch Management: `fileindexing_batch`

- `district` ← `District`- **Purpose**: Track import batches and shelf allocation

- `lga` ← `LGA`- **Key Fields**:

- `location` ← `District, LGA` (fallback: use single value if one missing, both if available)  - `batch_number`, `start_shelf_id`, `end_shelf_id`

- `tp_no` ← `TP No`  - `shelf_count`, `used_shelves`, `is_full`

- `lpkn_no` ← `LPKN No`  - `shelf_label_id`, `full_label`

- `serial_no` ← `Serial No`

- `shelf_location` ← direct from CSV input (grouping no longer drives shelf assignment)## Import Strategy

- `shelf_label_id` ← not used in current workflow

- `tracking_id` ← shared tracking ID format: `TRK-XXXXXXXX-XXXXX`### Phase 1: CSV Validation and Parsing

- `status` ← `"Indexed"` (default)1. **File Upload Validation**

- `created_by` ← `"MDC Import"`   - Check file format (.csv)

- `has_cofo` ← boolean (true if CofO data detected)   - Validate file size limits

   - Verify required columns exist

### 2. `CofO` (Certificate of Occupancy - Conditional)

**Purpose**: Certificate of Occupancy records (only if CofO data exists)2. **Data Quality Checks**

 

**CofO Detection Rule**: Record created if ANY of these fields have data:   - Required field validation

- `CofO Date`, `Serial No`, `Page No`, `Vol No`, `Deeds Time`, `Deeds Date`   - Data format validation (dates, numbers)

   - Reference integrity checks

**Field Mappings**:

 

- `mlsFNo` ← `File Number`   - Column mapping from CSV to database fields

- `transaction_date` ← `Deeds Date`   - Data transformation rules

- `transaction_time` ← `Deeds Time`   - Default value assignment

- `serialNo` ← `Serial No`

- `pageNo` ← `Page No`### Phase 2: Batch Processing

- `volumeNo` ← `Vol No`1. **Batch Creation**

- `regNo` ← `Serial No/Page No/Vol No` (combination)   - Generate unique batch number

- `property_description` ← `District, LGA` (same fallback logic)   - Calculate shelf requirements

- `location` ← `District, LGA` (same fallback logic)   - Reserve shelf labels from `Rack_Shelf_Labels`

- `plot_no` ← `Plot Number`

- `lgsaOrCity` ← `LGA`2. **Shelf Allocation Logic**

- `land_use` ← `Landuse`   ```python

- `instrument_type` ← `"Certificate of Occupancy"`   # Pseudocode for shelf allocation

- `transaction_type` ← `"Certificate of Occupancy"`   def allocate_shelves(record_count):

- `cofo_type` ← `"Legacy CofO"`       available_shelves = get_available_shelves()

- `Grantor` ← `"Kano State Government"` (always for CofO)       required_shelves = calculate_shelf_needs(record_count)

- `Grantee` ← `File Title` (applicant name)       

- `created_by` ← `"MDC Import"`       if available_shelves >= required_shelves:

           batch = create_batch(required_shelves)

### 3. `fileNumber` (File Tracking)           reserve_shelves(batch.id, required_shelves)

**Purpose**: File number tracking and reference system           return batch

       else:

**Field Mappings**:           raise InsufficientShelfSpace()
 

- `mlsfNo` ← `File Number`

- `FileName` ← `File Title`### Phase 3: Multi-Table Import

- `plot_no` ← `Plot Number`1. **Transaction Management**

- `tp_no` ← `TP No`   - Use database transactions for data integrity

- `location` ← `District, LGA` (fallback logic)   - Rollback on any failure

- `tracking_id` ← shared tracking ID   - Atomic batch operations

- `type` ← `"Indexing"`

- `SOURCE` ← `"Indexing"`2. **Import Sequence**

- `created_by` ← `"MDC Import"`   ```

   BEGIN TRANSACTION

### 4. `grouping` (Update Existing Records)   1. Insert/Update batch record in `fileindexing_batch`

**Purpose**: Match incoming file numbers with pre-existing awaiting records   2. Update shelf reservations in `Rack_Shelf_Labels`

   3. Insert records into `file_indexings`

**Critical Business Rule**:    4. Update batch statistics

- `awaiting_fileno` already exists in table with shelf assignments   COMMIT TRANSACTION

- Incoming `File Number` must match EXACTLY with existing `awaiting_fileno`   ```

- Shelf location remains whatever the CSV provides; grouping is used for mapping only

3. **Error Handling**

**Example Process**:   - Capture and log all errors

```   - Provide detailed error reports

Existing in grouping table:   - Support partial imports with error logs

awaiting_fileno = "RES-1981-1", grouping only tracks awaiting_fileno reference

## Data Flow Architecture

CSV Import:

File Number = "RES-1981-1" (EXACT MATCH required)### Input Processing

```

Update Process:CSV Upload → Validation → Column Mapping → Data Transformation

SET indexing_mls_fileno = "RES-1981-1"```

SET indexing_mapping = 1

Shelf rack values are no longer extracted during import### Batch Management

``````

Record Count → Shelf Calculation → Batch Creation → Shelf Reservation

**Fields Updated on Match**:```

- `indexing_mls_fileno` ← `File Number` (fill in the match)

- `mdc_batch_no` ← `Batch No`### Database Operations

- `indexing_mapping` ← `1` (indicates successful mapping)```

- `date_indexed` ← `datetime.utcnow()`Begin Transaction → Batch Insert → Shelf Update → File Records → Commit

- `indexed_by` ← `"MDC Import"````



**File Number Exclusions**: Skip grouping table lookup for patterns:## Quality Control Features

- Contains `(TEMP)` - e.g., "CON-COM-1985-80 (TEMP)"

- Contains ` T,` - e.g., "COM-1985-80 T, RES-1992-4131"### Pre-Import Validation

- Contains `AND EXTENSION` - e.g., "RES-1992-4131 AND EXTENSION"- **Duplicate Detection**: Check existing file_numbers

- **Data Completeness**: Ensure required fields are populated

## Shared Business Logic- **Format Validation**: Verify data types and formats

- **Business Rules**: Apply domain-specific validation

### Tracking ID Generation

**Format**: `TRK-XXXXXXXX-XXXXX` (8 chars - 5 chars)### Post-Import Verification

- Generated once per CSV import batch- **Record Count Verification**: Confirm all records imported

- Shared across all table inserts for the same record- **Data Integrity Checks**: Verify foreign key relationships

- Used for tracking related records across tables- **Shelf Allocation Verification**: Ensure proper shelf assignments

- **Audit Trail**: Log all import activities

### Location Field Logic

**Rule**: Combine `District, LGA` with fallback strategy:## Performance Considerations

- If both available: `"District Name, LGA Name"`

- If District missing: `"LGA Name"`### Batch Size Optimization

- If LGA missing: `"District Name"`- Process records in configurable batch sizes (default: 1000)

- If both missing: `NULL`- Use bulk insert operations where possible

- Implement progress tracking and reporting

### CofO Detection Algorithm

```python### Database Optimization

def has_cofo_data(row):- Use appropriate indexes on lookup fields

    cofo_fields = ['CofO Date', 'Serial No', 'Page No', 'Vol No', 'Deeds Time', 'Deeds Date']- Implement connection pooling

    return any(row.get(field) and str(row.get(field)).strip() for field in cofo_fields)- Consider read replicas for reporting

```

### Memory Management

## Data Flow Architecture- Stream large CSV files instead of loading entirely

- Use generators for record processing

### Single CSV Row Processing- Implement cleanup for temporary data

```

CSV Row Input## Error Recovery and Monitoring

    ↓

1. Validate and clean data### Error Categories

    ↓1. **Validation Errors**: Data quality issues

2. Generate shared tracking_id2. **System Errors**: Database connectivity, disk space

    ↓3. **Business Logic Errors**: Shelf allocation, duplicate handling

3. Check grouping table for exact file number match

    ↓### Recovery Strategies

4. Insert file_indexings record (with shelf info if matched)- **Validation Errors**: Provide detailed reports, allow correction

    ↓- **System Errors**: Retry mechanisms, fallback procedures

5. Insert fileNumber record- **Business Logic Errors**: Manual intervention workflows

    ↓

6. IF CofO data detected → Insert CofO record### Monitoring and Alerting

    ↓- Import success/failure rates

7. IF grouping match found → Update grouping record- Processing time metrics

    ↓- System resource utilization

Complete- Data quality trends

```

## Implementation Phases

### Multi-Table Insert Strategy

**Always Created**:### Phase 1: Core Import Engine

- `file_indexings` record- Basic CSV processing

- `fileNumber` record- Single table import to `file_indexings`

- Error handling and validation

**Conditionally Created**:

- `CofO` record (only if CofO data exists)### Phase 2: Batch Management

- Integration with `fileindexing_batch`

**Conditionally Updated**:- Shelf allocation logic

- `grouping` record (only if exact file number match found)- Transaction management



## Staging Strategy### Phase 3: Advanced Features

- Shelf label management

### Staging Tables Approach- Complex validation rules

Before importing to production tables, create temporary staging tables:- Performance optimizations



1. **stage_file_indexings**: Validate all file indexing data### Phase 4: Monitoring and Reporting

2. **stage_cofo**: Validate CofO records (conditional)- Dashboard for import status

3. **stage_filenumber**: Validate file number records- Data quality reports

4. **stage_grouping_updates**: Preview grouping table matches- Performance analytics



### Staging Benefits## Configuration Management

- **Data Validation**: Check all data integrity before production insert

- **Grouping Preview**: Show which file numbers will match existing awaiting records### Environment Variables

- **User Review**: Allow approval/rejection before final commit```

- **Rollback Safety**: Easy cleanup if issues found# Database Configuration

- **Batch Management**: Handle large imports in manageable chunksDB_SQLSRV_HOST=server_name

DB_SQLSRV_DATABASE=database_name

### Staging WorkflowDB_SQLSRV_USERNAME=username

```DB_SQLSRV_PASSWORD=password

1. Upload CSV → Load to staging tables

2. Auto-validate → Mark validation status per record# Import Configuration

3. Preview results → Show user validation summaryMAX_BATCH_SIZE=1000

4. User approval → Promote valid records to productionSHELF_CAPACITY=100

5. Cleanup → Drop staging tables after completionIMPORT_TIMEOUT=3600

``````



## Risk Mitigation### Configurable Parameters

- Batch processing size

### Data Quality Checks- Validation rules

- **Required Field Validation**: Ensure File Number, Registry, etc. are present- Shelf allocation algorithms

- **File Number Pattern Validation**: Exclude problematic patterns (TEMP, T, AND EXTENSION)- Error tolerance levels

- **Exact Match Verification**: Validate grouping table matches before update

- **Duplicate Detection**: Check for duplicate File Numbers within same import batch## Testing Strategy



### Error Handling### Unit Testing

- **Partial Import Support**: Continue processing valid records if some fail- Individual function validation

- **Detailed Error Logging**: Log specific validation failures per record- Mock database operations

- **Transaction Safety**: Use database transactions for multi-table consistency- Error condition testing

- **Graceful Degradation**: Handle missing grouping matches without failing entire import

### Integration Testing

### Performance Considerations- End-to-end import workflows

- **Batch Processing**: Process large CSV files in configurable batch sizes- Database transaction testing

- **Index Utilization**: Ensure proper indexing on grouping.awaiting_fileno for fast lookups- Multi-table consistency checks

- **Memory Management**: Stream large CSV files instead of loading entirely into memory

- **Progress Tracking**: Provide real-time feedback for long-running imports### Performance Testing

- Large file processing

## Success Criteria- Concurrent import handling

- Resource utilization monitoring

### Data Integrity Validation

- All file_indexings records have required fields populated## Security Considerations

- CofO records only created when appropriate data exists

- Grouping table updates only occur for exact matches### Data Protection

- Shared tracking_id maintains consistency across tables- Input sanitization

- SQL injection prevention

### Performance Targets- File upload security

- Process 1000 records per minute minimum

- Complete validation within 30 seconds for typical CSV files### Access Control

- Provide progress updates every 100 records processed- User authentication

- Support CSV files up to 50MB in size- Role-based permissions

- Audit logging

### User Experience Requirements

- Clear validation feedback before final import### Data Integrity

- Detailed preview of records to be created/updated- Transaction isolation

- Easy identification of grouping table matches/misses- Backup and recovery procedures

- Simple approval workflow for batch processing- Data validation checkpoints