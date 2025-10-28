class ExcelConverter {
    constructor() {
        this.sessionId = null;
        this.setupEventListeners();
    }

    setupEventListeners() {
        const fileInput = document.getElementById('excel-file-input');
        const uploadArea = document.getElementById('upload-area');
        const downloadAllBtn = document.getElementById('download-all-btn');

        // File input change
        fileInput.addEventListener('change', (e) => this.handleFileSelect(e.target.files[0]));

        // Drag and drop
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });

        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            const file = e.dataTransfer.files[0];
            if (file) {
                this.handleFileSelect(file);
            }
        });

        // Download all button
        downloadAllBtn.addEventListener('click', () => this.downloadAllSheets());
    }

    async handleFileSelect(file) {
        if (!file) return;

        // Validate file type
        if (!file.name.toLowerCase().endsWith('.xlsx') && !file.name.toLowerCase().endsWith('.xls')) {
            this.showMessage('Please select a valid Excel file (.xlsx or .xls)', 'error');
            return;
        }

        // Show progress
        this.showProgress(true);
        this.hideResults();

        try {
            const formData = new FormData();
            formData.append('file', file);

            const response = await fetch('/api/upload-excel', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.detail || 'Upload failed');
            }

            this.sessionId = result.session_id;
            this.displayResults(result);
            this.showMessage('Excel file processed successfully!', 'success');

        } catch (error) {
            console.error('Upload error:', error);
            this.showMessage(`Error: ${error.message}`, 'error');
        } finally {
            this.showProgress(false);
        }
    }

    displayResults(data) {
        // Update file info
        document.getElementById('excel-filename').textContent = data.filename;
        document.getElementById('total-sheets').textContent = data.total_sheets;

        // Build sheets table
        const tbody = document.getElementById('sheets-table-body');
        tbody.innerHTML = '';

        data.sheets.forEach((sheet, index) => {
            const row = document.createElement('tr');
            
            // Truncate column names if too many
            let columnDisplay = sheet.column_names.slice(0, 3).join(', ');
            if (sheet.column_names.length > 3) {
                columnDisplay += ` ... (+${sheet.column_names.length - 3} more)`;
            }

            row.innerHTML = `
                <td>
                    <strong>${this.escapeHtml(sheet.name)}</strong>
                </td>
                <td>
                    <span class="badge bg-info">${sheet.rows.toLocaleString()}</span>
                </td>
                <td>
                    <span class="badge bg-secondary">${sheet.columns}</span>
                </td>
                <td>
                    <small class="text-muted" title="${sheet.column_names.join(', ')}">${columnDisplay}</small>
                </td>
                <td>
                    <button class="btn btn-sm btn-outline-primary" onclick="excelConverter.downloadSheet('${sheet.name}')">
                        <i class="fas fa-download me-1"></i>Download CSV
                    </button>
                </td>
            `;
            tbody.appendChild(row);
        });

        // Show results section
        document.getElementById('results-section').style.display = 'block';
    }

    async downloadSheet(sheetName) {
        if (!this.sessionId) {
            this.showMessage('No active session found', 'error');
            return;
        }

        try {
            const encodedSheetName = encodeURIComponent(sheetName);
            const url = `/api/export-sheet-csv/${this.sessionId}/${encodedSheetName}`;
            
            // Create a temporary link to trigger download
            const link = document.createElement('a');
            link.href = url;
            link.download = `${sheetName}.csv`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            this.showMessage(`${sheetName} downloaded successfully!`, 'success');

        } catch (error) {
            console.error('Download error:', error);
            this.showMessage(`Error downloading ${sheetName}: ${error.message}`, 'error');
        }
    }

    async downloadAllSheets() {
        if (!this.sessionId) {
            this.showMessage('No active session found', 'error');
            return;
        }

        try {
            const url = `/api/export-all-sheets-csv/${this.sessionId}`;
            
            // Create a temporary link to trigger download
            const link = document.createElement('a');
            link.href = url;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            this.showMessage('All sheets downloaded as ZIP file!', 'success');

        } catch (error) {
            console.error('Download all error:', error);
            this.showMessage(`Error downloading ZIP: ${error.message}`, 'error');
        }
    }

    showProgress(show) {
        const progressDiv = document.getElementById('upload-progress');
        if (show) {
            progressDiv.style.display = 'block';
            progressDiv.querySelector('.progress-bar').style.width = '100%';
        } else {
            progressDiv.style.display = 'none';
            progressDiv.querySelector('.progress-bar').style.width = '0%';
        }
    }

    hideResults() {
        document.getElementById('results-section').style.display = 'none';
    }

    showMessage(message, type) {
        const container = document.getElementById('message-container');
        
        // Remove existing messages
        container.innerHTML = '';
        
        const alertClass = type === 'error' ? 'alert-danger' : 'alert-success';
        const iconClass = type === 'error' ? 'fa-exclamation-circle' : 'fa-check-circle';
        
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert ${alertClass} alert-dismissible fade show`;
        alertDiv.innerHTML = `
            <i class="fas ${iconClass} me-2"></i>
            ${this.escapeHtml(message)}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        container.appendChild(alertDiv);
        
        // Auto-dismiss success messages after 5 seconds
        if (type === 'success') {
            setTimeout(() => {
                if (alertDiv.parentNode) {
                    alertDiv.remove();
                }
            }, 5000);
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize the converter when page loads
let excelConverter;
document.addEventListener('DOMContentLoaded', function() {
    excelConverter = new ExcelConverter();
});

// Add CSS for drag and drop styling
const style = document.createElement('style');
style.textContent = `
    .upload-area {
        transition: all 0.3s ease;
        cursor: pointer;
    }
    
    .upload-area:hover {
        background-color: #f8f9fa;
        border-color: #007bff !important;
    }
    
    .upload-area.dragover {
        background-color: #e3f2fd;
        border-color: #2196f3 !important;
        transform: scale(1.02);
    }
    
    .table th {
        border-top: none;
    }
    
    .badge {
        font-size: 0.75em;
    }
`;
document.head.appendChild(style);