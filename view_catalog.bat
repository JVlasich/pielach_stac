@echo off
setlocal
rem ============================================================
rem Pielach STAC catalog viewer. Double-click to open.
rem Serves this folder locally and opens STAC Browser.
rem Close the server window to stop. Needs python on PATH.
rem ============================================================
set "PORT=8111"
start "Pielach catalog server" python -m http.server %PORT% --directory "%~dp0"
start "" http://localhost:%PORT%/browser/
