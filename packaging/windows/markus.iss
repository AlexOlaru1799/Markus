; Inno Setup 6 — Markus MCP Windows installer
#define MyAppName "Markus MCP"
#define MyAppVersion "0.7.0"
#define MyAppExeName "markus-mcp.exe"

[Setup]
AppId={{A7C3E2F1-9B4D-4E6A-8C1F-2D3E4F5A6B7C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Markus
DefaultGroupName=Markus
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=MarkusSetup-{#MyAppVersion}-win64
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "repair-cursor-mcp.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "prompt-credentials.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Repair Cursor MCP"; Filename: "{app}\repair-cursor-mcp.bat"
Name: "{group}\Uninstall Markus"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--setup"; StatusMsg: "Setting up Markus and downloading its browser (about 150 MB)…"; Flags: runhidden waituntilterminated
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File ""{app}\prompt-credentials.ps1"" -Exe ""{app}\{#MyAppExeName}"""; StatusMsg: "Asking for SAGA credentials and optional SmartBill token…"; Flags: waituntilterminated skipifsilent
Filename: "{app}\repair-cursor-mcp.bat"; Description: "Open repair / finish notes"; Flags: postinstall skipifsilent unchecked
