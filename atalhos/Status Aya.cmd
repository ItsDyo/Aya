@echo off
set "PROJECT_ROOT=%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\status_v1.ps1"
pause
