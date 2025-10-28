# CSV Importer - Implementation Guidelines & UI Specifications

## User Experience Flow

### 1. Upload → Preview → Edit → Import
The user workflow should be simple and intuitive:
1. **Upload CSV file**
2. **Preview all records** in a table format
3. **Edit directly in the table** by clicking any cell
4. **Handle file numbers that occur multiple times** 
5. **Fast import** with progress tracking

## Core UI Requirements

### Preview Table with Inline Editing
- **Main Table**: Display all CSV records in a responsive data table
- **Click-to-Edit**: User clicks any cell in the table to edit it directly
- **In-Table Editing**: No pop-ups or separate forms - edit right where the data is displayed
- **Auto-Save**: Changes are saved automatically when user moves to next cell
- **Visual Feedback**: Show which cells have been edited with subtle highlighting

### File Number Occurrence Detection
- **Multiple Occurrences**: Detect file numbers that appear more than twice
- **Visual Indicators**: Highlight these file numbers with warning colors (orange/yellow)
- **Count Badge**: Show how many times each file number appears (e.g., "×3")
- **Don't Call It "Duplicates"**: Use terms like "Multiple Occurrences" or "Repeated File Numbers"

### Action Buttons
- **Edit Button**: Per-row edit button (though clicking cells also works)
- **Delete Button**: Per-row delete button to remove records
- **Bulk Actions**: Select multiple rows for batch operations
- **Import Button**: Start the import process after review

### Fast Import Performance
- **Progress Bar**: Real-time progress indicator
- **Batch Processing**: Process records in chunks for speed
- **Background Processing**: Non-blocking import with status updates
- **ETA Display**: Show estimated time remaining

## Technical Implementation

### HTML Structure
```html
<div class="csv-preview-container">
    <!-- Stats Summary -->
    <div class="preview-stats">
        <div class="stat-card">
            <span class="number">1,234</span>
            <span class="label">Total Records</span>
        </div>
        <div class="stat-card warning">
            <span class="number">25</span>
            <span class="label">Multiple Occurrences</span>
        </div>
        <div class="stat-card success">
            <span class="number">1,209</span>
            <span class="label">Ready to Import</span>
        </div>
    </div>

    <!-- Action Toolbar -->
    <div class="preview-actions">
        <button class="btn btn-primary" id="importBtn">
            <i class="fas fa-upload"></i> Import Records
        </button>
        <button class="btn btn-secondary" id="selectAllBtn">
            <i class="fas fa-check-square"></i> Select All
        </button>
        <button class="btn btn-warning" id="bulkEditBtn" disabled>
            <i class="fas fa-edit"></i> Edit Selected
        </button>
        <button class="btn btn-danger" id="deleteSelectedBtn" disabled>
            <i class="fas fa-trash"></i> Delete Selected
        </button>
    </div>

    <!-- Main Data Table -->
    <div class="table-responsive">
        <table class="table table-striped table-hover" id="previewTable">
            <thead class="table-dark sticky-top">
                <tr>
                    <th width="50"><input type="checkbox" id="selectAll"></th>
                    <th width="60">#</th>
                    <th>File Number</th>
                    <th>Registry</th>
                    <th>Batch No</th>
                    <th>File Title</th>
                    <th>District</th>
                    <th>LGA</th>
                    <th>Plot Number</th>
                    <th width="120">Actions</th>
                </tr>
            </thead>
            <tbody id="tableBody">
                <!-- Dynamic content -->
            </tbody>
        </table>
    </div>

    <!-- Import Progress Modal -->
    <div class="modal fade" id="importProgressModal" tabindex="-1">
        <div class="modal-dialog modal-lg">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Importing Records</h5>
                </div>
                <div class="modal-body">
                    <div class="progress mb-3">
                        <div class="progress-bar progress-bar-striped progress-bar-animated" 
                             id="progressBar" style="width: 0%"></div>
                    </div>
                    <div class="d-flex justify-content-between">
                        <span id="progressText">Processing...</span>
                        <span id="progressETA">Calculating...</span>
                    </div>
                    <div class="mt-3">
                        <small class="text-muted">
                            <span id="processedCount">0</span> of <span id="totalCount">0</span> records processed
                        </small>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
```

### CSS Styling
```css
/* Table Styling */
.csv-preview-container {
    padding: 20px;
    background: #f8f9fa;
}

.preview-stats {
    display: flex;
    gap: 15px;
    margin-bottom: 20px;
}

.stat-card {
    background: white;
    border-radius: 8px;
    padding: 15px 20px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    text-align: center;
    min-width: 120px;
}

.stat-card .number {
    display: block;
    font-size: 24px;
    font-weight: bold;
    color: #495057;
}

.stat-card .label {
    display: block;
    font-size: 12px;
    color: #6c757d;
    text-transform: uppercase;
}

.stat-card.warning .number { color: #fd7e14; }
.stat-card.success .number { color: #198754; }

/* Editable Table */
#previewTable {
    background: white;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.editable-cell {
    position: relative;
    cursor: pointer;
    padding: 8px 12px;
}

.editable-cell:hover {
    background-color: #f8f9fa;
}

.editable-cell.editing {
    padding: 4px;
}

.editable-cell input {
    border: none;
    background: transparent;
    width: 100%;
    padding: 4px 8px;
    font-size: 14px;
}

.editable-cell input:focus {
    outline: 2px solid #0d6efd;
    border-radius: 4px;
}

/* Multiple Occurrence Indicators */
.multiple-occurrence {
    background-color: #fff3cd;
    border-left: 3px solid #fd7e14;
}

.occurrence-badge {
    background: #fd7e14;
    color: white;
    border-radius: 10px;
    padding: 2px 6px;
    font-size: 10px;
    margin-left: 5px;
}

/* Modified Cell Indicator */
.cell-modified {
    background-color: #d1ecf1;
    border-left: 3px solid #0dcaf0;
}

/* Action Buttons */
.row-actions .btn {
    margin-right: 5px;
    padding: 4px 8px;
    font-size: 12px;
}

/* Progress Indicators */
.progress {
    height: 25px;
}

.progress-bar {
    font-size: 14px;
    line-height: 25px;
}
```

### JavaScript Implementation
```javascript
class CSVPreviewTable {
    constructor() {
        this.data = [];
        this.editingCell = null;
        this.selectedRows = new Set();
        this.modifiedCells = new Map();
        this.multipleOccurrences = new Map();
        
        this.initializeTable();
        this.bindEvents();
    }

    // Load and display CSV data
    loadData(csvData) {
        this.data = csvData;
        this.analyzeFileNumbers();
        this.renderTable();
        this.updateStats();
    }

    // Analyze file numbers for multiple occurrences
    analyzeFileNumbers() {
        const fileNumberCounts = {};
        
        this.data.forEach((row, index) => {
            const fileNumber = row.file_number;
            if (!fileNumberCounts[fileNumber]) {
                fileNumberCounts[fileNumber] = [];
            }
            fileNumberCounts[fileNumber].push(index);
        });

        // Find file numbers that appear more than twice
        this.multipleOccurrences.clear();
        Object.entries(fileNumberCounts).forEach(([fileNumber, occurrences]) => {
            if (occurrences.length > 2) {
                this.multipleOccurrences.set(fileNumber, occurrences);
            }
        });
    }

    // Render the data table
    renderTable() {
        const tbody = document.getElementById('tableBody');
        tbody.innerHTML = '';

        this.data.forEach((row, index) => {
            const tr = document.createElement('tr');
            tr.dataset.rowIndex = index;

            // Checkbox
            tr.innerHTML = `
                <td>
                    <input type="checkbox" class="row-select" data-row="${index}">
                </td>
                <td>${index + 1}</td>
                ${this.renderEditableCell('file_number', row.file_number, index)}
                ${this.renderEditableCell('registry', row.registry, index)}
                ${this.renderEditableCell('batch_no', row.batch_no, index)}
                ${this.renderEditableCell('file_title', row.file_title, index)}
                ${this.renderEditableCell('district', row.district, index)}
                ${this.renderEditableCell('lga', row.lga, index)}
                ${this.renderEditableCell('plot_number', row.plot_number, index)}
                <td class="row-actions">
                    <button class="btn btn-sm btn-outline-primary edit-row" data-row="${index}">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger delete-row" data-row="${index}">
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            `;

            tbody.appendChild(tr);
        });
    }

    // Render editable cell with multiple occurrence detection
    renderEditableCell(field, value, rowIndex) {
        const isMultiple = field === 'file_number' && this.multipleOccurrences.has(value);
        const occurrenceCount = isMultiple ? this.multipleOccurrences.get(value).length : 0;
        const isModified = this.modifiedCells.has(`${rowIndex}-${field}`);

        let cellClass = 'editable-cell';
        if (isMultiple) cellClass += ' multiple-occurrence';
        if (isModified) cellClass += ' cell-modified';

        const occurrenceBadge = isMultiple ? 
            `<span class="occurrence-badge">×${occurrenceCount}</span>` : '';

        return `
            <td class="${cellClass}" data-field="${field}" data-row="${rowIndex}">
                <span class="cell-value">${value || ''}</span>
                ${occurrenceBadge}
            </td>
        `;
    }

    // Handle cell click for inline editing
    handleCellClick(cell) {
        if (this.editingCell) {
            this.saveCurrentEdit();
        }

        const field = cell.dataset.field;
        const rowIndex = cell.dataset.row;
        const currentValue = cell.querySelector('.cell-value').textContent;

        // Create input element
        const input = document.createElement('input');
        input.type = 'text';
        input.value = currentValue;
        input.className = 'form-control form-control-sm';

        // Replace cell content
        cell.innerHTML = '';
        cell.appendChild(input);
        cell.classList.add('editing');

        // Focus and select
        input.focus();
        input.select();

        // Store editing state
        this.editingCell = {
            cell: cell,
            field: field,
            rowIndex: parseInt(rowIndex),
            originalValue: currentValue,
            input: input
        };

        // Handle input events
        input.addEventListener('blur', () => this.saveCurrentEdit());
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                this.saveCurrentEdit();
            } else if (e.key === 'Escape') {
                this.cancelCurrentEdit();
            }
        });
    }

    // Save current cell edit
    saveCurrentEdit() {
        if (!this.editingCell) return;

        const { cell, field, rowIndex, originalValue, input } = this.editingCell;
        const newValue = input.value.trim();

        // Update data
        this.data[rowIndex][field] = newValue;

        // Track modification
        if (newValue !== originalValue) {
            this.modifiedCells.set(`${rowIndex}-${field}`, {
                original: originalValue,
                new: newValue
            });
        }

        // Re-analyze file numbers if changed
        if (field === 'file_number') {
            this.analyzeFileNumbers();
        }

        // Restore cell display
        this.restoreCellDisplay(cell, field, rowIndex);
        this.editingCell = null;
    }

    // Cancel current edit
    cancelCurrentEdit() {
        if (!this.editingCell) return;

        const { cell, field, rowIndex } = this.editingCell;
        this.restoreCellDisplay(cell, field, rowIndex);
        this.editingCell = null;
    }

    // Restore cell to display mode
    restoreCellDisplay(cell, field, rowIndex) {
        const value = this.data[rowIndex][field];
        cell.innerHTML = this.renderEditableCell(field, value, rowIndex).match(/>([^<]*)</)[1];
        cell.classList.remove('editing');
    }

    // Delete selected rows
    deleteSelectedRows() {
        const selected = Array.from(this.selectedRows).sort((a, b) => b - a);
        selected.forEach(index => {
            this.data.splice(index, 1);
        });
        
        this.selectedRows.clear();
        this.analyzeFileNumbers();
        this.renderTable();
        this.updateStats();
    }

    // Start import process
    async startImport() {
        const modal = new bootstrap.Modal(document.getElementById('importProgressModal'));
        modal.show();

        const progressBar = document.getElementById('progressBar');
        const progressText = document.getElementById('progressText');
        const progressETA = document.getElementById('progressETA');
        const processedCount = document.getElementById('processedCount');
        const totalCount = document.getElementById('totalCount');

        totalCount.textContent = this.data.length;
        
        try {
            // Process in batches
            const batchSize = 100;
            let processed = 0;
            const startTime = Date.now();

            for (let i = 0; i < this.data.length; i += batchSize) {
                const batch = this.data.slice(i, i + batchSize);
                
                // Send batch to server
                await this.processBatch(batch, i);
                
                processed += batch.length;
                const progress = Math.round((processed / this.data.length) * 100);
                
                // Update progress
                progressBar.style.width = progress + '%';
                progressBar.textContent = progress + '%';
                processedCount.textContent = processed;
                
                // Calculate ETA
                const elapsed = Date.now() - startTime;
                const rate = processed / elapsed;
                const remaining = (this.data.length - processed) / rate;
                const eta = Math.round(remaining / 1000);
                
                progressETA.textContent = eta > 0 ? `ETA: ${eta}s` : 'Almost done...';
                progressText.textContent = `Processing batch ${Math.floor(i / batchSize) + 1}...`;
                
                // Small delay to show progress
                await new Promise(resolve => setTimeout(resolve, 100));
            }

            progressText.textContent = 'Import completed successfully!';
            setTimeout(() => modal.hide(), 2000);
            
        } catch (error) {
            progressText.textContent = 'Import failed: ' + error.message;
            progressBar.classList.add('bg-danger');
        }
    }

    // Process a batch of records
    async processBatch(batch, startIndex) {
        const response = await fetch('/api/import-batch', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                records: batch,
                start_index: startIndex
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        return await response.json();
    }

    // Update statistics display
    updateStats() {
        document.querySelector('.stat-card .number').textContent = this.data.length;
        document.querySelector('.stat-card.warning .number').textContent = this.multipleOccurrences.size;
        document.querySelector('.stat-card.success .number').textContent = 
            this.data.length - this.multipleOccurrences.size;
    }

    // Bind event listeners
    bindEvents() {
        // Cell click for editing
        document.addEventListener('click', (e) => {
            if (e.target.closest('.editable-cell') && !e.target.closest('.editing')) {
                this.handleCellClick(e.target.closest('.editable-cell'));
            }
        });

        // Row selection
        document.addEventListener('change', (e) => {
            if (e.target.classList.contains('row-select')) {
                const rowIndex = parseInt(e.target.dataset.row);
                if (e.target.checked) {
                    this.selectedRows.add(rowIndex);
                } else {
                    this.selectedRows.delete(rowIndex);
                }
                this.updateActionButtons();
            }
        });

        // Action buttons
        document.getElementById('importBtn').addEventListener('click', () => this.startImport());
        document.getElementById('deleteSelectedBtn').addEventListener('click', () => this.deleteSelectedRows());
        document.getElementById('selectAllBtn').addEventListener('click', () => this.selectAll());

        // Row action buttons
        document.addEventListener('click', (e) => {
            if (e.target.closest('.delete-row')) {
                const rowIndex = parseInt(e.target.closest('.delete-row').dataset.row);
                this.deleteRow(rowIndex);
            }
        });
    }

    // Initialize table
    initializeTable() {
        // Set up initial state
        this.updateActionButtons();
    }

    // Update action button states
    updateActionButtons() {
        const hasSelection = this.selectedRows.size > 0;
        document.getElementById('bulkEditBtn').disabled = !hasSelection;
        document.getElementById('deleteSelectedBtn').disabled = !hasSelection;
    }

    // Select all rows
    selectAll() {
        const checkboxes = document.querySelectorAll('.row-select');
        const allSelected = Array.from(checkboxes).every(cb => cb.checked);
        
        checkboxes.forEach((cb, index) => {
            cb.checked = !allSelected;
            if (cb.checked) {
                this.selectedRows.add(index);
            } else {
                this.selectedRows.delete(index);
            }
        });
        
        this.updateActionButtons();
    }

    // Delete single row
    deleteRow(rowIndex) {
        if (confirm('Are you sure you want to delete this record?')) {
            this.data.splice(rowIndex, 1);
            this.analyzeFileNumbers();
            this.renderTable();
            this.updateStats();
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.csvTable = new CSVPreviewTable();
});
```

## Key Features Summary

### ✅ **Preview Before Import**
- User sees ALL data in a table before importing
- Clear statistics showing total records and potential issues

### ✅ **Click-to-Edit Anywhere**
- Click any cell in the table to edit it directly
- No pop-ups or separate forms
- Auto-save when moving to next cell

### ✅ **Multiple Occurrence Detection** 
- File numbers appearing more than twice are highlighted
- Visual badges show occurrence count (×3, ×4, etc.)
- Uses user-friendly terms, not "duplicates"

### ✅ **Edit & Delete Actions**
- Individual row edit/delete buttons
- Bulk operations for selected rows
- Confirmation dialogs for safety

### ✅ **Fast Import Processing**
- Batch processing for large datasets
- Real-time progress bar with ETA
- Background processing with visual feedback

This implementation focuses exactly on your vision: simple preview table, click-to-edit functionality, multiple occurrence detection (not called duplicates), and fast import performance.
