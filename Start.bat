@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1

set "APP_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"

"%APP_PYTHON%" "src\kiwiremanager.py"
set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" (
    echo.
    echo Application failed. Review the messages above.
    pause
)
popd
exit /b %APP_EXIT_CODE%
