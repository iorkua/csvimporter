# CSV Importer – Copilot Guide

## Architecture snapshot
- FastAPI entrypoint in `main.py` handles every feature (PRA import, file indexing, file history, Excel conversion) and mounts the Jinja templates under `templates/`.
- Upload flows buffer parsed CSV/Excel rows into `app.sessions[session_id]` dictionaries; each session stores `property_records`, `cofo_records`, QC buckets, duplicate summaries, and is cleared after import.
- Database access lives in `app/models/database.py` using SQLAlchemy; `get_database_url()` auto-switches between SQL Server (via `.env`) and local SQLite `file_indexing.db`.
- Frontend pages follow the same naming triad: HTML in `templates/`, controller script in `static/js/<feature>.js`, and shared styling in `static/css/style.css`.

## Backend patterns
- Reuse helpers in `main.py` (e.g. `_run_pra_qc_validation`, `_assign_property_ids`, `_refresh_file_history_session_state`) instead of open-coding QC or session math—UI scripts expect their output shape.
- Keep record arrays aligned by index: the same `record_index` updates both property and CofO rows, so deletions must pop from both lists.
- New endpoints should return the standard preview payload (`property_records`, `cofo_records`, `issues`, `duplicates`, `total_records`, `ready_records`) so the existing JS renderers continue to work.
- Long-running tasks rely on Pandas plus in-memory processing; stream uploads into `io.BytesIO` and call the existing normalization utilities (`_normalize_string`, `_strip_all_whitespace`, etc.) for consistency.

## Quality control & file-number rules
- `_run_pra_qc_validation` is the single source for file-number QC. It fans out to `_check_padding_issue`, `_check_year_issue`, and `_check_spacing_issue`, returning entries that include `record_index`, `file_number`, and optional `suggested_fix` strings.
- File History adds supplemental buckets (`missing_required_fields`, `invalid_dates`, `missing_reg_components`) in `_run_file_history_qc_validation`; mark `record['hasIssues']` when anything is appended so the UI highlights the row.
- When updating a record server-side, call `_apply_file_history_field_update` so linked fields stay in sync (e.g. editing `mlsFNo` also updates `fileno`, `file_number`, and parallel CofO rows).
- The frontend expects QC payload keys to match `fileNumberIssueTypes` in `static/js/file-history-import.js` (default: `padding`, `year`, `spacing`, `missing_file_number`). Adding a new bucket means updating that array plus the summary card config.
- Auto-fix buttons use the `suggested_fix` string: `applyFileNumberFix` posts a `record_type='records'` update for `mlsFNo`. Populate `suggested_fix` whenever a backend rule can safely normalize a value.

## Frontend patterns
- Feature scripts such as `static/js/file-history-import.js` and `static/js/file-indexing.js` expect JSON responses in the shapes produced by the backend helpers; adjust both sides together when adding fields.
- Inline editing and delete actions call `/api/file-history/update|delete/{session_id}` and assume optimistic updates—remember to re-run QC+duplicate counts server-side before responding.
- Table badges and summary counts are derived from QC category keys (`padding`, `year`, `spacing`, etc.); if you add a new category, update both the config array and CSS badge mapping.
- Bootstrap 5 plus custom utilities (`inline-editable`, `history-delete-btn`) drive the UI; keep new components compatible with the existing class structure.

## Developer workflow
- Preferred startup is `start_csvimporter.bat`, which creates `.venv`, installs `requirements.txt`, and runs `python main.py`; manual fallback is `uvicorn main:app --reload --port 5000`.
- Tests under `tests/` and `scripts/test_*.py` use `pytest` but expect a running API (`http://127.0.0.1:5000`) and an accessible SQL Server. Spin those up or mock the calls before running `python -m pytest`.
- Database utilities in `scripts/` (e.g. `list_tables.py`, `add_missing_columns.py`) assume the same `.env` connection string—keep credentials out of version control and copy from `.env.example` when onboarding.
- Static assets are versioned with cache-busting query params (see `<script src="/static/js/file-history-import.js?v=20251031">`); increment the version when shipping meaningful JS changes.

## When extending features
- Follow the existing upload → preview → edit → import lifecycle: build preprocessing helpers, store normalized session data, expose an import endpoint that persists via SQLAlchemy models (`FileIndexing`, `CofO`, `FileNumber`, etc.).
- Coordinate changes across `templates/`, `static/js/`, and `static/css/` so UI controls, data bindings, and styling stay aligned.
- Logically group new QC logic alongside `_run_file_history_qc_validation` and `_detect_file_history_duplicates` so both backend and frontend reuse the same category names.
- Always keep `.env` local, and prefer environment lookups over hard-coded secrets when introducing new integrations.
