@echo off
chcp 65001 >nul
rem Lance Remanence. Un projet .remanence glissé sur ce fichier s'ouvre directement.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto installer
".venv\Scripts\python.exe" -c "import remanence, PySide6, av" >nul 2>nul
if errorlevel 1 goto installer
start "" ".venv\Scripts\pythonw.exe" -m remanence %*
exit /b 0

:installer
echo Remanence n'est pas installé correctement sur cette machine
echo (Python ou une bibliothèque est introuvable).
echo.
echo Double-cliquez sur Installer.bat, attendez la fin, puis relancez ce fichier.
pause
exit /b 1
