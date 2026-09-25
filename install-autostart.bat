@echo off
chcp 65001 >nul
title Jarvis - autostart setup
cd /d "%~dp0"

REM ASCII only - cmd.exe reads .bat in the OEM codepage, see start-sheet.bat
REM
REM A shortcut in the Startup folder instead of a scheduled task:
REM Task Scheduler needs administrator rights, the Startup folder does not.

echo.
echo  ============================================================
echo   Autostart for the hourly Google Sheets update
echo  ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "try {" ^
  "  $lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Jarvis sheet.lnk';" ^
  "  $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk);" ^
  "  $s.TargetPath = '%~dp0start-sheet.bat';" ^
  "  $s.WorkingDirectory = '%~dp0'.TrimEnd('\');" ^
  "  $s.WindowStyle = 7;" ^
  "  $s.Description = 'Jarvis: hourly update of the analytics sheet';" ^
  "  $s.Save();" ^
  "  Write-Host ('  Shortcut created: ' + $lnk);" ^
  "  exit 0" ^
  "} catch { Write-Host ('  ERROR: ' + $_.Exception.Message); exit 1 }"

if errorlevel 1 goto failed

echo.
echo  ------------------------------------------------------------
echo   DONE. The update starts automatically every time someone
echo   logs in to Windows on this PC. The window opens minimized
echo   and must stay open.
echo.
echo   Start it right now without rebooting:
echo       double-click start-sheet.bat
echo.
echo   To turn autostart off:
echo       double-click uninstall-autostart.bat
echo  ------------------------------------------------------------
echo.
pause
exit /b 0

:failed
echo.
echo   FAILED to set up autostart. By hand:
echo     1. Press Win+R, type   shell:startup   and press Enter
echo     2. Right-click start-sheet.bat - Copy, then in the opened
echo        folder right-click - Paste shortcut
echo.
pause
exit /b 1
