@echo off
setlocal
rem ============================================================
rem Pielach STAC catalog viewer. Double-click to open.
rem Layout: this repo folder lives inside the data root; the
rem server must serve the data root so /catalog and the campaign
rem asset files are reachable. Browser is served from this repo.
rem Close the server window to stop. Needs python on PATH.
rem Set DATA_ROOT as environment variable to override.
rem ============================================================
set "PORT=8111"
if not defined DATA_ROOT for %%I in ("%~dp0..") do set "DATA_ROOT=%%~fI"
rem strip trailing backslash; "dir\" breaks quoting on the python line
if "%DATA_ROOT:~-1%"=="\" set "DATA_ROOT=%DATA_ROOT:~0,-1%"
rem repo folder name, needed for the browser URL below
for %%I in ("%~dp0.") do set "REPONAME=%%~nxI"
start "Pielach catalog server" python -m http.server %PORT% --directory "%DATA_ROOT%"
start "" http://localhost:%PORT%/%REPONAME%/browser/
