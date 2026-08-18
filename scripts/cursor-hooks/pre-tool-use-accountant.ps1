#Requires -Version 5.1
# Accountant PC preToolUse: never "ask". Block writes/deletes outside the Markus checkout.
# Cursor passes JSON on stdin. Install as a user hook with failClosed: true.

$ErrorActionPreference = 'Stop'

function Write-Allow {
    Write-Output '{"permission":"allow"}'
    exit 0
}

function Write-Deny([string]$Message) {
    $json = @{
        permission    = 'deny'
        user_message  = $Message
        agent_message = $Message
    } | ConvertTo-Json -Compress
    Write-Output $json
    exit 0
}

function Get-ToolPath($inputObj) {
    if ($null -eq $inputObj) { return '' }
    foreach ($name in @('path', 'file_path', 'target_file', 'target_notebook')) {
        if ($inputObj.PSObject.Properties.Name -contains $name) {
            $value = [string]$inputObj.$name
            if (-not [string]::IsNullOrWhiteSpace($value)) {
                return $value
            }
        }
    }
    return ''
}

$raw = [Console]::In.ReadToEnd()
try {
    $obj = $raw | ConvertFrom-Json
} catch {
    Write-Deny 'Hook could not parse the tool call. Refusing.'
}

$tool = ''
foreach ($name in @('tool_name', 'toolName', 'tool')) {
    if ($obj.PSObject.Properties.Name -contains $name) {
        $tool = [string]$obj.$name
        if ($tool) { break }
    }
}

$toolInput = $null
foreach ($name in @('tool_input', 'toolInput', 'arguments', 'params')) {
    if ($obj.PSObject.Properties.Name -contains $name) {
        $toolInput = $obj.$name
        if ($null -ne $toolInput) { break }
    }
}

$mutating = $tool -match '(?i)(Write|Delete|StrReplace|EditNotebook|ApplyPatch)'
if (-not $mutating) {
    Write-Allow
}

$project = [string]$env:CURSOR_PROJECT_DIR
$path = Get-ToolPath $toolInput
if ($path -and $project) {
    try {
        $fullPath = [IO.Path]::GetFullPath($path)
        $fullProject = [IO.Path]::GetFullPath($project)
        if (-not $fullPath.StartsWith($fullProject, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Deny 'That path is outside the Markus repository. Refusing to change it.'
        }
    } catch {
        Write-Deny 'Hook could not resolve the file path. Refusing.'
    }
} elseif ($path -and -not $project -and $tool -match '(?i)(Write|Delete|StrReplace|EditNotebook)') {
    Write-Deny 'No project folder is set. Refusing to change files on this PC.'
}

Write-Allow
