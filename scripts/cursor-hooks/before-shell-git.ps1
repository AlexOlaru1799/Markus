#Requires -Version 5.1
# Example beforeShellExecution policy for the accountant PC (install as a user hook).
# Cursor passes JSON on stdin. This script is a reference; wire it in hooks.json.

$ErrorActionPreference = 'Stop'
$raw = [Console]::In.ReadToEnd()
$command = ''
try {
    $obj = $raw | ConvertFrom-Json
    $command = [string]$obj.command
} catch {
    Write-Output '{"permission":"allow"}'
    exit 0
}

if ($command -match '(?i)python(\.exe)?\s+scripts[/\\](accountant-checkpoint|quality_gate)\.py') {
    Write-Output '{"permission":"allow"}'
    exit 0
}

if ($command -match '(?i)\bgit(\.exe)?\b' -and $command -match '(?i)\b(commit|push|checkout|switch|reset|rebase|tag|branch\s+-D|--force|\s-f\b)') {
    $msg = 'Use python scripts/accountant-checkpoint.py instead of raw Git publish commands.'
    $json = @{
        permission = 'deny'
        user_message = $msg
        agent_message = $msg
    } | ConvertTo-Json -Compress
    Write-Output $json
    exit 0
}

Write-Output '{"permission":"allow"}'
exit 0
