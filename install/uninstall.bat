@echo off
rem Remove FootageGrab's native messaging registration and CEP panel (Windows).
rem Keeps your config, history, and downloaded footage.
setlocal

for %%r in (
  "HKCU\Software\Google\Chrome\NativeMessagingHosts\com.footagegrab.host"
  "HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.footagegrab.host"
  "HKCU\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\com.footagegrab.host"
  "HKCU\Software\Chromium\NativeMessagingHosts\com.footagegrab.host"
) do reg delete %%r /f >nul 2>&1

del /q "%APPDATA%\FootageGrab\com.footagegrab.host.json" >nul 2>&1
taskkill /f /im bgutil-pot.exe >nul 2>&1
rmdir /s /q "%APPDATA%\FootageGrab\bin" >nul 2>&1
rmdir /s /q "%APPDATA%\yt-dlp\plugins\bgutil-ytdlp-pot-provider" >nul 2>&1
rmdir /s /q "%APPDATA%\Adobe\CEP\extensions\FootageGrabBridge" >nul 2>&1

echo FootageGrab unregistered. Config and history kept in %%APPDATA%%\FootageGrab.
echo Remove the extension from chrome://extensions yourself if you like.
pause
