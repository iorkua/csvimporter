const FILE_HISTORY_QC_CATEGORY_CONFIG = [
    { key: 'padding', label: 'Padding Issues', tone: 'warning', severity: 'Medium' },
    { key: 'year', label: 'Year Issues', tone: 'danger', severity: 'High' },
    { key: 'spacing', label: 'Spacing Issues', tone: 'info', severity: 'Medium' },
    { key: 'temp', label: 'TEMP Issues', tone: 'secondary', severity: 'Low' },
    { key: 'missing_file_number', label: 'Missing File Numbers', tone: 'danger', severity: 'High' },
    { key: 'missing_required_fields', label: 'Missing Required Fields', tone: 'danger', severity: 'High' },
    { key: 'invalid_dates', label: 'Invalid Dates', tone: 'warning', severity: 'Medium' },
    { key: 'missing_reg_components', label: 'Missing Reg Components', tone: 'warning', severity: 'Medium' }
];

const FILE_HISTORY_QC_TONE_CLASSMAP = {
    warning: { border: 'border-warning', text: 'text-warning' },
    danger: { border: 'border-danger', text: 'text-danger' },
    info: { border: 'border-info', text: 'text-info' },
    secondary: { border: 'border-secondary', text: 'text-secondary' },
    success: { border: 'border-success', text: 'text-success' },
    primary: { border: 'border-primary', text: 'text-primary' }
};

class FileHistoryImportManager {
    constructor() {
        this.propertyRecords = [];
        this.cofoRecords = [];
        this.filteredRows = [];
        this.currentTab = 'records';
        this.currentFilter = 'all';
        this.currentPage = 1;
        this.itemsPerPage = 20;
    this.sessionId = null;
    this.qcIssues = {};
        this.loadingModal = null;
        this.isUploading = false;
        this.categoryConfig = {};
        this.categoryOrder = [];
        this.filterControls = document.getElementById('historyFilterControls');
    this.fileNumberIssueTypes = ['padding', 'year', 'spacing', 'temp', 'missing_file_number'];
        this.activeInlineEdit = null;
        FILE_HISTORY_QC_CATEGORY_CONFIG.forEach((cfg) => {
            this.categoryConfig[cfg.key] = { ...cfg };
            this.categoryOrder.push(cfg.key);
        });

        this.registerEventHandlers();
        this.updateFilterButtons();
        this.resetSessionData({ keepFileInput: true });
    }

    registerEventHandlers() {
        const uploadForm = document.getElementById('historyUploadForm');
        if (uploadForm) {
            uploadForm.addEventListener('submit', (event) => this.handleUploadSubmit(event));
        }

        const uploadBtn = document.getElementById('historyUploadBtn');
        if (uploadBtn) {
            uploadBtn.addEventListener('click', (event) => {
                event.preventDefault();
                this.handleUploadSubmit(event);
            });
        }

        document.getElementById('historyShowAllBtn')?.addEventListener('click', () => this.setFilter('all'));
        document.getElementById('historyShowIssuesBtn')?.addEventListener('click', () => this.setFilter('issues'));
        document.getElementById('historyShowValidBtn')?.addEventListener('click', () => this.setFilter('valid'));

        const tabs = document.querySelectorAll('#historyPreviewTabs button[data-bs-toggle="tab"]');
        tabs.forEach((tab) => {
            tab.addEventListener('shown.bs.tab', (event) => {
                const target = event.target.getAttribute('data-bs-target');
                if (target === '#history-records-pane') {
                    this.handleTabChange('records');
                } else if (target === '#history-cofo-pane') {
                    this.handleTabChange('cofo');
                } else if (target === '#history-fileno-pane') {
                    this.handleTabChange('file-number-qc');
                }
            });
        });

        const importBtn = document.getElementById('importHistoryBtn');
        if (importBtn) {
            importBtn.addEventListener('click', () => this.importData());
        }

        const pagination = document.getElementById('historyPagination');
        if (pagination) {
            pagination.addEventListener('click', (event) => {
                const button = event.target.closest('button[data-page]');
                if (!button) {
                    return;
                }
                event.preventDefault();
                const page = Number.parseInt(button.dataset.page, 10);
                if (!Number.isNaN(page)) {
                    this.goToPage(page);
                }
            });
        }
    }

    handleUploadSubmit(event) {
        event.preventDefault();
        const fileInput = document.getElementById('historyFileInput');
        const file = fileInput?.files?.[0];

        if (this.isUploading) {
            this.showAlert('An upload is already in progress. Please wait for it to finish.', 'info');
            return;
        }

        if (!file) {
            this.showAlert('Please select a CSV or Excel file to upload.', 'warning');
            return;
        }

        this.uploadFile(file);
    }

    async uploadFile(file) {
        if (!this.validateFileFormat(file)) {
            this.showAlert('Please choose a valid CSV or Excel file.', 'danger');
            return;
        }

        this.resetSessionData({ keepFileInput: true });

        this.showUploadProgress(true);
        this.updateProgress(10, 'Uploading file…');
        this.disableUpload(true);
        this.showLoadingModal();
        this.isUploading = true;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/api/upload-file-history', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(await this.extractErrorMessage(response));
            }

            this.updateProgress(45, 'Processing data…');
            const result = await response.json();

            this.sessionId = result.session_id || null;
            this.propertyRecords = Array.isArray(result.property_records) ? result.property_records : [];
            this.cofoRecords = Array.isArray(result.cofo_records) ? result.cofo_records : [];
            this.qcIssues = result.issues || {};

            this.updateProgress(70, 'Rendering preview…');
            this.updateStatistics(result);
            this.updatePreview();
            this.showValidationIssues(this.qcIssues);
            this.setImportButtonState(result.ready_records);
            this.updateProgress(100, 'Ready');

            this.showAlert(`${result.total_records || 0} file history rows processed successfully.`, 'success');
        } catch (error) {
            console.error('File history upload failed:', error);
            this.showAlert(error.message || 'Upload failed. Please try again.', 'danger');
            this.resetSessionData({ keepFileInput: true });
        } finally {
            this.isUploading = false;
            this.hideLoadingModal();
            this.showUploadProgress(false);
            this.disableUpload(false);
        }
    }

    validateFileFormat(file) {
        const allowedExtensions = ['.csv', '.xls', '.xlsx'];
        const allowedMimeTypes = [
            'text/csv',
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        ];

        const fileName = file.name?.toLowerCase() || '';
        const hasValidExtension = allowedExtensions.some((ext) => fileName.endsWith(ext));
        const hasValidMime = file.type ? allowedMimeTypes.includes(file.type) : true;

        return hasValidExtension && hasValidMime;
    }

    async extractErrorMessage(response) {
        try {
            const data = await response.json();
            if (data?.detail) {
                return data.detail;
            }
            if (data?.message) {
                return data.message;
            }
        } catch (error) {
            // Ignore JSON parse errors
        }
        return `Request failed with status ${response.status}`;
    }

    updateProgress(percent, labelText) {
        const progressBar = document.getElementById('historyProgressBar');
        const progressText = document.getElementById('historyProgressText');

        if (progressBar) {
            const value = Math.max(0, Math.min(Number(percent) || 0, 100));
            progressBar.style.width = `${value}%`;
            progressBar.setAttribute('aria-valuenow', value.toString());
            progressBar.textContent = `${value}%`;
        }

        if (progressText && labelText) {
            progressText.textContent = labelText;
        }
    }

    showUploadProgress(visible) {
        const progressContainer = document.getElementById('historyUploadProgress');
        if (progressContainer) {
            progressContainer.style.display = visible ? 'block' : 'none';
        }
    }

    disableUpload(disabled) {
        const uploadBtn = document.getElementById('historyUploadBtn');
        const fileInput = document.getElementById('historyFileInput');

        if (uploadBtn) {
            uploadBtn.disabled = disabled;
        }
        if (fileInput) {
            fileInput.disabled = disabled;
        }
    }

    showLoadingModal() {
        const modalElement = document.getElementById('historyLoadingModal');
        if (!modalElement || !window.bootstrap?.Modal) {
            return;
        }

        if (!this.loadingModal) {
            this.loadingModal = new bootstrap.Modal(modalElement);
        }
        this.loadingModal.show();
    }

    hideLoadingModal() {
        if (this.loadingModal) {
            this.loadingModal.hide();
        }
    }

    resetSessionData(options = {}) {
        const { keepFileInput = false } = options;

        this.propertyRecords = [];
        this.cofoRecords = [];
        this.filteredRows = [];
        this.sessionId = null;
        this.qcIssues = {};
        this.currentTab = 'records';
        this.currentFilter = 'all';
        this.currentPage = 1;

        this.updateFilterButtons();
        this.clearTableBodies();
        this.hidePreviewSection();
        this.resetValidationPanel();
        this.resetStatistics();
        this.updateCounts();
        this.updateShowingInfo(0);
        this.renderPagination();
        this.setImportButtonState(0);
        this.setTableVisibility();

        if (!keepFileInput) {
            const fileInput = document.getElementById('historyFileInput');
            if (fileInput) {
                fileInput.value = '';
            }
        }
    }

    clearTableBodies() {
        const recordsBody = document.getElementById('historyRecordsTableBody');
        const cofoBody = document.getElementById('historyCofoTableBody');

        if (recordsBody) {
            recordsBody.innerHTML = '';
        }
        if (cofoBody) {
            cofoBody.innerHTML = '';
        }
    }

    hidePreviewSection() {
        const previewSection = document.getElementById('historyPreviewSection');
        if (previewSection) {
            previewSection.style.display = 'none';
        }
    }

    showPreviewSection() {
        const previewSection = document.getElementById('historyPreviewSection');
        if (previewSection) {
            previewSection.style.display = 'block';
        }
    }

    resetValidationPanel() {
        const panel = document.getElementById('historyValidationPanel');
        const summaryContainer = document.getElementById('historyQcSummaryContainer');
        const issuesBody = document.getElementById('historyQcIssuesBody');
        const emptyState = document.getElementById('historyQcEmptyState');
        const table = document.getElementById('historyQcIssuesTable');

        if (summaryContainer) {
            summaryContainer.innerHTML = '';
        }
        if (issuesBody) {
            issuesBody.innerHTML = '';
        }
        if (emptyState) {
            emptyState.style.display = 'none';
        }
        if (table) {
            table.style.display = 'none';
        }
        if (panel) {
            panel.style.display = 'none';
        }
    }

    resetStatistics() {
        this.updateElementText('historyTotalRecords', 0);
        this.updateElementText('historyDuplicateRecords', 0);
        this.updateElementText('historyValidationIssues', 0);
        this.updateElementText('historyReadyRecords', 0);

        const statRow = document.getElementById('historyStatisticsRow');
        if (statRow) {
            statRow.style.display = 'none';
        }
    }

    updateStatistics(result) {
        const total = result?.total_records ?? 0;
        const duplicates = result?.duplicate_count ?? 0;
        const validation = result?.validation_issues ?? 0;
        const ready = result?.ready_records ?? 0;

        this.updateElementText('historyTotalRecords', total);
        this.updateElementText('historyDuplicateRecords', duplicates);
        this.updateElementText('historyValidationIssues', validation);
        this.updateElementText('historyReadyRecords', ready);

        const statRow = document.getElementById('historyStatisticsRow');
        if (statRow) {
            statRow.style.display = 'flex';
        }
    }

    updatePreview() {
        this.updateCounts();
        this.setTableVisibility();
        this.currentTab = 'records';
        this.currentFilter = 'all';
        this.currentPage = 1;
        this.updateFilterButtons();
        this.applyFilter();
        this.showPreviewSection();
    }

    updateCounts() {
        this.updateElementText('historyRecordsCount', this.propertyRecords.length);
        this.updateElementText('historyCofoCount', this.cofoRecords.length);
        this.updateFileNumberIssueCount();
    }

    updateElementText(id, value) {
        const element = document.getElementById(id);
        if (!element) {
            return;
        }

        if (typeof value === 'number') {
            element.textContent = Number.isFinite(value) ? value.toString() : '0';
        } else if (value === null || value === undefined) {
            element.textContent = '';
        } else {
            element.textContent = value;
        }
    }

    setTableVisibility() {
        const recordsWrapper = document.getElementById('historyRecordsTableWrapper');
        const cofoWrapper = document.getElementById('historyCofoTableWrapper');
        const qcWrapper = document.getElementById('historyFileNumberQcWrapper');

        if (recordsWrapper) {
            recordsWrapper.style.display = this.propertyRecords.length ? 'block' : 'none';
        }
        if (cofoWrapper) {
            cofoWrapper.style.display = this.cofoRecords.length ? 'block' : 'none';
        }
        if (qcWrapper) {
            if (this.currentTab === 'file-number-qc') {
                qcWrapper.style.display = qcWrapper.dataset.hasIssues === 'true' ? 'block' : 'none';
            } else {
                qcWrapper.style.display = 'none';
            }
        }
    }

    toggleFilterControls(isVisible) {
        if (!this.filterControls) {
            return;
        }
        this.filterControls.style.display = isVisible ? 'inline-flex' : 'none';
    }

    setImportButtonState(readyRecords) {
        const importBtn = document.getElementById('importHistoryBtn');
        if (!importBtn) {
            return;
        }

        const readyCount = Number(readyRecords) || 0;
        importBtn.disabled = !this.sessionId || readyCount === 0;
        importBtn.dataset.readyCount = readyCount.toString();
    }

    updateFilterButtons() {
        const buttons = {
            all: document.getElementById('historyShowAllBtn'),
            issues: document.getElementById('historyShowIssuesBtn'),
            valid: document.getElementById('historyShowValidBtn')
        };

        Object.entries(buttons).forEach(([key, button]) => {
            if (!button) {
                return;
            }
            if (this.currentFilter === key) {
                button.classList.add('active');
            } else {
                button.classList.remove('active');
            }
        });
    }

    setFilter(filter) {
        if (!filter || this.currentFilter === filter) {
            return;
        }

        this.currentFilter = filter;
        this.currentPage = 1;
        this.updateFilterButtons();
        this.applyFilter();
    }

    handleTabChange(tab) {
        if (!['records', 'cofo', 'file-number-qc'].includes(tab)) {
            return;
        }

        this.currentTab = tab;
        this.currentPage = 1;
        this.toggleFilterControls(tab !== 'file-number-qc');
        this.setTableVisibility();

        if (tab === 'file-number-qc') {
            this.renderFileNumberQcTable();
            this.updateShowingInfoForQc(this.countFileNumberIssues());
            const pagination = document.getElementById('historyPagination');
            if (pagination) {
                pagination.innerHTML = '';
            }
            return;
        }

        this.applyFilter();
    }

    applyFilter() {
        if (this.currentTab === 'file-number-qc') {
            return;
        }
        const sourceData = this.currentTab === 'records' ? this.propertyRecords : this.cofoRecords;
        const decorated = sourceData.map((record, index) => ({ record, index }));

        let filtered = decorated;
        if (this.currentFilter === 'issues') {
            filtered = decorated.filter((item) => item.record?.hasIssues);
        } else if (this.currentFilter === 'valid') {
            filtered = decorated.filter((item) => !item.record?.hasIssues);
        }

        this.filteredRows = filtered;

        const totalPages = Math.max(1, Math.ceil(Math.max(this.filteredRows.length, 1) / this.itemsPerPage));
        if (this.currentPage > totalPages) {
            this.currentPage = 1;
        }

        this.renderTable();
        this.renderPagination();
    }

    renderTable() {
        if (this.currentTab === 'file-number-qc') {
            return;
        }
        const bodyId = this.currentTab === 'records' ? 'historyRecordsTableBody' : 'historyCofoTableBody';
        const tableBody = document.getElementById(bodyId);
        if (!tableBody) {
            return;
        }

        const sourceData = this.currentTab === 'records' ? this.propertyRecords : this.cofoRecords;

        tableBody.innerHTML = '';

        if (!this.filteredRows.length) {
            const columnCount = this.currentTab === 'records' ? 15 : 13;
            const message = sourceData.length
                ? 'No rows match the current filter.'
                : 'Upload a file to preview records.';
            tableBody.innerHTML = `
                <tr>
                    <td colspan="${columnCount}" class="text-center text-muted py-4">
                        ${message}
                    </td>
                </tr>
            `;
            this.updateShowingInfo(0);
            return;
        }

        const startIndex = (this.currentPage - 1) * this.itemsPerPage;
        const pageItems = this.filteredRows.slice(startIndex, startIndex + this.itemsPerPage);

        pageItems.forEach((item, offset) => {
            const displayIndex = startIndex + offset + 1;
            const row = this.currentTab === 'records'
                ? this.createPropertyRecordRow(item, displayIndex)
                : this.createCofoRow(item, displayIndex);
            tableBody.appendChild(row);
        });

        this.updateShowingInfo(this.filteredRows.length);
    }

    createPropertyRecordRow(item, displayIndex) {
        const { record, index } = item;
        const tr = document.createElement('tr');

        if (record?.hasIssues) {
            tr.classList.add('table-warning');
        }

        const fileNumber = this.sanitizeValue(record?.mlsFNo);
        const transactionType = this.sanitizeValue(record?.transaction_type);
        const assignor = this.resolvePreferredValue(
            record?.Assignor,
            record?.Grantor,
            record?.grantor_assignor,
            record?.OriginalHolder
        );
        const assignee = this.resolvePreferredValue(
            record?.Assignee,
            record?.Grantee,
            record?.grantee_assignee,
            record?.CurrentHolder
        );
        const landUse = this.sanitizeValue(record?.land_use);
        const location = this.sanitizeValue(record?.location);
        const transactionDate = this.resolvePreferredValue(record?.transaction_date, record?.transaction_date_raw);
        const serialNo = this.sanitizeValue(record?.serialNo);
        const pageNo = this.sanitizeValue(record?.pageNo);
        const volumeNo = this.sanitizeValue(record?.volumeNo);
        const regDate = this.resolvePreferredValue(record?.reg_date, record?.reg_date_raw, record?.date_created);
        const createdBy = this.resolvePreferredValue(record?.created_by, record?.CreatedBy);
        const statusBadge = this.buildStatusBadge(record?.hasIssues);

        const columnConfigs = [
            { kind: 'text', value: displayIndex.toString() },
            { kind: 'editable', field: 'mlsFNo', value: fileNumber },
            { kind: 'editable', field: 'transaction_type', value: transactionType },
            { kind: 'editable', field: 'Assignor', value: assignor },
            { kind: 'editable', field: 'Assignee', value: assignee },
            { kind: 'editable', field: 'land_use', value: landUse },
            { kind: 'editable', field: 'location', value: location },
            { kind: 'editable', field: 'transaction_date', value: transactionDate },
            { kind: 'editable', field: 'serialNo', value: serialNo },
            { kind: 'editable', field: 'pageNo', value: pageNo },
            { kind: 'editable', field: 'volumeNo', value: volumeNo },
            { kind: 'editable', field: 'reg_date', value: regDate },
            { kind: 'editable', field: 'created_by', value: createdBy },
            { kind: 'status', html: statusBadge },
            { kind: 'actions', typeKey: 'records', rowIndex: index }
        ];

        columnConfigs.forEach((config) => {
            const td = document.createElement('td');
            switch (config.kind) {
                case 'text':
                    td.textContent = config.value ?? '';
                    break;
                case 'editable':
                    td.textContent = config.value ?? '';
                    this.attachInlineEditing(td, 'records', index, config.field);
                    break;
                case 'status':
                    td.innerHTML = config.html ?? '';
                    break;
                case 'actions':
                    td.classList.add('text-center');
                    this.appendDeleteButton(td, config.typeKey, config.rowIndex);
                    break;
                default:
                    td.textContent = config.value ?? '';
            }
            tr.appendChild(td);
        });

        return tr;
    }

    createCofoRow(item, displayIndex) {
        const { record, index } = item;
        const tr = document.createElement('tr');

        if (record?.hasIssues) {
            tr.classList.add('table-warning');
        }

        const fileNumber = this.sanitizeValue(record?.mlsFNo);
        const transactionType = this.sanitizeValue(record?.transaction_type);
        const assignor = this.resolvePreferredValue(record?.Assignor, record?.Grantor);
        const assignee = this.resolvePreferredValue(record?.Assignee, record?.Grantee);
        const transactionDate = this.resolvePreferredValue(record?.transaction_date, record?.transaction_date_raw);
        const transactionTime = this.resolvePreferredValue(record?.transaction_time, record?.transaction_time_raw);
        const serialNo = this.sanitizeValue(record?.serialNo);
        const pageNo = this.sanitizeValue(record?.pageNo);
        const volumeNo = this.sanitizeValue(record?.volumeNo);
        const regNo = this.sanitizeValue(record?.regNo);
        const statusBadge = this.buildStatusBadge(record?.hasIssues);

        const columnConfigs = [
            { kind: 'text', value: displayIndex.toString() },
            { kind: 'editable', field: 'mlsFNo', value: fileNumber },
            { kind: 'editable', field: 'transaction_type', value: transactionType },
            { kind: 'editable', field: 'Assignor', value: assignor },
            { kind: 'editable', field: 'Assignee', value: assignee },
            { kind: 'editable', field: 'transaction_date', value: transactionDate },
            { kind: 'editable', field: 'transaction_time', value: transactionTime },
            { kind: 'editable', field: 'serialNo', value: serialNo },
            { kind: 'editable', field: 'pageNo', value: pageNo },
            { kind: 'editable', field: 'volumeNo', value: volumeNo },
            { kind: 'editable', field: 'regNo', value: regNo },
            { kind: 'status', html: statusBadge },
            { kind: 'actions', typeKey: 'cofo', rowIndex: index }
        ];

        columnConfigs.forEach((config) => {
            const td = document.createElement('td');
            switch (config.kind) {
                case 'text':
                    td.textContent = config.value ?? '';
                    break;
                case 'editable':
                    td.textContent = config.value ?? '';
                    this.attachInlineEditing(td, 'cofo', index, config.field);
                    break;
                case 'status':
                    td.innerHTML = config.html ?? '';
                    break;
                case 'actions':
                    td.classList.add('text-center');
                    this.appendDeleteButton(td, config.typeKey, config.rowIndex);
                    break;
                default:
                    td.textContent = config.value ?? '';
            }
            tr.appendChild(td);
        });

        return tr;
    }

    appendDeleteButton(cell, recordType, rowIndex) {
        if (!cell) {
            return;
        }

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm btn-outline-danger history-delete-btn';
        button.innerHTML = '<i class="fas fa-trash-alt me-1"></i>Delete';
        button.addEventListener('click', (event) => {
            event.preventDefault();
            this.confirmDeleteRow(recordType, rowIndex);
        });

        cell.appendChild(button);
    }

    attachInlineEditing(cell, recordType, rowIndex, field) {
        if (!cell) {
            return;
        }

        cell.classList.add('inline-editable');
        cell.tabIndex = 0;

        const activateEdit = (event) => {
            event.preventDefault();
            this.beginInlineEdit(cell, recordType, rowIndex, field);
        };

        cell.addEventListener('click', activateEdit);
        cell.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                activateEdit(event);
            }
        });
    }

    beginInlineEdit(cell, recordType, rowIndex, field) {
        if (!cell || cell.dataset.editing === 'true') {
            return;
        }

        if (this.activeInlineEdit) {
            this.cancelInlineEdit(false);
        }

        const originalValue = this.sanitizeValue(cell.textContent);
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control form-control-sm inline-edit-input';
        input.value = originalValue;

        const handleBlur = () => {
            this.commitInlineEdit(true);
        };

        const handleKeydown = (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                this.commitInlineEdit(true);
            } else if (event.key === 'Escape') {
                event.preventDefault();
                this.cancelInlineEdit(false);
            }
        };

        cell.dataset.editing = 'true';
        cell.classList.add('inline-editing');
        cell.textContent = '';
        cell.appendChild(input);

        this.activeInlineEdit = {
            cell,
            input,
            originalValue,
            recordType,
            rowIndex,
            field,
            handleBlur,
            handleKeydown
        };

        input.addEventListener('blur', handleBlur);
        input.addEventListener('keydown', handleKeydown);

        requestAnimationFrame(() => {
            input.focus();
            input.select();
        });
    }

    async commitInlineEdit(applyChanges = true) {
        if (!this.activeInlineEdit) {
            return;
        }

        const {
            cell,
            input,
            originalValue,
            recordType,
            rowIndex,
            field,
            handleBlur,
            handleKeydown
        } = this.activeInlineEdit;

        input.removeEventListener('blur', handleBlur);
        input.removeEventListener('keydown', handleKeydown);

        const nextValue = applyChanges ? input.value : originalValue;
        const sanitized = this.sanitizeValue(nextValue);

        cell.classList.remove('inline-editing');
        cell.dataset.editing = 'false';
        cell.textContent = sanitized;

        this.activeInlineEdit = null;

        if (!applyChanges || nextValue === originalValue) {
            return;
        }

        cell.classList.add('inline-saving');

        await this.updateField(recordType, rowIndex, field, nextValue, {
            onError: () => {
                cell.textContent = this.sanitizeValue(originalValue);
            }
        });

        cell.classList.remove('inline-saving');
    }

    async cancelInlineEdit(applyChanges = false) {
        await this.commitInlineEdit(applyChanges);
    }

    async updateField(recordType, rowIndex, field, value, options = {}) {
        if (!this.sessionId) {
            this.showAlert('Your preview session has expired. Please upload the file again.', 'warning');
            return false;
        }

        const payload = {
            record_index: rowIndex,
            record_type: recordType,
            field,
            value
        };

        try {
            const response = await fetch(`/api/file-history/update/${this.sessionId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                throw new Error(await this.extractErrorMessage(response));
            }

            const result = await response.json();
            this.applySessionUpdate(result);

            if (options.successMessage) {
                this.showAlert(options.successMessage, 'success');
            }

            return true;
        } catch (error) {
            console.error('File history update failed:', error);
            this.showAlert(error.message || 'Update failed. Changes reverted.', 'danger');
            if (typeof options.onError === 'function') {
                options.onError(error);
            }
            return false;
        }
    }

    async confirmDeleteRow(recordType, rowIndex) {
        if (!this.sessionId) {
            this.showAlert('Please upload a file before deleting rows.', 'warning');
            return;
        }

        if (!Number.isInteger(rowIndex) || rowIndex < 0) {
            return;
        }

        this.cancelInlineEdit(false);

        const confirmation = window.confirm('Remove this row from the preview? This cannot be undone.');
        if (!confirmation) {
            return;
        }

        await this.deleteRecord(recordType, rowIndex);
    }

    async deleteRecord(recordType, rowIndex) {
        const payload = {
            record_index: rowIndex,
            record_type: recordType
        };

        try {
            const response = await fetch(`/api/file-history/delete/${this.sessionId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                throw new Error(await this.extractErrorMessage(response));
            }

            const result = await response.json();
            this.applySessionUpdate(result);
            this.showAlert('Row removed from preview.', 'success');
        } catch (error) {
            console.error('File history delete failed:', error);
            this.showAlert(error.message || 'Unable to remove row. Please try again.', 'danger');
        }
    }

    applySessionUpdate(result) {
        if (!result || typeof result !== 'object') {
            return;
        }

        if (Array.isArray(result.property_records)) {
            this.propertyRecords = result.property_records;
        }
        if (Array.isArray(result.cofo_records)) {
            this.cofoRecords = result.cofo_records;
        }

        this.qcIssues = result.issues || {};

        this.updateCounts();
        this.updateStatistics(result);
        this.setImportButtonState(result.ready_records);
        this.setTableVisibility();

        if (this.currentTab === 'file-number-qc') {
            this.renderFileNumberQcTable();
            this.updateShowingInfoForQc(this.countFileNumberIssues());
        } else {
            this.applyFilter();
        }

        this.showValidationIssues(this.qcIssues);
    }

    collectFileNumberIssues() {
        const issues = [];
        this.fileNumberIssueTypes.forEach((category) => {
            const items = this.qcIssues?.[category];
            if (!Array.isArray(items)) {
                return;
            }
            items.forEach((item) => {
                issues.push({
                    ...item,
                    category
                });
            });
        });
        return issues;
    }

    renderFileNumberQcTable() {
        const wrapper = document.getElementById('historyFileNumberQcWrapper');
        const tbody = document.getElementById('historyFileNumberQcBody');
        const emptyState = document.getElementById('historyFileNumberQcEmpty');

        if (!wrapper || !tbody || !emptyState) {
            return;
        }

        const issues = this.collectFileNumberIssues();
        const hasIssues = issues.length > 0;

        wrapper.dataset.hasIssues = hasIssues ? 'true' : 'false';
        wrapper.style.display = hasIssues ? 'block' : 'none';
        emptyState.classList.toggle('d-none', hasIssues);

        if (!hasIssues) {
            tbody.innerHTML = '';
            return;
        }

        tbody.innerHTML = '';

        issues.forEach((issue, index) => {
            const row = this.buildFileNumberQcRow(issue, index + 1);
            tbody.appendChild(row);
        });
    }

    buildFileNumberQcRow(issue, displayIndex) {
        const tr = document.createElement('tr');

        const categoryConfig = this.getCategoryConfig(issue.category);
        const issueLabel = categoryConfig?.label || this.formatCategoryName(issue.category);
        const description = issue.description || issue.message || issue.issue_description || '';
        const suggestedFix = issue.suggested_fix || '';
        const severity = issue.severity || 'Medium';
        const fileNumber = this.sanitizeValue(issue.file_number || issue.fileNumber || '');

        const cells = [
            { kind: 'text', value: displayIndex.toString() },
            { kind: 'text', value: issueLabel },
            { kind: 'code', value: fileNumber },
            { kind: 'text', value: description },
            { kind: 'code', value: suggestedFix },
            { kind: 'badge', value: severity },
            { kind: 'actions', value: issue }
        ];

        cells.forEach((config) => {
            const td = document.createElement('td');
            switch (config.kind) {
                case 'code':
                    td.innerHTML = config.value ? `<code>${this.escapeHtml(config.value)}</code>` : '<span class="text-muted">—</span>';
                    break;
                case 'badge':
                    td.innerHTML = this.formatSeverityBadge(config.value);
                    break;
                case 'actions': {
                    td.classList.add('text-center');
                    if (config.value?.suggested_fix && Number.isInteger(config.value.record_index)) {
                        const applyBtn = document.createElement('button');
                        applyBtn.type = 'button';
                        applyBtn.className = 'btn btn-sm btn-outline-primary';
                        applyBtn.innerHTML = '<i class="fas fa-magic me-1"></i>Apply Fix';
                        applyBtn.addEventListener('click', () => this.applyFileNumberFix(config.value));
                        td.appendChild(applyBtn);
                    } else {
                        td.innerHTML = '<span class="text-muted">Manual review</span>';
                    }
                    break;
                }
                default:
                    td.textContent = config.value ?? '';
            }
            tr.appendChild(td);
        });

        return tr;
    }

    formatSeverityBadge(severity) {
        const normalized = (severity || '').toString().toLowerCase();
        const mapping = {
            high: 'danger',
            medium: 'warning',
            low: 'secondary'
        };
        const theme = mapping[normalized] || 'secondary';
        const label = severity || 'Medium';
        return `<span class="badge bg-${theme}">${this.escapeHtml(label)}</span>`;
    }

    async applyFileNumberFix(issue) {
        if (!issue || typeof issue.record_index !== 'number') {
            return;
        }

        const fix = issue.suggested_fix;
        if (!fix) {
            return;
        }

        await this.updateField('records', issue.record_index, 'mlsFNo', fix, {
            successMessage: `File number updated to ${this.escapeHtml(fix)}`,
            onError: () => {
                // No-op; updateField already shows alert
            }
        });
    }

    buildStatusBadge(hasIssues) {
        if (hasIssues) {
            return '<span class="badge bg-warning text-dark">Needs review</span>';
        }
        return '<span class="badge bg-success">Ready</span>';
    }

    renderPagination() {
        const pagination = document.getElementById('historyPagination');
        if (!pagination) {
            return;
        }

        const totalItems = this.filteredRows.length;
        if (totalItems === 0) {
            pagination.innerHTML = '';
            return;
        }

        const totalPages = Math.max(1, Math.ceil(totalItems / this.itemsPerPage));
        const pages = this.calculatePaginationPages(totalPages);

        let html = '';
        html += `
            <li class="page-item ${this.currentPage === 1 ? 'disabled' : ''}">
                <button type="button" class="page-link" data-page="${this.currentPage - 1}">Previous</button>
            </li>
        `;

        pages.forEach((page) => {
            if (page === 'ellipsis') {
                html += `
                    <li class="page-item disabled">
                        <span class="page-link">…</span>
                    </li>
                `;
            } else {
                html += `
                    <li class="page-item ${page === this.currentPage ? 'active' : ''}">
                        <button type="button" class="page-link" data-page="${page}">${page}</button>
                    </li>
                `;
            }
        });

        html += `
            <li class="page-item ${this.currentPage === totalPages ? 'disabled' : ''}">
                <button type="button" class="page-link" data-page="${this.currentPage + 1}">Next</button>
            </li>
        `;

        pagination.innerHTML = html;
    }

    calculatePaginationPages(totalPages) {
        if (totalPages <= 7) {
            return Array.from({ length: totalPages }, (_, idx) => idx + 1);
        }

        const pages = [1];
        if (this.currentPage > 4) {
            pages.push('ellipsis');
        }

        const start = Math.max(2, this.currentPage - 1);
        const end = Math.min(totalPages - 1, this.currentPage + 1);

        for (let page = start; page <= end; page += 1) {
            pages.push(page);
        }

        if (this.currentPage < totalPages - 3) {
            pages.push('ellipsis');
        }

        pages.push(totalPages);
        return pages;
    }

    goToPage(page) {
        const totalPages = Math.max(1, Math.ceil(Math.max(this.filteredRows.length, 1) / this.itemsPerPage));
        const nextPage = Math.min(Math.max(page, 1), totalPages);

        if (nextPage === this.currentPage) {
            return;
        }

        this.currentPage = nextPage;
        this.renderTable();
        this.renderPagination();
    }

    updateShowingInfo(total) {
        const totalCount = Number(total) || 0;
        const start = totalCount === 0 ? 0 : (this.currentPage - 1) * this.itemsPerPage + 1;
        const end = totalCount === 0
            ? 0
            : Math.min(this.currentPage * this.itemsPerPage, totalCount);

        this.updateElementText('historyShowingStart', start);
        this.updateElementText('historyShowingEnd', end);
        this.updateElementText('historyShowingTotal', totalCount);
    }

    updateShowingInfoForQc(total) {
        const count = Number(total) || 0;
        const start = count === 0 ? 0 : 1;
        this.updateElementText('historyShowingStart', start);
        this.updateElementText('historyShowingEnd', count);
        this.updateElementText('historyShowingTotal', count);
    }

    countFileNumberIssues() {
        return this.fileNumberIssueTypes.reduce((accumulator, key) => {
            const list = this.qcIssues?.[key];
            if (Array.isArray(list)) {
                return accumulator + list.length;
            }
            return accumulator;
        }, 0);
    }

    updateFileNumberIssueCount() {
        const issueCountElement = document.getElementById('historyFileNumberIssueCount');
        if (!issueCountElement) {
            return;
        }
        const total = this.countFileNumberIssues();
        issueCountElement.textContent = total.toString();
    }

    showValidationIssues(issues) {
        const panel = document.getElementById('historyValidationPanel');
        const summaryContainer = document.getElementById('historyQcSummaryContainer');
        const table = document.getElementById('historyQcIssuesTable');
        const tbody = document.getElementById('historyQcIssuesBody');
        const emptyState = document.getElementById('historyQcEmptyState');

        if (!panel || !summaryContainer || !table || !tbody || !emptyState) {
            return;
        }

        const normalizedIssues = this.normalizeIssues(issues);

        const hasIssueEntries = Object.values(normalizedIssues).some((list) => Array.isArray(list) && list.length);

        if (!hasIssueEntries) {
            this.resetValidationPanel();
            return;
        }

        panel.style.display = 'block';

        this.renderQcSummaryCards(summaryContainer, normalizedIssues);

        const detailRows = this.buildIssueDetailRows(normalizedIssues);
        this.renderIssueTable(table, tbody, detailRows);

        if (emptyState) {
            emptyState.style.display = detailRows.length === 0 ? 'block' : 'none';
        }
    }

    normalizeIssues(rawIssues = {}) {
        const normalized = {};
        Object.entries(rawIssues || {}).forEach(([key, value]) => {
            if (Array.isArray(value)) {
                normalized[key] = value;
                this.getCategoryConfig(key);
            }
        });

        this.categoryOrder.forEach((key) => {
            if (!normalized[key]) {
                normalized[key] = [];
            }
        });

        return normalized;
    }

    renderQcSummaryCards(container, issueMap) {
        if (!container) {
            return;
        }

        const fragment = document.createDocumentFragment();

        this.categoryOrder.forEach((key) => {
            const config = this.getCategoryConfig(key);
            const toneClasses = FILE_HISTORY_QC_TONE_CLASSMAP[config.tone] || FILE_HISTORY_QC_TONE_CLASSMAP.secondary;
            const borderClass = toneClasses?.border || 'border-secondary';
            const textClass = toneClasses?.text || 'text-secondary';
            const count = this.getCategoryCount(key, issueMap);

            const col = document.createElement('div');
            col.className = 'col-sm-6 col-lg-3';

            const card = document.createElement('div');
            card.className = `card shadow-sm ${borderClass}`;
            card.innerHTML = `
                <div class="card-body py-2">
                    <h6 class="mb-1 ${textClass}">${this.escapeHtml(config.label)}</h6>
                    <div class="fw-bold fs-5">${count}</div>
                </div>
            `;

            col.appendChild(card);
            fragment.appendChild(col);
        });

        container.innerHTML = '';
        container.appendChild(fragment);
    }

    getCategoryConfig(key) {
        if (!this.categoryConfig[key]) {
            this.categoryConfig[key] = {
                key,
                label: this.formatCategoryName(key),
                tone: 'secondary',
                severity: 'Medium'
            };
            this.categoryOrder.push(key);
        }
        return this.categoryConfig[key];
    }

    getCategoryCount(key, issueMap) {
        const list = issueMap[key];
        return Array.isArray(list) ? list.length : 0;
    }

    buildIssueDetailRows(issueMap) {
        const rows = [];

        Object.entries(issueMap).forEach(([key, items]) => {
            if (!Array.isArray(items) || !items.length) {
                return;
            }

            const config = this.getCategoryConfig(key);
            const label = config.label || this.formatCategoryName(key);
            const severity = config.severity || 'Medium';

            items.forEach((item) => {
                rows.push({
                    type: label,
                    fileNumber: this.sanitizeValue(item.file_number || item.fileNumber || item.mlsFNo),
                    details: this.composeIssueText(item),
                    severity,
                    notes: item.suggested_fix ? `Suggested fix: ${item.suggested_fix}` : ''
                });
            });
        });

        return rows;
    }

    renderIssueTable(table, tbody, rows) {
        if (!table || !tbody) {
            return;
        }

        if (!rows.length) {
            tbody.innerHTML = '';
            table.style.display = 'none';
            return;
        }

        table.style.display = '';
        tbody.innerHTML = rows.map((row) => `
            <tr>
                <td>${this.formatTableCell(row.type)}</td>
                <td>${this.formatTableCell(row.fileNumber)}</td>
                <td>${this.formatTableCell(row.details)}</td>
                <td>${this.formatTableCell(row.severity)}</td>
                <td>${this.formatTableCell(row.notes)}</td>
            </tr>
        `).join('');
    }

    formatTableCell(value, placeholder = '—') {
        const sanitized = this.sanitizeValue(value);
        if (!sanitized) {
            return `<span class="text-muted">${placeholder}</span>`;
        }
        return this.escapeHtml(sanitized);
    }

    formatCategoryName(category) {
        const friendly = {
            padding: 'Padding Issues',
            year: 'Year Issues',
            spacing: 'Spacing Issues',
            temp: 'TEMP Issues',
            missing_file_number: 'Missing File Numbers',
            missing_required_fields: 'Missing Required Fields',
            invalid_dates: 'Invalid Dates',
            missing_reg_components: 'Missing Reg Components'
        };
        return friendly[category] || category.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
    }

    composeIssueText(issue) {
        if (!issue || typeof issue !== 'object') {
            return '';
        }

        const parts = [];
        if (issue.row) {
            parts.push(`Row ${issue.row}`);
        }
        const fileNumber = this.sanitizeValue(issue.file_number || issue.fileNumber || issue.mlsFNo);
        if (fileNumber) {
            parts.push(`File ${fileNumber}`);
        }

        const message = issue.message || issue.description || issue.issue_description || issue.reason || '';
        if (message) {
            parts.push(message);
        } else if (issue.field) {
            const value = this.sanitizeValue(issue.value);
            parts.push(value ? `${issue.field}: ${value}` : issue.field);
        }

        return parts.join(' – ');
    }

    sanitizeValue(value) {
        if (value === null || value === undefined) {
            return '';
        }
        if (typeof value === 'number') {
            return Number.isFinite(value) ? value.toString() : '';
        }
        if (typeof value === 'string') {
            const trimmed = value.trim();
            if (!trimmed) {
                return '';
            }
            if (['nan', 'none', 'null', 'undefined'].includes(trimmed.toLowerCase())) {
                return '';
            }
            return trimmed;
        }
        return String(value);
    }

    resolvePreferredValue(...values) {
        for (const value of values) {
            const sanitized = this.sanitizeValue(value);
            if (sanitized) {
                return sanitized;
            }
        }
        return '';
    }

    escapeHtml(value) {
        const str = value ?? '';
        return str
            .toString()
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    showAlert(message, type = 'info') {
        const container = document.getElementById('historyAlertContainer');
        if (!container) {
            return;
        }

        const alertId = `history-alert-${Date.now()}`;
        const iconMap = {
            success: 'fa-check-circle',
            danger: 'fa-times-circle',
            warning: 'fa-exclamation-triangle',
            info: 'fa-info-circle'
        };
        const icon = iconMap[type] || iconMap.info;

        container.insertAdjacentHTML('beforeend', `
            <div class="alert alert-${type} alert-dismissible fade show" id="${alertId}">
                <i class="fas ${icon} me-2"></i>
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `);

        window.setTimeout(() => {
            const alert = document.getElementById(alertId);
            if (alert) {
                alert.remove();
            }
        }, 6000);
    }

    async importData() {
        if (!this.sessionId) {
            this.showAlert('Please upload and review a file before importing.', 'warning');
            return;
        }

        const readyCount = this.propertyRecords.filter((record) => !record?.hasIssues).length;
        if (readyCount === 0) {
            this.showAlert('No valid property records are ready for import.', 'warning');
            return;
        }

        if (!window.confirm(`Import ${readyCount} property record${readyCount === 1 ? '' : 's'} into the database?`)) {
            return;
        }

        this.showLoadingModal();
        this.updateProgress(25, 'Importing records…');

        try {
            const response = await fetch(`/api/import-file-history/${this.sessionId}`, {
                method: 'POST'
            });

            if (!response.ok) {
                throw new Error(await this.extractErrorMessage(response));
            }

            const result = await response.json();
            this.showAlert(
                `Import completed. ${result.imported_count || 0} record${result.imported_count === 1 ? '' : 's'} saved.`,
                'success'
            );

            this.resetSessionData();
        } catch (error) {
            console.error('File history import failed:', error);
            this.showAlert(error.message || 'Import failed. Please try again.', 'danger');
        } finally {
            this.hideLoadingModal();
            this.showUploadProgress(false);
            this.disableUpload(false);
        }
    }
}

let fileHistoryManager;

document.addEventListener('DOMContentLoaded', () => {
    fileHistoryManager = new FileHistoryImportManager();
    window.fileHistoryManager = fileHistoryManager;
});
