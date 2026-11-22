@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ===== Instalacia Lili (lokalna domaca asistentka) =====
echo.

set RESTART=
where py >nul 2>nul
if errorlevel 1 (
  echo [1/4] Instalujem Python...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  set RESTART=1
) else (
  echo [1/4] Python je nainstalovany.
)

where ollama >nul 2>nul
if errorlevel 1 (
  echo [2/4] Instalujem Ollama...
  winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
  set RESTART=1
) else (
  echo [2/4] Ollama je nainstalovana.
)

if defined RESTART (
  echo.
  echo Prva cast je hotova. ZATVOR toto okno a spusti instaluj.bat este raz.
  pause
  exit /b
)

echo [3/4] Pripravujem kniznice (moze to trvat par minut)...
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv || py -3 -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo CHYBA pri instalacii kniznic. Posli mi text chyby vyssie.
  pause
  exit /b 1
)

echo [4/4] Stahujem mozog Lili (asi 3 GB, raz a navzdy)...
ollama list >nul 2>nul
if errorlevel 1 (
  start "" /min ollama serve
  timeout /t 5 >nul
)
ollama pull gemma3:4b
if errorlevel 1 (
  echo.
  echo CHYBA pri stahovani modelu. Skontroluj internet a spusti instaluj.bat znova.
  pause
  exit /b 1
)

echo.
echo ===== Hotovo! Lili spustis cez spusti.bat =====
pause
