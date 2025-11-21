class FileNumberImportManager {
    constructor() {
        this.sessionId = null;
        this.summary = null;
        this.previewRows = [];
        this.testControl = null;

        this.uploadBtn = document.getElementById('fileNumberUploadBtn');
        this.importBtn = document.getElementById('fileNumberImportBtn');
        this.importHeaderBtn = document.getElementById('fileNumberImportHeaderBtn');
        this.fileInput = document.getElementById('fileNumberFileInput');
        this.testControlSelect = document.getElementById('fileNumberTestControl');
        this.progressBar = document.getElementById('fileNumberProgressBar');
        this.progressText = document.getElementById('fileNumberProgressText');
        this.progressContainer = document.getElementById('fileNumberUploadProgress');
        this.alertContainer = document.getElementById('fileNumberAlertContainer');

        this.previewSection = document.getElementById('fileNumberPreviewSection');
        this.previewBody = document.getElementById('fileNumberPreviewBody');
        this.badge = document.getElementById('fileNumberTestControlBadge');
        this.importSummaryCard = document.getElementById('fileNumberImportSummary');
        this.importSummaryList = document.getElementById('fileNumberImportSummaryList');

        this.bindEvents();
    }

    bindEvents() {
        this.uploadBtn?.addEventListener('click', () => this.uploadFile());
        this.importBtn?.addEventListener('click', () => this.startImport());
        this.importHeaderBtn?.addEventListener('click', () => this.startImport());
    }

    showAlert(message, level = 'info') {
        if (!this.alertContainer) return;
        this.alertContainer.innerHTML = `
            <div class="alert alert-${level} alert-dismissible fade show" role="alert">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>`;
    }

    clearAlert() {
        if (this.alertContainer) {
            this.alertContainer.innerHTML = '';
        }
    }

    setProgress(percent, text) {
        if (!this.progressContainer || !this.progressBar || !this.progressText) {
            return;
        }
        this.progressContainer.style.display = 'block';
        this.progressBar.style.width = `${percent}%`;
        this.progressText.textContent = text;
    }

    hideProgress() {
        if (!this.progressContainer) return;
        this.progressContainer.style.display = 'none';
        this.progressBar.style.width = '0%';
        this.progressText.textContent = '';
    }

    async uploadFile() {
        const file = this.fileInput?.files?.[0];
        const controlValue = this.testControlSelect?.value || '';

        if (!controlValue) {
            this.showAlert('Select TEST or PRODUCTION before uploading.', 'warning');
            return;
        }
        if (!file) {
            this.showAlert('Choose a CSV or Excel file to upload.', 'warning');
            return;
        }

        this.clearAlert();
        this.importSummaryCard.style.display = 'none';
        this.setProgress(20, 'Uploading...');
        this.uploadBtn.disabled = true;

        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('test_control', controlValue);

            const response = await fetch('/api/file-number-import/upload', {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                const payload = await response.json().catch(() => ({ detail: 'Upload failed' }));
                throw new Error(payload.detail || 'Upload failed');
            }

            this.setProgress(80, 'Processing preview...');
            const result = await response.json();
            this.handlePreviewResponse(result);
            this.setProgress(100, 'Preview ready');
        } catch (error) {
            this.showAlert(error.message || 'Upload failed', 'danger');
        } finally {
            this.uploadBtn.disabled = false;
            setTimeout(() => this.hideProgress(), 500);
        }
    }

    handlePreviewResponse(result) {
        this.sessionId = result.session_id;
        this.summary = result.summary || {};
        this.previewRows = Array.isArray(result.preview_rows) ? result.preview_rows : [];
        this.testControl = result.test_control || 'PRODUCTION';

        if (this.badge) {
            this.badge.textContent = `Mode: ${this.testControl}`;
            this.badge.classList.toggle('bg-secondary', this.testControl !== 'PRODUCTION');
            this.badge.classList.toggle('bg-primary', this.testControl === 'PRODUCTION');
        }

        this.renderSummaryCards();
        this.renderPreviewTable();
        this.previewSection.style.display = 'block';
        const readyCount = this.summary.ready_for_import || 0;
        const allowImport = readyCount > 0;
        if (this.importBtn) this.importBtn.disabled = !allowImport;
        if (this.importHeaderBtn) this.importHeaderBtn.disabled = !allowImport;
        this.showAlert('Preview generated. Review the rows and click Import when ready.', 'success');

        const url = new URL(window.location);
        url.searchParams.set('session_id', this.sessionId);
        window.history.replaceState({}, '', url);
    }

    renderSummaryCards() {
        const total = document.getElementById('fileNumberTotalRows');
        const newCount = document.getElementById('fileNumberNewCount');
        const updateCount = document.getElementById('fileNumberUpdateCount');
        const duplicateCount = document.getElementById('fileNumberDuplicateCount');

        if (total) total.textContent = this.summary.total_rows || 0;
        if (newCount) newCount.textContent = this.summary.new_records || 0;
        if (updateCount) updateCount.textContent = this.summary.update_records || 0;
        if (duplicateCount) duplicateCount.textContent = this.summary.duplicates || 0;
    }

    renderPreviewTable() {
        if (!this.previewBody) return;
        if (!Array.isArray(this.previewRows) || this.previewRows.length === 0) {
            this.previewBody.innerHTML = `
                <tr>
                    <td colspan="9" class="text-center text-muted py-4">No rows to display.</td>
                </tr>`;
            return;
        }

        const statusClassMap = {
            insert: 'success',
            update: 'info',
            duplicate_upload: 'warning',
            duplicate_existing: 'warning',
            invalid: 'danger',
            ready: 'secondary',
        };

        const groupingClassMap = {
            matched: 'success',
            missing: 'secondary',
        };

        this.previewBody.innerHTML = '';
        this.previewRows.forEach((row, index) => {
            const status = row.status || 'ready';
            const statusClass = statusClassMap[status] || 'secondary';
            const groupingStatus = row.grouping_status || 'missing';
            const groupingClass = groupingClassMap[groupingStatus] || 'secondary';

            const tr = document.createElement('tr');
            if (status === 'duplicate_upload' || status === 'invalid') {
                tr.classList.add('table-warning');
            }

            tr.innerHTML = `
                <td>${row.index ?? index + 1}</td>
                <td>${this.escape(row.file_number)}</td>
                <td>${this.escape(row.kangis_file_no)}</td>
                <td><span class="badge bg-${statusClass}">${this.escape(row.status_label)}</span></td>
                <td>${this.escape(row.file_name)}</td>
                <td>${this.escape(row.location)}</td>
                <td>${this.escape(row.plot_no)}</td>
                <td>${this.escape(row.tp_no)}</td>
                <td><span class="badge bg-${groupingClass}">${groupingStatus === 'matched' ? 'Matched' : 'Missing'}</span></td>
            `;

            this.previewBody.appendChild(tr);
        });
    }

    escape(value) {
        if (value == null) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    async startImport() {
        if (!this.sessionId) {
            this.showAlert('Upload a file before importing.', 'warning');
            return;
        }

        if (this.importBtn) this.importBtn.disabled = true;
        if (this.importHeaderBtn) this.importHeaderBtn.disabled = true;
        this.showAlert('Import started...', 'info');

        try {
            const response = await fetch(`/api/file-number-import/import/${this.sessionId}`, {
                method: 'POST',
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => ({ detail: 'Import failed' }));
                throw new Error(payload.detail || 'Import failed');
            }
            const result = await response.json();
            this.handleImportResult(result);
        } catch (error) {
            this.showAlert(error.message || 'Import failed', 'danger');
            if (this.importBtn) this.importBtn.disabled = false;
            if (this.importHeaderBtn) this.importHeaderBtn.disabled = false;
        }
    }

    handleImportResult(result) {
        const summary = result.summary || {};
        this.importSummaryList.innerHTML = '';
        const entries = [
            { label: 'Inserted', value: summary.inserted },
            { label: 'Updated', value: summary.updated },
            { label: 'Duplicates Skipped', value: summary.skipped_duplicates },
            { label: 'Invalid Rows Skipped', value: summary.skipped_invalid },
            { label: 'Grouping Updated', value: summary.grouping_updates },
        ];
        entries.forEach(({ label, value }) => {
            const li = document.createElement('li');
            li.textContent = `${label}: ${value ?? 0}`;
            this.importSummaryList.appendChild(li);
        });
        this.importSummaryCard.style.display = 'block';
        this.showAlert('Import completed successfully.', 'success');
        if (this.importBtn) this.importBtn.disabled = true;
        if (this.importHeaderBtn) this.importHeaderBtn.disabled = true;
    }
}

window.addEventListener('DOMContentLoaded', () => {
    new FileNumberImportManager();
});
