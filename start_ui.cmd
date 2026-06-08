@echo off
title 图文材料转换器 UI
set SCRIPT_DIR=%~dp0
pushd "%SCRIPT_DIR%.."
python "%SCRIPT_DIR%book_converter_ui.py"
popd
