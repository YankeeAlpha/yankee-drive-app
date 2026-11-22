@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Lili
if not exist ".venv\Scripts\python.exe" (
  echo Najprv spusti instaluj.bat
  pause
  exit /b
)
ollama list >nul 2>nul
if errorlevel 1 (
  start "" /min ollama serve
  timeout /t 5 >nul
)
".venv\Scripts\python.exe" lili.py
pause
