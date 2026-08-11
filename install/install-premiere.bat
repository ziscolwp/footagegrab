@echo off
rem Install the FootageGrab Bridge CEP panel into Premiere Pro (Windows).
rem Double-click me. Re-run after updating the folder. No admin needed.
setlocal
set "SRC=%~dp0..\premiere"
set "DEST=%APPDATA%\Adobe\CEP\extensions\FootageGrabBridge"

if not exist "%SRC%\CSXS\manifest.xml" (
  echo premiere\CSXS\manifest.xml not found - run from the FootageGrab folder.
  pause
  exit /b 1
)

if exist "%DEST%" rmdir /s /q "%DEST%"
mkdir "%DEST%"
xcopy /e /i /q /y "%SRC%\CSXS" "%DEST%\CSXS\" >nul
xcopy /e /i /q /y "%SRC%\css" "%DEST%\css\" >nul
xcopy /e /i /q /y "%SRC%\js" "%DEST%\js\" >nul
xcopy /e /i /q /y "%SRC%\jsx" "%DEST%\jsx\" >nul
copy /y "%SRC%\index.html" "%DEST%\" >nul
copy /y "%SRC%\.debug" "%DEST%\" >nul

rem unsigned CEP extensions need PlayerDebugMode; Premiere versions differ in
rem which CSXS version they read - extra keys are harmless
for %%v in (9 10 11 12) do reg add "HKCU\Software\Adobe\CSXS.%%v" /v PlayerDebugMode /t REG_SZ /d 1 /f >nul

echo.
echo FootageGrab Bridge installed.
echo Restart Premiere Pro, then open Window ^> Extensions ^> FootageGrab Bridge.
pause
