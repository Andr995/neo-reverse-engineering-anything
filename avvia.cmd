@echo off
setlocal
cd /d "%~dp0"
if exist "rea-desktop\dist\REA-Desktop\REA-Desktop.exe" (
  "rea-desktop\dist\REA-Desktop\REA-Desktop.exe" %*
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "rea-desktop\app.py" %*
) else (
  call "rea-desktop\avvia.cmd" %*
)
