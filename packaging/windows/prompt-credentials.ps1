# Collect SAGA credentials and hand them to markus-mcp.exe on stdin.
param([Parameter(Mandatory = $true)][string]$Exe)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Markus setup'
$form.Size = New-Object System.Drawing.Size(420, 220)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true

function New-Label($text, $y) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $text
    $label.Location = New-Object System.Drawing.Point(15, $y)
    $label.Size = New-Object System.Drawing.Size(380, 20)
    return $label
}

function New-Box($y) {
    $box = New-Object System.Windows.Forms.TextBox
    $box.Location = New-Object System.Drawing.Point(15, $y)
    $box.Size = New-Object System.Drawing.Size(370, 22)
    return $box
}

$form.Controls.Add((New-Label 'SAGA email / username:' 15))
$userBox = New-Box 38
$form.Controls.Add($userBox)

$form.Controls.Add((New-Label 'SAGA password:' 70))
$passBox = New-Box 93
$passBox.UseSystemPasswordChar = $true
$form.Controls.Add($passBox)

$ok = New-Object System.Windows.Forms.Button
$ok.Text = 'Save'
$ok.Location = New-Object System.Drawing.Point(215, 135)
$ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.Controls.Add($ok)
$form.AcceptButton = $ok

$skip = New-Object System.Windows.Forms.Button
$skip.Text = 'Skip'
$skip.Location = New-Object System.Drawing.Point(305, 135)
$skip.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$form.Controls.Add($skip)
$form.CancelButton = $skip

$form.Add_Shown({ $userBox.Focus() })
$result = $form.ShowDialog()

if ($result -ne [System.Windows.Forms.DialogResult]::OK -or
    [string]::IsNullOrWhiteSpace($userBox.Text) -or
    [string]::IsNullOrWhiteSpace($passBox.Text)) {
    Write-Output "Skipped credentials. Add them later in $env:USERPROFILE\.markus\private.data"
    exit 0
}

# Piped on stdin so the password never appears in the process list.
$payload = "saga_username=$($userBox.Text)`nsaga_password=$($passBox.Text)"
$payload | & $Exe --set-credentials
