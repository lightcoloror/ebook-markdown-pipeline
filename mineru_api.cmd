@echo off
setlocal
cd /d "%~dp0"
python scripts\mineru_api_service.py %*
