@echo off
setlocal
rem ============================================================
rem Pielach STAC catalog viewer. Double-click to open.
rem serve_catalog.py maps /browser to this repo and the
rem rest to the data root (default: parent of this repo).
rem Close the server window to stop. Needs python on PATH.
rem Set DATA_ROOT as environment variable to override.
rem ============================================================

set "PORT=8111"

if not defined DATA_ROOT for %%I in ("%~dp0..") do set "DATA_ROOT=%%~fI"

rem strip trailing backslash; "dir\" breaks quoting on the python line
if "%DATA_ROOT:~-1%"=="\" set "DATA_ROOT=%DATA_ROOT:~0,-1%"

start "Pielach catalog server" python "%~dp0scripts\serve_catalog.py" "%DATA_ROOT%" "%~dp0." %PORT%
start "" http://localhost:%PORT%/browser/
