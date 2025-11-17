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
        this.qcIssues = {
            padding: [],
            year: [],
            spacing: []
        };
        this.propertyAssignments = [];
        this.selectedRows = new Set();
        this.pageSizeOptions = [10, 25, 50, 100];
        this.pageSize = 25;
        this.currentPage = 1;
        this.cofoRecordIndices = [];
        this.fileNumberRecordIndices = [];
        this.cofoPreviewNeedsRender = false;
        this.fileNumberPreviewNeedsRender = false;
        this.COFO_PREVIEW_LIMIT = 300;
        this.FILE_NUMBER_PREVIEW_LIMIT = 500;
        this.testControlSelect = document.getElementById('testControlSelect');
        this.testControlMode = this.testControlSelect?.value && this.testControlSelect.value !== ''
            ? this.testControlSelect.value.toUpperCase()
            : null;
        this.clearModeBtn = document.getElementById('clearModeBtn');
        this.confirmClearDataBtn = document.getElementById('confirmClearDataBtn');
        const clearDataModalElement = document.getElementById('clearDataModal');
        this.clearDataModal = (this.clearModeBtn && clearDataModalElement && window.bootstrap && window.bootstrap.Modal)
            ? new window.bootstrap.Modal(clearDataModalElement)
            : null;
        this.isClearingMode = false;
        this.propIdHeader = document.getElementById('propIdHeader');
        this.shouldShowPropIdColumn = false;
        
        this.initializeEventListeners();
        this.initializePaginationControls();
        this.renderGroupingPreview();
        this.checkForSession();
        this.updateModeButtons();
    }
    
    initializeEventListeners() {
        // File upload events
        const csvFileInput = document.getElementById('csvFile');
        const uploadBtn = document.getElementById('uploadBtn');
        const testControlSelect = this.testControlSelect;
        const clearModeBtn = this.clearModeBtn;
        const confirmClearDataBtn = this.confirmClearDataBtn;

        csvFileInput?.addEventListener('change', () => {
            this.updateUploadButtonState();
        });

        testControlSelect?.addEventListener('change', (event) => {
            const value = event.target.value || '';
            this.testControlMode = value ? value.toUpperCase() : null;
            if (this.testControlSelect && this.testControlMode) {
                this.testControlSelect.value = this.testControlMode;
            }
            this.updateUploadButtonState();
            this.updateModeButtons();
        });

        uploadBtn?.addEventListener('click', () => this.uploadFile());
        clearModeBtn?.addEventListener('click', () => {
            if (!this.modeIsSelected()) {
                return;
            }
            if (this.clearDataModal) {
                this.clearDataModal.show();
            }
        });

        confirmClearDataBtn?.addEventListener('click', () => this.handleClearMode());
        
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

        document.getElementById('cofo-preview-tab')?.addEventListener('shown.bs.tab', () => {
            this.renderCoFOPreview({ force: true });
        });

        document.getElementById('filenumber-preview-tab')?.addEventListener('shown.bs.tab', () => {
            this.renderFileNumberPreview({ force: true });
        });

        this.updateUploadButtonState();
    }

    updateUploadButtonState() {
        const uploadBtn = document.getElementById('uploadBtn');
        const fileInput = document.getElementById('csvFile');
        const fileSelected = Boolean(fileInput?.files?.length);
        const modeSelected = this.testControlMode === 'TEST' || this.testControlMode === 'PRODUCTION';

        if (uploadBtn) {
            uploadBtn.disabled = !(fileSelected && modeSelected);
        }

        this.updateModeButtons();
    }

    modeIsSelected() {
        return this.testControlMode === 'TEST' || this.testControlMode === 'PRODUCTION';
    }

    updateModeButtons() {
        if (!this.clearModeBtn || this.isClearingMode) {
            return;
        }
        this.clearModeBtn.disabled = !this.modeIsSelected();
        if (this.confirmClearDataBtn) {
            this.confirmClearDataBtn.disabled = !this.modeIsSelected() || this.isClearingMode;
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
        } else {
            const original = this.clearModeBtn.dataset.originalContent;
            if (original) {
                this.clearModeBtn.innerHTML = original;
            }
        }

        this.clearModeBtn.disabled = isLoading || !this.modeIsSelected();
        if (this.confirmClearDataBtn) {
            this.confirmClearDataBtn.disabled = isLoading;
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
            const response = await fetch('/api/file-indexing/clear-data', {
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
            const entries = Object.entries(counts);
            const totalCleared = entries.reduce((sum, [, value]) => sum + (Number(value) || 0), 0);
            const detailText = entries
                .map(([table, value]) => `${table}: ${Number(value) || 0}`)
                .join(', ');

            const summary = totalCleared > 0
                ? `Cleared ${totalCleared} ${modeLabel} rows (${detailText}).`
                : `No ${modeLabel} rows found to clear.`;

            this.showNotification(summary, 'success');
            if (this.clearDataModal) {
                this.clearDataModal.hide();
            }
        } catch (error) {
            console.error('Clear data error:', error);
            this.showNotification(error.message || 'Failed to clear data', 'error');
            if (this.clearDataModal) {
                this.clearDataModal.hide();
            }
        } finally {
            this.isClearingMode = false;
            this.setClearModeLoading(false);
            this.updateModeButtons();
        }
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
        const testControl = this.testControlMode;
        
        if (!file) {
            this.showNotification('Please select a CSV file', 'warning');
            return;
        }

        if (!testControl) {
            this.showNotification('Select whether this upload is TEST or PRODUCTION before proceeding.', 'warning');
            return;
        }
        
        // Show progress
        this.showSection('progress-section');
        this.hideSection('upload-section');
        this.updateProgress('Uploading file...', 'Reading and validating CSV structure', 20);
        
        const formData = new FormData();
        formData.append('file', file);
        formData.append('test_control', testControl);
        
        try {
            this.updateProgress('Processing data...', 'Analyzing records and checking for duplicates', 40);
            
            const response = await fetch('/api/upload-csv', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                let errorDetail = 'Upload failed';
                const rawBody = await response.text();
                if (rawBody) {
                    try {
                        const parsedError = JSON.parse(rawBody);
                        errorDetail = parsedError.detail || parsedError.message || errorDetail;
                    } catch (parseError) {
                        const fallbackMessage = rawBody.trim();
                        if (fallbackMessage) {
                            if (fallbackMessage.startsWith('<')) {
                                errorDetail = `Upload failed (status ${response.status})`;
                            } else {
                                errorDetail = fallbackMessage;
                            }
                        }
                    }
                }

                throw new Error(errorDetail);
            }
            
            this.updateProgress('Processing complete', 'Finalizing preview data', 90);
            
            const result = await response.json();
            this.currentSessionId = result.session_id;
            if (result.test_control) {
                this.testControlMode = result.test_control;
                if (this.testControlSelect) {
                    this.testControlSelect.value = result.test_control;
                }
                this.updateModeButtons();
            }
            
            // Update URL to include session_id
            const newUrl = new URL(window.location);
            newUrl.searchParams.set('session_id', this.currentSessionId);
            window.history.pushState({}, '', newUrl);
            
            // Update QC summary from upload response
            if (result.qc_summary) {
                const qcSummary = result.qc_summary;
                const totalIssues = qcSummary.total_issues || 0;
                
                // Update tab badge
                const totalIssuesEl = document.getElementById('qc-total-issues');
                if (totalIssuesEl) totalIssuesEl.textContent = totalIssues;
                
                // Update QC summary cards
                const paddingEl = document.getElementById('qcPaddingCount');
                if (paddingEl) paddingEl.textContent = qcSummary.padding_issues || 0;
                
                const yearEl = document.getElementById('qcYearCount');
                if (yearEl) yearEl.textContent = qcSummary.year_issues || 0;
                
                const spacingEl = document.getElementById('qcSpacingCount');
                if (spacingEl) spacingEl.textContent = qcSummary.spacing_issues || 0;
                
                
                // Show notification with QC summary
                if (totalIssues > 0) {
                    this.showNotification(`File uploaded! Found ${totalIssues} QC issues that can be reviewed in the QC tab.`, 'warning');
                }
            }
            
            // Load preview data
            await this.loadPreviewData();
            
            this.showNotification(`File uploaded successfully! ${result.total_records} records found.`, 'success');
            
        } catch (error) {
            console.error('Upload error:', error);
            this.showNotification(`Upload failed: ${error.message}`, 'error');
            this.showSection('upload-section');
        } finally {
            this.hideSection('progress-section');
            this.updateUploadButtonState();
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

            if (result.test_control) {
                this.testControlMode = result.test_control;
                if (this.testControlSelect) {
                    this.testControlSelect.value = result.test_control;
                }
                this.updateModeButtons();
            }
            
            // Update QC data if it exists
            if (result.qc_issues) {
                this.qcIssues.padding = result.qc_issues.padding || [];
                this.qcIssues.year = result.qc_issues.year || [];
                this.qcIssues.spacing = result.qc_issues.spacing || [];
            }
            if (result.property_assignments) {
                this.propertyAssignments = result.property_assignments || [];
            }
            
            this.selectedRows.clear();
            this.currentPage = 1;
            
            this.updateStatistics(result);
            this.renderPreviewTable();
            this.renderGroupingPreview();
            this.renderQCIssues();
            this.prepareDeferredPreviews();
            this.showSection('preview-section');
            this.updateUploadButtonState();
            
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
        const note = typeof this.groupingPreview?.note === 'string' ? this.groupingPreview.note : '';
        const columnCount = 9;
        const displayOrDash = (value) => {
            if (value === null || value === undefined) {
                return '<span class="text-muted">—</span>';
            }
            const stringValue = String(value).trim();
            if (!stringValue) {
                return '<span class="text-muted">—</span>';
            }
            return this.escapeHtml(stringValue);
        };
        const hasValue = (value) => value !== null && value !== undefined && String(value).trim() !== '';

        if (note) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="${columnCount}" class="text-center text-muted py-4">
                        ${this.escapeHtml(note)}
                    </td>
                </tr>`;
            return;
        }

        if (!rows.length) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="${columnCount}" class="text-center text-muted py-4">
                        No grouping matches evaluated yet. Upload a file to preview grouping matches.
                    </td>
                </tr>`;
            return;
        }

        tbody.innerHTML = '';

        rows.forEach((row) => {
            const status = row.status || 'unknown';
            const tr = document.createElement('tr');
            this.applyGroupingStatusStyle(tr, status);

            const originalText = row.file_number != null ? String(row.file_number) : '';
            const normalizedText = row.normalized_file_number != null ? String(row.normalized_file_number) : '';
            const awaitingDisplay = row.awaiting_fileno != null ? String(row.awaiting_fileno) : '';
            const awaitingNormalized = row.awaiting_normalized != null ? String(row.awaiting_normalized) : '';
            const statusReason = row.reason || row.notes || '';

            const normalizedMarkup = normalizedText && normalizedText !== originalText.toUpperCase()
                ? `<div class="text-muted small">Normalized: ${this.escapeHtml(normalizedText)}</div>`
                : '';

            const awaitingDetails = [];
            if (awaitingDisplay) {
                awaitingDetails.push(`Awaiting: ${this.escapeHtml(awaitingDisplay)}`);
            }
            if (awaitingNormalized && awaitingDisplay && awaitingNormalized !== awaitingDisplay.toUpperCase()) {
                awaitingDetails.push(`Awaiting normalized: ${this.escapeHtml(awaitingNormalized)}`);
            }
            const awaitingMarkup = awaitingDetails.length
                ? `<div class="text-muted small">${awaitingDetails.join(' · ')}</div>`
                : '';

            const reasonMarkup = statusReason
                ? `<div>${this.escapeHtml(String(statusReason))}</div>`
                : '';

            const registryMarkup = displayOrDash(row.registry);

            const registryBatchMarkup = displayOrDash(row.registry_batch_no);

            const mdcBatchParts = [];
            const mdcBatchValue = row.mdc_batch_no;
            const csvBatchValue = row.csv_batch_no;
            if (hasValue(mdcBatchValue)) {
                mdcBatchParts.push(`<div>${this.escapeHtml(String(mdcBatchValue))}</div>`);
            }
            if (hasValue(csvBatchValue)) {
                const csvValueEscaped = this.escapeHtml(String(csvBatchValue));
                if (!hasValue(mdcBatchValue)) {
                    mdcBatchParts.push(`<div>${csvValueEscaped}</div>`);
                } else if (String(csvBatchValue).toUpperCase() !== String(mdcBatchValue).toUpperCase()) {
                    mdcBatchParts.push(`<div class="text-muted small">CSV: ${csvValueEscaped}</div>`);
                }
            }
            const mdcBatchMarkup = mdcBatchParts.length ? mdcBatchParts.join('') : '<span class="text-muted">—</span>';

            const notesContent = reasonMarkup || awaitingMarkup
                ? `${reasonMarkup}${awaitingMarkup}`
                : '<span class="text-muted">—</span>';

            tr.innerHTML = `
                <td>
                    <div>${this.escapeHtml(originalText)}</div>
                    ${normalizedMarkup}
                </td>
                <td>${notesContent}</td>
                <td>${displayOrDash(row.sys_batch_no)}</td>
                <td>${mdcBatchMarkup}</td>
                <td>${displayOrDash(row.group)}</td>
                <td>${displayOrDash(row.grouping_number)}</td>
                <td>${registryMarkup}</td>
                <td>${displayOrDash(row.registry_batch_no)}</td>
                <td>${this.getGroupingStatusBadge(status)}</td>
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

    renderQCIssues() {
        const safeIssues = {
            padding: Array.isArray(this.qcIssues.padding) ? this.qcIssues.padding : [],
            year: Array.isArray(this.qcIssues.year) ? this.qcIssues.year : [],
            spacing: Array.isArray(this.qcIssues.spacing) ? this.qcIssues.spacing : []
        };

        this.qcIssues = safeIssues;

        // Update summary cards
        const totalIssues = Object.values(this.qcIssues).reduce((sum, issues) => sum + issues.length, 0);
        const totalIssuesEl = document.getElementById('qc-total-issues');
        if (totalIssuesEl) totalIssuesEl.textContent = totalIssues;
        
        const paddingEl = document.getElementById('qcPaddingCount');
        if (paddingEl) paddingEl.textContent = this.qcIssues.padding.length;
        
        const yearEl = document.getElementById('qcYearCount');
        if (yearEl) yearEl.textContent = this.qcIssues.year.length;
        
        const spacingEl = document.getElementById('qcSpacingCount');
        if (spacingEl) spacingEl.textContent = this.qcIssues.spacing.length;
        
        
        const newAssignments = this.propertyAssignments.filter(item => item.status === 'new').length;
        const existingAssignments = this.propertyAssignments.filter(item => item.status === 'existing').length;
        const propNewEl = document.getElementById('newPropertyIdCount');
        if (propNewEl) propNewEl.textContent = newAssignments;
        const propExistingEl = document.getElementById('existingPropertyIdCount');
        if (propExistingEl) propExistingEl.textContent = existingAssignments;

        // Count fixable issues and show/hide bulk apply button
        const fixableIssues = Object.values(this.qcIssues).reduce((count, issues) => {
            return count + issues.filter(issue => issue.suggested_fix).length;
        }, 0);
        
        const applyAllBtn = document.getElementById('applyAllFixesBtn');
        const fixableCountEl = document.getElementById('fixableIssuesCount');
        
        if (applyAllBtn && fixableCountEl) {
            if (fixableIssues > 0) {
                applyAllBtn.style.display = 'inline-block';
                fixableCountEl.textContent = `${fixableIssues} issues can be auto-fixed`;
            } else {
                applyAllBtn.style.display = 'none';
                fixableCountEl.textContent = totalIssues > 0 ? 'All issues require manual review' : '0 issues can be auto-fixed';
            }
        }

        // Render issues table
        const tbody = document.getElementById('qcIssuesBody');
        if (!tbody) return;

        const allIssues = [];
        
        // Combine all issue types
        ['padding', 'year', 'spacing'].forEach(type => {
            this.qcIssues[type].forEach(issue => {
                allIssues.push({
                    type: type,
                    ...issue
                });
            });
        });

        if (allIssues.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center text-muted py-4">
                        No QC issues found. All file numbers appear to be properly formatted.
                    </td>
                </tr>`;
            return;
        }
        tbody.innerHTML = '';
        allIssues.forEach(issue => {
            const tr = document.createElement('tr');

            const description = issue.description || issue.issue_description || '';
            const severity = issue.severity || issue.priority || 'Medium';
            const suggestedFix = issue.suggested_fix || '';

            const typeTd = document.createElement('td');
            typeTd.innerHTML = this.getIssueTypeBadge(issue.type);
            tr.appendChild(typeTd);

            const fileTd = document.createElement('td');
            fileTd.innerHTML = `<code>${this.escapeHtml(issue.file_number || '')}</code>`;
            tr.appendChild(fileTd);

            const descriptionTd = document.createElement('td');
            descriptionTd.textContent = description;
            tr.appendChild(descriptionTd);

            const fixTd = document.createElement('td');
            fixTd.innerHTML = suggestedFix ? `<code>${this.escapeHtml(suggestedFix)}</code>` : '<span class="text-muted">N/A</span>';
            tr.appendChild(fixTd);

            const severityTd = document.createElement('td');
            severityTd.textContent = severity;
            tr.appendChild(severityTd);

            const actionTd = document.createElement('td');
            if (suggestedFix) {
                const btn = document.createElement('button');
                btn.className = 'btn btn-sm btn-outline-primary qc-auto-fix-btn';
                btn.textContent = 'Auto Fix';
                btn.dataset.recordIndex = issue.record_index;
                btn.dataset.suggestedFix = suggestedFix;
                actionTd.appendChild(btn);
            } else {
                actionTd.innerHTML = '<span class="text-muted">Manual review needed</span>';
            }
            tr.appendChild(actionTd);

            tbody.appendChild(tr);
        });

        // Attach auto-fix handlers
        tbody.querySelectorAll('.qc-auto-fix-btn').forEach(button => {
            button.addEventListener('click', () => {
                const recordIndex = parseInt(button.dataset.recordIndex, 10);
                const suggestedFix = button.dataset.suggestedFix;
                if (!Number.isNaN(recordIndex) && suggestedFix) {
                    this.applyAutoFix(recordIndex, suggestedFix);
                }
            });
        });
    }

    getIssueTypeBadge(type) {
        const typeConfig = {
            padding: { label: 'Padding', theme: 'warning' },
            year: { label: 'Year Format', theme: 'danger' },
            spacing: { label: 'Spacing', theme: 'info' }
        };

        const config = typeConfig[type] || { label: type, theme: 'secondary' };
        return `<span class="badge bg-${config.theme}">${config.label}</span>`;
    }

    async applyAutoFix(recordIndex, suggestedFix) {
        try {
            if (!this.currentSessionId) {
                throw new Error('No active session. Please upload a file first.');
            }

            const response = await fetch(`/api/qc/apply-fixes/${this.currentSessionId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    fixes: [{
                        record_index: recordIndex,
                        new_value: suggestedFix
                    }]
                })
            });

            if (!response.ok) {
                throw new Error('Failed to apply fix');
            }

            const result = await response.json();
            this.showNotification(`Applied fix for record #${recordIndex + 1}`, 'success');
            
            // Update QC issues from response
            if (result.updated_qc_issues) {
                this.qcIssues = result.updated_qc_issues;
            }
            
            // Update grouping preview from response
            if (result.updated_grouping_preview) {
                this.groupingPreview = result.updated_grouping_preview;
                this.renderGroupingPreview();
            }
            
            // Reload preview data to reflect all changes
            await this.loadPreviewData();
            
        } catch (error) {
            console.error('Auto-fix error:', error);
            this.showNotification(`Failed to apply fix: ${error.message}`, 'error');
        }
    }

    setAutoFixLoading(isLoading) {
        const applyAllBtn = document.getElementById('applyAllFixesBtn');
        const idleState = document.getElementById('applyAllFixesIdleState');
        const loadingState = document.getElementById('applyAllFixesLoadingState');
        const fixableCountEl = document.getElementById('fixableIssuesCount');

        if (!applyAllBtn || !idleState || !loadingState) {
            return;
        }

        if (isLoading) {
            applyAllBtn.disabled = true;
            applyAllBtn.setAttribute('aria-busy', 'true');
            idleState.classList.add('d-none');
            loadingState.classList.remove('d-none');

            if (fixableCountEl) {
                fixableCountEl.dataset.originalText = fixableCountEl.textContent || '';
                fixableCountEl.textContent = 'Fixing in progress...';
            }
        } else {
            applyAllBtn.disabled = false;
            applyAllBtn.removeAttribute('aria-busy');
            idleState.classList.remove('d-none');
            loadingState.classList.add('d-none');

            if (fixableCountEl && fixableCountEl.dataset.originalText !== undefined) {
                if (fixableCountEl.textContent === 'Fixing in progress...') {
                    fixableCountEl.textContent = fixableCountEl.dataset.originalText;
                }
                delete fixableCountEl.dataset.originalText;
            }
        }
    }

    async applyAllAutoFixes() {
        const allIssues = [];
        
        // Collect all issues with suggested fixes
        ['padding', 'year', 'spacing'].forEach(type => {
            this.qcIssues[type].forEach(issue => {
                if (issue.suggested_fix) {
                    allIssues.push({
                        record_index: issue.record_index,
                        new_value: issue.suggested_fix
                    });
                }
            });
        });

        if (allIssues.length === 0) {
            this.showNotification('No auto-fixable issues found', 'info');
            return;
        }

        if (!this.currentSessionId) {
            this.showNotification('No active session. Please upload a file first.', 'warning');
            return;
        }

        this.setAutoFixLoading(true);

        try {
            const response = await fetch(`/api/qc/apply-fixes/${this.currentSessionId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    fixes: allIssues
                })
            });

            if (!response.ok) {
                throw new Error('Failed to apply fixes');
            }

            const result = await response.json();
            this.showNotification(`Applied ${allIssues.length} auto-fixes successfully!`, 'success');
            
            // Update QC issues from response
            if (result.updated_qc_issues) {
                this.qcIssues = result.updated_qc_issues;
            }
            
            // Update grouping preview from response
            if (result.updated_grouping_preview) {
                this.groupingPreview = result.updated_grouping_preview;
                this.renderGroupingPreview();
            }
            
            // Reload preview data to reflect all changes
            await this.loadPreviewData();
            
        } catch (error) {
            console.error('Bulk auto-fix error:', error);
            this.showNotification(`Failed to apply fixes: ${error.message}`, 'error');
        } finally {
            this.setAutoFixLoading(false);
        }
    }

    escapeHtml(value) {
        const str = value === undefined || value === null ? '' : String(value);
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    recordHasCofoPayload(record) {
        if (!record || typeof record !== 'object') {
            return false;
        }
        const cofoFields = ['cofo_date', 'serial_no', 'page_no', 'vol_no', 'deeds_time', 'deeds_date'];
        return cofoFields.some((field) => {
            const value = record[field];
            if (value === null || value === undefined) {
                return false;
            }
            const normalized = String(value).trim();
            return normalized.length > 0 && normalized.toLowerCase() !== 'nan';
        });
    }

    prepareDeferredPreviews() {
        this.cofoRecordIndices = [];
        this.fileNumberRecordIndices = [];

        this.currentData.forEach((record, index) => {
            if (this.recordHasCofoPayload(record)) {
                this.cofoRecordIndices.push(index);
            }
            if (record && record.file_number && String(record.file_number).trim() !== '') {
                this.fileNumberRecordIndices.push(index);
            }
        });

        this.updateCofoPreviewCounts();
        this.updateFileNumberPreviewCounts();

        this.cofoPreviewNeedsRender = true;
        this.fileNumberPreviewNeedsRender = true;

        this.clearCofoPreviewTable();
        this.clearFileNumberPreviewTable();

        if (this.isPaneActive('cofo-preview-pane')) {
            this.renderCoFOPreview({ force: true });
        }

        if (this.isPaneActive('filenumber-preview-pane')) {
            this.renderFileNumberPreview({ force: true });
        }
    }

    updateCofoPreviewCounts() {
        const total = this.cofoRecordIndices.length;
        const countBadge = document.getElementById('cofo-preview-count');
        const totalCount = document.getElementById('cofo-total-count');
        if (countBadge) {
            countBadge.textContent = total;
        }
        if (totalCount) {
            totalCount.textContent = total;
        }
    }

    updateFileNumberPreviewCounts() {
        const total = this.fileNumberRecordIndices.length;
        const countBadge = document.getElementById('filenumber-preview-count');
        const totalCount = document.getElementById('filenumber-total-count');
        if (countBadge) {
            countBadge.textContent = total;
        }
        if (totalCount) {
            totalCount.textContent = total;
        }
    }

    clearCofoPreviewTable() {
        const tbody = document.getElementById('cofo-preview-body');
        if (!tbody) {
            return;
        }

        tbody.innerHTML = '';
        const placeholder = document.createElement('tr');
        const message = this.cofoRecordIndices.length === 0
            ? 'No CofO records detected.'
            : 'CofO preview loads when you open this tab.';
        placeholder.innerHTML = `<td colspan="9" class="text-muted text-center py-3">${message}</td>`;
        tbody.appendChild(placeholder);
    }

    clearFileNumberPreviewTable() {
        const tbody = document.getElementById('filenumber-preview-body');
        if (!tbody) {
            return;
        }

        tbody.innerHTML = '';
        const placeholder = document.createElement('tr');
        const message = this.fileNumberRecordIndices.length === 0
            ? 'No file numbers detected.'
            : 'File number preview loads when you open this tab.';
        placeholder.innerHTML = `<td colspan="6" class="text-muted text-center py-3">${message}</td>`;
        tbody.appendChild(placeholder);
    }

    isPaneActive(paneId) {
        const pane = document.getElementById(paneId);
        return pane ? pane.classList.contains('show') && pane.classList.contains('active') : false;
    }

    updatePropIdColumnVisibility() {
        const shouldShow = this.currentData.some((record) => this.recordHasCofoPayload(record));
        this.shouldShowPropIdColumn = shouldShow;
        if (this.propIdHeader) {
            this.propIdHeader.style.display = shouldShow ? '' : 'none';
        }
    }

    refreshPropIdCells() {
        const tbody = document.getElementById('previewTableBody');
        if (!tbody) {
            return;
        }

        const rows = tbody.querySelectorAll('tr');
        rows.forEach((row) => {
            const cell = row.querySelector('.prop-id-cell');
            if (!cell) {
                return;
            }

            const indexAttr = row.dataset.index;
            const recordIndex = Number(indexAttr);
            const record = Number.isNaN(recordIndex) ? null : this.currentData[recordIndex];
            const hasCofoPayload = record ? this.recordHasCofoPayload(record) : false;

            cell.style.display = this.shouldShowPropIdColumn ? '' : 'none';
            cell.textContent = hasCofoPayload && record?.prop_id !== undefined && record?.prop_id !== null
                ? String(record.prop_id)
                : '';
        });
    }

    renderPreviewTable() {
        const tbody = document.getElementById('previewTableBody');
        if (!tbody) return;
        
        this.updatePropIdColumnVisibility();

        const totalRecords = this.currentData.length;
        const totalPages = this.getTotalPages();

        const selectAllCheckbox = document.getElementById('selectAllCheckbox');
        const columnCount = this.shouldShowPropIdColumn ? 20 : 19;

        if (totalRecords === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="${columnCount}" class="text-center text-muted py-4">
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
        this.refreshPropIdCells();
    }
    
    createTableRow(record, displayIndex, actualIndex) {
        const tr = document.createElement('tr');
        tr.dataset.index = actualIndex;
        
        // Check if this file number has multiple occurrences
        const hasMultipleOccurrences = this.multipleOccurrences[record.file_number];
        if (hasMultipleOccurrences) {
            tr.classList.add('table-warning');
        }
        
        const safe = (value) => this.escapeHtml(value ?? '');
        const hasCofoPayload = this.recordHasCofoPayload(record);
        const propIdCellStyle = this.shouldShowPropIdColumn ? '' : ' style="display:none;"';
        const propIdDisplayValue = hasCofoPayload ? safe(record.prop_id) : '';

        tr.innerHTML = `
            <td>
                <input type="checkbox" class="row-select" data-index="${actualIndex}">
            </td>
            <td>${displayIndex}</td>
            <td class="editable-cell" data-field="file_number" data-index="${actualIndex}">
                ${safe(record.file_number)}
                ${hasMultipleOccurrences ? `<span class="badge bg-warning ms-1">×${hasMultipleOccurrences.count}</span>` : ''}
            </td>
            <td class="prop-id-cell"${propIdCellStyle}>${propIdDisplayValue}</td>
            <td class="editable-cell" data-field="registry" data-index="${actualIndex}">${safe(record.registry)}</td>
            <td class="editable-cell" data-field="batch_no" data-index="${actualIndex}">${safe(record.batch_no)}</td>
            <td class="editable-cell" data-field="file_title" data-index="${actualIndex}">${safe(record.file_title)}</td>
            <td class="editable-cell" data-field="district" data-index="${actualIndex}">${safe(record.district)}</td>
            <td class="editable-cell" data-field="lga" data-index="${actualIndex}">${safe(record.lga)}</td>
            <td class="editable-cell" data-field="plot_number" data-index="${actualIndex}">${safe(record.plot_number)}</td>
            <td class="editable-cell" data-field="tp_no" data-index="${actualIndex}">${safe(record.tp_no)}</td>
            <td class="editable-cell" data-field="lpkn_no" data-index="${actualIndex}">${safe(record.lpkn_no)}</td>
            <td class="editable-cell" data-field="cofo_date" data-index="${actualIndex}">${safe(record.cofo_date)}</td>
            <td class="editable-cell" data-field="serial_no" data-index="${actualIndex}">${safe(record.serial_no)}</td>
            <td class="editable-cell" data-field="page_no" data-index="${actualIndex}">${safe(record.page_no)}</td>
            <td class="editable-cell" data-field="vol_no" data-index="${actualIndex}">${safe(record.vol_no)}</td>
            <td class="editable-cell" data-field="deeds_time" data-index="${actualIndex}">${safe(record.deeds_time)}</td>
            <td class="editable-cell" data-field="deeds_date" data-index="${actualIndex}">${safe(record.deeds_date)}</td>
            <td class="editable-cell" data-field="created_by" data-index="${actualIndex}">${safe(record.created_by)}</td>
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

            const cofoFields = ['cofo_date', 'serial_no', 'page_no', 'vol_no', 'deeds_time', 'deeds_date'];
            if (cofoFields.includes(field)) {
                this.updatePropIdColumnVisibility();
                this.refreshPropIdCells();
            }
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
        
        try {
            // Start the background import
            const response = await fetch(`/api/import-file-indexing/${this.currentSessionId}`, {
                method: 'POST'
            });

            const rawBody = await response.text();

            if (!response.ok) {
                let errorDetail = 'Import failed';
                if (rawBody) {
                    try {
                        const parsedError = JSON.parse(rawBody);
                        errorDetail = parsedError.detail || parsedError.message || errorDetail;
                    } catch (parseError) {
                        const fallbackMessage = rawBody.trim();
                        if (fallbackMessage) {
                            errorDetail = fallbackMessage.startsWith('<')
                                ? `Import failed (status ${response.status})`
                                : fallbackMessage;
                        }
                    }
                }
                throw new Error(errorDetail);
            }

            let startResult = {};
            if (rawBody) {
                try {
                    startResult = JSON.parse(rawBody);
                } catch (parseSuccessError) {
                    console.warn('Unexpected import response format:', parseSuccessError);
                }
            }

            // Start polling for progress
            await this.pollImportProgress(modal);
            
        } catch (error) {
            console.error('Import error:', error);
            const progressText = document.getElementById('importProgressText');
            const progressBar = document.getElementById('importProgressBar');
            
            if (progressText) progressText.textContent = 'Import failed!';
            if (progressBar) progressBar.classList.add('bg-danger');
            
            setTimeout(() => {
                modal.hide();
                this.showNotification(`Import failed: ${error.message}`, 'error');
            }, 2000);
        }
    }

    async pollImportProgress(modal) {
        const progressBar = document.getElementById('importProgressBar');
        const progressText = document.getElementById('importProgressText');
        const progressCount = document.getElementById('importProgressCount');
        
        let pollCount = 0;
        const maxPolls = 600; // 10 minutes max (600 * 1000ms) - increased for individual record updates
        
        const poll = async () => {
            try {
                const response = await fetch(`/api/import-progress/${this.currentSessionId}`);
                const progress = await response.json();
                
                if (progress.status === 'not_found') {
                    throw new Error('Import progress not found');
                }
                
                // Update progress UI
                const percentage = Math.round(progress.progress || 0);
                if (progressBar) {
                    progressBar.style.width = `${percentage}%`;
                    progressBar.textContent = `${percentage}%`;
                }
                
                if (progressText) {
                    progressText.textContent = progress.message || 'Processing...';
                }
                
                if (progressCount) {
                    const current = progress.current || 0;
                    const total = progress.total || this.currentData.length;
                    progressCount.textContent = `Record ${current} of ${total}`;
                }
                
                // Check if completed
                if (progress.status === 'completed') {
                    const result = progress.result || {};
                    const importedCount = Number(result.imported_count) || 0;
                    
                    if (progressText) progressText.textContent = 'Import completed successfully!';
                    if (progressCount) progressCount.textContent = `Completed: ${importedCount} of ${this.currentData.length} records`;
                    
                    setTimeout(() => {
                        modal.hide();
                        this.showNotification(`Successfully imported ${importedCount} file indexing records!`, 'success');
                        this.resetInterface();
                    }, 2000);
                    return;
                }
                
                // Check if failed
                if (progress.status === 'error') {
                    throw new Error(progress.error || 'Import failed');
                }
                
                // Continue polling if still processing
                pollCount++;
                if (pollCount < maxPolls) {
                    setTimeout(poll, 1000); // Poll every second
                } else {
                    throw new Error('Import timeout - taking too long');
                }
                
            } catch (error) {
                console.error('Progress polling error:', error);
                if (progressText) progressText.textContent = 'Import failed!';
                if (progressBar) progressBar.classList.add('bg-danger');
                
                setTimeout(() => {
                    modal.hide();
                    this.showNotification(`Import failed: ${error.message}`, 'error');
                }, 2000);
            }
        };
        
        // Start polling
        setTimeout(poll, 500); // Start after 500ms
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
        this.cofoRecordIndices = [];
        this.fileNumberRecordIndices = [];
        this.cofoPreviewNeedsRender = false;
        this.fileNumberPreviewNeedsRender = false;
        this.renderPreviewTable();
        this.renderGroupingPreview();
        this.updateCofoPreviewCounts();
        this.updateFileNumberPreviewCounts();
        this.clearCofoPreviewTable();
        this.clearFileNumberPreviewTable();
        
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
    
    // Staging Preview Functions (NEW)

    renderCoFOPreview({ force = false } = {}) {
        if (!force && !this.cofoPreviewNeedsRender) {
            return;
        }

        const tbody = document.getElementById('cofo-preview-body');
        if (!tbody) {
            return;
        }

        this.cofoPreviewNeedsRender = false;
        tbody.innerHTML = '';

        const total = this.cofoRecordIndices.length;
        this.updateCofoPreviewCounts();

        if (total === 0) {
            const emptyRow = document.createElement('tr');
            emptyRow.innerHTML = '<td colspan="9" class="text-center text-muted py-3">No CofO records detected.</td>';
            tbody.appendChild(emptyRow);
            return;
        }

        const fragment = document.createDocumentFragment();
        const limit = this.COFO_PREVIEW_LIMIT;

        this.cofoRecordIndices.slice(0, limit).forEach((recordIndex, position) => {
            const record = this.currentData[recordIndex];
            const formattedDeedsTime = this.formatDeedsTime(record.deeds_time);
            const row = document.createElement('tr');
            row.innerHTML = `
                <td class="text-center"><strong>${position + 1}</strong></td>
                <td><code>${record.file_number || '—'}</code></td>
                <td>${record.cofo_date || '—'}</td>
                <td>${record.deeds_date || '—'}</td>
                <td>${formattedDeedsTime}</td>
                <td>${record.registry || '—'}</td>
                <td><code>${record.serial_no || '—'}</code></td>
                <td><code>${record.page_no || '—'}</code></td>
                <td><code>${record.vol_no || '—'}</code></td>
            `;
            fragment.appendChild(row);
        });

        tbody.appendChild(fragment);

        if (total > limit) {
            const noteRow = document.createElement('tr');
            noteRow.innerHTML = `<td colspan="9" class="text-muted small">Showing first ${limit} of ${total} CofO records. Export or paginate data for the full list.</td>`;
            tbody.appendChild(noteRow);
        }
    }

    renderFileNumberPreview({ force = false } = {}) {
        if (!force && !this.fileNumberPreviewNeedsRender) {
            return;
        }

        const tbody = document.getElementById('filenumber-preview-body');
        if (!tbody) {
            return;
        }

        this.fileNumberPreviewNeedsRender = false;
        tbody.innerHTML = '';

        const total = this.fileNumberRecordIndices.length;
        this.updateFileNumberPreviewCounts();

        if (total === 0) {
            const emptyRow = document.createElement('tr');
            emptyRow.innerHTML = '<td colspan="6" class="text-center text-muted py-3">No file numbers detected.</td>';
            tbody.appendChild(emptyRow);
            return;
        }

        const fragment = document.createDocumentFragment();
        const limit = this.FILE_NUMBER_PREVIEW_LIMIT;

        this.fileNumberRecordIndices.slice(0, limit).forEach((recordIndex, position) => {
            const record = this.currentData[recordIndex];
            const locationParts = [];
            if (record.district) {
                locationParts.push(record.district);
            }
            if (record.lga) {
                locationParts.push(record.lga);
            }
            const location = locationParts.length > 0 ? locationParts.join(', ') : '—';

            const registryBatch = record.registry_batch_no || '—';

            const row = document.createElement('tr');
            row.innerHTML = `
                <td class="text-center"><strong>${position + 1}</strong></td>
                <td><code>${record.file_number || '—'}</code></td>
                <td>${record.file_title || '—'}</td>
                <td>${record.plot_number || '—'}</td>
                <td>${record.tp_no || '—'}</td>
                <td>${location}</td>
                <td>${registryBatch}</td>
            `;
            fragment.appendChild(row);
        });

        tbody.appendChild(fragment);

        if (total > limit) {
            const noteRow = document.createElement('tr');
            noteRow.innerHTML = `<td colspan="6" class="text-muted small">Showing first ${limit} of ${total} file indexing rows.</td>`;
            tbody.appendChild(noteRow);
        }
    }
    
    getTypeClass(type) {
        const classMap = {
            'Individual': 'badge-individual',
            'Corporate': 'badge-corporate',
            'Multiple': 'badge-multiple'
        };
        return classMap[type] || 'badge-secondary';
    }
    
    truncate(text, length) {
        if (!text) return '';
        return text.length > length ? text.substring(0, length) + '...' : text;
    }

    formatDeedsTime(value) {
        if (value === null || value === undefined) {
            return '—';
        }

        const raw = String(value).trim();
        if (!raw) {
            return '—';
        }

        const upper = raw.toUpperCase();
        if (upper.endsWith('AM') || upper.endsWith('PM')) {
            // Ensure there is a space before the period marker
            const period = upper.slice(-2);
            const base = upper.slice(0, -2).trim();
            return base ? `${base} ${period}` : `12:00 ${period}`;
        }

        const numericCandidate = upper.replace(/[^0-9]/g, '');
        const colonNormalized = upper.replace(/[^0-9:]/g, '');
        let hour;
        let minutes;
        let seconds = null;

        if (colonNormalized.includes(':')) {
            const segments = colonNormalized.split(':').filter(segment => segment !== '');
            if (segments.length === 0) {
                return raw;
            }

            hour = parseInt(segments[0], 10);
            if (Number.isNaN(hour)) {
                return raw;
            }

            minutes = segments[1] ? segments[1].padStart(2, '0').slice(0, 2) : '00';
            seconds = segments[2] ? segments[2].padStart(2, '0').slice(0, 2) : null;
        } else {
            const match = numericCandidate.match(/^([0-9]{1,2})([0-9]{2})([0-9]{2})?$/);
            if (!match) {
                return raw;
            }

            hour = parseInt(match[1], 10);
            minutes = match[2];
            seconds = match[3] || null;
        }

        minutes = minutes.padStart(2, '0');
        if (seconds) {
            seconds = seconds.padStart(2, '0');
        }

        let period = 'AM';
        if (hour >= 12) {
            period = 'PM';
        }

        hour = hour % 12;
        if (hour === 0) {
            hour = 12;
        }

        const hourDisplay = hour.toString().padStart(2, '0');
        const timeCore = seconds ? `${hourDisplay}:${minutes}:${seconds}` : `${hourDisplay}:${minutes}`;
        return `${timeCore} ${period}`;
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
    
    updateProgress(title, description, percentage) {
        const titleEl = document.getElementById('progress-title');
        const descEl = document.getElementById('progress-description');
        const barEl = document.getElementById('upload-progress-bar');
        
        if (titleEl) titleEl.textContent = title;
        if (descEl) descEl.textContent = description;
        if (barEl) barEl.style.width = `${percentage}%`;
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const manager = new FileIndexingManager();
    window.fileIndexingManager = manager;
    window.fileIndexer = manager; // Legacy alias for inline handlers

    const qcTab = document.getElementById('qc-issues-tab');
    qcTab?.addEventListener('shown.bs.tab', () => {
        manager.renderQCIssues();
    });
});