@echo off
setlocal EnableExtensions

py -3 "%~dp0longbridge_plan_sources.py" %*
set "EXIT_CODE=%errorlevel%"

exit /b %EXIT_CODE%
