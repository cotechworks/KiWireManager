@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1

set "PACKAGE_SOURCE=%~dp0build\kiwiremanager.dist"
set "PACKAGE_TARGET=%~dp0build\KiWireManager.zip"
if not exist "%PACKAGE_SOURCE%\KiWireManager.exe" (
    echo ERROR: Build output was not found. Run Build.bat first.
    goto :failed
)

powershell.exe -NoProfile -Command "$ErrorActionPreference = 'Stop'; Add-Type -AssemblyName System.IO.Compression.FileSystem; $source = $env:PACKAGE_SOURCE; $target = $env:PACKAGE_TARGET; $temporary = $target + '.' + [guid]::NewGuid().ToString('N') + '.tmp'; try { [System.IO.Compression.ZipFile]::CreateFromDirectory($source, $temporary, [System.IO.Compression.CompressionLevel]::Optimal, $false); if ([System.IO.File]::Exists($target)) { [System.IO.File]::Replace($temporary, $target, [System.Management.Automation.Language.NullString]::Value) } else { [System.IO.File]::Move($temporary, $target) }; Write-Host ('Created: ' + $target) } catch { Write-Error $_; exit 1 } finally { if ([System.IO.File]::Exists($temporary)) { [System.IO.File]::Delete($temporary) } }"
if errorlevel 1 goto :failed

echo.
echo Package succeeded: build\KiWireManager.zip
popd
pause
exit /b 0

:failed
echo.
echo Packaging failed. Review the messages above.
popd
pause
exit /b 1
