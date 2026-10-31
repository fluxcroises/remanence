@echo off
chcp 65001 >nul
rem Lance Remanence. Un projet .remanence glissé sur ce fichier s'ouvre directement.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Remanence n'est pas encore installé sur cette machine.
    echo Lancez d'abord Installer.bat, puis relancez ce fichier.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m remanence %*
