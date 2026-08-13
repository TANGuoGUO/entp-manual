@echo off
setlocal
cd /d "%~dp0"

set "APP_DIR=%CD%"
set "FLET_PY=%APP_DIR%\.venv\Scripts\python.exe"
set "FLET_PYW=%APP_DIR%\.venv\Scripts\pythonw.exe"

if not exist "%APP_DIR%\flet_app.py" goto missing_app
if not exist "%FLET_PY%" goto missing_python
if "%~1"=="" goto run_windowless
goto run_console

:run_windowless
start "" "%FLET_PYW%" "%APP_DIR%\launcher_flet.pyw"
exit /b 0

:run_console
echo Starting ENTP Manual 2.0...
"%FLET_PY%" "%APP_DIR%\flet_app.py" %*
set "APP_EXIT=%ERRORLEVEL%"
goto finished

:missing_app
echo [ERROR] flet_app.py was not found in:
echo %APP_DIR%
pause
exit /b 2

:missing_python
echo [ERROR] The Flet runtime was not found.
echo Run: py -3 -m venv .venv
echo Then: .venv\Scripts\python.exe -m pip install -r requirements-flet.txt
pause
exit /b 3

:finished
if "%APP_EXIT%"=="0" exit /b 0
echo.
echo [ERROR] The application exited with code %APP_EXIT%.
echo Send the error text above to the developer.
pause
exit /b %APP_EXIT%
