@echo off
title Graphic-Text Material Converter MCP
setlocal
set "SCRIPT_DIR=%~dp0"
python "%SCRIPT_DIR%ebook_converter_mcp.py" %*
