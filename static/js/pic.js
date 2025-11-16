class PropertyIndexCardManager {
    constructor() {
        this.propertyRecords = [];
        this.cofoRecords = [];
        this.fileNumberRecords = [];
        this.entityStagingRecords = [];
        this.customerStagingRecords = [];
        this.stagingSummary = {};
        this.sessionId = null;
        this.testControlMode = '';
        this.qcIssues = {};

        this.summaryRow = document.getElementById('picSummaryRow');
        this.workspaceCard = document.getElementById('picWorkspaceCard');
        this.placeholderAlert = document.getElementById('picPlaceholderAlert');
        this.searchInput = document.getElementById('picSearchInput');
        this.filterButton = document.getElementById('picFilterBtn');
        this.exportButton = document.getElementById('picExportBtn');
        this.newCardButton = document.getElementById('picNewCardBtn');
        this.statusPlaceholder = document.getElementById('picStatusPlaceholder');
        this.testControlSelect = document.getElementById('picTestControlSelect');
        this.uploadForm = document.getElementById('picUploadForm');
        this.uploadBtn = document.getElementById('picUploadBtn');
        this.importBtn = document.getElementById('picImportBtn');

        this.bindEvents();
    }

    bindEvents() {
        if (this.searchInput) {
            this.searchInput.addEventListener('input', () => this.handleSearch());
        }

        if (this.filterButton) {
            this.filterButton.addEventListener('click', () => this.handleFilterPanel());
        }

        if (this.exportButton) {
            this.exportButton.addEventListener('click', () => this.handleExport());
        }

        if (this.newCardButton) {
            this.newCardButton.addEventListener('click', () => this.handleNewCard());
        }

        if (this.uploadForm) {
            this.uploadForm.addEventListener('submit', (e) => this.handleUploadSubmit(e));
        }

        if (this.testControlSelect) {
            this.testControlSelect.addEventListener('change', (e) => {
                this.testControlMode = (e.target.value || '').toUpperCase();
            });
        }
    }

    handleUploadSubmit(event) {
        event.preventDefault();
        const fileInput = document.getElementById('picFileInput');
        const file = fileInput?.files?.[0];
        
        if (!file) {
            alert('Please select a file');
            return;
        }

        if (!this.testControlMode) {
            alert('Please select a test control mode');
            return;
        }

        this.uploadFile(file);
    }

    async uploadFile(file) {
        const formData = new FormData();
        formData.append('test_control', this.testControlMode);
        formData.append('file', file);

        try {
            const response = await fetch('/api/upload-pic', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`Upload failed: ${response.status}`);
            }

            const result = await response.json();
            this.sessionId = result.session_id;
            this.propertyRecords = result.property_records || [];
            this.cofoRecords = result.cofo_records || [];
            this.fileNumberRecords = result.file_number_records || [];
            this.entityStagingRecords = result.entity_staging_preview || [];
            this.customerStagingRecords = result.customer_staging_preview || [];
            this.stagingSummary = result.staging_summary || {};
            this.qcIssues = result.issues || {};

            this.updateStatistics(result);
            this.updateStagingDisplay();
            this.showPreviewSection();
            alert(`Upload successful! ${result.total_records} records loaded.`);
        } catch (error) {
            console.error('Upload error:', error);
            alert('Upload failed: ' + error.message);
        }
    }

    updateStatistics(result) {
        const total = result?.total_records ?? this.propertyRecords.length;
        const validation = result?.validation_issues ?? 0;
        const ready = result?.ready_records ?? total;

        const totalElem = document.getElementById('picTotalRecords');
        const readyElem = document.getElementById('picReadyRecords');
        const statsRow = document.getElementById('picStatisticsRow');

        if (totalElem) totalElem.textContent = total;
        if (readyElem) readyElem.textContent = ready;
        if (statsRow) statsRow.style.display = 'flex';
    }

    updateStagingDisplay() {
        const entityCount = this.entityStagingRecords.length;
        const customerCount = this.customerStagingRecords.length;

        const entitiesCountElem = document.getElementById('picEntitiesCount');
        const customersCountElem = document.getElementById('picCustomersCount');
        if (entitiesCountElem) {
            entitiesCountElem.textContent = entityCount;
        }
        if (customersCountElem) {
            customersCountElem.textContent = customerCount;
        }

        const entitiesWrapper = document.getElementById('picEntitiesTableWrapper');
        const entitiesBody = document.getElementById('picEntitiesTableBody');
        if (entitiesWrapper && entitiesBody) {
            entitiesBody.innerHTML = '';

            if (!entityCount) {
                entitiesBody.innerHTML = `
                    <tr>
                        <td colspan="6" class="text-center text-muted py-4">
                            No entities were extracted from this upload.
                        </td>
                    </tr>
                `;
                entitiesWrapper.style.display = 'none';
            } else {
                this.entityStagingRecords.forEach((entity, index) => {
                    const entityName = entity.entity_name || entity.name || '';
                    const entityType = entity.entity_type || '';
                    const status = (entity.status || 'new').toString().trim() || 'new';
                    const entityId = entity.entity_id || entity.entityId || '';
                    const fileNumber = entity.file_number || entity.fileNumber || '';
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
                    entitiesBody.appendChild(row);
                });

                entitiesWrapper.style.display = 'block';
            }
        }

        const customersWrapper = document.getElementById('picCustomersTableWrapper');
        const customersBody = document.getElementById('picCustomersTableBody');
        if (customersWrapper && customersBody) {
            customersBody.innerHTML = '';

            if (!customerCount) {
                customersBody.innerHTML = `
                    <tr>
                        <td colspan="12" class="text-center text-muted py-4">
                            No customers were extracted from this upload.
                        </td>
                    </tr>
                `;
                customersWrapper.style.display = 'none';
            } else {
                this.customerStagingRecords.forEach((customer, index) => {
                    const customerName = customer.customer_name || customer.name || '';
                    const customerType = customer.customer_type || customer.type || '';
                    const customerCode = customer.customer_code || customer.customerCode || '';
                    const reasonRetired = customer.reason_retired || customer.reasonRetired || '';
                    const reasonBy = customer.reason_by || customer.reasonBy || '';
                    const fileNumber = customer.file_number || customer.mlsFNo || customer.fileNumber || '';
                    const accountNo = customer.account_no || customer.accountNo || fileNumber;
                    const entityId = customer.entity_id || customer.entityId || '';
                    const email = customer.email || '';
                    const phone = customer.phone || '';
                    const address = customer.property_address || customer.address || '';

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
                        ? `<span title="${this.escapeHtml(address)}">${this.escapeHtml(address)}</span>`
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
                    customersBody.appendChild(row);
                });

                customersWrapper.style.display = 'block';
            }
        }
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

    showPreviewSection() {
        const previewSection = document.getElementById('picPreviewSection');
        if (previewSection) {
            previewSection.style.display = 'block';
        }
    }

    handleSearch() {
        if (!this.statusPlaceholder) {
            return;
        }
        this.statusPlaceholder.textContent = 'Search wiring pending: received query "' + (this.searchInput?.value || '') + '"';
    }

    handleFilterPanel() {
        window.alert('Filter configuration will be added once PIC logic is defined.');
    }

    handleExport() {
        window.alert('Export flow will be implemented after receiving PIC requirements.');
    }

    handleNewCard() {
        window.alert('Card creation wizard is not available yet.');
    }
}

let propertyIndexCardManager;

document.addEventListener('DOMContentLoaded', () => {
    propertyIndexCardManager = new PropertyIndexCardManager();
    window.propertyIndexCardManager = propertyIndexCardManager;
});
