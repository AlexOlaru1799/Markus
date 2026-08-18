#Requires -Version 5.1
# Accountant PC beforeShellExecution: never "ask". Allow or deny only.
# Cursor passes JSON on stdin. Install as a user hook with failClosed: true.

$ErrorActionPreference = 'Stop'

function Write-Allow {
    Write-Output '{"permission":"allow"}'
    exit 0
}

function Write-Deny([string]$Message) {
    $json = @{
        permission     = 'deny'
        user_message   = $Message
        agent_message  = $Message
    } | ConvertTo-Json -Compress
    Write-Output $json
    exit 0
}

$raw = [Console]::In.ReadToEnd()
$command = ''
$cwd = ''
try {
    $obj = $raw | ConvertFrom-Json
    $command = [string]$obj.command
    if ($obj.PSObject.Properties.Name -contains 'cwd') {
        $cwd = [string]$obj.cwd
    }
} catch {
    Write-Deny 'Hook could not parse the shell command. Refusing.'
}

if ([string]::IsNullOrWhiteSpace($command)) {
    Write-Deny 'Empty shell command. Refusing.'
}

$project = [string]$env:CURSOR_PROJECT_DIR
if ($cwd -and $project) {
    try {
        $fullCwd = [IO.Path]::GetFullPath($cwd)
        $fullProject = [IO.Path]::GetFullPath($project)
        if (-not $fullCwd.StartsWith($fullProject, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Deny 'Shell must stay inside the Markus checkout. Refusing a command outside the project folder.'
        }
    } catch {
        Write-Deny 'Hook could not resolve the working directory. Refusing.'
    }
}

if ($command -match '(?i)python(\.exe)?\s+scripts[/\\](accountant-checkpoint|quality_gate)\.py') {
    Write-Allow
}

if ($command -match '(?i)\bgit(\.exe)?\b' -and $command -match '(?i)\b(commit|push|checkout|switch|reset|rebase|tag|branch\s+-D|--force|\s-f\b)') {
    Write-Deny 'Use python scripts/accountant-checkpoint.py instead of raw Git publish commands.'
}

$destructive = @(
    '(?i)\b(rm|rmdir|rd)\b.*(/s|/q|-r|-rf|--recursive)',
    '(?i)\bRemove-Item\b.*(-Recurse|-Force)',
    '(?i)\b(del|erase)\b.+\s/s\b',
    '(?i)\bFormat-Volume\b',
    '(?i)\bformat\.com\b',
    '(?i)\bdiskpart\b',
    '(?i)\b(Stop-Computer|Restart-Computer|shutdown)\b',
    '(?i)\b(reg(\.exe)?\s+delete|Remove-ItemProperty)\b',
    '(?i)\bcipher\s+/w',
    '(?i)\b(net(\.exe)?\s+user.+/delete|Remove-LocalUser)\b',
    '(?i)\biex\b|\bInvoke-Expression\b',
    '(?i)\b(irm|Invoke-RestMethod|Invoke-WebRequest).+\|\s*(iex|Invoke-Expression)',
    '(?i)\bClear-Disk\b',
    '(?i)\bReset-ComputerMachinePassword\b',
    '(?i)\breg(\.exe)?\s+(add|delete|import|restore|save|load)\b',
    '(?i)\b(New|Set|Remove)-ItemProperty\b',
    '(?i)\bSet-ItemProperty\b',
    '(?i)\bnetsh\b',
    '(?i)\bbcdedit\b',
    '(?i)\bpowercfg\b',
    '(?i)\bSet-ExecutionPolicy\b',
    '(?i)\b(Enable|Disable)-WindowsOptionalFeature\b',
    '(?i)\b(Set|Stop|Start|Restart)-Service\b',
    '(?i)\bsc(\.exe)?\s+(config|delete|stop|start|create)\b',
    '(?i)\bschtasks\b',
    '(?i)\b(New|Set)-NetFirewall(Rule|Profile)\b',
    '(?i)\bSet-MpPreference\b',
    '(?i)\bcontrol\.exe\b',
    '(?i)ms-settings:',
    '(?i)\bSystemProperties\b',
    '(?i)\b(Add|Remove|Enable|Disable)-LocalUser\b',
    '(?i)\bnet(\.exe)?\s+(user|localgroup|share|accounts)\b'
)

foreach ($pattern in $destructive) {
    if ($command -match $pattern) {
        Write-Deny 'That command can damage this PC. The agent must use another approach inside the Markus folder.'
    }
}

Write-Allow
