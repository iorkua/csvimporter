@echo off
echo Starting KLAES Data Tools Python Application...

:: Change to the application directory
cd /d "C:\Users\Administrator\Documents\csvimporter"

:: Check if virtual environment exists, if not create it
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
)

:: Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

:: Install/update requirements
echo Installing requirements...
pip install -r requirements.txt

:: Start the application
echo Starting FastAPI application on port 5000...
python main.py

pause