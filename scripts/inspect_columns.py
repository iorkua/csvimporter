import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text
from app.models.database import engine

import sys

table_name = sys.argv[1] if len(sys.argv) > 1 else 'file_indexings'

query = "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = :table"

with engine.connect() as conn:
    columns = [row[0] for row in conn.execute(text(query), {'table': table_name})]

print(columns)
