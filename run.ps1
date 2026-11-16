$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..."
    py -m venv .venv
}

Write-Host "Installing dependencies..."
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

$uvicornArgs = @("-m", "uvicorn", "backend.app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000")
if (Test-Path -LiteralPath ".env") {
    $uvicornArgs += @("--env-file", ".env")
}

Write-Host "StudyCloud AI: http://127.0.0.1:8000"
& .\.venv\Scripts\python.exe @uvicornArgs

