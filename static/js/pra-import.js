// PRA Import JavaScript
class PRAImportManager {
    constructor() {
        this.data = [];
        this.filteredData = [];
        this.currentPage = 1;
        this.itemsPerPage = 20;
        this.sessionId = null;
        this.currentFilter = 'all'; // 'all', 'issues', 'valid'
        
        this.initializeEventListeners();
    }

    initializeEventListeners() {
        // File input handling
        const fileInput = document.getElementById('fileInput');
        const uploadArea = document.getElementById('uploadArea');

        if (fileInput) {
            fileInput.addEventListener('change', (e) => this.handleFileSelect(e));
        }

        if (uploadArea) {
            // Drag and drop functionality
            uploadArea.addEventListener('dragover', (e) => {
                e.preventDefault();
                uploadArea.classList.add('drag-over');
            });

            uploadArea.addEventListener('dragleave', (e) => {
                e.preventDefault();
                uploadArea.classList.remove('drag-over');
            });

            uploadArea.addEventListener('drop', (e) => {
                e.preventDefault();
                uploadArea.classList.remove('drag-over');
                const files = e.dataTransfer.files;
                if (files.length > 0) {
                    this.processFile(files[0]);
                }
            });
        }

        // Filter buttons
        document.getElementById('showAllBtn')?.addEventListener('click', () => this.setFilter('all'));
        document.getElementById('showIssuesBtn')?.addEventListener('click', () => this.setFilter('issues'));
        document.getElementById('showValidBtn')?.addEventListener('click', () => this.setFilter('valid'));

        // Action buttons
        document.getElementById('selectAllBtn')?.addEventListener('click', () => this.selectAll());
        document.getElementById('deselectAllBtn')?.addEventListener('click', () => this.deselectAll());
        document.getElementById('importBtn')?.addEventListener('click', () => this.importData());
        document.getElementById('validateBtn')?.addEventListener('click', () => this.revalidateData());

        // Bulk actions
        document.getElementById('bulkEditBtn')?.addEventListener('click', () => this.bulkEdit());
        document.getElementById('deleteSelectedBtn')?.addEventListener('click', () => this.deleteSelected());

        // Select all checkbox
        document.getElementById('selectAllCheckbox')?.addEventListener('change', (e) => {
            this.toggleSelectAll(e.target.checked);
        });

        // Edit modal save button
        document.getElementById('saveRecordBtn')?.addEventListener('click', () => this.saveRecord());
    }

    handleFileSelect(event) {
        const file = event.target.files[0];
        if (file) {
            this.processFile(file);
        }
    }

    async processFile(file) {
        if (!this.validateFileFormat(file)) {
            this.showAlert('Please select a valid CSV or Excel file.', 'danger');
            return;
        }

        this.showLoadingModal();
        this.showUploadProgress(true);

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/api/upload-pra', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const result = await response.json();
            this.sessionId = result.session_id;
            this.data = result.data || [];
            
            this.updateStatistics(result);
            this.applyFilter();
            this.showPreviewSection();
            this.showAlert(`File processed successfully! ${result.total_records} records loaded.`, 'success');

            // Enable import button if there are valid records
            const importBtn = document.getElementById('importBtn');
            if (importBtn && result.ready_records > 0) {
                importBtn.disabled = false;
            }

        } catch (error) {
            console.error('Upload error:', error);
            this.showAlert('Error processing file: ' + error.message, 'danger');
        } finally {
            this.hideLoadingModal();
            this.showUploadProgress(false);
        }
    }

    validateFileFormat(file) {
        const allowedTypes = [
            'text/csv',
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        ];
        const allowedExtensions = ['.csv', '.xls', '.xlsx'];
        
        const fileName = file.name.toLowerCase();
        const hasValidExtension = allowedExtensions.some(ext => fileName.endsWith(ext));
        const hasValidType = allowedTypes.includes(file.type);
        
        return hasValidExtension || hasValidType;
    }

    updateStatistics(result) {
        document.getElementById('total-records').textContent = result.total_records || 0;
        document.getElementById('validation-issues').textContent = result.validation_issues || 0;
        document.getElementById('property-assignments').textContent = result.property_assignments || 0;
        document.getElementById('ready-records').textContent = result.ready_records || 0;

        // Show statistics row
        document.getElementById('statisticsRow').style.display = 'flex';

        // Update validation panel if there are issues
        if (result.validation_issues > 0) {
            this.showValidationIssues(result.issues || []);
        }
    }

    showValidationIssues(issues) {
        const panel = document.getElementById('validationPanel');
        const issuesList = document.getElementById('validationIssuesList');
        
        if (!panel || !issuesList) return;

        let html = '';
        for (const [category, categoryIssues] of Object.entries(issues)) {
            if (categoryIssues.length > 0) {
                html += `
                    <div class="mb-3">
                        <h6 class="text-warning">
                            <i class="fas fa-exclamation-circle me-1"></i>
                            ${this.formatCategoryName(category)} (${categoryIssues.length})
                        </h6>
                        <ul class="list-unstyled ms-3">
                `;
                categoryIssues.forEach(issue => {
                    html += `<li class="text-muted small">• Row ${issue.row}: ${issue.message}</li>`;
                });
                html += '</ul></div>';
            }
        }

        issuesList.innerHTML = html;
        panel.style.display = 'block';
    }

    formatCategoryName(category) {
        const names = {
            'required_fields': 'Required Fields Missing',
            'data_format': 'Data Format Issues',
            'business_rules': 'Business Rule Violations',
            'duplicates': 'Duplicate Records'
        };
        return names[category] || category.replace('_', ' ').toUpperCase();
    }

    setFilter(filterType) {
        this.currentFilter = filterType;
        this.currentPage = 1;
        this.applyFilter();
        
        // Update button states
        document.querySelectorAll('[id*="show"][id*="Btn"]').forEach(btn => {
            btn.classList.remove('active');
        });
        document.getElementById(`show${filterType === 'all' ? 'All' : filterType === 'issues' ? 'Issues' : 'Valid'}Btn`).classList.add('active');
    }

    applyFilter() {
        switch (this.currentFilter) {
            case 'issues':
                this.filteredData = this.data.filter(record => record.hasIssues);
                break;
            case 'valid':
                this.filteredData = this.data.filter(record => !record.hasIssues);
                break;
            default:
                this.filteredData = [...this.data];
                break;
        }
        
        this.renderTable();
        this.renderPagination();
    }

    renderTable() {
        const tbody = document.getElementById('previewTableBody');
        if (!tbody) return;

        const startIndex = (this.currentPage - 1) * this.itemsPerPage;
        const endIndex = startIndex + this.itemsPerPage;
        const pageData = this.filteredData.slice(startIndex, endIndex);

        tbody.innerHTML = '';

        pageData.forEach((record, index) => {
            const actualIndex = startIndex + index;
            const tr = this.createTableRow(record, actualIndex + 1, actualIndex);
            tbody.appendChild(tr);
        });

        this.updateShowingInfo();
    }

    createTableRow(record, displayIndex, actualIndex) {
        const tr = document.createElement('tr');
        tr.dataset.index = actualIndex;
        
        // Add warning class for records with issues
        if (record.hasIssues) {
            tr.classList.add('table-warning');
        }
        
        tr.innerHTML = `
            <td>
                <input type="checkbox" class="row-select" data-index="${actualIndex}">
            </td>
            <td>${displayIndex}</td>
            <td class="editable-cell" data-field="file_number" data-index="${actualIndex}">
                ${record.file_number || ''}
                ${record.hasIssues ? '<i class="fas fa-exclamation-triangle text-warning ms-1" title="Has validation issues"></i>' : ''}
            </td>
            <td>${record.prop_id || ''}</td>
            <td class="editable-cell" data-field="title_type" data-index="${actualIndex}">${record.title_type || ''}</td>
            <td class="editable-cell" data-field="transaction_type" data-index="${actualIndex}">${record.transaction_type || ''}</td>
            <td class="editable-cell" data-field="serial_no" data-index="${actualIndex}">${record.serial_no || ''}</td>
            <td class="editable-cell" data-field="page_no" data-index="${actualIndex}">${record.page_no || ''}</td>
            <td class="editable-cell" data-field="volume_no" data-index="${actualIndex}">${record.volume_no || ''}</td>
            <td class="editable-cell" data-field="grantor" data-index="${actualIndex}">${record.grantor || ''}</td>
            <td class="editable-cell" data-field="grantee" data-index="${actualIndex}">${record.grantee || ''}</td>
            <td class="editable-cell" data-field="property_description" data-index="${actualIndex}">${record.property_description || ''}</td>
            <td class="editable-cell" data-field="location" data-index="${actualIndex}">${record.location || ''}</td>
            <td class="editable-cell" data-field="plot_no" data-index="${actualIndex}">${record.plot_no || ''}</td>
            <td class="editable-cell" data-field="lga" data-index="${actualIndex}">${record.lga || ''}</td>
            <td class="editable-cell" data-field="district" data-index="${actualIndex}">${record.district || ''}</td>
            <td>
                <span class="badge ${record.hasIssues ? 'bg-warning' : 'bg-success'}">
                    ${record.hasIssues ? 'Issues' : 'Valid'}
                </span>
            </td>
            <td class="text-center">
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary btn-sm" onclick="praManager.editRecord(${actualIndex})" title="Edit">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-outline-danger btn-sm" onclick="praManager.deleteRecord(${actualIndex})" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </td>
        `;

        // Add click handlers for editable cells
        tr.querySelectorAll('.editable-cell').forEach(cell => {
            cell.addEventListener('click', () => this.editCell(cell));
        });

        // Add change handler for row select checkbox
        tr.querySelector('.row-select')?.addEventListener('change', (e) => this.handleRowSelect(e, actualIndex));
        
        return tr;
    }

    editCell(cell) {
        const field = cell.dataset.field;
        const index = parseInt(cell.dataset.index);
        const currentValue = cell.textContent.trim();
        
        // Create input element
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control form-control-sm';
        input.value = currentValue;
        
        // Replace cell content with input
        cell.innerHTML = '';
        cell.appendChild(input);
        input.focus();
        input.select();
        
        // Handle save on blur or enter
        const saveValue = () => {
            const newValue = input.value.trim();
            this.filteredData[index][field] = newValue;
            cell.innerHTML = newValue;
        };
        
        input.addEventListener('blur', saveValue);
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                saveValue();
            }
        });
    }

    renderPagination() {
        const pagination = document.getElementById('pagination');
        if (!pagination) return;

        const totalPages = Math.ceil(this.filteredData.length / this.itemsPerPage);
        let html = '';

        // Previous button
        html += `
            <li class="page-item ${this.currentPage === 1 ? 'disabled' : ''}">
                <a class="page-link" href="#" onclick="praManager.goToPage(${this.currentPage - 1})">Previous</a>
            </li>
        `;

        // Page numbers
        for (let i = 1; i <= totalPages; i++) {
            if (i === 1 || i === totalPages || (i >= this.currentPage - 2 && i <= this.currentPage + 2)) {
                html += `
                    <li class="page-item ${i === this.currentPage ? 'active' : ''}">
                        <a class="page-link" href="#" onclick="praManager.goToPage(${i})">${i}</a>
                    </li>
                `;
            } else if (i === this.currentPage - 3 || i === this.currentPage + 3) {
                html += '<li class="page-item disabled"><span class="page-link">...</span></li>';
            }
        }

        // Next button
        html += `
            <li class="page-item ${this.currentPage === totalPages ? 'disabled' : ''}">
                <a class="page-link" href="#" onclick="praManager.goToPage(${this.currentPage + 1})">Next</a>
            </li>
        `;

        pagination.innerHTML = html;
    }

    goToPage(page) {
        const totalPages = Math.ceil(this.filteredData.length / this.itemsPerPage);
        if (page >= 1 && page <= totalPages) {
            this.currentPage = page;
            this.renderTable();
            this.renderPagination();
        }
    }

    updateShowingInfo() {
        const startIndex = (this.currentPage - 1) * this.itemsPerPage;
        const endIndex = Math.min(startIndex + this.itemsPerPage, this.filteredData.length);
        
        document.getElementById('showingStart').textContent = this.filteredData.length > 0 ? startIndex + 1 : 0;
        document.getElementById('showingEnd').textContent = endIndex;
        document.getElementById('showingTotal').textContent = this.filteredData.length;
    }

    selectAll() {
        document.querySelectorAll('.row-select').forEach(checkbox => {
            checkbox.checked = true;
        });
        this.updateBulkActionButtons();
    }

    deselectAll() {
        document.querySelectorAll('.row-select').forEach(checkbox => {
            checkbox.checked = false;
        });
        this.updateBulkActionButtons();
    }

    toggleSelectAll(checked) {
        document.querySelectorAll('.row-select').forEach(checkbox => {
            checkbox.checked = checked;
        });
        this.updateBulkActionButtons();
    }

    handleRowSelect(event, index) {
        this.updateBulkActionButtons();
    }

    updateBulkActionButtons() {
        const selectedCheckboxes = document.querySelectorAll('.row-select:checked');
        const hasSelection = selectedCheckboxes.length > 0;
        
        document.getElementById('bulkEditBtn').disabled = !hasSelection;
        document.getElementById('deleteSelectedBtn').disabled = !hasSelection;
    }

    editRecord(index) {
        const record = this.filteredData[index];
        if (!record) return;

        // Populate modal form
        const form = document.getElementById('editRecordForm');
        if (form) {
            Object.keys(record).forEach(key => {
                const input = form.querySelector(`[name="${key}"]`);
                if (input) {
                    input.value = record[key] || '';
                }
            });
            
            // Store index for saving
            form.dataset.editIndex = index;
            
            // Show modal
            new bootstrap.Modal(document.getElementById('editRecordModal')).show();
        }
    }

    saveRecord() {
        const form = document.getElementById('editRecordForm');
        const index = parseInt(form.dataset.editIndex);
        
        if (isNaN(index) || !this.filteredData[index]) return;

        // Update record with form data
        const formData = new FormData(form);
        for (const [key, value] of formData.entries()) {
            this.filteredData[index][key] = value;
        }

        // Refresh table
        this.renderTable();
        
        // Hide modal
        bootstrap.Modal.getInstance(document.getElementById('editRecordModal')).hide();
        
        this.showAlert('Record updated successfully', 'success');
    }

    deleteRecord(index) {
        if (confirm('Are you sure you want to delete this record?')) {
            this.filteredData.splice(index, 1);
            this.data = this.data.filter(record => record !== this.filteredData[index]);
            this.renderTable();
            this.renderPagination();
            this.showAlert('Record deleted successfully', 'success');
        }
    }

    async importData() {
        if (!this.sessionId) {
            this.showAlert('No data to import. Please upload a file first.', 'warning');
            return;
        }

        this.showLoadingModal();

        try {
            const response = await fetch(`/api/import-pra/${this.sessionId}`, {
                method: 'POST'
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const result = await response.json();
            
            this.showAlert(`Import completed successfully! ${result.imported_count || 0} records imported.`, 'success');
            
            // Reset form
            this.resetForm();

        } catch (error) {
            console.error('Import error:', error);
            this.showAlert('Error importing data: ' + error.message, 'danger');
        } finally {
            this.hideLoadingModal();
        }
    }

    resetForm() {
        this.data = [];
        this.filteredData = [];
        this.sessionId = null;
        
        document.getElementById('fileInput').value = '';
        document.getElementById('statisticsRow').style.display = 'none';
        document.getElementById('previewSection').style.display = 'none';
        document.getElementById('validationPanel').style.display = 'none';
        document.getElementById('importBtn').disabled = true;
    }

    showPreviewSection() {
        document.getElementById('previewSection').style.display = 'block';
    }

    showLoadingModal() {
        new bootstrap.Modal(document.getElementById('loadingModal')).show();
    }

    hideLoadingModal() {
        const modal = bootstrap.Modal.getInstance(document.getElementById('loadingModal'));
        if (modal) {
            modal.hide();
        }
    }

    showUploadProgress(show) {
        const progress = document.getElementById('uploadProgress');
        if (progress) {
            progress.style.display = show ? 'block' : 'none';
        }
    }

    showAlert(message, type = 'info') {
        const alertContainer = document.getElementById('alertContainer');
        if (!alertContainer) return;

        const alertId = 'alert-' + Date.now();
        const alertHtml = `
            <div class="alert alert-${type} alert-dismissible fade show" id="${alertId}">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;
        
        alertContainer.insertAdjacentHTML('beforeend', alertHtml);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            const alert = document.getElementById(alertId);
            if (alert) {
                alert.remove();
            }
        }, 5000);
    }

    revalidateData() {
        if (!this.sessionId) {
            this.showAlert('No data to validate. Please upload a file first.', 'warning');
            return;
        }

        this.showAlert('Re-validation feature will be implemented in the backend.', 'info');
    }

    bulkEdit() {
        this.showAlert('Bulk edit feature will be implemented.', 'info');
    }

    deleteSelected() {
        const selectedCheckboxes = document.querySelectorAll('.row-select:checked');
        if (selectedCheckboxes.length === 0) return;

        if (confirm(`Are you sure you want to delete ${selectedCheckboxes.length} selected records?`)) {
            const indicesToDelete = Array.from(selectedCheckboxes).map(cb => parseInt(cb.dataset.index));
            
            // Remove from filteredData and data
            indicesToDelete.sort((a, b) => b - a); // Sort descending to avoid index issues
            indicesToDelete.forEach(index => {
                this.filteredData.splice(index, 1);
            });
            
            this.renderTable();
            this.renderPagination();
            this.showAlert(`${indicesToDelete.length} records deleted successfully`, 'success');
        }
    }
}

// Initialize the PRA Import Manager when DOM is loaded
let praManager;
document.addEventListener('DOMContentLoaded', function() {
    praManager = new PRAImportManager();
});