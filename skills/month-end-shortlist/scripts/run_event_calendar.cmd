@echo off
setlocal EnableExtensions

py -3 "%~dp0event_calendar_runtime.py" %*
set "EXIT_CODE=%errorlevel%"

exit /b %EXIT_CODE%
