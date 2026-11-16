@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" main.py %*
    goto :end
)

if exist "D:\PYPY\python.exe" (
    "D:\PYPY\python.exe" main.py %*
    goto :end
)

python main.py %*

:end
endlocal
