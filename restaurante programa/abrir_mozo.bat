@echo off
cd /d "%~dp0" || exit /b 1
if exist "venv\Scripts\python.exe" (
    set PY=venv\Scripts\python.exe
) else (
    set PY=python
)
start "" "http://localhost:8510/?terminal=mozo"
start /max "Restaurante Pro - Mozo" "%PY%" -m streamlit run sistema_restaurante.py --server.port 8510 --server.headless true
