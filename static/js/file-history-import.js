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
        this.duplicates = { csv: [], database: [] };
        this.loadingModal = null;
    this.isUploading = false;

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
            this.duplicates = result.duplicates || { csv: [], database: [] };

            this.updateProgress(70, 'Rendering preview…');
            this.updateStatistics(result);
            this.updatePreview();
            this.showValidationIssues(this.qcIssues, this.duplicates);
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
        this.duplicates = { csv: [], database: [] };
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
        const list = document.getElementById('historyValidationIssuesList');

        if (list) {
            list.innerHTML = '';
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

        if (recordsWrapper) {
            recordsWrapper.style.display = this.propertyRecords.length ? 'block' : 'none';
        }
        if (cofoWrapper) {
            cofoWrapper.style.display = this.cofoRecords.length ? 'block' : 'none';
        }
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
        if (tab !== 'records' && tab !== 'cofo') {
            return;
        }

        this.currentTab = tab;
        this.currentPage = 1;
        this.setTableVisibility();
        this.applyFilter();
    }

    applyFilter() {
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
        const transactionDate = this.resolvePreferredValue(record?.transaction_date, record?.transaction_date_raw);
        const regDate = this.resolvePreferredValue(record?.reg_date, record?.reg_date_raw, record?.date_created);
        const statusBadge = this.buildStatusBadge(record?.hasIssues);

        tr.innerHTML = `
            <td>${displayIndex}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.mlsFNo))}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.transaction_type))}</td>
            <td>${this.escapeHtml(assignor)}</td>
            <td>${this.escapeHtml(assignee)}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.land_use))}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.location))}</td>
            <td>${this.escapeHtml(transactionDate)}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.serialNo))}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.pageNo))}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.volumeNo))}</td>
            <td>${this.escapeHtml(regDate)}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.created_by || record?.CreatedBy))}</td>
            <td>${statusBadge}</td>
            <td class="text-center">
                ${this.buildActionButton('records', index)}
            </td>
        `;

        const detailBtn = tr.querySelector('.history-detail-btn');
        detailBtn?.addEventListener('click', (event) => {
            const btn = event.currentTarget;
            const dataIndex = Number.parseInt(btn.dataset.recordIndex, 10);
            if (!Number.isNaN(dataIndex)) {
                this.showRecordDetails('records', dataIndex);
            }
        });

        return tr;
    }

    createCofoRow(item, displayIndex) {
        const { record, index } = item;
        const tr = document.createElement('tr');

        if (record?.hasIssues) {
            tr.classList.add('table-warning');
        }

        const assignor = this.resolvePreferredValue(record?.Assignor, record?.Grantor);
        const assignee = this.resolvePreferredValue(record?.Assignee, record?.Grantee);
        const transactionDate = this.resolvePreferredValue(record?.transaction_date, record?.transaction_date_raw);
        const transactionTime = this.resolvePreferredValue(record?.transaction_time, record?.transaction_time_raw);
        const statusBadge = this.buildStatusBadge(record?.hasIssues);

        tr.innerHTML = `
            <td>${displayIndex}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.mlsFNo))}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.transaction_type))}</td>
            <td>${this.escapeHtml(assignor)}</td>
            <td>${this.escapeHtml(assignee)}</td>
            <td>${this.escapeHtml(transactionDate)}</td>
            <td>${this.escapeHtml(transactionTime)}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.serialNo))}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.pageNo))}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.volumeNo))}</td>
            <td>${this.escapeHtml(this.sanitizeValue(record?.regNo))}</td>
            <td>${statusBadge}</td>
            <td class="text-center">
                ${this.buildActionButton('cofo', index)}
            </td>
        `;

        const detailBtn = tr.querySelector('.history-detail-btn');
        detailBtn?.addEventListener('click', (event) => {
            const btn = event.currentTarget;
            const dataIndex = Number.parseInt(btn.dataset.recordIndex, 10);
            if (!Number.isNaN(dataIndex)) {
                this.showRecordDetails('cofo', dataIndex);
            }
        });

        return tr;
    }

    buildStatusBadge(hasIssues) {
        if (hasIssues) {
            return '<span class="badge bg-warning text-dark">Needs review</span>';
        }
        return '<span class="badge bg-success">Ready</span>';
    }

    buildActionButton(type, index) {
        return `
            <button type="button"
                    class="btn btn-sm btn-outline-secondary history-detail-btn"
                    data-history-type="${type}"
                    data-record-index="${index}">
                <i class="fas fa-list me-1"></i>
                Details
            </button>
        `;
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

    showValidationIssues(issues, duplicates) {
        const panel = document.getElementById('historyValidationPanel');
        const list = document.getElementById('historyValidationIssuesList');

        if (!panel || !list) {
            return;
        }

        const issueEntries = Object.entries(issues || {}).filter(([, value]) => Array.isArray(value) && value.length);
        const csvDuplicates = Array.isArray(duplicates?.csv) ? duplicates.csv : [];
        const dbDuplicates = Array.isArray(duplicates?.database) ? duplicates.database : [];

        if (!issueEntries.length && !csvDuplicates.length && !dbDuplicates.length) {
            this.resetValidationPanel();
            return;
        }

        let html = '';

        issueEntries.forEach(([category, items]) => {
            html += `
                <div class="mb-3">
                    <h6 class="text-warning mb-1">
                        <i class="fas fa-exclamation-circle me-1"></i>
                        ${this.formatCategoryName(category)} (${items.length})
                    </h6>
                    <ul class="small text-muted ps-3 mb-0">
                        ${items.map((item) => `<li>${this.escapeHtml(this.composeIssueText(item))}</li>`).join('')}
                    </ul>
                </div>
            `;
        });

        if (csvDuplicates.length) {
            html += this.buildDuplicateList(csvDuplicates, 'CSV');
        }
        if (dbDuplicates.length) {
            html += this.buildDuplicateList(dbDuplicates, 'Database');
        }

        list.innerHTML = html;
        panel.style.display = 'block';
    }

    formatCategoryName(category) {
        const friendly = {
            padding: 'Padding issues',
            year: 'Year format issues',
            spacing: 'Spacing issues',
            temp: 'TEMP notation concerns',
            missing_file_number: 'Missing file numbers',
            missing_required_fields: 'Missing required fields',
            invalid_dates: 'Un-parsable dates',
            missing_reg_components: 'Incomplete registry details'
        };
        return friendly[category] || category.replace(/_/g, ' ');
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

    buildDuplicateList(duplicates, label) {
        const items = duplicates.slice(0, 10).map((duplicate) => {
            const fileNumber = this.escapeHtml(this.sanitizeValue(duplicate.file_number));
            const count = duplicate.count || duplicate.records?.length || '';
            return `
                <li>
                    <strong>${fileNumber || 'Unknown file number'}</strong>
                    appears ${count} time(s).
                </li>
            `;
        }).join('');

        const extraCount = Math.max(duplicates.length - 10, 0);
        const extraHtml = extraCount > 0
            ? `<li class="text-muted">…and ${extraCount} more</li>`
            : '';

        return `
            <div class="mb-3">
                <h6 class="text-warning mb-1">
                    <i class="fas fa-clone me-1"></i>
                    ${label} duplicates (${duplicates.length})
                </h6>
                <ul class="small text-muted ps-3 mb-0">
                    ${items}${extraHtml}
                </ul>
            </div>
        `;
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

    ensureDetailModal() {
        let modal = document.getElementById('historyRecordDetailModal');
        if (modal) {
            return modal;
        }

        modal = document.createElement('div');
        modal.id = 'historyRecordDetailModal';
        modal.className = 'modal fade';
        modal.setAttribute('tabindex', '-1');
        modal.setAttribute('aria-hidden', 'true');

        modal.innerHTML = `
            <div class="modal-dialog modal-lg modal-dialog-scrollable">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Record details</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body" id="historyRecordDetailContent"></div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        return modal;
    }

    showRecordDetails(type, index) {
        const source = type === 'cofo' ? this.cofoRecords : this.propertyRecords;
        const record = source[index];
        if (!record) {
            return;
        }

        const modalElement = this.ensureDetailModal();
        const title = modalElement.querySelector('.modal-title');
        const content = modalElement.querySelector('#historyRecordDetailContent');

        if (title) {
            const fileNumber = this.sanitizeValue(record.mlsFNo || record.file_number);
            title.textContent = `${type === 'cofo' ? 'CofO record' : 'Property record'} — ${fileNumber || 'Details'}`;
        }

        if (content) {
            content.innerHTML = this.buildDetailsTable(record);
        }

        if (window.bootstrap?.Modal) {
            const modalInstance = bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
            modalInstance.show();
        }
    }

    buildDetailsTable(record) {
        const entries = Object.entries(record || {})
            .filter(([, value]) => this.sanitizeValue(value))
            .sort(([keyA], [keyB]) => keyA.localeCompare(keyB));

        if (!entries.length) {
            return '<p class="text-muted mb-0">No additional fields to display for this record.</p>';
        }

        const rows = entries
            .map(([key, value]) => `
                <tr>
                    <th scope="row" class="text-nowrap">${this.escapeHtml(key)}</th>
                    <td>${this.escapeHtml(this.sanitizeValue(value))}</td>
                </tr>
            `)
            .join('');

        return `
            <div class="table-responsive">
                <table class="table table-sm table-bordered mb-0">
                    <tbody>
                        ${rows}
                    </tbody>
                </table>
            </div>
        `;
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
