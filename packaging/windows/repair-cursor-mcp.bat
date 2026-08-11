@echo off
setlocal
set APP=%~dp0markus-mcp.exe
echo Repairing Markus setup (downloads the browser if missing)...
"%APP%" --setup
echo.
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0prompt-credentials.ps1" -Exe "%APP%"
echo.
echo Markus is registered in Cursor. Restart Cursor and ask the agent: health_check
pause
