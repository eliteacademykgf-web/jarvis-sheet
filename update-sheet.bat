@echo off
chcp 65001 >nul
title Jarvis - update from GitHub
cd /d "%~dp0"

REM ASCII only - cmd.exe reads .bat in the OEM codepage, see start-sheet.bat
REM
REM No restart needed afterwards: run_loop.py starts every hourly run as a
REM new process, so the next run already uses the new code. Restart
REM start-sheet.bat only if run_loop.py itself changed.

where git >nul 2>&1
if errorlevel 1 goto nogit

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 goto notarepo

git pull
if errorlevel 1 goto pullfailed

echo.
echo   DONE. The next hourly run uses the new code.
echo.
pause
exit /b 0

:nogit
echo   Git is not installed: https://git-scm.com/download/win
echo.
pause
exit /b 1

:notarepo
echo   This folder is a plain copy, not a git clone - nothing to pull.
echo   Update it by copying the new jarvis-sheet folder over this one
echo   (keep .env and google-key.json).
echo.
pause
exit /b 1

:pullfailed
echo.
echo   Update failed. Most common reasons:
echo     - no access to the private repository (login / token)
echo     - no internet on this PC
echo     - local edits in this folder conflict with GitHub
echo.
pause
exit /b 1
