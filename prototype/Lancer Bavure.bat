@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Lance d'abord Installer.bat.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" lancer.py
