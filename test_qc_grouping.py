#!/usr/bin/env python3

import pandas as pd
from main import process_file_indexing_data, _run_qc_validation, _build_grouping_preview

# Test QC fix affecting grouping matches
print("Testing QC fix impact on grouping matches...")

# Create test data with a spacing issue that might affect grouping
df = pd.DataFrame({
    'Registry': [3, 3], 
    'Batch No': [3, 3], 
    'File Number': ['CON -COM- 1985-53', 'CON-COM-1985-54']  # First has spacing issue
})

records = process_file_indexing_data(df).to_dict('records')
print(f"\nOriginal file numbers:")
for i, r in enumerate(records):
    print(f"  {i+1}: '{r['file_number']}'")

# Run initial QC validation
qc_issues = _run_qc_validation(records)
print(f"\nQC issues found: {sum(len(issues) for issues in qc_issues.values())}")
for issue_type, issues in qc_issues.items():
    if issues:
        print(f"  {issue_type}: {len(issues)} issues")

# Build initial grouping preview
grouping_preview = _build_grouping_preview(records)
print(f"\nInitial grouping matches:")
print(f"  Matched: {grouping_preview['summary'].get('matched', 0)}")
print(f"  Missing: {grouping_preview['summary'].get('missing', 0)}")
print(f"  Skipped: {grouping_preview['summary'].get('skipped', 0)}")

# Simulate applying a QC fix (remove spaces)
if qc_issues['spacing']:
    spacing_issue = qc_issues['spacing'][0]
    record_index = spacing_issue['record_index']
    suggested_fix = spacing_issue['suggested_fix']
    
    print(f"\nApplying QC fix:")
    print(f"  Record {record_index + 1}: '{records[record_index]['file_number']}' -> '{suggested_fix}'")
    
    # Apply the fix
    records[record_index]['file_number'] = suggested_fix
    
    # Recalculate grouping preview after fix
    updated_grouping_preview = _build_grouping_preview(records)
    print(f"\nUpdated grouping matches after QC fix:")
    print(f"  Matched: {updated_grouping_preview['summary'].get('matched', 0)}")
    print(f"  Missing: {updated_grouping_preview['summary'].get('missing', 0)}")
    print(f"  Skipped: {updated_grouping_preview['summary'].get('skipped', 0)}")
    
    # Show if any changes occurred
    if grouping_preview['summary'] != updated_grouping_preview['summary']:
        print(f"\n✅ Grouping matches changed after QC fix!")
    else:
        print(f"\n📝 Grouping matches remained the same after QC fix.")
else:
    print("No spacing issues found to test with.")