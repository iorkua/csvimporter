# KLAES Data Tools Service Management Script
# Run as Administrator for service operations

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("start", "stop", "restart", "status", "install", "uninstall")]
    [string]$Action = "start"
)

$AppPath = "C:\Users\Administrator\Documents\csvimporter"
$AppName = "KLAESDataTools"
$ServiceName = "CSVImporterService"

function Start-CSVImporter {
    Write-Host "Starting KLAES Data Tools Application..." -ForegroundColor Green
    
    # Change to app directory
    Set-Location $AppPath
    
    # Check if virtual environment exists
    if (!(Test-Path "venv\Scripts\activate.ps1")) {
        Write-Host "Creating virtual environment..." -ForegroundColor Yellow
        python -m venv venv
    }
    
    # Activate virtual environment and start app
    & "venv\Scripts\Activate.ps1"
    
    Write-Host "Installing/updating requirements..." -ForegroundColor Yellow
    pip install -r requirements.txt
    
    Write-Host "Starting FastAPI application on port 5000..." -ForegroundColor Green
    python main.py
}

function Stop-CSVImporter {
    Write-Host "Stopping KLAES Data Tools processes..." -ForegroundColor Yellow
    Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {$_.Path -like "*csvimporter*"} | Stop-Process -Force
    Write-Host "KLAES Data Tools stopped." -ForegroundColor Green
}

function Get-CSVImporterStatus {
    $pythonProcesses = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {$_.Path -like "*csvimporter*"}
    if ($pythonProcesses) {
        Write-Host "KLAES Data Tools is running (PID: $($pythonProcesses.Id -join ', '))" -ForegroundColor Green
        return $true
    } else {
        Write-Host "KLAES Data Tools is not running" -ForegroundColor Red
        return $false
    }
}

function Install-CSVImporterService {
    Write-Host "Installing KLAES Data Tools as Windows Service..." -ForegroundColor Yellow
    
    # Download NSSM if not exists
    $nssmPath = "$AppPath\nssm.exe"
    if (!(Test-Path $nssmPath)) {
        Write-Host "Downloading NSSM (Non-Sucking Service Manager)..." -ForegroundColor Yellow
        # You would need to download NSSM manually and place it in the app directory
        Write-Host "Please download NSSM from https://nssm.cc/download and place nssm.exe in $AppPath" -ForegroundColor Red
        return
    }
    
    $pythonExe = "$AppPath\venv\Scripts\python.exe"
    $mainPy = "$AppPath\main.py"
    
    & $nssmPath install $ServiceName $pythonExe $mainPy
    & $nssmPath set $ServiceName AppDirectory $AppPath
    & $nssmPath set $ServiceName DisplayName "KLAES Data Tools Service"
    & $nssmPath set $ServiceName Description "FastAPI KLAES Data Tools Application"
    & $nssmPath set $ServiceName Start SERVICE_AUTO_START
    
    Write-Host "Service installed successfully. Use 'sc start $ServiceName' to start it." -ForegroundColor Green
}

function Uninstall-CSVImporterService {
    Write-Host "Uninstalling KLAES Data Tools Service..." -ForegroundColor Yellow
    $nssmPath = "$AppPath\nssm.exe"
    if (Test-Path $nssmPath) {
        & $nssmPath stop $ServiceName
        & $nssmPath remove $ServiceName confirm
        Write-Host "Service uninstalled successfully." -ForegroundColor Green
    } else {
        Write-Host "NSSM not found. Cannot uninstall service automatically." -ForegroundColor Red
    }
}

# Main script logic
switch ($Action.ToLower()) {
    "start" { Start-CSVImporter }
    "stop" { Stop-CSVImporter }
    "restart" { 
        Stop-CSVImporter
        Start-Sleep -Seconds 2
        Start-CSVImporter
    }
    "status" { Get-CSVImporterStatus }
    "install" { Install-CSVImporterService }
    "uninstall" { Uninstall-CSVImporterService }
    default { 
        Write-Host "Usage: .\manage_csvimporter.ps1 -Action [start|stop|restart|status|install|uninstall]" -ForegroundColor Yellow
    }
}