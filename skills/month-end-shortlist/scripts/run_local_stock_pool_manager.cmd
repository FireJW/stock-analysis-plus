@echo off
setlocal EnableExtensions

py -3 "%~dp0local_stock_pool_manager.py" %*
set "EXIT_CODE=%errorlevel%"

exit /b %EXIT_CODE%
