@echo off
title Graphic-Text Material Converter HTTP API
setlocal
set "SCRIPT_DIR=%~dp0"
python "%SCRIPT_DIR%ebook_converter_http.py" %*
