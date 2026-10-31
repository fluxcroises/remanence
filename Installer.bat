@echo off
chcp 65001 >nul
rem Prépare Remanence : un Python 3.12 privé dans le dossier .venv, sans toucher au reste de Windows.
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
"%UV%" python install 3.12 >nul 2>nul
for /f "delims=" %%p in ('"%UV%" python find 3.12') do set PY312=%%p
"%UV%" venv --python "%PY312%" .venv
"%UV%" pip install --python .venv\Scripts\python.exe -r requirements.txt
if errorlevel 1 (
    echo L'installation des bibliothèques a échoué. Vérifiez la connexion Internet puis relancez ce fichier.
    pause
    exit /b 1
)
echo.
echo Remanence est installé. Double-cliquez sur Remanence.bat pour le lancer.
pause
