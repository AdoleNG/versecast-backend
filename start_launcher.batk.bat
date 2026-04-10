@echo off
title VerseCast STT Launcher

REM Change directory to the folder containing this script
cd /d "%~dp0"

echo Starting VerseCast launcher server...
echo (This window can remain minimized.)

:loop
    python launcher_server.py
    echo Launcher crashed or exited. Restarting in 3 seconds...
    timeout /t 3 >nul
goto loop
