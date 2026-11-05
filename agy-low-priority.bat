@echo off
setlocal

cd /d "%~dp0"

echo Starting Antigravity in this window with BELOWNORMAL Windows process priority...
echo Project: %CD%
echo.

start "" /b /wait /belownormal "%LOCALAPPDATA%\agy\bin\agy.exe" %*

endlocal

