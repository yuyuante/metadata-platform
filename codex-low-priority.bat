@echo off
setlocal

cd /d "%~dp0"

echo Starting Codex in this window with BELOWNORMAL Windows process priority...
echo Project: %CD%
echo.

start "" /b /wait /belownormal cmd /c codex

endlocal
