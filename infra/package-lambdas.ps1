param(
    [string]$Python = "python",
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$Backend = Join-Path $ProjectRoot "backend"
$Worker = Join-Path $ProjectRoot "worker"
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("studycloud-lambda-" + [guid]::NewGuid().ToString("N"))
$ApiStage = Join-Path $TempRoot "api"
$WorkerStage = Join-Path $TempRoot "worker"
$DependenciesStage = Join-Path $TempRoot "dependencies"
$ApiZip = Join-Path $Backend "dist\api.zip"
$WorkerZip = Join-Path $Worker "dist\worker.zip"

try {
    New-Item -ItemType Directory -Force -Path $ApiStage, $WorkerStage, $DependenciesStage | Out-Null

    & $Python -m pip install --disable-pip-version-check --only-binary=:all: --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --abi cp312 --target $DependenciesStage -r (Join-Path $Backend "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Installing Linux Lambda dependencies failed." }
    Copy-Item (Join-Path $DependenciesStage "*") -Destination $ApiStage -Recurse -Force
    Copy-Item (Join-Path $DependenciesStage "*") -Destination $WorkerStage -Recurse -Force

    New-Item -ItemType Directory -Force -Path (Join-Path $ApiStage "backend"), (Join-Path $WorkerStage "backend"), (Join-Path $WorkerStage "worker") | Out-Null
    foreach ($item in (Get-ChildItem (Join-Path $ProjectRoot "backend") -Force | Where-Object Name -ne "dist")) {
        Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $ApiStage "backend") -Recurse
    }
    Copy-Item (Join-Path $ProjectRoot "frontend") (Join-Path $ApiStage "frontend") -Recurse
    Copy-Item (Join-Path $ProjectRoot "frontend") (Join-Path $WorkerStage "frontend") -Recurse
    foreach ($item in (Get-ChildItem (Join-Path $ProjectRoot "backend") -Force | Where-Object Name -ne "dist")) {
        Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $WorkerStage "backend") -Recurse
    }
    foreach ($item in (Get-ChildItem (Join-Path $ProjectRoot "worker") -Force | Where-Object Name -ne "dist")) {
        Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $WorkerStage "worker") -Recurse
    }

    foreach ($stage in @($ApiStage, $WorkerStage)) {
        Remove-Item (Join-Path $stage "backend\tests") -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem $stage -Directory -Filter "__pycache__" -Recurse | Remove-Item -Recurse -Force
        Get-ChildItem $stage -File -Include "*.pyc", "*.pyo", "*.db", "*.key", ".env" -Recurse | Remove-Item -Force
    }

    New-Item -ItemType Directory -Force -Path (Split-Path $ApiZip), (Split-Path $WorkerZip) | Out-Null
    Remove-Item $ApiZip, $WorkerZip -Force -ErrorAction SilentlyContinue
    Compress-Archive -Path (Join-Path $ApiStage "*") -DestinationPath $ApiZip -CompressionLevel Optimal
    Compress-Archive -Path (Join-Path $WorkerStage "*") -DestinationPath $WorkerZip -CompressionLevel Optimal

    Write-Output "Created API Lambda package: $ApiZip"
    Write-Output "Created worker Lambda package: $WorkerZip"
    Write-Output "The packages contain no local database or environment secrets."
}
finally {
    if (Test-Path $TempRoot) { Remove-Item $TempRoot -Recurse -Force }
}
