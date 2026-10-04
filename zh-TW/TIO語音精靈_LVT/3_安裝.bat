@echo off
title TIO - Setup
REM  pushd (not cd /d): on a UNC path such as \\server\share\tool,
REM  `cd /d` fails and the script would run from C:\Windows\System32.
REM  pushd maps a temporary drive letter, so UNC paths work too.
pushd "%~dp0"
echo.
echo   TIO
echo   ===========================================
echo.

REM ======================================================================
REM  Stage 1 : make sure a REAL Python exists.
REM
REM  Do NOT use "where python": Windows ships a 0-byte Microsoft Store
REM  alias at WindowsApps\python.exe, so "where" succeeds even with NO
REM  Python installed. We must actually RUN it and check it prints.
REM ======================================================================
call :findpy
if defined PYEXE goto :gotpy

echo   Python is not installed on this computer.
echo.

REM --- ask for consent, in Chinese, via a PowerShell dialog -------------
powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand QQBkAGQALQBUAHkAcABlACAALQBBAHMAcwBlAG0AYgBsAHkATgBhAG0AZQAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAgAHwAIABPAHUAdAAtAE4AdQBsAGwAOwAgACQAcgAgAD0AIABbAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAE0AZQBzAHMAYQBnAGUAQgBvAHgAXQA6ADoAUwBoAG8AdwAoACcAGZDwU/uWZoGEkJJsCWeJW92IIABQAHkAdABoAG8AbgAM/xmQC1DlXXdRAJeBiYNbTWL9gPdXTIgCMCcAIAArACAAWwBjAGgAYQByAF0AMQAwACAAKwAgACcAJwAgACsAIABbAGMAaABhAHIAXQAxADAAIAArACAAJwAJYwwwuniaWw0wjF8DZ+qB1VKJW92IDP8nWQR9AJeBiSAAMQBe/zMAIAAGUhiUAjAnACAAKwAgAFsAYwBoAGEAcgBdADEAMAAgACsAIAAnAIlb3YhOkAt6LU7RnnKClomXegNnCWeHZVdbAE70dtGNDP+jkC9mY2s4XoR2DP/Lig1OgYnclYljg1sCMCcAIAArACAAWwBjAGgAYQByAF0AMQAwACAAKwAgACcAJwAgACsAIABbAGMAaABhAHIAXQAxADAAIAArACAAJwD7MIlb3YgoV2BP6oHxXYR2f08odQWAM15fhpVeC04M/w1OAJeBift8cX2hewZ04VQKa1CWJwAgACsAIABbAGMAaABhAHIAXQAxADAAIAArACAAJwD7MA1OA2c5ZTBSGZDwU/uWZoGEdnZR1k4tippbJwAgACsAIABbAGMAaABhAHIAXQAxADAAIAArACAAJwD7MN2IjFsDZ+qB8V2lY1eE0Y0M/w1OKHVgT41R3p4ATiFrJwAgACsAIABbAGMAaABhAHIAXQAxADAAIAArACAAJwAnACAAKwAgAFsAYwBoAGEAcgBdADEAMAAgACsAIAAnAIGJfH6Mfs5VH/8nACwAIAAnAFQASQBPAJ6K85e+fEiXIAAUICAAAJeBiUhRiVvdiCAAUAB5AHQAaABvAG4AJwAsACAAWwBTAHkAcwB0AGUAbQAuAFcAaQBuAGQAbwB3AHMALgBGAG8AcgBtAHMALgBNAGUAcwBzAGEAZwBlAEIAbwB4AEIAdQB0AHQAbwBuAHMAXQA6ADoATwBLAEMAYQBuAGMAZQBsACwAIABbAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAE0AZQBzAHMAYQBnAGUAQgBvAHgASQBjAG8AbgBdADoAOgBRAHUAZQBzAHQAaQBvAG4AKQA7ACAAaQBmACAAKAAkAHIAIAAtAGUAcQAgAFsAUwB5AHMAdABlAG0ALgBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4ARABpAGEAbABvAGcAUgBlAHMAdQBsAHQAXQA6ADoAQwBhAG4AYwBlAGwAKQAgAHsAIABlAHgAaQB0ACAAMgAgAH0AIABlAGwAcwBlACAAewAgAGUAeABpAHQAIAAwACAAfQA=
if errorlevel 2 goto :userquit

where winget >nul 2>nul
if errorlevel 1 goto :nowinget

echo   -----------------------------------------------------------
echo    STEP 1 of 2 : Installing Python   (1-3 minutes, please wait)
echo    Text will scroll by. That is normal. Do NOT close this window.
echo   -----------------------------------------------------------
echo.
winget install --id Python.Python.3.13 -e --scope user --accept-source-agreements --accept-package-agreements
set "WGRC=%ERRORLEVEL%"
echo.
echo   STEP 1 finished. Locating the Python that was just installed...

REM --- 1) plain PATH lookup (usually still stale in this window) --------
call :findpy
if defined PYEXE goto :gotpy

REM --- 2) refresh PATH from the registry, then look again ---------------
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "NEWPATH=%%B"
if defined NEWPATH set "PATH=%PATH%;%NEWPATH%"
call :findpy
if defined PYEXE goto :gotpy

REM --- 3) go straight to where winget puts it (--scope user) ------------
call :findpy_folders
if defined PYEXE goto :gotpy

REM --- 4) still nothing. Which message depends on whether winget worked.
REM     Getting this wrong is worse than useless: telling someone
REM     "Python is installed, just click again" when the install actually
REM     FAILED sends them round in circles.
if not "%WGRC%"=="0" goto :manualpy
powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand QQBkAGQALQBUAHkAcABlACAALQBBAHMAcwBlAG0AYgBsAHkATgBhAG0AZQAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAgAHwAIABPAHUAdAAtAE4AdQBsAGwAOwAgACQAcgAgAD0AIABbAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAE0AZQBzAHMAYQBnAGUAQgBvAHgAXQA6ADoAUwBoAG8AdwAoACcAUAB5AHQAaABvAG4AIADyXZN93Yh9WYZODP9GTxmQC1CWiZd6hJCAiw1OMFKDWwIwJwAgACsAIABbAGMAaABhAHIAXQAxADAAIAArACAAJwAnACAAKwAgAFsAYwBoAGEAcgBdADEAMAAgACsAIAAnAMuK3JWJYxmQC1DRnnKClomXegz/jVHenmlRC04MMDMAXwCJW92ILgBiAGEAdAANMABOIWsxXO9T5U6GTgIwJwAgACsAIABbAGMAaABhAHIAXQAxADAAIAArACAAJwAI/+pTA2d8dh91GZAATiFrDP9LToxf/ZANTih1AjAJ/ycALAAgACcAVABJAE8Anorzl758SJcgABQgIADLio1R3p4ATiFriVvdiCcALAAgAFsAUwB5AHMAdABlAG0ALgBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4ATQBlAHMAcwBhAGcAZQBCAG8AeABCAHUAdAB0AG8AbgBzAF0AOgA6AE8ASwAsACAAWwBTAHkAcwB0AGUAbQAuAFcAaQBuAGQAbwB3AHMALgBGAG8AcgBtAHMALgBNAGUAcwBzAGEAZwBlAEIAbwB4AEkAYwBvAG4AXQA6ADoASQBuAGYAbwByAG0AYQB0AGkAbwBuACkAOwAgAGkAZgAgACgAJAByACAALQBlAHEAIABbAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAEQAaQBhAGwAbwBnAFIAZQBzAHUAbAB0AF0AOgA6AEMAYQBuAGMAZQBsACkAIAB7ACAAZQB4AGkAdAAgADIAIAB9ACAAZQBsAHMAZQAgAHsAIABlAHgAaQB0ACAAMAAgAH0A
exit /b 1

REM ======================================================================
REM  Stage 2 : hand over to the graphical setup wizard.
REM ======================================================================
:gotpy
echo.
echo   [OK] Python: %PYEXE%
echo.
echo   -----------------------------------------------------------
echo    STEP 2 of 2 : Opening the setup window...
echo    A window will appear in a moment. Continue there.
echo   -----------------------------------------------------------
%PYEXE% -c "import tkinter" >nul 2>nul
if errorlevel 1 goto :textmode
%PYEXE% "scripts\setup_gui.py"
exit /b 0

:textmode
powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand QQBkAGQALQBUAHkAcABlACAALQBBAHMAcwBlAG0AYgBsAHkATgBhAG0AZQAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAgAHwAIABPAHUAdAAtAE4AdQBsAGwAOwAgACQAcgAgAD0AIABbAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAE0AZQBzAHMAYQBnAGUAQgBvAHgAXQA6ADoAUwBoAG8AdwAoACcAGZDwU/uWZoGEdiAAUAB5AHQAaABvAG4AIACSbAlnZ1H6XpaJl3qfUv2ACP90AGsAaQBuAHQAZQByAAn/DP8nACAAKwAgAFsAYwBoAGEAcgBdADEAMAAgACsAIAAnAEBi5U6JW92IvnxIl5aJl3qLlQ1Od42GTwIwJwAgACsAIABbAGMAaABhAHIAXQAxADAAIAArACAAJwAnACAAKwAgAFsAYwBoAGEAcgBdADEAMAAgACsAIAAnAJJs3JXCTwz/pWMLToZPA2codYdlV1tIcnx+jH6JW92IAjA7ToGJZWtfmgBOI2oM/0ZPDU4DZ/pey3pMaGKXd2ORXwj/3Yh9WYxf9HalY96eaVELTseMmWU+WeGIhHYgADQAXwCLlctZf08odS4AYgBhAHQACf8M/2xR+FOyfe+NFGUqYpFhSYtCZl9ODU4DZ+qB1VLNkWaKAjAnACAAKwAgAFsAYwBoAGEAcgBdADEAMAAgACsAIAAnAMuKZ3HRnnKClomXeuGIhHZPVUyY3lZUezFc71PlToZOAjAnACwAIAAnAFQASQBPAJ6K85e+fEiXIAAUICAAOWUodYdlV1tIcolb3YgnACwAIABbAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAE0AZQBzAHMAYQBnAGUAQgBvAHgAQgB1AHQAdABvAG4AcwBdADoAOgBPAEsALAAgAFsAUwB5AHMAdABlAG0ALgBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4ATQBlAHMAcwBhAGcAZQBCAG8AeABJAGMAbwBuAF0AOgA6AEkAbgBmAG8AcgBtAGEAdABpAG8AbgApADsAIABpAGYAIAAoACQAcgAgAC0AZQBxACAAWwBTAHkAcwB0AGUAbQAuAFcAaQBuAGQAbwB3AHMALgBGAG8AcgBtAHMALgBEAGkAYQBsAG8AZwBSAGUAcwB1AGwAdABdADoAOgBDAGEAbgBjAGUAbAApACAAewAgAGUAeABpAHQAIAAyACAAfQAgAGUAbABzAGUAIAB7ACAAZQB4AGkAdAAgADAAIAB9AA==
%PYEXE% "scripts\setup.py"
exit /b 0

REM ======================================================================
REM  Failure paths
REM ======================================================================
:nowinget
powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand QQBkAGQALQBUAHkAcABlACAALQBBAHMAcwBlAG0AYgBsAHkATgBhAG0AZQAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAgAHwAIABPAHUAdAAtAE4AdQBsAGwAOwAgACQAcgAgAD0AIABbAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAE0AZQBzAHMAYQBnAGUAQgBvAHgAXQA6ADoAUwBoAG8AdwAoACcAGZDwU/uWZoGSbAlnIABXAGkAbgBkAG8AdwBzACAAhHbqgdVSiVvdiOVdd1EI/3cAaQBuAGcAZQB0AAn/DP8nACAAKwAgAFsAYwBoAGEAcgBdADEAMAAgACsAIAAnAEBi5U6SbKaP1WzqgdVSa15gT92IIABQAHkAdABoAG8AbgACMCcAIAArACAAWwBjAGgAYQByAF0AMQAwACAAKwAgACcAJwAgACsAIABbAGMAaABhAHIAXQAxADAAIAArACAAJwClYwtOhk8DZ4uVX1UgAFAAeQB0AGgAbwBuACAAmFu5ZQtOCY8BmAz/y4pncRmQCU5la1pQGv8nACAAKwAgAFsAYwBoAGEAcgBdADEAMAAgACsAIAAnACcAIAArACAAWwBjAGgAYQByAF0AMQAwACAAKwAgACcAMQAuACAAC04JjyZO91dMiCAAUAB5AHQAaABvAG4AIACJW92IC3oPXycAIAArACAAWwBjAGgAYQByAF0AMQAwACAAKwAgACcAMgAuACAAPdg03SAAiVvdiGt1YpcAZwtOYpejkAtQDDBBAGQAZAAgAHAAeQB0AGgAbwBuAC4AZQB4AGUAIAB0AG8AIABQAEEAVABIAA0wAE6aW4GJU2L+UicAIAArACAAWwBjAGgAYQByAF0AMQAwACAAKwAgACcAMwAuACAA3YiMW4xfDP/eVoZPjVHenmlRC04MMDMAXwCJW92ILgBiAGEAdAANMCcALAAgACcAVABJAE8Anorzl758SJcgABQgIAAAl4GJS2LVUolb3YggAFAAeQB0AGgAbwBuACcALAAgAFsAUwB5AHMAdABlAG0ALgBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4ATQBlAHMAcwBhAGcAZQBCAG8AeABCAHUAdAB0AG8AbgBzAF0AOgA6AE8ASwAsACAAWwBTAHkAcwB0AGUAbQAuAFcAaQBuAGQAbwB3AHMALgBGAG8AcgBtAHMALgBNAGUAcwBzAGEAZwBlAEIAbwB4AEkAYwBvAG4AXQA6ADoAVwBhAHIAbgBpAG4AZwApADsAIABpAGYAIAAoACQAcgAgAC0AZQBxACAAWwBTAHkAcwB0AGUAbQAuAFcAaQBuAGQAbwB3AHMALgBGAG8AcgBtAHMALgBEAGkAYQBsAG8AZwBSAGUAcwB1AGwAdABdADoAOgBDAGEAbgBjAGUAbAApACAAewAgAGUAeABpAHQAIAAyACAAfQAgAGUAbABzAGUAIAB7ACAAZQB4AGkAdAAgADAAIAB9AA==
start "" "https://www.python.org/downloads/"
exit /b 1

:manualpy
powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand QQBkAGQALQBUAHkAcABlACAALQBBAHMAcwBlAG0AYgBsAHkATgBhAG0AZQAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAgAHwAIABPAHUAdAAtAE4AdQBsAGwAOwAgACQAcgAgAD0AIABbAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAE0AZQBzAHMAYQBnAGUAQgBvAHgAXQA6ADoAUwBoAG8AdwAoACcAUAB5AHQAaABvAG4AIADqgdVSiVvdiJJsCWcQYp9SAjAnACAAKwAgAFsAYwBoAGEAcgBdADEAMAAgACsAIAAnACcAIAArACAAWwBjAGgAYQByAF0AMQAwACAAKwAgACcApWMLToZPA2drXmBPi5VfVSAAUAB5AHQAaABvAG4AIACYW7llC04JjwGYDP/LimdxGZAJTmVrWlAa/ycAIAArACAAWwBjAGgAYQByAF0AMQAwACAAKwAgACcAJwAgACsAIABbAGMAaABhAHIAXQAxADAAIAArACAAJwAxAC4AIAALTgmPJk73V0yIIABQAHkAdABoAG8AbgAgAIlb3YgLeg9fJwAgACsAIABbAGMAaABhAHIAXQAxADAAIAArACAAJwAyAC4AIAA92DTdIACJW92Ia3VilwBnC05il6OQC1AMMEEAZABkACAAcAB5AHQAaABvAG4ALgBlAHgAZQAgAHQAbwAgAFAAQQBUAEgADTAATppbgYlTYv5SJwAgACsAIABbAGMAaABhAHIAXQAxADAAIAArACAAJwAzAC4AIADdiIxbjF8M/95Whk+NUd6eaVELTgwwMwBfAIlb3YguAGIAYQB0AA0wJwAgACsAIABbAGMAaABhAHIAXQAxADAAIAArACAAJwAnACAAKwAgAFsAYwBoAGEAcgBdADEAMAAgACsAIAAnAIJZnGdsUfhT+5ZmgQ1OQVExiuqBTIiJW92I347Umgz/y4p+YseMCoq6TuFUVFOpUgIwJwAsACAAJwBUAEkATwCeivOXvnxIlyAAFCAgAACXgYlLYtVSiVvdiCAAUAB5AHQAaABvAG4AJwAsACAAWwBTAHkAcwB0AGUAbQAuAFcAaQBuAGQAbwB3AHMALgBGAG8AcgBtAHMALgBNAGUAcwBzAGEAZwBlAEIAbwB4AEIAdQB0AHQAbwBuAHMAXQA6ADoATwBLACwAIABbAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAE0AZQBzAHMAYQBnAGUAQgBvAHgASQBjAG8AbgBdADoAOgBXAGEAcgBuAGkAbgBnACkAOwAgAGkAZgAgACgAJAByACAALQBlAHEAIABbAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwAuAEQAaQBhAGwAbwBnAFIAZQBzAHUAbAB0AF0AOgA6AEMAYQBuAGMAZQBsACkAIAB7ACAAZQB4AGkAdAAgADIAIAB9ACAAZQBsAHMAZQAgAHsAIABlAHgAaQB0ACAAMAAgAH0A
start "" "https://www.python.org/downloads/"
exit /b 1

:userquit
echo   Cancelled by user.
exit /b 0

REM ======================================================================
REM  Helpers
REM ======================================================================
:findpy
set "PYEXE="
call :trypy py -3
if defined PYEXE goto :eof
call :trypy python
if defined PYEXE goto :eof
call :trypy python3
goto :eof

:findpy_folders
set "PYEXE="
if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" (
  call :trypy "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" -3
  if defined PYEXE goto :eof
)
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
  if exist "%%D\python.exe" call :trypy "%%D\python.exe"
)
if defined PYEXE goto :eof
for /d %%D in ("%ProgramFiles%\Python3*") do (
  if exist "%%D\python.exe" call :trypy "%%D\python.exe"
)
goto :eof

:trypy
if defined PYEXE goto :eof
%* -c "print(1)" >"%TEMP%\_gspy.txt" 2>nul
if errorlevel 1 goto :eof
set /p _V=<"%TEMP%\_gspy.txt"
if "%_V%"=="1" set "PYEXE=%*"
goto :eof
