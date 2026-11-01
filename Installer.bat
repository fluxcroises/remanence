@echo off
chcp 65001 >nul
rem Installe Remanence dans son propre dossier : Python 3.12 dans .python, bibliothèques dans .venv.
rem Rien n'est installé ailleurs sur la machine, à part l'outil uv.
cd /d "%~dp0"
echo Installation de Remanence...
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% -m pip install --user --quiet uv
if errorlevel 1 (
    echo Python est introuvable. Installez Python depuis https://www.python.org puis relancez ce fichier.
    pause
    exit /b 1
)
for /f "delims=" %%u in ('%PY% -c "import sysconfig,os;print(os.path.join(sysconfig.get_path('scripts','nt_user'),'uv.exe'))"') do set UV=%%u
set UV_PYTHON_INSTALL_DIR=%~dp0.python
"%UV%" python install 3.12 --no-bin
set PY312=
for /d %%d in ("%~dp0.python\cpython-3.12.*") do if exist "%%d\python.exe" set PY312=%%d\python.exe
if not defined PY312 (
    echo Le téléchargement de Python 3.12 a échoué. Vérifiez la connexion Internet puis relancez ce fichier.
    pause
    exit /b 1
)
if exist .venv rmdir /s /q .venv
"%UV%" venv --python "%PY312%" .venv
"%UV%" pip install --python .venv\Scripts\python.exe -r requirements.txt
if errorlevel 1 (
    echo L'installation des bibliothèques a échoué. Vérifiez la connexion Internet puis relancez ce fichier.
    pause
    exit /b 1
)
.venv\Scripts\python.exe -m remanence.moteurs.codec.installation
echo.
echo Remanence est installé. Double-cliquez sur Remanence.bat pour le lancer.
pause
