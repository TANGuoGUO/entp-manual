@echo off
setlocal
cd /d "%~dp0"
set "BUNDLED_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

echo ===== ENTP Manual Environment Check =====
echo Project: %CD%
echo.

if exist "app.py" (echo [OK] app.py) else (echo [MISSING] app.py)
if exist "database.py" (echo [OK] database.py) else (echo [MISSING] database.py)
if exist "markdown_store.py" (echo [OK] markdown_store.py) else (echo [MISSING] markdown_store.py)
if exist "vendor\markdown2.py" (echo [OK] Markdown components) else (echo [MISSING] Markdown components)

echo.
if not exist "%BUNDLED_PY%" goto no_bundled_python
echo [OK] Python: %BUNDLED_PY%
"%BUNDLED_PY%" --version
"%BUNDLED_PY%" -B -c "import app; print('[OK] Application modules imported')"
goto check_done

:no_bundled_python
echo [INFO] Codex bundled Python was not found. Checking system Python...
where py 2>nul
where python 2>nul

:check_done
echo.
echo Check finished.
pause

