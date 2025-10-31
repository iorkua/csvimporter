// PRA Import JavaScript
class PRAImportManager {
    constructor() {
        this.propertyRecordsData = [];
        this.fileNumbersData = [];
        this.filteredData = [];
        this.currentPage = 1;
        this.itemsPerPage = 20;
        this.sessionId = null;
        this.currentFilter = 'all'; // 'all', 'issues', 'valid'
        this.currentTab = 'property-records'; // 'property-records', 'file-numbers'
        this.duplicates = {
            csv: [],
            database: []
        };
        this.ACRE_TO_HECTARE = 0.40468564224;
        
        this.initializeEventListeners();
    }

    initializeEventListeners() {
        // Form submission handling
        const uploadForm = document.getElementById('uploadForm');
        if (uploadForm) {
            uploadForm.addEventListener('submit', (e) => this.handleFormSubmit(e));
        }

        // Filter buttons
        document.getElementById('showAllBtn')?.addEventListener('click', () => this.setFilter('all'));
        document.getElementById('showIssuesBtn')?.addEventListener('click', () => this.setFilter('issues'));
        document.getElementById('showValidBtn')?.addEventListener('click', () => this.setFilter('valid'));

        // Tab switching
        document.getElementById('property-records-tab')?.addEventListener('click', () => this.switchTab('property-records'));
        document.getElementById('file-numbers-tab')?.addEventListener('click', () => this.switchTab('file-numbers'));

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

    handleFormSubmit(event) {
        event.preventDefault();
        const fileInput = document.getElementById('fileInput');
        const file = fileInput.files[0];
        
        if (!file) {
            this.showAlert('Please select a file to upload.', 'warning');
            return;
        }
        
        this.processFile(file);
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
            this.propertyRecordsData = result.property_records || [];
            this.fileNumbersData = result.file_numbers || [];
            this.duplicates = result.duplicates || { csv: [], database: [] };
            
            this.updateStatistics(result);
            this.showDuplicates();
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
        document.getElementById('duplicate-records').textContent = result.duplicate_count || 0;
        document.getElementById('validation-issues').textContent = result.validation_issues || 0;
        document.getElementById('ready-records').textContent = result.ready_records || 0;

        // Update tab counts
        document.getElementById('propertyRecordsCount').textContent = this.propertyRecordsData.length;
        document.getElementById('fileNumbersCount').textContent = this.fileNumbersData.length;

        // Show statistics row
        document.getElementById('statisticsRow').style.display = 'flex';

        // Update validation panel if there are issues
        if (result.validation_issues > 0) {
            this.showValidationIssues(result.issues || []);
        }
    }

    switchTab(tabName) {
        this.currentTab = tabName;
        this.currentPage = 1;
        this.applyFilter();
    }

    showDuplicates() {
        const csvDuplicates = this.duplicates.csv || [];
        const dbDuplicates = this.duplicates.database || [];
        
        document.getElementById('csvDuplicatesCount').textContent = csvDuplicates.length;
        document.getElementById('dbDuplicatesCount').textContent = dbDuplicates.length;

        if (csvDuplicates.length > 0 || dbDuplicates.length > 0) {
            this.renderDuplicatesList(csvDuplicates, 'csvDuplicatesList', 'CSV');
            this.renderDuplicatesList(dbDuplicates, 'dbDuplicatesList', 'Database');
            document.getElementById('duplicatesPanel').style.display = 'block';
        }
    }

    renderDuplicatesList(duplicates, containerId, type) {
        const container = document.getElementById(containerId);
        if (!container || duplicates.length === 0) return;

        let html = '';
        duplicates.forEach(duplicate => {
            html += `
                <div class="card mb-3 border-warning">
                    <div class="card-header bg-light">
                        <h6 class="mb-0">
                            <i class="fas fa-file-alt me-2"></i>
                            File Number: <strong>${duplicate.file_number}</strong>
                            <span class="badge bg-warning ms-2">${duplicate.count} occurrences</span>
                        </h6>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            ${duplicate.records.map((record, index) => `
                                <div class="col-md-6 mb-2">
                                    <div class="border rounded p-2 bg-light">
                                        <small class="text-muted">${type} Record ${index + 1}:</small>
                                        <div><strong>Grantee:</strong> ${record.grantee || 'N/A'}</div>
                                        <div><strong>Transaction Type:</strong> ${record.transaction_type || 'N/A'}</div>
                                        <div><strong>Plot No:</strong> ${record.plot_no || 'N/A'}</div>
                                        ${type === 'Database' ? `<div><strong>Existing Prop ID:</strong> ${record.prop_id || 'N/A'}</div>` : ''}
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                        <div class="mt-3">
                            <div class="btn-group btn-group-sm">
                                <button class="btn btn-outline-primary" onclick="praManager.editDuplicate('${duplicate.file_number}', '${type}')">
                                    <i class="fas fa-edit me-1"></i>Edit
                                </button>
                                <button class="btn btn-outline-success" onclick="praManager.confirmDuplicate('${duplicate.file_number}', '${type}')">
                                    <i class="fas fa-check me-1"></i>Confirm Import
                                </button>
                                <button class="btn btn-outline-danger" onclick="praManager.skipDuplicate('${duplicate.file_number}', '${type}')">
                                    <i class="fas fa-times me-1"></i>Skip
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });
        
        container.innerHTML = html;
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
        // Get data based on current tab
        const sourceData = this.currentTab === 'property-records' ? this.propertyRecordsData : this.fileNumbersData;
        
        switch (this.currentFilter) {
            case 'issues':
                this.filteredData = sourceData.filter(record => record.hasIssues);
                break;
            case 'valid':
                this.filteredData = sourceData.filter(record => !record.hasIssues);
                break;
            default:
                this.filteredData = [...sourceData];
                break;
        }
        
        this.renderTable();
        this.renderPagination();
    }

    sanitizeValue(value) {
        if (value === null || value === undefined) {
            return '';
        }

        if (typeof value === 'number') {
            return Number.isNaN(value) ? '' : value.toString();
        }

        if (typeof value === 'string') {
            const trimmed = value.trim();
            if (!trimmed) {
                return '';
            }
            if (["nan", "none", "null", "undefined", "n/a"].includes(trimmed.toLowerCase())) {
                return '';
            }
            return trimmed;
        }

        return String(value ?? '');
    }

    formatDecimal(value, decimals = 3) {
        if (!Number.isFinite(value)) {
            return '';
        }
        const fixed = value.toFixed(decimals);
        return fixed
            .replace(/(\.\d*?[1-9])0+$/, '$1')
            .replace(/\.0+$/, '')
            .replace(/\.$/, '');
    }

    detectPlotSizeUnit(value) {
        const lowerValue = (value || '').toString().toLowerCase();

        if (/\b(ha|hectare|hectares)\b/.test(lowerValue)) {
            return 'hectares';
        }

        if (/\b(ac|acre|acres)\b/.test(lowerValue)) {
            return 'acres';
        }

        return null;
    }

    parsePlotSize(value) {
        if (value === null || value === undefined) {
            return { numericValue: null, unit: null };
        }

        if (typeof value === 'number') {
            return { numericValue: value, unit: null };
        }

        const raw = value.toString().trim();
        if (!raw) {
            return { numericValue: null, unit: null };
        }

        const numberMatch = raw.match(/-?\d+(?:[.,]\d+)?/);
        const numericValue = numberMatch ? parseFloat(numberMatch[0].replace(/,/g, '')) : Number.NaN;
        const hasValidNumber = Number.isFinite(numericValue);

        const unit = this.detectPlotSizeUnit(raw);

        return {
            numericValue: hasValidNumber ? numericValue : null,
            unit
        };
    }

    renderTable() {
        const tableBodyId = this.currentTab === 'property-records' ? 'propertyRecordsTableBody' : 'fileNumbersTableBody';
        const tbody = document.getElementById(tableBodyId);
        if (!tbody) return;

        const startIndex = (this.currentPage - 1) * this.itemsPerPage;
        const endIndex = startIndex + this.itemsPerPage;
        const pageData = this.filteredData.slice(startIndex, endIndex);

        tbody.innerHTML = '';

        pageData.forEach((record, index) => {
            const actualIndex = startIndex + index;
            const tr = this.currentTab === 'property-records' ? 
                this.createPropertyRecordRow(record, actualIndex + 1, actualIndex) :
                this.createFileNumberRow(record, actualIndex + 1, actualIndex);
            tbody.appendChild(tr);
        });

        this.updateShowingInfo();
    }

    createPropertyRecordRow(record, displayIndex, actualIndex) {
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
            <td class="editable-cell" data-field="mlsFNo" data-index="${actualIndex}">
                ${this.sanitizeValue(record.mlsFNo)}
                ${record.hasIssues ? '<i class="fas fa-exclamation-triangle text-warning ms-1" title="Has validation issues"></i>' : ''}
            </td>
            <td>${this.sanitizeValue(record.prop_id)}</td>
            <td class="editable-cell" data-field="transaction_type" data-index="${actualIndex}">${this.sanitizeValue(record.transaction_type)}</td>
            <td class="editable-cell" data-field="transaction_date" data-index="${actualIndex}">${this.sanitizeValue(record.transaction_date)}</td>
            <td class="editable-cell" data-field="serialNo" data-index="${actualIndex}">${this.sanitizeValue(record.serialNo)}</td>
            <td class="editable-cell" data-field="pageNo" data-index="${actualIndex}">${this.sanitizeValue(record.pageNo)}</td>
            <td class="editable-cell" data-field="volumeNo" data-index="${actualIndex}">${this.sanitizeValue(record.volumeNo)}</td>
            <td>${this.sanitizeValue(record.regNo)}</td>
            <td class="editable-cell" data-field="grantor_assignor" data-index="${actualIndex}">${this.sanitizeValue(record.grantor_assignor)}</td>
            <td class="editable-cell" data-field="grantee_assignee" data-index="${actualIndex}">${this.sanitizeValue(record.grantee_assignee)}</td>
            <td class="editable-cell" data-field="streetName" data-index="${actualIndex}">${this.sanitizeValue(record.streetName)}</td>
            <td class="editable-cell" data-field="house_no" data-index="${actualIndex}">${this.sanitizeValue(record.house_no)}</td>
            <td class="editable-cell" data-field="districtName" data-index="${actualIndex}">${this.sanitizeValue(record.districtName)}</td>
            <td class="editable-cell" data-field="plot_no" data-index="${actualIndex}">${this.sanitizeValue(record.plot_no)}</td>
            <td class="editable-cell" data-field="LGA" data-index="${actualIndex}">${this.sanitizeValue(record.LGA)}</td>
            <td class="editable-cell" data-field="plot_size" data-index="${actualIndex}">${this.sanitizeValue(record.plot_size)}</td>
            <td>
                <span class="badge ${record.hasIssues ? 'bg-warning text-dark' : 'bg-success'}">
                    ${record.hasIssues ? 'Issues' : 'Valid'}
                </span>
            </td>
            <td class="text-center">
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary btn-sm" onclick="praManager.convertPlotSizeToHectares(${actualIndex})" title="Convert acres to hectares">
                        <i class="fas fa-ruler-combined"></i>
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

    createFileNumberRow(record, displayIndex, actualIndex) {
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
            <td class="editable-cell" data-field="mlsfNo" data-index="${actualIndex}">
                ${this.sanitizeValue(record.mlsfNo)}
                ${record.hasIssues ? '<i class="fas fa-exclamation-triangle text-warning ms-1" title="Has validation issues"></i>' : ''}
            </td>
            <td class="editable-cell" data-field="FileName" data-index="${actualIndex}">${this.sanitizeValue(record.FileName)}</td>
            <td class="editable-cell" data-field="location" data-index="${actualIndex}">${this.sanitizeValue(record.location)}</td>
            <td class="editable-cell" data-field="plot_no" data-index="${actualIndex}">${this.sanitizeValue(record.plot_no)}</td>
            <td>${this.sanitizeValue(record.type || 'MLS')}</td>
            <td>${this.sanitizeValue(record.SOURCE || 'PRA')}</td>
            <td>${this.sanitizeValue(record.created_by)}</td>
            <td>${this.sanitizeValue(record.tracking_id)}</td>
            <td>
                <span class="badge ${record.hasIssues ? 'bg-warning text-dark' : 'bg-success'}">
                    ${record.hasIssues ? 'Issues' : 'Valid'}
                </span>
            </td>
            <td class="text-center">
                <div class="btn-group btn-group-sm">
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
        const index = Number.parseInt(cell.dataset.index, 10);

        if (Number.isNaN(index)) {
            return;
        }

        const record = this.filteredData[index];
        if (!record) {
            return;
        }

        const originalRawValue = record[field] ?? '';
        const originalDisplayValue = this.sanitizeValue(originalRawValue);

        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control form-control-sm';
        input.value = originalDisplayValue;

        cell.innerHTML = '';
        cell.appendChild(input);
        input.focus();
        input.select();

        let committed = false;

        const restoreCell = (value) => {
            cell.innerHTML = this.sanitizeValue(value);
            this.decorateCellAfterEdit(cell, field, record);
        };

        const commitValue = () => {
            if (committed) {
                return;
            }
            committed = true;

            const newDisplayValue = input.value.trim();

            if (newDisplayValue === originalDisplayValue) {
                restoreCell(originalRawValue);
                return;
            }

            const newRawValue = newDisplayValue;
            record[field] = newRawValue;
            this.updateLinkedFields(record, field, newRawValue);
            this.syncLinkedDatasets(record, field, originalRawValue, newRawValue);
            restoreCell(newRawValue);
        };

        input.addEventListener('blur', commitValue);
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                commitValue();
                input.blur();
            } else if (event.key === 'Escape') {
                committed = true;
                restoreCell(originalRawValue);
                input.blur();
            }
        });
    }

    decorateCellAfterEdit(cell, field, record) {
        const needsIssueIcon = record.hasIssues && (field === 'mlsFNo' || field === 'mlsfNo');
        if (needsIssueIcon) {
            cell.insertAdjacentHTML('beforeend', '<i class="fas fa-exclamation-triangle text-warning ms-1" title="Has validation issues"></i>');
        }
    }

    updateLinkedFields(record, field, value) {
        const updates = {
            mlsFNo: ['fileno'],
            fileno: ['mlsFNo'],
            serialNo: ['SerialNo'],
            SerialNo: ['serialNo'],
            grantor_assignor: ['Grantor'],
            Grantor: ['grantor_assignor'],
            grantee_assignee: ['Grantee'],
            Grantee: ['grantee_assignee'],
            LGA: ['lgsaOrCity'],
            created_by: ['CreatedBy'],
            CreatedBy: ['created_by'],
            DateCreated: ['date_created'],
            date_created: ['DateCreated']
        };

        const aliases = updates[field] || [];
        aliases.forEach((alias) => {
            record[alias] = value;
        });
    }

    syncLinkedDatasets(record, field, oldValue, newValue) {
        if (this.currentTab === 'property-records') {
            const oldFileNumber = this.sanitizeValue(field === 'mlsFNo' || field === 'fileno' ? oldValue : record.mlsFNo);
            const currentFileNumber = this.sanitizeValue(record.mlsFNo || record.fileno);

            if (field === 'mlsFNo' || field === 'fileno') {
                this.fileNumbersData.forEach((fileRecord) => {
                    if (this.sanitizeValue(fileRecord.mlsfNo) === oldFileNumber) {
                        fileRecord.mlsfNo = newValue;
                    }
                });
            }

            if (field === 'grantee_assignee' || field === 'Grantee') {
                this.fileNumbersData.forEach((fileRecord) => {
                    if (this.sanitizeValue(fileRecord.mlsfNo) === currentFileNumber) {
                        fileRecord.FileName = newValue;
                    }
                });
            }
        } else if (this.currentTab === 'file-numbers') {
            if (field === 'mlsfNo') {
                const oldFileNumber = this.sanitizeValue(oldValue);
                this.propertyRecordsData.forEach((propRecord) => {
                    if (this.sanitizeValue(propRecord.mlsFNo) === oldFileNumber) {
                        propRecord.mlsFNo = newValue;
                        propRecord.fileno = newValue;
                    }
                });
            }

            if (field === 'FileName') {
                const currentFileNumber = this.sanitizeValue(record.mlsfNo);
                this.propertyRecordsData.forEach((propRecord) => {
                    if (this.sanitizeValue(propRecord.mlsFNo) === currentFileNumber) {
                        propRecord.Grantee = newValue;
                        propRecord.grantee_assignee = newValue;
                    }
                });
            }
        }
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

    convertPlotSizeToHectares(index) {
        const record = this.filteredData[index];
        if (!record) {
            return;
        }

        const plotSizeValue = record.plot_size ?? record.plotSize ?? record.PlotSize ?? '';
        const sanitizedValue = this.sanitizeValue(plotSizeValue);

        if (!sanitizedValue) {
            this.showAlert('Plot size is empty for this record.', 'warning');
            return;
        }

        const { numericValue, unit } = this.parsePlotSize(plotSizeValue);

        if (numericValue === null) {
            this.showAlert('Unable to determine the numeric plot size for this record.', 'warning');
            return;
        }

        const normalizedUnit = unit ?? 'acres';

        if (normalizedUnit === 'hectares') {
            this.showAlert('Plot size is already expressed in hectares.', 'info');
            return;
        }

        if (normalizedUnit !== 'acres') {
            this.showAlert(`Plot size unit "${unit}" is not supported for automatic conversion yet.`, 'warning');
            return;
        }

        const hectaresValue = numericValue * this.ACRE_TO_HECTARE;
        const formattedHectares = this.formatDecimal(hectaresValue) || hectaresValue.toString();
        const formattedAcres = this.formatDecimal(numericValue) || numericValue.toString();
        const newValue = `${formattedHectares} ha`;

        record.plot_size = newValue;
        if ('plotSize' in record) {
            record.plotSize = newValue;
        }
        if ('PlotSize' in record) {
            record.PlotSize = newValue;
        }

        this.renderTable();
        this.renderPagination();
        this.showAlert(`Converted ${formattedAcres} acres to ${formattedHectares} ha.`, 'success');
    }

    deleteRecord(index) {
        if (!confirm('Are you sure you want to delete this record?')) {
            return;
        }

        const record = this.filteredData[index];
        if (!record) {
            return;
        }

        const sourceData = this.currentTab === 'property-records'
            ? this.propertyRecordsData
            : this.fileNumbersData;

        const sourceIndex = sourceData.indexOf(record);
        if (sourceIndex !== -1) {
            sourceData.splice(sourceIndex, 1);
        }

        this.filteredData.splice(index, 1);
        this.renderTable();
        this.renderPagination();

        document.getElementById('propertyRecordsCount').textContent = this.propertyRecordsData.length;
        document.getElementById('fileNumbersCount').textContent = this.fileNumbersData.length;

        this.updateShowingInfo();
        this.showAlert('Record deleted successfully', 'success');
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
        this.propertyRecordsData = [];
        this.fileNumbersData = [];
        this.filteredData = [];
        this.sessionId = null;
        this.duplicates = { csv: [], database: [] };
        
        document.getElementById('fileInput').value = '';
        document.getElementById('statisticsRow').style.display = 'none';
        document.getElementById('previewSection').style.display = 'none';
        document.getElementById('validationPanel').style.display = 'none';
        document.getElementById('duplicatesPanel').style.display = 'none';
        document.getElementById('importBtn').disabled = true;
    }

    // Duplicate handling methods
    editDuplicate(fileNumber, type) {
        this.showAlert(`Edit duplicate functionality for ${fileNumber} (${type}) will be implemented.`, 'info');
    }

    confirmDuplicate(fileNumber, type) {
        this.showAlert(`Confirmed duplicate ${fileNumber} for import.`, 'success');
        // Logic to mark duplicate as confirmed for import
    }

    skipDuplicate(fileNumber, type) {
        if (confirm(`Are you sure you want to skip importing ${fileNumber}?`)) {
            this.showAlert(`Skipped duplicate ${fileNumber}.`, 'warning');
            // Logic to remove duplicate from import queue
        }
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