@echo off
cd /d "%~dp0"
echo Pornesc Perfume Price Tracker...
echo.

start "" cmd /c "timeout /t 3 /nobreak >nul & start chrome http://127.0.0.1:8000"

".venv\Scripts\python.exe" run.py

echo.
echo Serverul s-a oprit.
pause
