const PIC_QC_CATEGORY_CONFIG = [
    { key: 'padding', label: 'Padding Issues', tone: 'warning', severity: 'Medium' },
    { key: 'year', label: 'Year Issues', tone: 'danger', severity: 'High' },
    { key: 'spacing', label: 'Spacing Issues', tone: 'info', severity: 'Medium' },
    { key: 'missing_file_number', label: 'Missing File Numbers', tone: 'danger', severity: 'High' }
];

const PIC_QC_TONE_CLASSMAP = {
    warning: { border: 'border-warning', text: 'text-warning' },
    danger: { border: 'border-danger', text: 'text-danger' },
    info: { border: 'border-info', text: 'text-info' },
    secondary: { border: 'border-secondary', text: 'text-secondary' },
    success: { border: 'border-success', text: 'text-success' },
    primary: { border: 'border-primary', text: 'text-primary' }
};

const PIC_FILE_NUMBER_ISSUE_TYPES = ['padding', 'year', 'spacing', 'missing_file_number'];

class PropertyIndexCardImportManager {
    constructor() {
        this.propertyRecords = [];
        this.cofoRecords = [];
        this.fileNumberRecords = [];
        this.entityStagingRecords = [];
        this.customerStagingRecords = [];
        this.filteredRows = [];
        this.currentTab = 'records';
        this.currentFilter = 'all';
        this.currentPage = 1;
        this.itemsPerPage = 20;
        this.sessionId = null;
        this.qcIssues = {};
        this.testControlMode = '';
        this.isUploading = false;
        this.isClearingMode = false;
        this.isApplyingFixAll = false;
        this.uploadManuallyDisabled = false;
        this.loadingModal = null;
        this.activeInlineEdit = null;
        this.customerLookupByEntityId = new Map();
        this.customerLookupByFileNumber = new Map();

        this.fileNumberIssueTypes = [...PIC_FILE_NUMBER_ISSUE_TYPES];
        this.categoryConfig = {};
        this.categoryOrder = [];

        PIC_QC_CATEGORY_CONFIG.forEach((config) => {
            this.categoryConfig[config.key] = { ...config };
            this.categoryOrder.push(config.key);
        });

        this.uploadForm = document.getElementById('picUploadForm');
        this.importButton = document.getElementById('importPicBtn');
        this.testControlSelect = document.getElementById('picTestControlSelect');
        this.clearModeBtn = document.getElementById('picClearModeBtn');
        this.confirmClearDataBtn = document.getElementById('picConfirmClearDataBtn');
        this.filterControls = document.getElementById('picFilterControls');
        this.fixAllButtonWrapper = document.getElementById('picFileNumberFixAllWrapper');
        this.fixAllButton = document.getElementById('picFileNumberFixAllBtn');

        this.clearDataModalElement = document.getElementById('picClearDataModal');
        this.clearDataModal = (this.clearDataModalElement && window.bootstrap?.Modal)
            ? new window.bootstrap.Modal(this.clearDataModalElement)
            : null;

        this.registerEventHandlers();

        const initialMode = this.testControlSelect?.value || '';
        this.syncTestControl(initialMode);
        this.toggleFilterControls(false);
        this.updateModeButtons();
        this.updateStagingDisplay();
        this.setTableVisibility();
        this.setImportButtonState(0);
        this.updateFileNumberFixAllState();
        this.updateShowingInfo(0);
        this.renderPagination();
    }

    registerEventHandlers() {
        if (this.uploadForm) {
            this.uploadForm.addEventListener('submit', (event) => this.handleUploadSubmit(event));
        }

        const fileInput = document.getElementById('picFileInput');
        if (fileInput) {
            fileInput.addEventListener('change', () => this.updateModeButtons());
        }

        if (this.testControlSelect) {
            this.testControlSelect.addEventListener('change', (event) => {
                this.syncTestControl(event.target.value);
                this.updateModeButtons();
            });
        }

        if (this.clearModeBtn) {
            this.clearModeBtn.addEventListener('click', (event) => {
                if (!this.modeIsSelected()) {
                    event.preventDefault();
                    this.showAlert('Select a Data Mode before clearing data.', 'warning');
                    return;
                }
                if (this.isClearingMode) {
                    event.preventDefault();
                    return;
                }
                if (this.clearDataModal) {
                    event.preventDefault();
                    this.clearDataModal.show();
                } else if (window.confirm(`Clear Property Index Card data in ${this.testControlMode || 'the selected'} mode?`)) {
                    this.handleClearMode();
                }
            });
        }

        if (this.confirmClearDataBtn) {
            this.confirmClearDataBtn.addEventListener('click', () => this.handleClearMode());
        }

        document.getElementById('picShowAllBtn')?.addEventListener('click', () => this.setFilter('all'));
        document.getElementById('picShowIssuesBtn')?.addEventListener('click', () => this.setFilter('issues'));
        document.getElementById('picShowValidBtn')?.addEventListener('click', () => this.setFilter('valid'));

        if (this.fixAllButton) {
            this.fixAllButton.addEventListener('click', () => this.handleFileNumberFixAll());
        }

        const tabs = document.querySelectorAll('#picPreviewTabs button[data-bs-toggle="tab"]');
        tabs.forEach((tab) => {
            tab.addEventListener('shown.bs.tab', (event) => {
                const target = event.target.getAttribute('data-bs-target');
                switch (target) {
                    case '#pic-records-pane':
                        this.handleTabChange('records');
                        break;
                    case '#pic-cofo-pane':
                        this.handleTabChange('cofo');
                        break;
                    case '#pic-file-numbers-pane':
                        this.handleTabChange('file-numbers');
                        break;
                    case '#pic-fileno-pane':
                        this.handleTabChange('file-number-qc');
                        break;
                    case '#pic-entities-pane':
                        this.handleTabChange('entities');
                        break;
                    case '#pic-customers-pane':
                        this.handleTabChange('customers');
                        break;
                    default:
                        break;
                }
            });
        });

        if (this.importButton) {
            this.importButton.addEventListener('click', () => this.importData());
        }

        const pagination = document.getElementById('picPagination');
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
        const fileInput = document.getElementById('picFileInput');
        const file = fileInput?.files?.[0];

        if (this.isUploading) {
            this.showAlert('An upload is already in progress. Please wait for it to finish.', 'info');
            return;
        }

        if (!this.modeIsSelected()) {
            this.showAlert('Select a Data Mode before uploading.', 'warning');
            this.testControlSelect?.focus();
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
        if (this.modeIsSelected()) {
            formData.append('test_control', this.testControlMode);
        }

        try {
            const response = await fetch('/api/upload-pic', {
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
            this.fileNumberRecords = Array.isArray(result.file_number_records) ? result.file_number_records : [];
            const entityPreview = this.resolvePreviewArray(result, [
                'entity_staging_preview',
                'entity_staging_records',
                'entities_preview',
                'entities'
            ]);
            this.entityStagingRecords = entityPreview ? entityPreview : [];
            const customerPreview = this.resolvePreviewArray(result, [
                'customer_staging_preview',
                'customer_staging_records',
                'customers_preview',
                'customers'
            ]);
            this.customerStagingRecords = customerPreview ? customerPreview : [];
            this.qcIssues = result.issues || {};
            if (result.test_control) {
                this.syncTestControl(result.test_control);
            }

            this.updateProgress(70, 'Rendering preview…');
            this.updateStatistics(result);
            this.updateStagingDisplay();
            this.updatePreview();
            this.showValidationIssues(this.qcIssues);
            this.setImportButtonState(result.ready_records);
            this.updateProgress(100, 'Ready');

            this.showAlert(`${result.total_records || 0} PIC rows processed successfully.`, 'success');
        } catch (error) {
            console.error('PIC upload failed:', error);
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
        const progressBar = document.getElementById('picProgressBar');
        const progressText = document.getElementById('picProgressText');

        if (progressBar) {
            const value = Math.max(0, Math.min(Number(percent) || 0, 100));
            progressBar.style.width = `${value}%`;
            progressBar.setAttribute('aria-valuenow', value.toString());
        }

        if (progressText && labelText) {
            progressText.textContent = labelText;
        }
    }

    showUploadProgress(visible) {
        const progressContainer = document.getElementById('picUploadProgress');
        if (progressContainer) {
            progressContainer.style.display = visible ? 'block' : 'none';
        }
    }

    disableUpload(disabled) {
        const fileInput = document.getElementById('picFileInput');
        this.uploadManuallyDisabled = Boolean(disabled);

        if (fileInput) {
            fileInput.disabled = Boolean(disabled);
        }

        this.updateModeButtons();
    }

    showLoadingModal() {
        const modalElement = document.getElementById('picLoadingModal');
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
        this.fileNumberRecords = [];
        this.entityStagingRecords = [];
        this.customerStagingRecords = [];
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
        this.updateFileNumberFixAllState();

        if (!keepFileInput) {
            const fileInput = document.getElementById('picFileInput');
            if (fileInput) {
                fileInput.value = '';
            }
        }

        this.isClearingMode = false;
        this.setClearModeLoading(false);
        this.updateModeButtons();

        this.rebuildCustomerLookupMaps();
        this.updateElementText('picEntitiesCount', 0);
        this.updateElementText('picCustomersCount', 0);
        this.renderEntitiesTable();
        this.renderCustomersTable();
    }

    clearTableBodies() {
        const recordsBody = document.getElementById('picRecordsTableBody');
        const cofoBody = document.getElementById('picCofoTableBody');
        const fileNumbersBody = document.getElementById('picFileNumbersTableBody');
        const qcBody = document.getElementById('picFileNumberQcBody');
        const entitiesBody = document.getElementById('picEntitiesTableBody');
        const customersBody = document.getElementById('picCustomersTableBody');

        if (recordsBody) {
            recordsBody.innerHTML = '';
        }
        if (cofoBody) {
            cofoBody.innerHTML = '';
        }
        if (fileNumbersBody) {
            fileNumbersBody.innerHTML = '';
        }
        if (qcBody) {
            qcBody.innerHTML = '';
        }
        if (entitiesBody) {
            entitiesBody.innerHTML = '';
        }
        if (customersBody) {
            customersBody.innerHTML = '';
        }
    }

    hidePreviewSection() {
        const previewSection = document.getElementById('picPreviewSection');
        if (previewSection) {
            previewSection.style.display = 'none';
        }

        const validationPanel = document.getElementById('picValidationPanel');
        if (validationPanel) {
            validationPanel.style.display = 'none';
        }
    }

    resetValidationPanel() {
        const panel = document.getElementById('picValidationPanel');
        const summaryContainer = document.getElementById('picQcSummaryContainer');
        const issuesBody = document.getElementById('picQcIssuesBody');
        const emptyState = document.getElementById('picQcEmptyState');
        const table = document.getElementById('picQcIssuesTable');

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
        this.updateElementText('picTotalRecords', 0);
        this.updateElementText('picReadyRecords', 0);

        const statRow = document.getElementById('picStatisticsRow');
        if (statRow) {
            statRow.style.display = 'none';
        }
    }

    updateStatistics(result) {
    const total = result?.total_records ?? 0;
    const ready = result?.ready_records ?? 0;

        this.updateElementText('picTotalRecords', total);
        this.updateElementText('picReadyRecords', ready);

        const statRow = document.getElementById('picStatisticsRow');
        if (statRow) {
            statRow.style.display = total > 0 ? 'flex' : 'none';
        }
    }

    updatePreview() {
        this.updateCounts();
        this.setTableVisibility();
        this.currentTab = 'records';
        this.currentFilter = 'all';
        this.currentPage = 1;
        this.updateFilterButtons();
        this.toggleFilterControls(true);
        this.applyFilter();
        this.updateFileNumberFixAllState();

        const previewSection = document.getElementById('picPreviewSection');
        if (previewSection) {
            previewSection.style.display = 'block';
        }
    }

    updateCounts() {
        this.updateElementText('picRecordsCount', this.propertyRecords.length);
        this.updateElementText('picCofoCount', this.cofoRecords.length);
        this.updateElementText('picFileNumberCount', this.fileNumberRecords.length);
        this.updateFileNumberIssueCount();
    }

    updateStagingDisplay() {
        this.rebuildCustomerLookupMaps();

        const entityCount = this.entityStagingRecords.length;
        const customerCount = this.customerStagingRecords.length;

        this.updateElementText('picEntitiesCount', entityCount);
        this.updateElementText('picCustomersCount', customerCount);

        this.renderEntitiesTable();
        this.renderCustomersTable();
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
        const recordsWrapper = document.getElementById('picRecordsTableWrapper');
        const cofoWrapper = document.getElementById('picCofoTableWrapper');
        const fileNumbersWrapper = document.getElementById('picFileNumbersTableWrapper');
        const qcWrapper = document.getElementById('picFileNumberQcWrapper');
        const qcEmpty = document.getElementById('picFileNumberQcEmpty');

        if (recordsWrapper) {
            recordsWrapper.style.display = this.propertyRecords.length ? 'block' : 'none';
        }
        if (cofoWrapper) {
            cofoWrapper.style.display = this.cofoRecords.length ? 'block' : 'none';
        }
        if (fileNumbersWrapper) {
            fileNumbersWrapper.style.display = this.fileNumberRecords.length ? 'block' : 'none';
        }
        if (qcWrapper) {
            const hasIssues = this.countFileNumberIssues() > 0;
            if (this.currentTab === 'file-number-qc') {
                qcWrapper.style.display = hasIssues ? 'block' : 'none';
                qcWrapper.dataset.hasIssues = hasIssues ? 'true' : 'false';
            } else {
                qcWrapper.style.display = 'none';
            }

            if (qcEmpty) {
                qcEmpty.classList.toggle('d-none', hasIssues);
            }
        }
    }

    toggleFilterControls(isVisible) {
        if (!this.filterControls) {
            return;
        }
        this.filterControls.style.display = isVisible ? 'inline-flex' : 'none';
    }

    modeIsSelected() {
        return this.testControlMode === 'TEST' || this.testControlMode === 'PRODUCTION';
    }

    syncTestControl(mode) {
        if (!mode) {
            return;
        }
        const normalized = mode.toString().toUpperCase();
        if (normalized !== 'TEST' && normalized !== 'PRODUCTION') {
            return;
        }
        this.testControlMode = normalized;
        if (this.testControlSelect) {
            this.testControlSelect.value = normalized;
        }
        this.updateModeButtons();
    }

    updateModeButtons() {
        const uploadBtn = document.getElementById('picUploadBtn');
        const fileInput = document.getElementById('picFileInput');
        const modeSelected = this.modeIsSelected();
        const hasFileSelected = Boolean(fileInput?.files?.length);

        if (uploadBtn) {
            if (this.uploadManuallyDisabled) {
                uploadBtn.disabled = true;
            } else {
                uploadBtn.disabled = !(modeSelected && hasFileSelected);
            }
        }

        if (this.importButton) {
            const readyCount = Number(this.importButton.dataset.readyCount || 0);
            const canImport = modeSelected && Boolean(this.sessionId) && readyCount > 0;
            this.importButton.disabled = !canImport;
        }

        if (this.testControlSelect && modeSelected) {
            this.testControlSelect.value = this.testControlMode;
        }

        if (this.clearModeBtn) {
            if (this.isClearingMode) {
                this.clearModeBtn.disabled = true;
            } else {
                this.clearModeBtn.disabled = !modeSelected;
            }
        }

        if (this.confirmClearDataBtn) {
            this.confirmClearDataBtn.disabled = !modeSelected || this.isClearingMode;
        }
    }

    setClearModeLoading(isLoading) {
        if (!this.clearModeBtn) {
            return;
        }

        if (isLoading) {
            if (!this.clearModeBtn.dataset.originalContent) {
                this.clearModeBtn.dataset.originalContent = this.clearModeBtn.innerHTML;
            }
            this.clearModeBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Clearing...';
        } else if (this.clearModeBtn.dataset.originalContent) {
            this.clearModeBtn.innerHTML = this.clearModeBtn.dataset.originalContent;
        }

        this.clearModeBtn.disabled = isLoading || !this.modeIsSelected();
        if (this.confirmClearDataBtn) {
            this.confirmClearDataBtn.disabled = isLoading || !this.modeIsSelected();
        }
    }

    async handleClearMode() {
        if (!this.modeIsSelected() || this.isClearingMode) {
            return;
        }

        const mode = this.testControlMode;
        const modeLabel = mode === 'TEST' ? 'TEST' : 'PRODUCTION';

        this.isClearingMode = true;
        this.setClearModeLoading(true);

        try {
            const response = await fetch('/api/pic/clear-data', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ mode })
            });

            if (!response.ok) {
                const errorBody = await response.json().catch(() => ({}));
                const message = errorBody.detail || 'Failed to clear data. Please try again.';
                throw new Error(message);
            }

            const result = await response.json();
            const counts = result.counts || {};
            const numericCounts = Object.entries(counts).map(([key, value]) => ({
                key,
                value: Number(value) || 0
            }));
            const totalCleared = numericCounts.reduce((sum, entry) => sum + entry.value, 0);
            const detailText = numericCounts
                .map((entry) => `${entry.key}: ${entry.value}`)
                .join(', ');

            const summary = totalCleared > 0
                ? `Cleared ${totalCleared} ${modeLabel} row${totalCleared === 1 ? '' : 's'} (${detailText}).`
                : `No ${modeLabel} rows found to clear.`;

            this.showAlert(summary, totalCleared > 0 ? 'success' : 'info');
            if (this.clearDataModal) {
                this.clearDataModal.hide();
            }
            this.resetSessionData({ keepFileInput: true });
        } catch (error) {
            console.error('PIC clear data failed:', error);
            this.showAlert(error.message || 'Failed to clear data. Please try again.', 'danger');
            if (this.clearDataModal) {
                this.clearDataModal.hide();
            }
        } finally {
            this.isClearingMode = false;
            this.setClearModeLoading(false);
            this.updateModeButtons();
        }
    }

    setImportButtonState(readyRecords) {
        const importBtn = this.importButton;
        if (!importBtn) {
            return;
        }

        const readyCount = Number(readyRecords) || 0;
        importBtn.disabled = !this.sessionId || readyCount === 0;
        importBtn.dataset.readyCount = readyCount.toString();
        this.updateElementText('picReadyRecords', readyCount);
        this.updateModeButtons();
    }

    updateFilterButtons() {
        const buttons = {
            all: document.getElementById('picShowAllBtn'),
            issues: document.getElementById('picShowIssuesBtn'),
            valid: document.getElementById('picShowValidBtn')
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
        if (!['records', 'cofo', 'file-numbers', 'file-number-qc', 'entities', 'customers'].includes(tab)) {
            return;
        }

        this.currentTab = tab;
        this.setTableVisibility();
        this.renderEntitiesTable();
        this.renderCustomersTable();

        if (tab === 'entities' || tab === 'customers') {
            this.toggleFilterControls(false);
            return;
        }

        this.currentPage = 1;
        this.toggleFilterControls(tab !== 'file-number-qc');
        this.updateFileNumberFixAllState();

        if (tab === 'file-number-qc') {
            this.renderFileNumberQcTable();
            this.updateShowingInfoForQc(this.countFileNumberIssues());
            const pagination = document.getElementById('picPagination');
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

        let sourceData = [];
        if (this.currentTab === 'records') {
            sourceData = this.propertyRecords;
        } else if (this.currentTab === 'cofo') {
            sourceData = this.cofoRecords;
        } else if (this.currentTab === 'file-numbers') {
            sourceData = this.fileNumberRecords;
        }
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

        let bodyId = 'picRecordsTableBody';
        if (this.currentTab === 'cofo') {
            bodyId = 'picCofoTableBody';
        } else if (this.currentTab === 'file-numbers') {
            bodyId = 'picFileNumbersTableBody';
        }
        const tableBody = document.getElementById(bodyId);
        if (!tableBody) {
            return;
        }

        let sourceData = this.propertyRecords;
        if (this.currentTab === 'cofo') {
            sourceData = this.cofoRecords;
        } else if (this.currentTab === 'file-numbers') {
            sourceData = this.fileNumberRecords;
        }
        tableBody.innerHTML = '';

        if (!this.filteredRows.length) {
            let columnCount = 16;
            if (this.currentTab === 'cofo') {
                columnCount = 14;
            } else if (this.currentTab === 'file-numbers') {
                columnCount = 11;
            }
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
                : this.currentTab === 'cofo'
                    ? this.createCofoRow(item, displayIndex)
                    : this.createFileNumberRow(item, displayIndex);
            tableBody.appendChild(row);
        });

        this.updateShowingInfo(this.filteredRows.length);
    }

    rebuildCustomerLookupMaps() {
        this.customerLookupByEntityId = new Map();
        this.customerLookupByFileNumber = new Map();

        if (!Array.isArray(this.customerStagingRecords) || !this.customerStagingRecords.length) {
            return;
        }

        this.customerStagingRecords.forEach((customer) => {
            const entityId = this.sanitizeValue(customer?.entity_id ?? customer?.entityId);
            if (entityId && !this.customerLookupByEntityId.has(entityId)) {
                this.customerLookupByEntityId.set(entityId, customer);
            }

            const fileNumber = this.sanitizeValue(customer?.file_number ?? customer?.mlsFNo ?? customer?.fileNumber);
            if (fileNumber && !this.customerLookupByFileNumber.has(fileNumber)) {
                this.customerLookupByFileNumber.set(fileNumber, customer);
            }
        });
    }

    findCustomerRecordForEntity(entity) {
        if (!entity) {
            return null;
        }

        const entityId = this.sanitizeValue(entity?.entity_id ?? entity?.entityId);
        if (entityId && this.customerLookupByEntityId?.has(entityId)) {
            return this.customerLookupByEntityId.get(entityId);
        }

        const fileNumber = this.sanitizeValue(entity?.file_number ?? entity?.fileNumber);
        if (fileNumber && this.customerLookupByFileNumber?.has(fileNumber)) {
            return this.customerLookupByFileNumber.get(fileNumber);
        }

        return null;
    }

    findCustomerNameForEntity(entity) {
        const customer = this.findCustomerRecordForEntity(entity);
        if (!customer) {
            return '';
        }

        return this.sanitizeValue(
            customer.customer_name
            ?? customer.name
            ?? customer.Grantee
            ?? customer.grantee_original
            ?? customer.entity_name
        );
    }

    stripFileLabel(value) {
        const sanitized = this.sanitizeValue(value);
        if (!sanitized) {
            return '';
        }

        return sanitized.replace(/^file(?:\s*number)?\s*[:\-]?/i, '').trim();
    }

    normalizeFileNumber(value) {
        const sanitized = this.sanitizeValue(value);
        if (!sanitized) {
            return '';
        }
        return sanitized.replace(/[^a-z0-9]/gi, '').toUpperCase();
    }

    entityNameLooksLikeFile(entityName, fileNumber) {
        if (!entityName || !fileNumber) {
            return false;
        }
        const normalizedName = this.normalizeFileNumber(this.stripFileLabel(entityName));
        const normalizedFile = this.normalizeFileNumber(fileNumber);
        if (!normalizedName || !normalizedFile) {
            return false;
        }
        return normalizedName === normalizedFile;
    }

    getEntityDisplayName(entity) {
        const rawName = this.sanitizeValue(entity?.entity_name ?? entity?.name);
        const fileNumber = this.sanitizeValue(entity?.file_number ?? entity?.fileNumber);

        if (!rawName || this.entityNameLooksLikeFile(rawName, fileNumber)) {
            const fallback = this.findCustomerNameForEntity(entity);
            if (fallback) {
                return fallback;
            }
        }

        return rawName;
    }

    renderEntitiesTable() {
        const wrapper = document.getElementById('picEntitiesTableWrapper');
        const tbody = document.getElementById('picEntitiesTableBody');

        if (!wrapper || !tbody) {
            return;
        }

        tbody.innerHTML = '';

        if (!this.entityStagingRecords.length) {
            const emptyRow = document.createElement('tr');
            emptyRow.innerHTML = `
                <td colspan="6" class="text-center text-muted py-4">
                    No entities were extracted from this upload.
                </td>
            `;
            tbody.appendChild(emptyRow);
            wrapper.style.display = this.currentTab === 'entities' ? 'block' : 'none';
            return;
        }

        this.entityStagingRecords.forEach((entity, index) => {
            const entityName = this.getEntityDisplayName(entity);
            const entityType = this.sanitizeValue(entity.entity_type);
            const status = (entity.status || 'new').toString().trim() || 'new';
            const entityId = this.sanitizeValue(entity.entity_id ?? entity.entityId);
            const fileNumber = this.sanitizeValue(entity.file_number ?? entity.fileNumber);
            const statusClass = status.toLowerCase() === 'new' ? 'badge bg-primary' : 'badge bg-info text-dark';

            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${index + 1}</td>
                <td>${entityId ? `<code>${this.escapeHtml(entityId)}</code>` : '<span class="text-muted">—</span>'}</td>
                <td>${fileNumber ? `<code>${this.escapeHtml(fileNumber)}</code>` : '<span class="text-muted">—</span>'}</td>
                <td>${entityType ? `<span class="badge bg-secondary">${this.escapeHtml(entityType)}</span>` : '<span class="text-muted">—</span>'}</td>
                <td>${entityName ? this.escapeHtml(entityName) : '<span class="text-muted">—</span>'}</td>
                <td><span class="${statusClass}">${this.escapeHtml(status)}</span></td>
            `;
            tbody.appendChild(row);
        });

        wrapper.style.display = this.currentTab === 'entities' ? 'block' : 'none';
    }

    renderCustomersTable() {
        const wrapper = document.getElementById('picCustomersTableWrapper');
        const tbody = document.getElementById('picCustomersTableBody');

        if (!wrapper || !tbody) {
            return;
        }

        tbody.innerHTML = '';

        if (!this.customerStagingRecords.length) {
            const emptyRow = document.createElement('tr');
            emptyRow.innerHTML = `
                <td colspan="12" class="text-center text-muted py-4">
                    No customers were extracted from this upload.
                </td>
            `;
            tbody.appendChild(emptyRow);
            wrapper.style.display = this.currentTab === 'customers' ? 'block' : 'none';
            return;
        }

        this.customerStagingRecords.forEach((customer, index) => {
            const customerName = this.sanitizeValue(customer.customer_name ?? customer.name);
            const customerType = this.sanitizeValue(customer.customer_type ?? customer.type);
            const customerCode = this.sanitizeValue(customer.customer_code ?? customer.customerCode);
            const reasonRetired = this.sanitizeValue(customer.reason_retired ?? customer.reasonRetired);
            const reasonBy = this.sanitizeValue(customer.reason_by ?? customer.reasonBy);
            const fileNumber = this.sanitizeValue(customer.file_number ?? customer.mlsFNo ?? customer.fileNumber);
            const accountNo = this.sanitizeValue(customer.account_no ?? customer.accountNo ?? fileNumber);
            const entityId = this.sanitizeValue(customer.entity_id ?? customer.entityId);
            const email = this.sanitizeValue(customer.email);
            const phone = this.sanitizeValue(customer.phone);
            const address = this.sanitizeValue(
                customer.property_address
                ?? customer.property_description
                ?? customer.address
            );

            const reasonByCell = reasonBy
                ? `<span>${this.escapeHtml(reasonBy)}</span>`
                : '<span class="text-muted">—</span>';
            const reasonRetiredCell = reasonRetired
                ? `<span class="badge bg-warning text-dark">${this.escapeHtml(reasonRetired)}</span>`
                : '<span class="text-muted">—</span>';
            const emailCell = email
                ? `<a href="mailto:${this.escapeHtml(email)}">${this.escapeHtml(email)}</a>`
                : '<span class="text-muted">—</span>';
            const phoneCell = phone
                ? `<a href="tel:${this.escapeHtml(phone)}">${this.escapeHtml(phone)}</a>`
                : '<span class="text-muted">—</span>';
            const addressCell = address
                ? `<span title="${this.escapeHtml(address)}">${this.escapeHtml(this.truncate(address, 60))}</span>`
                : '<span class="text-muted">—</span>';

            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${index + 1}</td>
                <td>${entityId ? `<code>${this.escapeHtml(entityId)}</code>` : '<span class="text-muted">—</span>'}</td>
                <td>${fileNumber ? `<code>${this.escapeHtml(fileNumber)}</code>` : '<span class="text-muted">—</span>'}</td>
                <td>${accountNo ? `<code>${this.escapeHtml(accountNo)}</code>` : '<span class="text-muted">—</span>'}</td>
                <td>${customerCode ? `<code>${this.escapeHtml(customerCode)}</code>` : '<span class="text-muted">—</span>'}</td>
                <td>${customerName ? this.escapeHtml(customerName) : '<span class="text-muted">—</span>'}</td>
                <td>${customerType ? `<span class="badge bg-secondary">${this.escapeHtml(customerType)}</span>` : '<span class="text-muted">—</span>'}</td>
                <td>${reasonByCell}</td>
                <td>${reasonRetiredCell}</td>
                <td>${emailCell}</td>
                <td>${phoneCell}</td>
                <td>${addressCell}</td>
            `;
            tbody.appendChild(row);
        });

        wrapper.style.display = this.currentTab === 'customers' ? 'block' : 'none';
    }

    createPropertyRecordRow(item, displayIndex) {
        const { record, index } = item;
        const tr = document.createElement('tr');

        if (record?.hasIssues) {
            tr.classList.add('table-warning');
        }

        const fileNumber = this.sanitizeValue(record?.mlsFNo);
        const registerSerial = this.sanitizeValue(record?.serialNo);
        const oldKnNumber = this.sanitizeValue(record?.oldKNNo);
        const transactionType = this.sanitizeValue(record?.transaction_type);
        const grantor = this.sanitizeValue(record?.Grantor);
        const grantee = this.sanitizeValue(record?.Grantee);
        const propertyDescription = this.sanitizeValue(record?.property_description ?? record?.propertyDescription);
        const locationValue = this.sanitizeValue(record?.location);
        const location = propertyDescription || locationValue;
        const propId = this.sanitizeValue(record?.prop_id);
        const assignmentDate = this.resolvePreferredValue(
            record?.assignment_date,
            record?.assignment_date_raw,
            record?.transaction_date,
            record?.transaction_date_raw
        );
        const pageNo = this.sanitizeValue(record?.pageNo);
        const volumeNo = this.sanitizeValue(record?.volumeNo);
        const comments = this.sanitizeValue(record?.comments);
        const remarks = this.sanitizeValue(record?.remarks);
    const statusBadge = this.buildStatusBadge(record);

        const columnConfigs = [
            { kind: 'text', value: displayIndex.toString() },
            { kind: 'editable', field: 'mlsFNo', value: fileNumber },
            { kind: 'prop-id', value: propId, source: record?.prop_id_source },
            { kind: 'editable', field: 'transaction_type', value: transactionType },
            { kind: 'editable', field: 'Grantor', value: grantor },
            { kind: 'editable', field: 'Grantee', value: grantee },
            { kind: 'editable', field: 'location', value: location },
            { kind: 'editable', field: 'assignment_date', value: assignmentDate },
            { kind: 'editable', field: 'comments', value: comments },
            { kind: 'editable', field: 'oldKNNo', value: oldKnNumber },
            { kind: 'editable', field: 'serialNo', value: registerSerial },
            { kind: 'editable', field: 'pageNo', value: pageNo },
            { kind: 'editable', field: 'volumeNo', value: volumeNo },
            { kind: 'editable', field: 'remarks', value: remarks },
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
                    if (config.field === 'location' && propertyDescription && locationValue) {
                        td.title = this.escapeHtml(locationValue);
                    } else if (config.field === 'location') {
                        td.removeAttribute('title');
                    }
                    this.attachInlineEditing(td, 'records', index, config.field);
                    break;
                case 'prop-id':
                    td.classList.add('text-nowrap');
                    this.renderPropIdCell(td, config.value, config.source);
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
        const grantor = this.sanitizeValue(record?.Grantor);
        const grantee = this.sanitizeValue(record?.Grantee);
        const transactionDate = this.resolvePreferredValue(record?.transaction_date, record?.transaction_date_raw);
        const registerSerial = this.sanitizeValue(record?.serialNo);
        const oldKnNumber = this.sanitizeValue(record?.oldKNNo);
        const pageNo = this.sanitizeValue(record?.pageNo);
        const volumeNo = this.sanitizeValue(record?.volumeNo);
        const regNo = this.sanitizeValue(record?.regNo);
    const statusBadge = this.buildStatusBadge(record);
        const propId = this.sanitizeValue(record?.prop_id);

        const columnConfigs = [
            { kind: 'text', value: displayIndex.toString() },
            { kind: 'editable', field: 'mlsFNo', value: fileNumber },
            { kind: 'editable', field: 'oldKNNo', value: oldKnNumber },
            { kind: 'prop-id', value: propId, source: record?.prop_id_source },
            { kind: 'editable', field: 'transaction_type', value: transactionType },
            { kind: 'editable', field: 'Grantor', value: grantor },
            { kind: 'editable', field: 'Grantee', value: grantee },
            { kind: 'editable', field: 'transaction_date', value: transactionDate },
            { kind: 'editable', field: 'serialNo', value: registerSerial },
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
                case 'prop-id':
                    td.classList.add('text-nowrap');
                    this.renderPropIdCell(td, config.value, config.source);
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

    createFileNumberRow(item, displayIndex) {
        const { record, index } = item;
        const tr = document.createElement('tr');

        if (record?.hasIssues) {
            tr.classList.add('table-warning');
        }

        const fileNumber = this.sanitizeValue(record?.mlsfNo || record?.mlsFNo);
        const trackingId = this.sanitizeValue(record?.tracking_id);
        const fileName = this.sanitizeValue(record?.FileName);
        const location = this.sanitizeValue(record?.location);
        const type = this.sanitizeValue(record?.type);
        const source = this.sanitizeValue(record?.SOURCE || record?.source);
        const plotNo = this.sanitizeValue(record?.plot_no);
        const propId = this.sanitizeValue(record?.prop_id);
        const createdBy = this.sanitizeValue(record?.created_by || record?.CreatedBy);
        const statusBadge = this.buildStatusBadge(record);

        const columnConfigs = [
            { kind: 'text', value: displayIndex.toString() },
            { kind: 'text', value: fileNumber },
            { kind: 'text', value: trackingId },
            { kind: 'text', value: fileName },
            { kind: 'text', value: location },
            { kind: 'text', value: type },
            { kind: 'text', value: source },
            { kind: 'text', value: plotNo },
            { kind: 'text', value: createdBy },
            { kind: 'status', html: statusBadge },
            { kind: 'actions', typeKey: 'file-numbers', rowIndex: index }
        ];

        columnConfigs.forEach((config) => {
            const td = document.createElement('td');
            switch (config.kind) {
                case 'text':
                    td.textContent = config.value ?? '';
                    break;
                case 'prop-id':
                    td.classList.add('text-nowrap');
                    this.renderPropIdCell(td, config.value, config.source);
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

        if (recordType === 'file-numbers') {
            cell.innerHTML = '<span class="text-muted">—</span>';
            return;
        }

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm btn-outline-danger';
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
            index: rowIndex,
            record_type: recordType,
            field,
            value
        };

        try {
            const response = await fetch(`/api/pic/update/${this.sessionId}`, {
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
            console.error('PIC update failed:', error);
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
            index: rowIndex,
            record_type: recordType
        };

        try {
            const response = await fetch(`/api/pic/delete/${this.sessionId}`, {
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
            console.error('PIC delete failed:', error);
            this.showAlert(error.message || 'Unable to remove row. Please try again.', 'danger');
        }
    }

    applySessionUpdate(result) {
        if (!result || typeof result !== 'object') {
            return;
        }

        if (result.test_control) {
            this.syncTestControl(result.test_control);
        }

        if (Array.isArray(result.property_records)) {
            this.propertyRecords = result.property_records;
        }
        if (Array.isArray(result.cofo_records)) {
            this.cofoRecords = result.cofo_records;
        }
        if (Array.isArray(result.file_number_records)) {
            this.fileNumberRecords = result.file_number_records;
        }

        const entityPreview = this.resolvePreviewArray(result, [
            'entity_staging_preview',
            'entity_staging_records',
            'entities_preview',
            'entities'
        ]);
        if (entityPreview !== null) {
            this.entityStagingRecords = entityPreview;
        }

        const customerPreview = this.resolvePreviewArray(result, [
            'customer_staging_preview',
            'customer_staging_records',
            'customers_preview',
            'customers'
        ]);
        if (customerPreview !== null) {
            this.customerStagingRecords = customerPreview;
        }

        this.qcIssues = result.issues || {};
        this.updateStagingDisplay();
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
        this.updateFileNumberFixAllState();
    }

    resolvePreviewArray(result, keys) {
        if (!result || typeof result !== 'object' || !Array.isArray(keys)) {
            return null;
        }
        for (const key of keys) {
            const candidate = result[key];
            if (Array.isArray(candidate)) {
                return candidate;
            }
        }
        return null;
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

    getAutoFixableFileNumberIssues(issues) {
        const source = Array.isArray(issues) ? issues : this.collectFileNumberIssues();
        return source.filter((item) => item && Number.isInteger(item.record_index) && item.suggested_fix);
    }

    buildFixAllLabel(count) {
        const suffix = count > 0 ? ` (${count})` : '';
        return `<i class="fas fa-magic me-1"></i>Fix All${suffix}`;
    }

    updateFileNumberFixAllState(issues) {
        if (!this.fixAllButton || !this.fixAllButtonWrapper) {
            return;
        }

        if (this.isApplyingFixAll) {
            this.fixAllButtonWrapper.style.display = 'flex';
            return;
        }

        const fixableCount = this.getAutoFixableFileNumberIssues(issues).length;
        const isQcTabActive = this.currentTab === 'file-number-qc';

        if (!isQcTabActive || fixableCount === 0) {
            this.fixAllButtonWrapper.style.display = 'none';
            this.fixAllButton.disabled = true;
            this.fixAllButton.innerHTML = this.buildFixAllLabel(fixableCount);
            return;
        }

        this.fixAllButtonWrapper.style.display = 'flex';
        this.fixAllButton.disabled = false;
        this.fixAllButton.innerHTML = this.buildFixAllLabel(fixableCount);
    }

    toggleFileNumberFixAllLoading(isLoading) {
        if (!this.fixAllButton) {
            return;
        }

        this.isApplyingFixAll = isLoading;

        if (isLoading) {
            if (this.fixAllButtonWrapper) {
                this.fixAllButtonWrapper.style.display = 'flex';
            }
            this.fixAllButton.disabled = true;
            this.fixAllButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Applying fixes...';
            return;
        }

        this.updateFileNumberFixAllState();
    }

    async handleFileNumberFixAll() {
        if (this.isApplyingFixAll) {
            return;
        }

        if (!this.sessionId) {
            this.showAlert('Please upload a file before applying fixes.', 'warning');
            return;
        }

        const initialIssues = this.getAutoFixableFileNumberIssues();
        if (!initialIssues.length) {
            this.showAlert('No auto-fixable file number issues available.', 'info');
            return;
        }

        this.toggleFileNumberFixAllLoading(true);

        let appliedCount = 0;
        let failed = false;
        const maxIterations = 500;
        let iteration = 0;

        try {
            while (iteration < maxIterations) {
                const [nextIssue] = this.getAutoFixableFileNumberIssues();
                if (!nextIssue) {
                    break;
                }

                const success = await this.updateField('records', nextIssue.record_index, 'mlsFNo', nextIssue.suggested_fix);
                if (!success) {
                    failed = true;
                    break;
                }

                appliedCount += 1;
                iteration += 1;
            }
        } finally {
            this.toggleFileNumberFixAllLoading(false);
        }

        if (iteration === maxIterations && this.getAutoFixableFileNumberIssues().length > 0) {
            failed = true;
        }

        if (appliedCount > 0 && !failed) {
            this.showAlert(`Applied ${appliedCount} auto-fix${appliedCount === 1 ? '' : 'es'} to file numbers.`, 'success');
        } else if (appliedCount > 0 && failed) {
            this.showAlert(`Applied ${appliedCount} auto-fix${appliedCount === 1 ? '' : 'es'}, but some issues still need review.`, 'warning');
        } else if (!failed) {
            this.showAlert('No auto-fixable file number issues available.', 'info');
        } else {
            this.showAlert('Unable to complete Fix All operation. Please review the remaining issues manually.', 'warning');
        }
    }

    renderFileNumberQcTable() {
        const wrapper = document.getElementById('picFileNumberQcWrapper');
        const tbody = document.getElementById('picFileNumberQcBody');
        const emptyState = document.getElementById('picFileNumberQcEmpty');

        if (!wrapper || !tbody || !emptyState) {
            return;
        }

        const issues = this.collectFileNumberIssues();
        this.updateFileNumberFixAllState(issues);
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
        const severity = issue.severity || categoryConfig?.severity || 'Medium';
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
            successMessage: `File number updated to ${this.escapeHtml(fix)}`
        });
    }

    buildStatusBadge(record) {
        if (!record) {
            return '';
        }
        if (record.hasIssues) {
            return '<span class="badge bg-warning text-dark">Needs review</span>';
        }

        return '<span class="badge bg-success">Ready</span>';
    }

    renderPropIdCell(cell, value, source) {
        if (!cell) {
            return;
        }

        const displayValue = this.formatPropIdValue(value);
        if (!displayValue) {
            cell.innerHTML = '<span class="text-muted">—</span>';
            cell.removeAttribute('title');
            return;
        }

        cell.textContent = displayValue;
        const sourceLabel = this.sanitizeValue(source);
        if (sourceLabel) {
            cell.title = sourceLabel;
        } else {
            cell.removeAttribute('title');
        }
    }

    formatPropIdValue(value) {
        const sanitized = this.sanitizeValue(value);
        if (!sanitized) {
            return '';
        }
        return sanitized.replace(/^#+/, '').trim();
    }

    renderPagination() {
        const pagination = document.getElementById('picPagination');
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

        this.updateElementText('picShowingStart', start);
        this.updateElementText('picShowingEnd', end);
        this.updateElementText('picShowingTotal', totalCount);
    }

    updateShowingInfoForQc(total) {
        const count = Number(total) || 0;
        const start = count === 0 ? 0 : 1;
        this.updateElementText('picShowingStart', start);
        this.updateElementText('picShowingEnd', count);
        this.updateElementText('picShowingTotal', count);
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
        const issueCountElement = document.getElementById('picFileNumberIssueCount');
        if (!issueCountElement) {
            return;
        }
        const total = this.countFileNumberIssues();
        issueCountElement.textContent = total.toString();
    }

    showValidationIssues(issues) {
        const panel = document.getElementById('picValidationPanel');
        const summaryContainer = document.getElementById('picQcSummaryContainer');
        const table = document.getElementById('picQcIssuesTable');
        const tbody = document.getElementById('picQcIssuesBody');
        const emptyState = document.getElementById('picQcEmptyState');

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

        emptyState.style.display = detailRows.length === 0 ? 'block' : 'none';
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
            const toneClasses = PIC_QC_TONE_CLASSMAP[config.tone] || PIC_QC_TONE_CLASSMAP.secondary;
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
                const notes = item.suggested_fix
                    ? `Suggested fix: ${item.suggested_fix}`
                    : item.auto_fixable
                        ? 'Auto-fixable'
                        : 'Manual review required';

                rows.push({
                    type: label,
                    fileNumber: this.sanitizeValue(item.file_number || item.fileNumber || item.mlsFNo),
                    details: this.composeIssueText(item),
                    severity,
                    notes
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
            missing_file_number: 'Missing File Numbers'
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

    truncate(value, maxLength = 60) {
        const sanitized = this.sanitizeValue(value);
        if (!sanitized) {
            return '';
        }
        if (sanitized.length <= maxLength) {
            return sanitized;
        }
        return `${sanitized.slice(0, Math.max(0, maxLength - 1))}…`;
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
        const container = document.getElementById('picAlertContainer');
        if (!container) {
            return;
        }

        const alertId = `pic-alert-${Date.now()}`;
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

        if (!this.modeIsSelected()) {
            this.showAlert('Select a Data Mode before importing.', 'warning');
            this.testControlSelect?.focus();
            return;
        }

        const readyCount = this.propertyRecords.filter((record) => !record?.hasIssues).length;
        if (readyCount === 0) {
            this.showAlert('No valid property records are ready for import.', 'warning');
            return;
        }

        const confirmationPrompt = `Import ${readyCount} property record${readyCount === 1 ? '' : 's'} in ${this.testControlMode} mode?`;
        if (!window.confirm(confirmationPrompt)) {
            return;
        }

        this.showLoadingModal();
        this.updateProgress(25, 'Importing records…');

        try {
            const response = await fetch(`/api/import-pic/${this.sessionId}`, {
                method: 'POST'
            });

            if (!response.ok) {
                throw new Error(await this.extractErrorMessage(response));
            }

            const result = await response.json();
            if (result.test_control) {
                this.syncTestControl(result.test_control);
            }
            this.showAlert(
                `Import completed in ${this.testControlMode} mode. ${result.imported_count || 0} record${result.imported_count === 1 ? '' : 's'} processed.`,
                'success'
            );

            this.resetSessionData();
        } catch (error) {
            console.error('PIC import failed:', error);
            this.showAlert(error.message || 'Import failed. Please try again.', 'danger');
        } finally {
            this.hideLoadingModal();
            this.showUploadProgress(false);
            this.disableUpload(false);
        }
    }
}

let propertyIndexCardManager;

document.addEventListener('DOMContentLoaded', () => {
    propertyIndexCardManager = new PropertyIndexCardImportManager();
    window.propertyIndexCardManager = propertyIndexCardManager;
});
