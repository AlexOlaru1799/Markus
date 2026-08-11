# Build MarkusSetup-*-win64.exe (requires Inno Setup 6 on the PATH or ISCC set).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root

& "$PSScriptRoot\..\build_binary.ps1"

$Iscc = $env:ISCC
if (-not $Iscc) {
  $candidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
  )
  foreach ($c in $candidates) {
    if (Test-Path $c) { $Iscc = $c; break }
  }
}
if (-not $Iscc) {
  Write-Error "Inno Setup 6 (ISCC.exe) not found. Install it or set ISCC=..."
}

& $Iscc "$PSScriptRoot\markus.iss"
Write-Host "Installer written under packaging\dist\"
