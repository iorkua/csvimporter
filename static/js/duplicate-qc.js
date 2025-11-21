const DUPLICATE_TABLES = {
    file_indexing: {
        label: 'File Indexing',
        tableId: 'table-file-indexing',
        paginationInfoId: 'file-indexing-pagination',
        paginationControlsId: 'file-indexing-page-buttons',
        columns: ['keep', 'id', 'file_number', 'file_name', 'batch_no', 'tracking_id', 'prop_id', 'created_by', 'registry', 'created_at', 'updated_at', 'test_control']
    },
    cofo: {
        label: 'CofO',
        tableId: 'table-cofo',
        paginationInfoId: 'cofo-pagination',
        paginationControlsId: 'cofo-page-buttons',
        columns: ['keep', 'id', 'file_number', 'grantor', 'grantee', 'created_by', 'created_at', 'updated_at', 'test_control']
    },
    file_number: {
        label: 'File Number',
        tableId: 'table-file-number',
        paginationInfoId: 'file-number-pagination',
        paginationControlsId: 'file-number-page-buttons',
        columns: ['keep', 'id', 'file_number', 'file_name', 'tracking_id', 'created_at', 'updated_at', 'test_control']
    }
};

class DuplicateQCManager {
    constructor() {
        this.pageSize = 25;
        this.currentTable = 'file_indexing';
        this.testControl = '';
        this.selections = {
            file_indexing: {},
            cofo: {},
            file_number: {}
        };
        this.visibleGroups = {
            file_indexing: [],
            cofo: [],
            file_number: []
        };
        this.summaryElements = {
            file_indexing: document.getElementById('fileIndexingDuplicateCount'),
            cofo: document.getElementById('cofoDuplicateCount'),
            file_number: document.getElementById('fileNumberDuplicateCount')
        };
        this.alertContainer = document.getElementById('duplicateAlertContainer');
        this.tableDeleteButtons = {
            file_indexing: document.getElementById('delete-file-indexing'),
            cofo: document.getElementById('delete-cofo'),
            file_number: document.getElementById('delete-file-number')
        };
        this.testControlSelect = document.getElementById('duplicateTestControl');
        this.tabs = document.getElementById('duplicateTabs');

        this.registerEvents();
        this.initialize();
    }

    registerEvents() {
        Object.entries(this.tableDeleteButtons).forEach(([tableKey, button]) => {
            if (!button) {
                return;
            }
            button.addEventListener('click', () => this.handleBulkDelete(tableKey));
        });
        if (this.testControlSelect) {
            this.testControlSelect.addEventListener('change', () => {
                this.testControl = this.testControlSelect.value;
                this.resetSelections();
                this.loadAllSummaries();
                this.loadTable(this.currentTable, 1);
            });
        }
        if (this.tabs) {
            this.tabs.addEventListener('shown.bs.tab', (event) => {
                const targetId = event.target.getAttribute('data-bs-target');
                if (targetId === '#pane-file-indexing') {
                    this.currentTable = 'file_indexing';
                } else if (targetId === '#pane-cofo') {
                    this.currentTable = 'cofo';
                } else {
                    this.currentTable = 'file_number';
                }
                this.loadTable(this.currentTable, 1);
            });
        }
    }

    async initialize() {
        await this.loadAllSummaries();
        await this.loadTable(this.currentTable, 1);
    }

    resetSelections() {
        this.selections = {
            file_indexing: {},
            cofo: {},
            file_number: {}
        };
        this.visibleGroups = {
            file_indexing: [],
            cofo: [],
            file_number: []
        };
        this.updateDeleteButtons();
    }

    async loadAllSummaries() {
        await Promise.all(Object.keys(DUPLICATE_TABLES).map((tableKey) => this.fetchSummary(tableKey)));
    }

    async fetchSummary(tableKey) {
        try {
            const params = new URLSearchParams({
                table: tableKey,
                page: '1',
                page_size: '1'
            });
            if (this.testControl) {
                params.append('test_control', this.testControl);
            }
            const response = await fetch(`/api/duplicate-qc/groups?${params.toString()}`);
            if (!response.ok) {
                throw new Error(await response.text());
            }
            const payload = await response.json();
            const summaryElement = this.summaryElements[tableKey];
            if (summaryElement) {
                summaryElement.textContent = payload.total_groups || 0;
            }
        } catch (error) {
            console.error('Failed to load duplicate summary:', error);
            this.showAlert('Unable to refresh duplicate counts.', 'danger');
        }
    }

    async loadTable(tableKey, page) {
        try {
            const params = new URLSearchParams({
                table: tableKey,
                page: String(page),
                page_size: String(this.pageSize)
            });
            if (this.testControl) {
                params.append('test_control', this.testControl);
            }
            const response = await fetch(`/api/duplicate-qc/groups?${params.toString()}`);
            if (!response.ok) {
                throw new Error(await response.text());
            }
            const payload = await response.json();
            this.renderTable(tableKey, payload);
            this.updateSummary(tableKey, payload.total_groups || 0);
            this.currentTable = tableKey;
            this.updateDeleteButtons();
        } catch (error) {
            console.error('Failed to load duplicate groups:', error);
            this.showAlert('Failed to load duplicate data.', 'danger');
        }
    }

    renderTable(tableKey, payload) {
        const config = DUPLICATE_TABLES[tableKey];
        const table = document.getElementById(config.tableId);
        if (!table) {
            return;
        }
        const tbody = table.querySelector('tbody');
        if (!tbody) {
            return;
        }

        tbody.innerHTML = '';
        const columnCount = table.querySelectorAll('thead th').length;
        const groups = payload.groups || [];
        this.visibleGroups[tableKey] = groups.map((group) => group.group_key);

        if (!groups.length) {
            const emptyRow = document.createElement('tr');
            emptyRow.innerHTML = `<td colspan="${columnCount}" class="text-center text-muted py-4">No duplicates found for this table.</td>`;
            tbody.appendChild(emptyRow);
            this.renderPaginationControls(tableKey, 0, payload.page || 1, payload.page_size || this.pageSize);
            return;
        }

        groups.forEach((group) => {
            const headerRow = document.createElement('tr');
            headerRow.className = 'table-secondary';

            const headerCell = document.createElement('td');
            headerCell.colSpan = columnCount;

            const headerContent = document.createElement('div');
            headerContent.className = 'd-flex justify-content-between align-items-center';

            const titleWrapper = document.createElement('div');
            const titleStrong = document.createElement('strong');
            titleStrong.textContent = group.display_value || group.group_key;
            titleWrapper.appendChild(titleStrong);
            titleWrapper.appendChild(document.createTextNode(` · ${group.records.length} duplicates`));

            const groupDeleteButton = document.createElement('button');
            groupDeleteButton.type = 'button';
            groupDeleteButton.className = 'btn btn-sm btn-outline-danger';
            groupDeleteButton.innerHTML = '<i class="fas fa-trash-alt me-1"></i>Delete group';
            groupDeleteButton.addEventListener('click', () => {
                this.handleGroupDelete(tableKey, group.group_key, groupDeleteButton);
            });

            headerContent.appendChild(titleWrapper);
            headerContent.appendChild(groupDeleteButton);

            headerCell.appendChild(headerContent);
            headerRow.appendChild(headerCell);
            tbody.appendChild(headerRow);

            const existingSelection = this.selections[tableKey][group.group_key];
            const keepId = existingSelection && existingSelection.keepId && group.records.some((record) => record.id === existingSelection.keepId)
                ? existingSelection.keepId
                : group.keep_id;

            group.records.forEach((record) => {
                const row = document.createElement('tr');
                row.dataset.groupKey = group.group_key;
                row.dataset.recordId = String(record.id);

                const keepCell = document.createElement('td');
                const radio = document.createElement('input');
                radio.type = 'radio';
                radio.name = `${tableKey}-${group.group_key}`;
                radio.value = String(record.id);
                radio.checked = Number(record.id) === Number(keepId);
                radio.addEventListener('change', () => {
                    this.setSelection(tableKey, group.group_key, Number(record.id), group.records, {
                        displayValue: group.display_value
                    });
                });
                keepCell.appendChild(radio);
                row.appendChild(keepCell);

                row.appendChild(this.buildCell(record.id));
                row.appendChild(this.buildCell(record.file_number || '--'));

                if (tableKey === 'cofo') {
                    const grantorValue = record.grantor || record.Grantor || '--';
                    const granteeValue = record.grantee || record.Grantee || '--';
                    row.appendChild(this.buildCell(grantorValue || '--'));
                    row.appendChild(this.buildCell(granteeValue || '--'));
                    row.appendChild(this.buildCell(record.created_by || record.CreatedBy || '--'));
                    row.appendChild(this.buildCell(this.formatTimestamp(record.created_at)));
                    row.appendChild(this.buildCell(this.formatTimestamp(record.updated_at)));
                    row.appendChild(this.buildCell(record.test_control || '--'));
                } else if (tableKey === 'file_indexing') {
                    const nameValue = record.file_name || record.file_title || record.FileName || record.FileTitle || '--';
                    const trackingValue = record.tracking_id || record.trackingId || '--';
                    const batchValue = record.batch_no ?? record.batchNo ?? record.BatchNo;
                    const propValue = record.prop_id || record.propId || '--';
                    const indexedBy = record.created_by || record.createdBy || '--';
                    const registryValue = record.registry || record.Registry || '--';
                    row.appendChild(this.buildCell(nameValue || '--'));
                    row.appendChild(this.buildCell(batchValue == null ? '--' : batchValue));
                    row.appendChild(this.buildCell(trackingValue || '--'));
                    row.appendChild(this.buildCell(propValue || '--'));
                    row.appendChild(this.buildCell(indexedBy || '--'));
                    row.appendChild(this.buildCell(registryValue || '--'));
                    row.appendChild(this.buildCell(this.formatTimestamp(record.created_at)));
                    row.appendChild(this.buildCell(this.formatTimestamp(record.updated_at)));
                    row.appendChild(this.buildCell(record.test_control || '--'));
                } else {
                    const nameValue = record.file_name || record.file_title || record.FileName || record.FileTitle || '--';
                    const trackingValue = record.tracking_id || record.trackingId || '--';
                    row.appendChild(this.buildCell(nameValue || '--'));
                    row.appendChild(this.buildCell(trackingValue || '--'));
                    row.appendChild(this.buildCell(this.formatTimestamp(record.created_at)));
                    row.appendChild(this.buildCell(this.formatTimestamp(record.updated_at)));
                    row.appendChild(this.buildCell(record.test_control || '--'));
                }

                tbody.appendChild(row);
            });

            this.setSelection(tableKey, group.group_key, Number(keepId), group.records, {
                displayValue: group.display_value,
                silent: true
            });
        });

        this.renderPaginationControls(tableKey, payload.total_groups || 0, payload.page || 1, payload.page_size || this.pageSize);
        this.updateDeleteButtons();
    }

    buildCell(value) {
        const td = document.createElement('td');
        td.textContent = value == null ? '--' : String(value);
        return td;
    }

    renderPaginationControls(tableKey, totalGroups, page, pageSize) {
        const infoEl = document.getElementById(DUPLICATE_TABLES[tableKey].paginationInfoId);
        const controlsEl = document.getElementById(DUPLICATE_TABLES[tableKey].paginationControlsId);
        const totalPages = totalGroups ? Math.ceil(totalGroups / pageSize) : 1;

        if (infoEl) {
            infoEl.textContent = totalGroups
                ? `Page ${page} of ${totalPages} · ${totalGroups} groups`
                : 'No duplicates detected.';
        }

        if (!controlsEl) {
            return;
        }

        controlsEl.innerHTML = '';

        const addButton = (label, targetPage, disabled) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-outline-secondary';
            btn.textContent = label;
            btn.disabled = disabled;
            btn.addEventListener('click', () => this.loadTable(tableKey, targetPage));
            controlsEl.appendChild(btn);
        };

        addButton('Prev', Math.max(page - 1, 1), page <= 1);
        addButton('Next', Math.min(page + 1, totalPages), page >= totalPages);
    }

    updateSummary(tableKey, total) {
        const summaryElement = this.summaryElements[tableKey];
        if (summaryElement) {
            summaryElement.textContent = total;
        }
    }

    setSelection(tableKey, groupKey, keepId, records, options = {}) {
        const { silent = false, displayValue = null } = options;
        this.selections[tableKey][groupKey] = {
            keepId,
            records,
            displayValue
        };
        if (!silent) {
            this.updateDeleteButtons();
        }
    }

    getDeletableGroups(tableKey, targetGroupKey = null) {
        const groups = this.selections[tableKey] || {};
        const visible = new Set(this.visibleGroups[tableKey] || []);

        return Object.entries(groups)
            .filter(([groupKey]) => {
                if (targetGroupKey && groupKey !== targetGroupKey) {
                    return false;
                }
                return visible.has(groupKey);
            })
            .map(([groupKey, state]) => {
                const deleteIds = (state.records || [])
                    .map((record) => record.id)
                    .filter((id) => Number(id) !== Number(state.keepId));
                return {
                    group_key: groupKey,
                    keep_id: state.keepId,
                    delete_ids: deleteIds
                };
            })
            .filter((entry) => entry.delete_ids.length > 0);
    }

    updateDeleteButtons() {
        Object.entries(this.tableDeleteButtons).forEach(([tableKey, button]) => {
            if (!button) {
                return;
            }
            const deletable = this.getDeletableGroups(tableKey);
            button.disabled = deletable.length === 0;
        });
    }

    async handleBulkDelete(tableKey) {
        const button = this.tableDeleteButtons[tableKey];
        const groups = this.getDeletableGroups(tableKey);
        if (!groups.length) {
            this.showAlert('Select a duplicate group before deleting.', 'warning');
            return;
        }

        const totalDeletes = groups.reduce((sum, group) => sum + group.delete_ids.length, 0);
        const label = DUPLICATE_TABLES[tableKey]?.label || tableKey;
        const confirmed = window.confirm(`Delete ${totalDeletes} record(s) across ${groups.length} ${groups.length === 1 ? 'group' : 'groups'} in ${label}?`);
        if (!confirmed) {
            return;
        }

        if (button) {
            button.disabled = true;
        }
        try {
            const payload = {
                table: tableKey,
                test_control: this.testControl || null,
                groups: groups
            };

            const response = await fetch('/api/duplicate-qc/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                throw new Error(await response.text());
            }

            const result = await response.json();
            this.showAlert(`Deleted ${result.deleted || 0} record(s).`, 'success');
            await this.loadAllSummaries();
            await this.loadTable(tableKey, 1);
        } catch (error) {
            console.error('Deletion failed:', error);
            this.showAlert('Deletion failed. See console for details.', 'danger');
        } finally {
            if (button) {
                button.disabled = false;
            }
            this.updateDeleteButtons();
        }
    }

    async handleGroupDelete(tableKey, groupKey, triggerButton) {
        const selection = this.selections[tableKey]?.[groupKey];
        if (!selection) {
            this.showAlert('Unable to determine selected record for this group.', 'warning');
            return;
        }

        const deleteIds = (selection.records || [])
            .map((record) => record.id)
            .filter((id) => Number(id) !== Number(selection.keepId));

        if (!deleteIds.length) {
            this.showAlert('No records available to delete for this group.', 'info');
            return;
        }

        const label = DUPLICATE_TABLES[tableKey]?.label || tableKey;
        const descriptor = selection.displayValue || groupKey;
        const confirmed = window.confirm(`Delete ${deleteIds.length} record(s) from group "${descriptor}" in ${label}?`);
        if (!confirmed) {
            return;
        }

        if (triggerButton) {
            triggerButton.disabled = true;
        }

        try {
            const payload = {
                table: tableKey,
                test_control: this.testControl || null,
                groups: [{
                    group_key: groupKey,
                    keep_id: selection.keepId,
                    delete_ids: deleteIds
                }]
            };

            const response = await fetch('/api/duplicate-qc/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                throw new Error(await response.text());
            }

            const result = await response.json();
            this.showAlert(`Deleted ${result.deleted || 0} record(s) from group "${descriptor}".`, 'success');
            await this.loadAllSummaries();
            await this.loadTable(tableKey, 1);
        } catch (error) {
            console.error('Group deletion failed:', error);
            this.showAlert('Group deletion failed. See console for details.', 'danger');
        } finally {
            if (triggerButton) {
                triggerButton.disabled = false;
            }
            this.updateDeleteButtons();
        }
    }

    formatTimestamp(value) {
        if (!value) {
            return '--';
        }
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return String(value);
        }
        return `${date.toLocaleDateString()} ${date.toLocaleTimeString()}`;
    }

    showAlert(message, type = 'info') {
        if (!this.alertContainer) {
            return;
        }
        const wrapper = document.createElement('div');
        wrapper.className = `alert alert-${type} alert-dismissible fade show`;
        wrapper.role = 'alert';
        wrapper.innerHTML = `
            ${this.escapeHtml(message)}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        this.alertContainer.appendChild(wrapper);
        setTimeout(() => {
            wrapper.classList.remove('show');
            wrapper.classList.add('hide');
            wrapper.addEventListener('transitionend', () => wrapper.remove(), { once: true });
        }, 5000);
    }

    escapeHtml(value) {
        const div = document.createElement('div');
        div.textContent = value ?? '';
        return div.innerHTML;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new DuplicateQCManager();
});

