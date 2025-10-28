from sqlalchemy import text
from app.models.database import engine

statements = [
    "IF COL_LENGTH('file_indexings', 'cofo_date') IS NULL BEGIN ALTER TABLE file_indexings ADD cofo_date NVARCHAR(100) NULL END",
    "IF COL_LENGTH('file_indexings', 'page_no') IS NULL BEGIN ALTER TABLE file_indexings ADD page_no NVARCHAR(100) NULL END",
    "IF COL_LENGTH('file_indexings', 'vol_no') IS NULL BEGIN ALTER TABLE file_indexings ADD vol_no NVARCHAR(100) NULL END",
    "IF COL_LENGTH('file_indexings', 'deeds_time') IS NULL BEGIN ALTER TABLE file_indexings ADD deeds_time NVARCHAR(100) NULL END",
    "IF COL_LENGTH('file_indexings', 'deeds_date') IS NULL BEGIN ALTER TABLE file_indexings ADD deeds_date NVARCHAR(100) NULL END",
]

with engine.begin() as connection:
    for stmt in statements:
        connection.execute(text(stmt))

print("file_indexings columns synchronized")
