@echo off
title TIO - Diagnostic
REM  pushd (not cd /d): on a UNC path such as \\server\share\tool,
REM  `cd /d` fails and the script would run from C:\Windows\System32.
REM  pushd maps a temporary drive letter, so UNC paths work too.
pushd "%~dp0"
echo.
echo   TIO - Diagnostic Report
echo   =======================================
echo   Please screenshot this whole window.
echo.

echo   [Windows]
ver
echo.

echo   [Python]
set "PYEXE="
call :trypy py -3
if not defined PYEXE call :trypy python
if not defined PYEXE call :trypy python3
if defined PYEXE (
  echo     Working command: %PYEXE%
  %PYEXE% -c "import sys;print('    Version:',sys.version.split()[0]);print('    Path:',sys.executable)"
) else (
  echo     NOT FOUND - this is the problem. Run the setup file.
)
echo.

echo   [Python packages]
if defined PYEXE (
  %PYEXE% "%~dp0scripts\_selfcheck.py" 2>nul
  if errorlevel 1 echo     could not check
) else (
  echo     skipped - no Python
)
echo.

echo   [Internet mark on files]
if defined PYEXE (
  %PYEXE% "%~dp0scripts\_selfcheck.py" mark 2>nul
  if errorlevel 1 echo     could not check
) else (
  echo     skipped - no Python
)
echo.

echo   [Graphical wizard support]
if defined PYEXE (
  %PYEXE% -c "import tkinter" >nul 2>nul
  if errorlevel 1 (echo     tkinter MISSING - installer falls back to text mode) else (echo     tkinter OK)
) else (
  echo     skipped - no Python
)
echo.

REM  2026-09-22 (P3): the microphone is where this tool breaks most often,
REM  yet the diagnostic had no audio check at all. Registry + COM only, no recording.
echo   [Audio devices]
if defined PYEXE (
  %PYEXE% "%~dp0scripts\_selfcheck.py" audio 2>nul
  if errorlevel 1 echo     could not check
) else (
  echo     skipped - no Python
)
echo.

REM  2026-09-28 (V1.31): [Audio devices] said OK on a PC where feature 6 then
REM  could not find the loopback device. This runs TIO's own device lookup and
REM  opens each device for a moment (nothing is kept).
echo   [Recording devices]
if defined PYEXE (
  %PYEXE% "%~dp0scripts\_selfcheck.py" capture 2>nul
  if errorlevel 1 echo     could not check
) else (
  echo     skipped - no Python
)
echo.

echo   [ffmpeg]
where ffmpeg >nul 2>nul
if errorlevel 1 (echo     NOT FOUND) else (echo     OK)
echo.

echo   [Package server (pypi.org)]
if defined PYEXE (
  %PYEXE% -c "import urllib.request,ssl;urllib.request.urlopen('https://pypi.org/simple/',timeout=15);print('    reachable - OK')" 2>"%TEMP%\_gsnet.txt"
  if errorlevel 1 (
    findstr /i "CERTIFICATE_VERIFY_FAILED SSLCertVerificationError certificate" "%TEMP%\_gsnet.txt" >nul 2>nul
    if errorlevel 1 (
      echo     CANNOT REACH - looks like a plain network/proxy problem
    ) else (
      echo     BLOCKED BY SSL INSPECTION
      echo     ^(the firewall/antivirus replaces the certificate; pip cannot verify it^)
      echo     -^> retry the setup, it will use the Windows certificate store,
      echo        or run the setup on a phone hotspot instead
    )
    echo     --- raw ---
    type "%TEMP%\_gsnet.txt" 2>nul
  )
  del "%TEMP%\_gsnet.txt" >nul 2>nul
) else (
  echo     skipped - no Python
)
echo.

echo   [API key]
REM  V1.29: the key saved by the app lives in HKCU\Environment. A window opened before it was saved
REM  (e.g. right after setup) does not see it in its environment, but the app reads it from there
REM  and does not ask again. An empty value counts as not saved (the app treats it that way too).
REM  The value only goes into a for-loop variable to test that it is non-empty; it is never printed.
set "_TIOKEY="
if defined GEMINI_API_KEY (
  echo     is set
) else (
  for /f "tokens=2,*" %%a in ('reg query "HKCU\Environment" /v GEMINI_API_KEY 2^>nul ^| findstr /i /c:"GEMINI_API_KEY"') do if not "%%b"=="" set "_TIOKEY=1"
  if defined _TIOKEY (
    echo     saved on this PC - the app will use it
  ) else (
    echo     NOT set - the app will ask you for it
  )
)
set "_TIOKEY="
echo.

echo   [winget]
where winget >nul 2>nul
if errorlevel 1 (echo     NOT available on this PC) else (echo     OK)
echo.

echo   [Files]
call :chk "requirements.txt"
call :chk "4_*.bat"
call :chk "3_*.bat"
call :chk "1_*.md"
call :chk "2_*.md"
call :chk "5_*.md"
call :chk "%~nx0"
call :chk "7_*.bat"
call :chk "8_*.bat"
call :chk "scripts\rescue.ps1"
call :chk "scripts\_winpath.py"
call :chk "scripts\_ui.py"
call :chk "scripts\_live.py"
REM  2026-09-22 (S1): _blockhint.py is a hard dependency of the three live scripts.
REM  Without this line the diagnostic reports all files OK while features 1/3/6 die.
call :chk "scripts\_blockhint.py"
call :chk "scripts\_apikey.py"
call :chk "scripts\_audioroute.py"
call :chk "scripts\menu.py"
call :chk "scripts\setup_gui.py"
call :chk "scripts\uninstall_gui.py"
call :chk "scripts\live_caption.py"
call :chk "scripts\live_bilingual.py"
call :chk "scripts\live_bilingual_hq.py"
call :chk "scripts\transcribe_meeting.py"
call :chk "scripts\translate_transcript.py"
call :chk "scripts\json_to_md.py"
call :chk "scripts\setup.py"
call :chk "scripts\_selfcheck.py"
echo.

echo   [Desktop shortcut]
if defined PYEXE (
  %PYEXE% -c "import sys;sys.path.insert(0,'scripts');import _winpath;print('    OK' if _winpath.shortcut_exists() else '    not created');print('    desktop:',_winpath.desktop_dir())" 2>nul
  if errorlevel 1 echo     could not check
) else (
  echo     skipped - no Python
)
echo.
echo   =======================================
pause
exit /b 0

:chk
if exist "%~1" (echo     %~1 OK) else (echo     %~1 MISSING - re-extract the zip)
goto :eof

:trypy
%* -c "print(1)" >"%TEMP%\_gspy.txt" 2>nul
if errorlevel 1 goto :eof
set /p _V=<"%TEMP%\_gspy.txt"
if "%_V%"=="1" set "PYEXE=%*"
goto :eof
