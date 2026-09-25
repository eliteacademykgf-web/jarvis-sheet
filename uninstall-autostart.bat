@echo off
chcp 65001 >nul
title Jarvis - remove autostart

REM ASCII only - cmd.exe reads .bat in the OEM codepage, see start-sheet.bat

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Jarvis sheet.lnk';" ^
  "if (Test-Path $lnk) { Remove-Item $lnk; Write-Host '  Autostart removed.' }" ^
  "else { Write-Host '  Autostart was not set up.' }"

echo   The window that is running now keeps working until you close it.
echo.
pause
