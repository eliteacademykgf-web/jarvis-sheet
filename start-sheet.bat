@echo off
chcp 65001 >nul
title Jarvis - skvoznaya analitika (hourly update)
cd /d "%~dp0"

REM ============================================================
REM  ASCII only! cmd.exe reads .bat in the OEM codepage (cp866),
REM  so Cyrillic here turns into garbage and breaks parsing.
REM  All Russian text lives in run_loop.py - Python handles UTF-8.
REM ============================================================

if not exist ".env" goto noenv

REM Same interpreter choice as the Elite site server: prefer 3.12,
REM the newest Pythons may lack ready-made packages.
set "PY="
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3.12"
if defined PY goto run

py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3.11"
if defined PY goto run

py -3.10 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3.10"
if defined PY goto run

where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto run

where python >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto run

goto nopython

:run
REM Install packages only when missing - pip without internet is slow.
%PY% -c "import gspread, google.oauth2, dotenv, requests" >nul 2>&1
if not errorlevel 1 goto loop

:install
echo   Installing packages (requirements.txt)...
%PY% -m pip install --disable-pip-version-check -q -r requirements.txt
%PY% -c "import gspread, google.oauth2, dotenv, requests" >nul 2>&1
if errorlevel 1 goto badpip

:loop
%PY% run_loop.py
REM Exit code 3 = new code arrived from GitHub (run_loop.py pulled it):
REM re-check packages and start again with the new code
if "%errorlevel%"=="3" goto install
if errorlevel 1 pause
goto :eof

:noenv
echo.
echo  ============================================================
echo   File .env not found in this folder:
echo     %~dp0
echo.
echo   Copy .env and google-key.json here (see OFFICE-PC.md),
echo   then run this file again.
echo  ============================================================
echo.
pause
exit /b 1

:badpip
echo.
echo   Packages could not be installed. Check the internet connection
echo   and run this file again. Python 3.12 is recommended:
echo     https://www.python.org/downloads/release/python-3129/
echo     (tick [x] Add python.exe to PATH during install)
echo.
pause
exit /b 1

:nopython
echo.
echo  ============================================================
echo   Python is not installed.
echo  ============================================================
echo   1. Open  https://www.python.org/downloads/release/python-3129/
echo   2. Download "Windows installer (64-bit)"
echo   3. TICK  [x] Add python.exe to PATH  and click Install Now
echo   4. Run this file again
echo.
pause
exit /b 1
