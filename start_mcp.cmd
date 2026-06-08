@echo off
title 图文材料转换器 MCP
setlocal
set "SCRIPT_DIR=%~dp0"
python "%SCRIPT_DIR%ebook_converter_mcp.py" %*
