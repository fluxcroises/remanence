@echo off
chcp 65001 >nul
rem Construit Remanence.exe dans dist\Remanence, puis l'installateur si Inno Setup 6 est là.
rem Il faut avoir lancé Installer.bat une fois avant.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Lancez d'abord Installer.bat, puis relancez ce fichier.
    pause
    exit /b 1
)
echo Préparation de la construction...
".venv\Scripts\python.exe" -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul && (set PY=py) || (set PY=python)
    for /f "delims=" %%u in ('%PY% -c "import sysconfig,os;print(os.path.join(sysconfig.get_path('scripts','nt_user'),'uv.exe'))"') do set UV=%%u
    "%UV%" pip install --python .venv\Scripts\python.exe -r requirements-construction.txt
)
".venv\Scripts\python.exe" scripts\icone.py
echo Construction de Remanence.exe (quelques minutes)...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --log-level WARN Remanence.spec
if errorlevel 1 (
    echo La construction a échoué : le détail est au-dessus.
    pause
    exit /b 1
)
echo.
echo Remanence est construit : dist\Remanence\Remanence.exe

rem Installateur : avec Inno Setup 6, s'il est installé (pour l'utilisateur ou pour tous).
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (
    echo Inno Setup 6 absent : pas d'installateur.
    pause
    exit /b 0
)
for /f "usebackq delims=" %%v in (`.venv\Scripts\python.exe -c "import remanence;print(remanence.__version__)"`) do set VERSION=%%v
".venv\Scripts\python.exe" scripts\images_installateur.py
echo Construction de l'installateur (quelques minutes)...
"%ISCC%" /Q /DVersion=%VERSION% Remanence.iss
if errorlevel 1 (
    echo L'installateur n'a pas pu être construit : le détail est au-dessus.
    pause
    exit /b 1
)
echo Installateur : dist\Remanence-%VERSION%-installation.exe
pause
