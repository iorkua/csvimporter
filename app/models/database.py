import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, Index, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

load_dotenv()

Base = declarative_base()

class FileIndexing(Base):
    __tablename__ = 'file_indexings'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    registry = Column(String(255))
    batch_no = Column(Integer)  # Changed to Integer to match SQL Server schema
    file_number = Column(String(100), unique=True, nullable=False)
    file_title = Column(String(500))
    land_use_type = Column(String(100))
    plot_number = Column(String(100))
    lpkn_no = Column(String(100))
    tp_no = Column(String(100))
    district = Column(String(100))
    lga = Column(String(100))
    location = Column(String(500))
    shelf_location = Column(String(100))
    serial_no = Column(String(100))
    batch_id = Column(Integer)
    tracking_id = Column(String(50), unique=True)
    status = Column(String(50), default='Indexed')
    created_by = Column(String(255), nullable=True)
    updated_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
    prop_id = Column('prop_id', String(100))
    is_updated = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    # Fields from actual database schema
    sys_batch_no = Column(String(255))  # System batch number
    group = Column(String(255))  # Group field
    registry_batch_no = Column(String(50))
    test_control = Column(String(20), default='PRODUCTION')


class CofO(Base):
    __tablename__ = 'CofO_staging'

    id = Column(Integer, primary_key=True, autoincrement=True)
    mls_fno = Column('mlsFNo', String(100))
    title_type = Column('title_type', String(100))
    transaction_type = Column('transaction_type', String(100))
    instrument_type = Column('instrument_type', String(150))
    transaction_date = Column('transaction_date', String(100))
    transaction_time = Column('transaction_time', String(100))
    serial_no = Column('serialNo', String(100))
    page_no = Column('pageNo', String(100))
    volume_no = Column('volumeNo', String(100))
    reg_no = Column('regNo', String(255))
    property_description = Column(String(500))
    location = Column(String(500))
    plot_no = Column('plot_no', String(100))
    lgsa_or_city = Column('lgsaOrCity', String(255))
    land_use = Column('land_use', String(100))
    cofo_type = Column('cofo_type', String(100))
    grantor = Column('Grantor', String(255))
    grantee = Column('Grantee', String(255))
    cofo_date = Column('cofo_date', String(100))
    prop_id = Column('prop_id', String(100))
    test_control = Column('test_control', String(20), default='PRODUCTION')

class RackShelfLabel(Base):
    __tablename__ = 'Rack_Shelf_Labels'
    
    id = Column(Integer, primary_key=True)
    rack = Column(String(10))  # matches existing 'rack' column
    shelf = Column(String(10))  # matches existing 'shelf' column  
    full_label = Column(String(50))
    is_used = Column(String(50))  # matches existing nvarchar(50)
    reserved_by = Column(Integer)
    reserved_at = Column(DateTime)

class FileIndexingBatch(Base):
    __tablename__ = 'fileindexing_batch'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_number = Column(Integer)
    start_shelf_id = Column(Integer)
    end_shelf_id = Column(Integer)  
    shelf_count = Column(Integer)
    used_shelves = Column(Integer)
    is_full = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    shelf_label_id = Column(Integer)
    full_label = Column(String(255))


class FileNumber(Base):
    __tablename__ = 'fileNumber'

    id = Column(Integer, primary_key=True, autoincrement=True)
    mlsf_no = Column('mlsfNo', String(100), unique=True)
    file_name = Column('FileName', String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
    location = Column(String(500))
    created_by = Column(String(255))
    updated_by = Column(String(255), nullable=True)
    type = Column(String(100))
    source = Column('SOURCE', String(100))
    plot_no = Column('plot_no', String(100))
    tp_no = Column('tp_no', String(100))
    tracking_id = Column('tracking_id', String(50))
    test_control = Column('test_control', String(20), default='PRODUCTION')


class Grouping(Base):
    __tablename__ = 'grouping'

    id = Column(Integer, primary_key=True, autoincrement=True)
    awaiting_fileno = Column(String(150), unique=True)
    indexing_mls_fileno = Column(String(150))
    indexing_mapping = Column(Integer, default=0)
    mdc_batch_no = Column(String(50))
    shelf_rack = Column(String(100))
    created_by = Column(String(255))
    indexed_by = Column(String(255))
    date_index = Column(DateTime)
    number = Column(String(100))
    registry = Column(String(100))
    group = Column(String(100))  # Group field
    sys_batch_no = Column(String(50))  # System batch number
    registry_batch_no = Column(String(50))
    test_control = Column('test_control', String(20), default='PRODUCTION')
    tracking_id = Column(String(50))


class EntityStaging(Base):
    __tablename__ = 'entities_staging'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(50), nullable=False)  # 'Individual', 'Corporate', 'Multiple'
    entity_name = Column(String(255), nullable=False, index=True)
    passport_photo = Column(String(500), nullable=True)  # URL only, can be NULL
    company_logo = Column(String(500), nullable=True)    # URL only, can be NULL
    file_number = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
    test_control = Column(String(20), default='PRODUCTION')
    
    __table_args__ = (
        Index('idx_entity_name_type', 'entity_name', 'entity_type'),
        Index('idx_entity_test_control', 'test_control'),
    )


class CustomerStaging(Base):
    __tablename__ = 'customers_staging'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_type = Column(String(50), nullable=False)  # 'Individual', 'Corporate', 'Multiple'
    status = Column(String(50), default='pending', nullable=False)  # pending, validated, migrated, failed
    customer_name = Column(String(255), nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(20), nullable=True)
    property_address = Column(String(500), nullable=True)
    residential_address = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    customer_code = Column(String(50), nullable=True, unique=True, index=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)  # Soft delete
    entity_id = Column(Integer, ForeignKey('entities_staging.id'), nullable=True, index=True)
    test_control = Column(String(20), default='PRODUCTION')
    file_number = Column(String(100), nullable=True, index=True)
    account_no = Column(String(100), nullable=True)
    reason_retired = Column(String(100), nullable=True)  # Revoked, Assignment, Power of Attorney, Surrender, Mortgage
    
    __table_args__ = (
        Index('idx_customer_name_type', 'customer_name', 'customer_type'),
        Index('idx_customer_test_control', 'test_control'),
        Index('idx_status', 'status'),
    )


def get_database_url():
    # Check if SQL Server configuration is available
    host = os.getenv('DB_SQLSRV_HOST')
    
    if host:  # Use SQL Server if host is configured
        port = os.getenv('DB_SQLSRV_PORT')
        database = os.getenv('DB_SQLSRV_DATABASE')
        username = os.getenv('DB_SQLSRV_USERNAME')
        password = os.getenv('DB_SQLSRV_PASSWORD')
        
        try:
            import pyodbc
            print(f"Connecting to SQL Server: {host}\\{database}")
            return f"mssql+pyodbc://{username}:{password}@{host}:{port}/{database}?driver=ODBC+Driver+17+for+SQL+Server"
        except ImportError:
            print("Warning: pyodbc not available, falling back to SQLite")
            return "sqlite:///./file_indexing.db"
    
    # Fall back to SQLite for demo/development
    print("No SQL Server configuration found, using SQLite")
    return "sqlite:///./file_indexing.db"

# Create engine and session
engine = create_engine(get_database_url(), echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_db_connection():
    """Get a direct database connection"""
    return SessionLocal()