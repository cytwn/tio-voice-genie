@echo off
chcp 65001 >nul
title TIO
REM  pushd (not cd /d): on a UNC path such as \\server\share\tool,
REM  `cd /d` fails and the script would run from C:\Windows\System32.
REM  pushd maps a temporary drive letter, so UNC paths work too.
pushd "%~dp0"

set "PYEXE="
call :trypy py -3
if defined PYEXE goto :gotpy
call :trypy python
if defined PYEXE goto :gotpy
call :trypy python3
if defined PYEXE goto :gotpy

echo.
echo   [X] Python not found.
echo   Please run the setup file in this folder first.
echo.
pause
exit /b 1

:gotpy
REM  Open the menu in its own window and end this batch file right away.
REM  While a batch file is running, pressing Ctrl+C (live captions are stopped
REM  with Ctrl+C) makes cmd ask "Terminate batch job (Y/N)?" in English when the
REM  menu closes. No batch-file layout avoids that (4 were tested). With START
REM  and an immediate exit, no batch is running, so it is never asked.
REM  Do NOT add /B: it makes the menu ignore Ctrl+C, so live captions could not be stopped.
REM  The new window runs cmd /c around Python. That is not a batch file, so Ctrl+C still
REM  never asks Y/N. If Python cannot even load the menu (a file is missing or damaged),
REM  it exits with 1 or 2 and the window pauses so the error can be read; without this the
REM  window just flashes and closes. menu.py exits with 3 after it has shown its own error
REM  and waited, so the window does not pause a second time.
REM  The full path to menu.py is on the command line on purpose: the rescue tool (8_...bat)
REM  finds programs holding this folder by looking for the folder path in command lines.
start "TIO" /D "%CD%" cmd /c %PYEXE% -u "%CD%\scripts\menu.py" ^|^| if not errorlevel 3 pause
exit /b 0

:trypy
%* -c "print(1)" >"%TEMP%\_gspy.txt" 2>nul
if errorlevel 1 goto :eof
set /p _V=<"%TEMP%\_gspy.txt"
if "%_V%"=="1" set "PYEXE=%*"
del "%TEMP%\_gspy.txt" >nul 2>nul
goto :eof
