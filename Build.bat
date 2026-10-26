@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1

rem Prefer the project's virtual environment when available.
set "BUILD_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "BUILD_PYTHON=%~dp0.venv\Scripts\python.exe"

"%BUILD_PYTHON%" -c "import sys; assert sys.version_info >= (3, 10); import tkinter" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.10 or later with Tkinter is required.
    goto :failed
)
"%BUILD_PYTHON%" -m nuitka --version
if errorlevel 1 (
    echo ERROR: Install Nuitka in the selected Python environment first:
    echo "%BUILD_PYTHON%" -m pip install Nuitka
    goto :failed
)

"%BUILD_PYTHON%" -m nuitka ^
    --mode=standalone ^
    --follow-imports ^
    --enable-plugin=tk-inter ^
    --windows-console-mode=disable ^
    --output-dir=build ^
    --output-filename=KiWireManager.exe ^
    src\kiwiremanager.py
if errorlevel 1 goto :failed

echo.
echo Build succeeded: build\kiwiremanager.dist\KiWireManager.exe
echo Distribute the ENTIRE build\kiwiremanager.dist folder.
echo KiCad 10 must be installed separately for schematic import and writeback.
popd
pause
exit /b 0

:failed
echo.
echo Build failed. Review the messages above.
popd
pause
exit /b 1
