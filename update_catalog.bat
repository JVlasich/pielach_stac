@echo off
setlocal
cd /d "%~dp0"

rem ============================================================
rem Pielach STAC catalog update. Double-click to run.
rem Needs only an OPALS installation; python deps ship in libs\.
rem Edit these paths if your layout differs, or set them as
rem environment variables before running.
rem ============================================================
if not defined OPALS_ROOT set "OPALS_ROOT=C:\opals_nightly_2.6.0"
if not defined REPO       set "REPO=%~dp0"
if not defined DATA_ROOT  set "DATA_ROOT=%~dp0"

rem strip trailing backslash; "dir\" breaks quoting on the python line
if "%REPO:~-1%"=="\"      set "REPO=%REPO:~0,-1%"
if "%DATA_ROOT:~-1%"=="\" set "DATA_ROOT=%DATA_ROOT:~0,-1%"

if not exist "%OPALS_ROOT%\opalsShell.bat" (
    echo OPALS not found at %OPALS_ROOT%.
    echo Install OPALS or set OPALS_ROOT to its install folder.
    pause
    exit /b 1
)

rem harvest the opalsShell environment (PATH, PYTHONPATH, GDAL_DATA, PROJ_LIB)
rem "rem" argument skips the interactive shell -> returns control here
call "%OPALS_ROOT%\opalsShell.bat" rem

rem put repo code + vendored deps on PYTHONPATH
set "PYTHONPATH=%REPO%;%REPO%\libs;%PYTHONPATH%"

rem optional config.yaml in the data root
set "CFG_ARG="
if exist "%DATA_ROOT%\config.yaml" set CFG_ARG=--config "%DATA_ROOT%\config.yaml"

echo Updating catalog for %DATA_ROOT% ...
python -m stac.core.cli "%DATA_ROOT%" %CFG_ARG% 2>&1
if errorlevel 1 (
    echo BUILD FAILED
    pause
    exit /b 1
)
echo Catalog updated OK.
pause
