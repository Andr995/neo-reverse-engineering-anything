@echo off
setlocal
cd /d "%~dp0"
if exist "dist\REA-Desktop\REA-Desktop.exe" (
  start "" "dist\REA-Desktop\REA-Desktop.exe" %*
) else if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" app.py %*
) else (
  py app.py %*
)
