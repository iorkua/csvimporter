// Simple test of the formatPropIdValue and renderPropIdCell helpers
function testFormatPropIdValue() {
    // Simulate the class structure
    const testInstance = {
        sanitizeValue: function(value) {
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
        },
        
        escapeHtml: function(value) {
            const str = value ?? '';
            return str
                .toString()
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        },
        formatPropIdValue: function(value) {
            const sanitized = this.sanitizeValue(value);
            if (!sanitized) {
                return '';
            }
            return sanitized.replace(/^#+/, '').trim();
        },
        renderPropIdCell: function(cell, value, source) {
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
    };
    
    // Test cases
    const sampleCell = () => ({
        textContent: '',
        innerHTML: '',
        _title: undefined,
        set title(value) {
            this._title = value;
        },
        get title() {
            return this._title;
        },
        removeAttribute(attr) {
            if (attr === 'title') {
                this._title = undefined;
            }
        }
    });

    const cell1 = sampleCell();
    testInstance.renderPropIdCell(cell1, '123', null);
    console.log('Test 1 - Basic prop ID:', cell1.textContent);

    const cell2 = sampleCell();
    testInstance.renderPropIdCell(cell2, '#456', 'Existing Source');
    console.log('Test 2 - Prop ID with source (trimmed):', cell2.textContent, 'title:', cell2.title);

    const cell3 = sampleCell();
    testInstance.renderPropIdCell(cell3, '  ##789  ', 'New Source');
    console.log('Test 3 - Multiple hashes removed:', cell3.textContent);

    const cell4 = sampleCell();
    testInstance.renderPropIdCell(cell4, '', null);
    console.log('Test 4 - Empty prop ID placeholder:', cell4.innerHTML);

    const cell5 = sampleCell();
    testInstance.renderPropIdCell(cell5, null, null);
    console.log('Test 5 - Null prop ID placeholder:', cell5.innerHTML);
}

// Run the test
testFormatPropIdValue();