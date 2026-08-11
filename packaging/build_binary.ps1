# Build a closed markus-mcp.exe with PyInstaller (Windows).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python -m pip install -e ".[packaging]"
python -m playwright install chromium
python -m PyInstaller packaging/markus-mcp.spec --noconfirm --clean --distpath packaging/dist --workpath packaging/build

$Bin = Join-Path $Root "packaging\dist\markus-mcp.exe"
if (-not (Test-Path $Bin)) {
  Write-Error "Binary not found at $Bin"
}
Write-Host "Built: $Bin"
Write-Host "Next: packaging\windows\build_installer.ps1"
