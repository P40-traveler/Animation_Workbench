@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0安装依赖.ps1"
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" launcher.py
if errorlevel 1 pause
