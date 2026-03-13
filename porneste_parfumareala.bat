@echo off
setlocal

cd /d "%~dp0"
title Parfumareala Launcher

set FIRST_SETUP=0

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Creez mediul virtual...
    py -3.13 -m venv .venv
    if errorlevel 1 (
        echo Nu am reusit sa creez venv-ul.
        pause
        exit /b 1
    )
    set FIRST_SETUP=1
)

echo [2/5] Activez mediul virtual...
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Nu am reusit sa activez venv-ul.
    pause
    exit /b 1
)

if not exist ".venv\Lib\site-packages\streamlit" (
    set FIRST_SETUP=1
)

if "%FIRST_SETUP%"=="1" (
    echo [3/5] Instalez dependentele...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Instalarea dependintelor a esuat.
        pause
        exit /b 1
    )

    echo [4/5] Instalez Playwright Chromium...
    python -m playwright install chromium
    if errorlevel 1 (
        echo Instalarea browserului Chromium pentru Playwright a esuat.
        pause
        exit /b 1
    )
) else (
    echo [3/5] Dependentele exista deja.
    echo [4/5] Playwright este presupus instalat deja.
)

echo [5/5] Pornesc aplicatia...
call ".venv\Scripts\activate.bat"
python -m streamlit run app/main.py --server.port 8501 --server.headless false