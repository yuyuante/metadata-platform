@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PROJECT_ROOT=%~dp0.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"
set "WORKSPACE_ROOT=%PROJECT_ROOT%\.."
for %%I in ("%WORKSPACE_ROOT%") do set "WORKSPACE_ROOT=%%~fI"
set "WORKFLOW_ROOT=%EMIP_WORKFLOW_ROOT%"
if not defined WORKFLOW_ROOT set "WORKFLOW_ROOT=%WORKSPACE_ROOT%\DataGovernance"
set "SUCCESS_COUNT=0"
set "FAILED_COUNT=0"
set "SKIPPED_COUNT=0"
set "COMMAND=%~1"

if /I "%COMMAND%"=="sql" goto sql
if /I "%COMMAND%"=="workflow" goto workflow
if /I "%COMMAND%"=="all" goto all
if /I "%COMMAND%"=="perf" goto perf
if /I "%COMMAND%"=="clean" goto clean
if /I "%COMMAND%"=="help" goto help
if "%COMMAND%"=="" goto help

echo Invalid command: %COMMAND%
call :usage
exit /b 2

:sql
call :run_sql
goto summary

:workflow
call :run_workflow
goto summary

:all
call :run_sql
call :run_workflow
goto summary

:perf
call :run_perf
goto summary

:clean
call :clean_reports
goto summary

:run_sql
call :run_scan "sp_EQGP\1_table" "D:\workplace\surveillance\sp_EQGP\1_table"
call :run_scan "sp_EQGP\3_sp" "D:\workplace\surveillance\sp_EQGP\3_sp"
call :run_scan "sp_EQGP\4_functions" "D:\workplace\surveillance\sp_EQGP\4_functions"
call :run_scan "sp_SVELGP\1_table" "D:\workplace\surveillance\sp_SVELGP\1_table"
call :run_scan "sp_SVELGP\2_view" "D:\workplace\surveillance\sp_SVELGP\2_view"
call :run_scan "sp_SVELGP\3_sp" "D:\workplace\surveillance\sp_SVELGP\3_sp"
call :run_scan "sp_SVELGP\4_function" "D:\workplace\surveillance\sp_SVELGP\4_function"
call :run_scan "sp_SVEL_MSAH" "D:\workplace\surveillance\sp_SVEL_MSAH"
call :run_scan "sp_SVEL_MSAH\function" "D:\workplace\surveillance\sp_SVEL_MSAH\function"
call :run_scan "sp_SVEL_MSAH\tab" "D:\workplace\surveillance\sp_SVEL_MSAH\tab"
call :run_scan "sp_SVEL_MSAH\view" "D:\workplace\surveillance\sp_SVEL_MSAH\view"
call :run_scan "sp_SVEL_MSAH_FLEX" "D:\workplace\surveillance\sp_SVEL_MSAH_FLEX"
call :run_scan "sp_SVEL_MSAH_FLEX\function" "D:\workplace\surveillance\sp_SVEL_MSAH_FLEX\function"
call :run_scan "sp_SVEL_MSAH_FLEX\tab" "D:\workplace\surveillance\sp_SVEL_MSAH_FLEX\tab"
call :run_scan "sp_SVEL_MSAH_FLEX\view" "D:\workplace\surveillance\sp_SVEL_MSAH_FLEX\view"
exit /b 0

:run_workflow
call :run_scan "Informatica XML (%WORKFLOW_ROOT%)" "%WORKFLOW_ROOT%"
exit /b 0

:run_scan
set "SCAN_NAME=%~1"
set "SCAN_ROOT=%~2"
if not exist "%SCAN_ROOT%\" (
    echo.
    echo Command: python -m emip scan "%SCAN_ROOT%"
    echo Result: Skipped - repository not found: %SCAN_ROOT%
    set /a SKIPPED_COUNT+=1
    exit /b 0
)
call :timestamp SCAN_START SCAN_START_TICKS
echo.
echo Command: python -m emip scan "%SCAN_ROOT%"
echo Start time: %SCAN_START%
pushd "%PROJECT_ROOT%"
set "PYTHONPATH=%PROJECT_ROOT%\src;%PYTHONPATH%"
python -m emip scan "%SCAN_ROOT%"
set "SCAN_RC=!ERRORLEVEL!"
popd
call :timestamp SCAN_END SCAN_END_TICKS
call :elapsed "!SCAN_START_TICKS!" "!SCAN_END_TICKS!" ELAPSED
echo End time: !SCAN_END!
echo Elapsed time: !ELAPSED! seconds
if "!SCAN_RC!"=="0" (
    echo Result: Succeeded - !SCAN_NAME!
    set /a SUCCESS_COUNT+=1
) else (
    echo Result: Failed - !SCAN_NAME! ^(exit code !SCAN_RC!^)
    set /a FAILED_COUNT+=1
)
exit /b 0

:run_perf
set "SCAN_NAME=Performance Investigation"
if not exist "%WORKFLOW_ROOT%\" (
    echo.
    echo Command: python scripts\profile_informatica.py "%WORKFLOW_ROOT%"
    echo Result: Skipped - workflow repository not found: %WORKFLOW_ROOT%
    set /a SKIPPED_COUNT+=1
    exit /b 0
)
call :timestamp SCAN_START SCAN_START_TICKS
echo.
echo Command: python scripts\profile_informatica.py "%WORKFLOW_ROOT%"
echo Start time: %SCAN_START%
pushd "%PROJECT_ROOT%"
set "PYTHONPATH=%PROJECT_ROOT%\src;%PYTHONPATH%"
python scripts\profile_informatica.py "%WORKFLOW_ROOT%"
set "SCAN_RC=!ERRORLEVEL!"
popd
call :timestamp SCAN_END SCAN_END_TICKS
call :elapsed "!SCAN_START_TICKS!" "!SCAN_END_TICKS!" ELAPSED
echo End time: !SCAN_END!
echo Elapsed time: !ELAPSED! seconds
if "!SCAN_RC!"=="0" (
    echo Result: Succeeded - !SCAN_NAME!
    set /a SUCCESS_COUNT+=1
) else (
    echo Result: Failed - !SCAN_NAME! ^(exit code !SCAN_RC!^)
    set /a FAILED_COUNT+=1
)
exit /b 0

:clean_reports
call :timestamp SCAN_START SCAN_START_TICKS
echo.
echo Command: remove "%PROJECT_ROOT%\scan-report"
echo Start time: %SCAN_START%
if exist "%PROJECT_ROOT%\scan-report\" rmdir /s /q "%PROJECT_ROOT%\scan-report"
set "SCAN_RC=!ERRORLEVEL!"
call :timestamp SCAN_END SCAN_END_TICKS
call :elapsed "!SCAN_START_TICKS!" "!SCAN_END_TICKS!" ELAPSED
echo End time: !SCAN_END!
echo Elapsed time: !ELAPSED! seconds
if "!SCAN_RC!"=="0" (
    echo Result: Succeeded - previous scan reports removed
    set /a SUCCESS_COUNT+=1
) else (
    echo Result: Failed - unable to remove previous scan reports
    set /a FAILED_COUNT+=1
)
exit /b 0

:timestamp
for /f "delims=" %%T in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyy-MM-dd HH:mm:ss.fff')"') do set "%~1=%%T"
for /f "delims=" %%T in ('powershell -NoProfile -Command "[DateTime]::UtcNow.Ticks"') do set "%~2=%%T"
exit /b 0

:elapsed
for /f "delims=" %%T in ('powershell -NoProfile -Command "('{0:N3}' -f (([Int64]('%~2') - [Int64]('%~1')) / 10000000))"') do set "%~3=%%T"
exit /b 0

:summary
echo.
echo ==================== Final Summary ====================
echo Succeeded: %SUCCESS_COUNT%
echo Failed:    %FAILED_COUNT%
echo Skipped:   %SKIPPED_COUNT%
if %FAILED_COUNT% GTR 0 exit /b 1
exit /b 0

:help
call :usage
exit /b 0

:usage
echo Usage: scan.bat ^<command^>
echo.
echo Commands:
echo   sql       Run all SQL production repositories.
echo   workflow  Run all configured Informatica XML repositories recursively.
echo   all       Run SQL first, then Workflow.
echo   perf      Run the Performance Investigation workflow.
echo   clean     Remove previous scan reports.
echo   help      Display this usage information.
echo.
echo Set EMIP_WORKFLOW_ROOT to override the default Informatica repository root.
exit /b 0
