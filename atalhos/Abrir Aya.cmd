@echo off
set "PROJECT_ROOT=%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\open_v1.ps1"
pause
