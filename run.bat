@echo off
cd /d "%~dp0"
set "PATH=%PATH%;C:\Program Files\nodejs"
start "" "%~dp0node_modules\electron\dist\electron.exe" "%~dp0."
