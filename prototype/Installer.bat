@echo off
chcp 65001 >nul
title Installation de Bavure
cd /d "%~dp0"
echo.
echo   Installation de Bavure (a faire une seule fois)
echo   ---------------------------------------------
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo   Python est introuvable.
  echo   Installe-le depuis https://www.python.org/downloads/  ^(coche "Add python.exe to PATH"^),
  echo   puis relance ce fichier.
  pause
  exit /b 1
)
echo   1/2  Creation de l'environnement Python...
py -3 -m venv .venv || goto erreur
echo   2/2  Telechargement des bibliotheques (FFmpeg compris), patience...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto erreur
".venv\Scripts\python.exe" -c "import tkinter, cv2, numpy, PIL, imageio_ffmpeg; imageio_ffmpeg.get_ffmpeg_exe()" || goto erreur
echo.
echo   Installation terminee. Double-clique sur "Lancer Bavure.bat".
pause
exit /b 0
:erreur
echo.
echo   Une erreur est survenue. Copie le message ci-dessus pour le diagnostic.
pause
exit /b 1
