# CSV Importer

A FastAPI-based web application for importing and managing CSV data with multi-table support, quality control features, and file indexing capabilities.

## Features

- **Multi-table CSV Import**: Import data into multiple database tables
- **Quality Control**: Built-in data validation and quality checks
- **File Indexing**: Track and manage imported files
- **Excel Converter**: Convert Excel files to CSV format
- **Property ID Management**: Automated property ID assignment and tracking
- **Web Interface**: Clean, responsive web UI with sidebar navigation

## Prerequisites

- Python 3.8 or higher
- Windows OS (configured for Windows PowerShell)
- SQL Server or compatible database
- Git (optional, for version control)

## Quick Start

### Option 1: Using the Batch File (Recommended)

1. **Clone or download the repository**
   ```powershell
   git clone https://github.com/iorkua/csvimporter.git
   cd csvimporter
   ```

2. **Run the startup script**
   ```powershell
   .\start_csvimporter.bat
   ```

   This script will automatically:
   - Create a virtual environment
   - Install dependencies
   - Start the application

3. **Access the application**
   - Open your browser and go to: `http://localhost:5000`

### Option 2: Manual Setup

1. **Clone the repository**
   ```powershell
   git clone https://github.com/iorkua/csvimporter.git
   cd csvimporter
   ```

2. **Create a virtual environment**
   ```powershell
   python -m venv .venv
   ```

3. **Activate the virtual environment**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

4. **Install dependencies**
   ```powershell
   pip install -r requirements.txt
   ```

5. **Configure database connection**
   - Create a `.env` file in the root directory
   - Add your database connection string:
     ```
     DATABASE_CONNECTION_STRING=your_connection_string_here
     ```

6. **Run the application**
   ```powershell
   python main.py
   ```

7. **Access the application**
   - Open your browser and go to: `http://localhost:5000`

## Project Structure

```
csvimporter/
├── app/
│   ├── models/
│   │   └── database.py          # Database models and connections
│   └── services/
│       └── qc_service.py        # Quality control services
├── static/
│   ├── css/
│   │   └── style.css           # Application styles
│   └── js/
│       ├── main.js             # Main JavaScript functionality
│       ├── excel-converter.js  # Excel conversion features
│       ├── file-indexing.js    # File indexing features
│       └── pra-import.js       # PRA import functionality
├── templates/
│   ├── base.html               # Base template
│   ├── index.html              # Home page
│   ├── excel_converter.html    # Excel converter page
│   ├── file_indexing.html      # File indexing page
│   └── pra_import.html         # PRA import page
├── scripts/
│   ├── add_missing_columns.py  # Database utility scripts
│   ├── inspect_columns.py
│   └── list_tables.py
├── tests/                      # Test files
├── docs/                       # Documentation
├── main.py                     # FastAPI application entry point
├── requirements.txt            # Python dependencies
├── start_csvimporter.bat      # Windows startup script
└── README.md                  # This file
```

## Configuration

### Database Setup

1. **SQL Server Configuration**
   - Ensure SQL Server is running and accessible
   - Create a database for the application
   - Update connection string in `.env` file

2. **Environment Variables**
   Create a `.env` file in the root directory:
   ```
   DATABASE_CONNECTION_STRING=Driver={ODBC Driver 17 for SQL Server};Server=your_server;Database=your_database;Trusted_Connection=yes;
   ```

### Application Settings

The application can be configured through environment variables or by modifying the settings in `main.py`:

- **Port**: Default is 5000
- **Debug Mode**: Set `debug=True` for development
- **Database Connection**: Configure in `.env` file

## Usage

### 1. CSV Import
- Navigate to the PRA Import page
- Upload CSV files for processing
- Monitor import progress and quality control results

### 2. Excel Conversion
- Use the Excel Converter to convert .xlsx files to CSV
- Batch conversion supported

### 3. File Indexing
- Track imported files and their status
- View file processing history
- Manage file metadata

### 4. Quality Control
- Automatic data validation during import
- View quality control reports
- Handle data exceptions and corrections

## Development

### Running in Development Mode

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install development dependencies
pip install -r requirements.txt

# Run with auto-reload
uvicorn main:app --reload --port 5000
```

### Running Tests

```powershell
# Run all tests
python -m pytest tests/

# Run specific test files
python test_property_id_system.py
python test_qc_grouping.py
```

### Database Management

Use the provided scripts for database operations:

```powershell
# List database tables
python scripts\list_tables.py

# Inspect column structures
python scripts\inspect_columns.py

# Add missing columns
python scripts\add_missing_columns.py
```

## Troubleshooting

### Common Issues

1. **Virtual Environment Issues**
   ```powershell
   # If activation fails, try:
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```

2. **Database Connection Issues**
   - Verify SQL Server is running
   - Check connection string in `.env` file
   - Ensure proper ODBC drivers are installed

3. **Port Already in Use**
   - Change port in `main.py` or kill process using port 5000
   ```powershell
   netstat -ano | findstr :5000
   taskkill /PID <PID> /F
   ```

4. **Permission Issues**
   - Run PowerShell as Administrator if needed
   - Check file permissions in project directory

### Logs and Debugging

- Application logs are displayed in the console
- Enable debug mode for detailed error information
- Check browser console for JavaScript errors

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## Dependencies

Main dependencies include:
- **FastAPI**: Web framework
- **SQLAlchemy**: Database ORM
- **Pandas**: Data processing
- **Uvicorn**: ASGI server
- **PyODBC**: Database connectivity

See `requirements.txt` for complete list.

## Support

For issues and questions:
1. Check the troubleshooting section above
2. Review application logs
3. Create an issue in the repository

## License

This project is licensed under the MIT License - see the LICENSE file for details.