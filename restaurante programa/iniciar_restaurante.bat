@echo off
cd /d "%~dp0" || exit /b 1
if exist "venv\Scripts\python.exe" (
    set PY=venv\Scripts\python.exe
) else (
    set PY=python
)
start /max "Restaurante Pro - Panel" "%PY%" -m streamlit run sistema_restaurante.py --server.port 8501
timeout /t 4 /nobreak >nul
start "" "http://localhost:8501"
