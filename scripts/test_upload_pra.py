import json
import requests
from pathlib import Path

BASE_URL = "http://127.0.0.1:5000"
DATA_FILE = Path(__file__).resolve().parents[1] / "docs" / "test_pra_Book1.csv"

if not DATA_FILE.exists():
    raise SystemExit(f"CSV file not found: {DATA_FILE}")

with DATA_FILE.open("rb") as fh:
    response = requests.post(
        f"{BASE_URL}/api/upload-pra",
        data={"test_control": "TEST"},
        files={"file": fh}
    )

print("Status:", response.status_code)
try:
    payload = response.json()
except Exception:
    print("Response text:\n", response.text)
else:
    print(json.dumps({
        "session_id": payload.get("session_id"),
        "total_records": payload.get("total_records"),
        "duplicate_count": payload.get("duplicate_count"),
        "validation_issues": payload.get("validation_issues"),
        "ready_records": payload.get("ready_records"),
        "property_sample": payload.get("property_records", [])[:1],
        "file_number_sample": payload.get("file_numbers", [])[:1]
    }, indent=2))
