@echo off
setlocal
set SCRIPT_DIR=%~dp0
py -3 "%SCRIPT_DIR%macro_health_assisted_shortlist.py" %*
