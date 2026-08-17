param()

$ErrorActionPreference = 'Stop'
$project = $env:CURSOR_PROJECT_DIR
if (-not $project) {
    Write-Output '{}'
    exit 0
}

$context = Join-Path $project '.cursor\accountant-context.md'
if (-not (Test-Path -LiteralPath $context)) {
    Write-Output '{}'
    exit 0
}

$text = Get-Content -LiteralPath $context -Raw
$payload = @{ additional_context = [string]$text } | ConvertTo-Json -Compress
Write-Output $payload
exit 0
