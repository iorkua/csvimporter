// File Indexing JavaScript
class FileIndexingManager {
    constructor() {
        this.currentSessionId = null;
        this.currentData = [];
        this.multipleOccurrences = {};
        this.groupingPreview = {
            rows: [],
            summary: { matched: 0, skipped: 0, missing: 0 }
        };
        this.selectedRows = new Set();
        this.pageSizeOptions = [10, 25, 50, 100];
        this.pageSize = 25;
        this.currentPage = 1;
        
        this.initializeEventListeners();
        this.initializePaginationControls();
        this.renderGroupingPreview();
        this.checkForSession();
    }
    
    initializeEventListeners() {
        // File upload events
        const csvFileInput = document.getElementById('csvFile');
        const uploadBtn = document.getElementById('uploadBtn');
        
        csvFileInput?.addEventListener('change', () => {
            uploadBtn.disabled = !csvFileInput.files.length;
        });
        
        uploadBtn?.addEventListener('click', () => this.uploadFile());
        
        // Import button
        document.getElementById('importBtn')?.addEventListener('click', () => this.startImport());
        
        // Select all functionality
        document.getElementById('selectAllBtn')?.addEventListener('click', () => this.toggleSelectAll());
        document.getElementById('selectAllCheckbox')?.addEventListener('change', (e) => this.handleSelectAllCheckbox(e));

        // Pagination controls
        document.getElementById('pageSizeSelect')?.addEventListener('change', (e) => {
            const value = parseInt(e.target.value, 10);
            if (!Number.isNaN(value)) {
                this.pageSize = value;
                this.currentPage = 1;
                this.renderPreviewTable();
            }
        });

        document.getElementById('paginationControls')?.addEventListener('click', (e) => {
            const button = e.target.closest('[data-page]');
            if (!button) {
                return;
            }
            e.preventDefault();
            const targetPage = parseInt(button.dataset.page, 10);
            if (!Number.isNaN(targetPage)) {
                this.goToPage(targetPage);
            }
        });
    }

    initializePaginationControls() {
        const pageSizeSelect = document.getElementById('pageSizeSelect');
        if (pageSizeSelect) {
            pageSizeSelect.innerHTML = this.pageSizeOptions
                .map(size => `<option value="${size}" ${size === this.pageSize ? 'selected' : ''}>${size}</option>`)
                .join('');
        }

        this.renderPaginationControls();
    }
    
    checkForSession() {
        // Check if there's a session_id in URL parameters
        const urlParams = new URLSearchParams(window.location.search);
        const sessionId = urlParams.get('session_id');
        
        if (sessionId) {
            this.currentSessionId = sessionId;
            this.loadPreviewData();
        }
    }
    
    async uploadFile() {
        const fileInput = document.getElementById('csvFile');
        const file = fileInput.files[0];
        
        if (!file) {
            this.showNotification('Please select a CSV file', 'warning');
            return;
        }
        
        // Show progress
        this.showSection('progress-section');
        this.hideSection('upload-section');
        
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            const response = await fetch('/api/upload-csv', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Upload failed');
            }
            
            const result = await response.json();
            this.currentSessionId = result.session_id;
            
            // Update URL to include session_id
            const newUrl = new URL(window.location);
            newUrl.searchParams.set('session_id', this.currentSessionId);
            window.history.pushState({}, '', newUrl);
            
            // Load preview data
            await this.loadPreviewData();
            
            this.showNotification(`File uploaded successfully! ${result.total_records} records found.`, 'success');
            
        } catch (error) {
            console.error('Upload error:', error);
            this.showNotification(`Upload failed: ${error.message}`, 'error');
            this.showSection('upload-section');
        } finally {
            this.hideSection('progress-section');
        }
    }
    
    async loadPreviewData() {
        if (!this.currentSessionId) return;
        
        try {
            const response = await fetch(`/api/preview-data/${this.currentSessionId}`);
            if (!response.ok) {
                throw new Error('Failed to load preview data');
            }
            
            const result = await response.json();
            this.currentData = result.data;
            this.multipleOccurrences = result.multiple_occurrences;
            this.groupingPreview = result.grouping_preview || { rows: [], summary: {} };
            this.selectedRows.clear();
            this.currentPage = 1;
            
            this.updateStatistics(result);
            this.renderPreviewTable();
            this.renderGroupingPreview();
            this.showSection('preview-section');
            
        } catch (error) {
            console.error('Preview data error:', error);
            this.showNotification('Failed to load preview data', 'error');
        }
    }
    
    updateStatistics(data) {
        document.getElementById('total-records').textContent = data.total_records || 0;
        document.getElementById('multiple-occurrences').textContent = Object.keys(data.multiple_occurrences || {}).length;
        document.getElementById('valid-records').textContent = (data.total_records || 0) - Object.keys(data.multiple_occurrences || {}).length;
    }
    
    renderGroupingPreview() {
        const tbody = document.getElementById('groupingPreviewBody');
        const matchedEl = document.getElementById('groupingMatchedCount');
        const skippedEl = document.getElementById('groupingSkippedCount');
        const missingEl = document.getElementById('groupingMissingCount');

        if (!tbody || !matchedEl || !skippedEl || !missingEl) {
            return;
        }

        const summary = this.groupingPreview?.summary || {};
        matchedEl.textContent = summary.matched ?? 0;
        skippedEl.textContent = summary.skipped ?? 0;
        missingEl.textContent = summary.missing ?? 0;

        const rows = Array.isArray(this.groupingPreview?.rows) ? this.groupingPreview.rows : [];

        if (!rows.length) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center text-muted py-4">
                        No grouping matches evaluated yet. Upload a file to preview automatic shelf resolution.
                    </td>
                </tr>`;
            return;
        }

        tbody.innerHTML = '';

        rows.forEach(row => {
            const status = row.status || 'unknown';
            const tr = document.createElement('tr');
            this.applyGroupingStatusStyle(tr, status);

            tr.innerHTML = `
                <td>${row.file_number || ''}</td>
                <td>${this.getGroupingStatusBadge(status)}</td>
                <td>${row.shelf_rack || ''}</td>
                <td>${row.grouping_registry || ''}</td>
                <td>${row.grouping_number || ''}</td>
                <td>${row.reason || row.notes || ''}</td>
            `;

            tbody.appendChild(tr);
        });
    }

    applyGroupingStatusStyle(rowElement, status) {
        const statusClassMap = {
            matched: 'table-success',
            skipped: 'table-warning',
            missing: 'table-danger'
        };

        const cssClass = statusClassMap[status];
        if (cssClass) {
            rowElement.classList.add(cssClass);
        }
    }

    getGroupingStatusBadge(status) {
        const statusConfig = {
            matched: { label: 'Matched', theme: 'success' },
            skipped: { label: 'Skipped', theme: 'warning' },
            missing: { label: 'Missing', theme: 'danger' }
        };

        const config = statusConfig[status] || { label: status, theme: 'secondary' };
        return `<span class="badge bg-${config.theme}">${config.label}</span>`;
    }

    renderPreviewTable() {
        const tbody = document.getElementById('previewTableBody');
        if (!tbody) return;
        
        const totalRecords = this.currentData.length;
        const totalPages = this.getTotalPages();

        const selectAllCheckbox = document.getElementById('selectAllCheckbox');

        if (totalRecords === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="18" class="text-center text-muted py-4">
                        No records to display. Upload a file to see preview data.
                    </td>
                </tr>`;
            if (selectAllCheckbox) {
                selectAllCheckbox.checked = false;
                selectAllCheckbox.indeterminate = false;
                selectAllCheckbox.disabled = true;
            }
            this.renderPaginationControls();
            return;
        }

        if (selectAllCheckbox && selectAllCheckbox.disabled) {
            selectAllCheckbox.disabled = false;
        }

        if (this.currentPage > totalPages) {
            this.currentPage = totalPages;
        }

        const { startIndex, endIndex } = this.getCurrentPageRange();
        const pageData = this.currentData.slice(startIndex, endIndex);
        
        tbody.innerHTML = '';
        
        pageData.forEach((record, pageIndex) => {
            const actualIndex = startIndex + pageIndex;
            const displayIndex = actualIndex + 1;
            const row = this.createTableRow(record, displayIndex, actualIndex);
            tbody.appendChild(row);

            const checkbox = row.querySelector('.row-select');
            if (checkbox) {
                checkbox.checked = this.selectedRows.has(actualIndex);
            }
        });
        
        this.updateSelectAllState();
        this.renderPaginationControls();
    }
    
    createTableRow(record, displayIndex, actualIndex) {
        const tr = document.createElement('tr');
        tr.dataset.index = actualIndex;
        
        // Check if this file number has multiple occurrences
        const hasMultipleOccurrences = this.multipleOccurrences[record.file_number];
        if (hasMultipleOccurrences) {
            tr.classList.add('table-warning');
        }
        
        tr.innerHTML = `
            <td>
                <input type="checkbox" class="row-select" data-index="${actualIndex}">
            </td>
            <td>${displayIndex}</td>
            <td class="editable-cell" data-field="file_number" data-index="${actualIndex}">
                ${record.file_number || ''}
                ${hasMultipleOccurrences ? `<span class="badge bg-warning ms-1">×${hasMultipleOccurrences.count}</span>` : ''}
            </td>
            <td class="editable-cell" data-field="registry" data-index="${actualIndex}">${record.registry || ''}</td>
            <td class="editable-cell" data-field="batch_no" data-index="${actualIndex}">${record.batch_no || ''}</td>
            <td class="editable-cell" data-field="file_title" data-index="${actualIndex}">${record.file_title || ''}</td>
            <td class="editable-cell" data-field="district" data-index="${actualIndex}">${record.district || ''}</td>
            <td class="editable-cell" data-field="lga" data-index="${actualIndex}">${record.lga || ''}</td>
            <td class="editable-cell" data-field="plot_number" data-index="${actualIndex}">${record.plot_number || ''}</td>
            <td class="editable-cell" data-field="tp_no" data-index="${actualIndex}">${record.tp_no || ''}</td>
            <td class="editable-cell" data-field="lpkn_no" data-index="${actualIndex}">${record.lpkn_no || ''}</td>
            <td class="editable-cell" data-field="cofo_date" data-index="${actualIndex}">${record.cofo_date || ''}</td>
            <td class="editable-cell" data-field="serial_no" data-index="${actualIndex}">${record.serial_no || ''}</td>
            <td class="editable-cell" data-field="page_no" data-index="${actualIndex}">${record.page_no || ''}</td>
            <td class="editable-cell" data-field="vol_no" data-index="${actualIndex}">${record.vol_no || ''}</td>
            <td class="editable-cell" data-field="deeds_time" data-index="${actualIndex}">${record.deeds_time || ''}</td>
            <td class="editable-cell" data-field="deeds_date" data-index="${actualIndex}">${record.deeds_date || ''}</td>
            <td class="actions-column">
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary edit-row" data-index="${actualIndex}" title="Edit Row">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-outline-danger delete-row" data-index="${actualIndex}" title="Delete Row">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </td>
        `;
        
        // Add click-to-edit functionality
        tr.querySelectorAll('.editable-cell').forEach(cell => {
            cell.addEventListener('click', () => this.editCell(cell));
        });
        
    // Add row action listeners
    tr.querySelector('.delete-row')?.addEventListener('click', () => this.deleteRow(actualIndex));
    tr.querySelector('.row-select')?.addEventListener('change', (e) => this.handleRowSelect(e, actualIndex));
        
        return tr;
    }
    
    editCell(cell) {
        if (cell.querySelector('input')) return; // Already editing
        
        const currentValue = cell.textContent.trim();
        const field = cell.dataset.field;
        const index = parseInt(cell.dataset.index);
        
        // Create input element
        const input = document.createElement('input');
        input.type = 'text';
        input.value = currentValue;
        input.className = 'form-control form-control-sm';
        
        // Replace cell content
        cell.innerHTML = '';
        cell.appendChild(input);
        
        // Focus and select
        input.focus();
        input.select();
        
        // Handle save/cancel
        const saveEdit = () => {
            const newValue = input.value.trim();
            this.currentData[index][field] = newValue;
            cell.textContent = newValue;
            cell.classList.add('table-info'); // Mark as edited
        };
        
        const cancelEdit = () => {
            cell.textContent = currentValue;
        };
        
        input.addEventListener('blur', saveEdit);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                saveEdit();
            } else if (e.key === 'Escape') {
                cancelEdit();
            }
        });
    }
    
    deleteRow(index) {
        if (confirm('Are you sure you want to delete this record?')) {
            this.currentData.splice(index, 1);

            // Rebuild selected rows set adjusting indices
            const updatedSelectedRows = new Set();
            this.selectedRows.forEach(selectedIndex => {
                if (selectedIndex === index) {
                    return;
                }
                const adjustedIndex = selectedIndex > index ? selectedIndex - 1 : selectedIndex;
                if (adjustedIndex >= 0 && adjustedIndex < this.currentData.length) {
                    updatedSelectedRows.add(adjustedIndex);
                }
            });
            this.selectedRows = updatedSelectedRows;

            const totalPages = this.getTotalPages();
            if (this.currentPage > totalPages) {
                this.currentPage = totalPages;
            }

            this.renderPreviewTable();
            this.updateStatistics({ 
                total_records: this.currentData.length,
                multiple_occurrences: this.multipleOccurrences 
            });
        }
    }
    
    handleRowSelect(event, index) {
        if (event.target.checked) {
            this.selectedRows.add(index);
        } else {
            this.selectedRows.delete(index);
        }
        
        this.updateSelectAllState();
    }
    
    toggleSelectAll() {
        if (this.currentData.length === 0) {
            return;
        }

        const allSelected = this.selectedRows.size === this.currentData.length;
        
        if (allSelected) {
            // Deselect all
            this.selectedRows.clear();
            document.querySelectorAll('.row-select').forEach(cb => cb.checked = false);
        } else {
            // Select all
            this.currentData.forEach((_, index) => this.selectedRows.add(index));
            document.querySelectorAll('.row-select').forEach(cb => cb.checked = true);
        }
        
        this.updateSelectAllState();
    }
    
    handleSelectAllCheckbox(event) {
        const checked = event.target.checked;
        
        const { startIndex, endIndex } = this.getCurrentPageRange();

        document.querySelectorAll('.row-select').forEach(cb => {
            cb.checked = checked;
        });

        for (let i = startIndex; i < endIndex; i += 1) {
            if (checked) {
                this.selectedRows.add(i);
            } else {
                this.selectedRows.delete(i);
            }
        }

        this.updateSelectAllState();
    }
    
    updateSelectAllState() {
        const selectAllCheckbox = document.getElementById('selectAllCheckbox');
        if (!selectAllCheckbox) {
            return;
        }

        const totalRecords = this.currentData.length;

        if (totalRecords === 0) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
            return;
        }

        const { startIndex, endIndex } = this.getCurrentPageRange();
        const visibleCount = endIndex - startIndex;
        const selectedVisible = Array.from(this.selectedRows).filter(index => index >= startIndex && index < endIndex).length;

        selectAllCheckbox.checked = visibleCount > 0 && selectedVisible === visibleCount;
        selectAllCheckbox.indeterminate = selectedVisible > 0 && selectedVisible < visibleCount;
    }

    getCurrentPageRange() {
        const totalRecords = this.currentData.length;
        if (totalRecords === 0) {
            return { startIndex: 0, endIndex: 0 };
        }

        const startIndex = (this.currentPage - 1) * this.pageSize;
        const endIndex = Math.min(startIndex + this.pageSize, totalRecords);
        return { startIndex, endIndex };
    }

    getTotalPages() {
        if (this.currentData.length === 0) {
            return 1;
        }
        return Math.ceil(this.currentData.length / this.pageSize);
    }

    calculatePagesToShow(totalPages) {
        const current = this.currentPage;
        const pages = [];

        const add = (value) => {
            if (pages[pages.length - 1] !== value) {
                pages.push(value);
            }
        };

        const addRange = (start, end) => {
            for (let i = start; i <= end; i += 1) {
                add(i);
            }
        };

        if (totalPages <= 7) {
            addRange(1, totalPages);
            return pages;
        }

        add(1);

        if (current <= 4) {
            addRange(2, 5);
            add('ellipsis');
        } else if (current >= totalPages - 3) {
            add('ellipsis');
            addRange(totalPages - 4, totalPages - 1);
        } else {
            add('ellipsis');
            addRange(current - 1, current + 1);
            add('ellipsis');
        }

        add(totalPages);
        return pages;
    }

    renderPaginationControls() {
        const paginationControls = document.getElementById('paginationControls');
        const paginationInfo = document.getElementById('paginationInfo');
        const pageSizeSelect = document.getElementById('pageSizeSelect');

        if (pageSizeSelect && parseInt(pageSizeSelect.value, 10) !== this.pageSize) {
            pageSizeSelect.value = this.pageSize;
        }

        if (!paginationControls || !paginationInfo) {
            return;
        }

        const totalRecords = this.currentData.length;

        if (totalRecords === 0) {
            paginationControls.innerHTML = '';
            paginationInfo.textContent = 'No records to display';
            return;
        }

        const { startIndex, endIndex } = this.getCurrentPageRange();
        paginationInfo.textContent = `Showing ${startIndex + 1}-${endIndex} of ${totalRecords}`;

        const totalPages = this.getTotalPages();
        const currentPage = this.currentPage;

        const createPageItem = (label, page, disabled = false, active = false) => {
            const li = document.createElement('li');
            li.className = `page-item${disabled ? ' disabled' : ''}${active ? ' active' : ''}`;
            const anchor = document.createElement('a');
            anchor.className = 'page-link';
            anchor.href = '#';
            anchor.textContent = label;
            if (!disabled) {
                anchor.dataset.page = page;
            }
            li.appendChild(anchor);
            return li;
        };

        paginationControls.innerHTML = '';

        paginationControls.appendChild(createPageItem('«', currentPage - 1, currentPage === 1));

        const pagesToShow = this.calculatePagesToShow(totalPages);
        pagesToShow.forEach(page => {
            if (page === 'ellipsis') {
                const li = document.createElement('li');
                li.className = 'page-item disabled';
                const span = document.createElement('span');
                span.className = 'page-link';
                span.textContent = '…';
                li.appendChild(span);
                paginationControls.appendChild(li);
            } else {
                paginationControls.appendChild(createPageItem(page, page, false, page === currentPage));
            }
        });

        paginationControls.appendChild(createPageItem('»', currentPage + 1, currentPage === totalPages));
    }

    goToPage(page) {
        const totalPages = this.getTotalPages();
        const targetPage = Math.min(Math.max(1, page), totalPages);
        if (targetPage !== this.currentPage) {
            this.currentPage = targetPage;
            this.renderPreviewTable();
        }
    }
    
    async startImport() {
        if (!this.currentSessionId || this.currentData.length === 0) {
            this.showNotification('No data to import', 'warning');
            return;
        }
        
        if (!confirm(`Are you sure you want to import ${this.currentData.length} records to the database?`)) {
            return;
        }
        
        // Show progress modal
        const modal = new bootstrap.Modal(document.getElementById('importProgressModal'));
        modal.show();
        
        // Update progress
        const progressBar = document.getElementById('importProgressBar');
        const progressText = document.getElementById('importProgressText');
        const progressCount = document.getElementById('importProgressCount');
        
        progressText.textContent = 'Starting import...';
        progressCount.textContent = `0 of ${this.currentData.length} records`;
        
        try {
            // Simulate progress (in real implementation, this would be actual progress)
            for (let i = 0; i <= 100; i += 10) {
                progressBar.style.width = i + '%';
                progressBar.textContent = i + '%';
                progressText.textContent = i < 100 ? 'Importing records...' : 'Finalizing import...';
                await new Promise(resolve => setTimeout(resolve, 200));
            }
            
            // Make actual import request
            const response = await fetch(`/api/import-file-indexing/${this.currentSessionId}`, {
                method: 'POST'
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Import failed');
            }
            
            const result = await response.json();
            
            progressText.textContent = 'Import completed successfully!';
            progressCount.textContent = `${result.imported_count} records imported`;
            
            setTimeout(() => {
                modal.hide();
                this.showNotification(`Successfully imported ${result.imported_count} file indexing records!`, 'success');
                
                // Reset the interface
                this.resetInterface();
            }, 2000);
            
        } catch (error) {
            console.error('Import error:', error);
            progressText.textContent = 'Import failed!';
            progressBar.classList.add('bg-danger');
            
            setTimeout(() => {
                modal.hide();
                this.showNotification(`Import failed: ${error.message}`, 'error');
            }, 2000);
        }
    }
    
    resetInterface() {
        // Clear data
        this.currentData = [];
        this.multipleOccurrences = {};
        this.groupingPreview = {
            rows: [],
            summary: { matched: 0, skipped: 0, missing: 0 }
        };
        this.selectedRows.clear();
        this.currentSessionId = null;
        this.currentPage = 1;
        this.renderPreviewTable();
        this.renderGroupingPreview();
        
        // Reset UI
        document.getElementById('csvFile').value = '';
        document.getElementById('uploadBtn').disabled = true;
        this.hideSection('preview-section');
        this.showSection('upload-section');
        
        // Clear URL parameters
        const newUrl = new URL(window.location);
        newUrl.searchParams.delete('session_id');
        window.history.pushState({}, '', newUrl);
    }
    
    showSection(sectionId) {
        const section = document.getElementById(sectionId);
        if (section) {
            section.style.display = 'block';
        }
    }
    
    hideSection(sectionId) {
        const section = document.getElementById(sectionId);
        if (section) {
            section.style.display = 'none';
        }
    }
    
    showNotification(message, type = 'info') {
        // Create Bootstrap toast
        const toastContainer = document.getElementById('toastContainer') || this.createToastContainer();
        
        const toastEl = document.createElement('div');
        toastEl.className = `toast align-items-center text-white bg-${type === 'error' ? 'danger' : type} border-0`;
        toastEl.setAttribute('role', 'alert');
        toastEl.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;
        
        toastContainer.appendChild(toastEl);
        
        const toast = new bootstrap.Toast(toastEl);
        toast.show();
        
        // Remove element after hidden
        toastEl.addEventListener('hidden.bs.toast', () => {
            toastEl.remove();
        });
    }
    
    createToastContainer() {
        const container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'toast-container position-fixed top-0 end-0 p-3';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
        return container;
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.fileIndexingManager = new FileIndexingManager();
});