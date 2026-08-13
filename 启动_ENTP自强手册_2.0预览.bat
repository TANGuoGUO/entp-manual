@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Flet 运行环境尚未安装。
  echo 请执行：python -m venv .venv
  echo 然后执行：.venv\Scripts\python.exe -m pip install -r requirements-flet.txt
  pause
  exit /b 1
)

".venv\Scripts\python.exe" "flet_app.py"
if errorlevel 1 pause
