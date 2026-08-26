@echo off
setlocal

cd /d "%~dp0"

echo Starting Codex with BELOWNORMAL Windows process priority...
echo Project: %CD%
echo.

start "EMIP Codex - BelowNormal" /belownormal cmd /k "cd /d ""%~dp0"" && codex"

endlocal
