@echo off
title TIO - Folder Rescue
REM ---------------------------------------------------------------------
REM  NEVER do `cd /d "%~dp0"` here.
REM  That makes cmd.exe AND the powershell it launches hold the folder we
REM  are trying to delete as their current directory. Windows then refuses
REM  to rename or delete it, so the rescue fails 100% of the time -- and
REM  the failure looks like a permissions problem, which sends the user
REM  off to change ACLs for no reason.
REM  Capture the path first, move the working directory somewhere else,
REM  then pass the target in as a parameter.
REM ---------------------------------------------------------------------
REM  This file lives INSIDE the folder the rescue deletes, so a successful run
REM  deletes this file too.  cmd.exe re-reads a batch file line by line while it
REM  runs, so every line after the PowerShell call then fails with
REM  "The system cannot find the path specified." (even `exit /b`, and even when
REM  everything is chained on one line -- verified 2026-09-15).
REM  Fix: copy this file to %TEMP% and hand over to the copy.  A batch file
REM  started WITHOUT `call` replaces the caller (cmd never returns to this file),
REM  and the copy is outside the folder being deleted.  The copy gets the target
REM  folder as %1.  The tiny copy is left in %TEMP% on purpose: deleting it from
REM  inside itself would bring the same error back.
REM ---------------------------------------------------------------------
REM  FALLBACK (added 2026-09-15).  When %TEMP% is missing or not writable the
REM  copy never happens.  Before this fallback existed the file simply fell
REM  through with an empty %1: powershell was handed a -File argument that did
REM  not exist, printed its own usage error, and the rescue never ran at all --
REM  while the exit code stayed 0, so it still looked like it had worked.
REM  Now a failed copy goes to :local, which moves the working directory to
REM  %SystemRoot% (anywhere but the target folder) and calls rescue.ps1 straight
REM  from this file.  That path knowingly accepts the cosmetic
REM  "The system cannot find the path specified." line described above, because
REM  actually running the rescue matters more than a tidy last line.
REM ---------------------------------------------------------------------
REM  Both paths share ONE powershell line, so the location of rescue.ps1 is
REM  written down only once.  %GSTARGET% is the folder to rescue: computed from
REM  %~dp0 in this original, taken from %1 in the copy (a fresh cmd, where it is
REM  not set yet).
REM ---------------------------------------------------------------------
if not "%~1"=="" goto :run
set "GSTARGET=%~dp0"
if "%GSTARGET:~-1%"=="\" set "GSTARGET=%GSTARGET:~0,-1%"
cd /d "%TEMP%" 2>nul
copy /y "%~f0" "%TEMP%\gs_rescue_run.bat" >nul 2>nul || goto :local
if not exist "%TEMP%\gs_rescue_run.bat" goto :local
"%TEMP%\gs_rescue_run.bat" "%GSTARGET%"
goto :local

:run
set "GSTARGET=%~1"
cd /d "%TEMP%"
goto :go

:local
cd /d "%SystemRoot%"

:go
powershell -NoProfile -ExecutionPolicy Bypass -File "%GSTARGET%\scripts\rescue.ps1" -Target "%GSTARGET%"
if errorlevel 1 pause
exit /b 0
