# FootageGrab native host installer for Windows.
# Run via install.bat (double-click) or:
#   powershell -NoProfile -ExecutionPolicy Bypass -File install\install.ps1
#
# Registers the native messaging host with Chrome, Edge, Brave, and Chromium
# (registry, current user only — no admin needed). Safe to re-run any time,
# e.g. after moving this folder. Works on Windows PowerShell 5.1+.

$ErrorActionPreference = "Stop"
$ExtId = "lklbfpaopllmcbehfahbapehpadmlnel"  # fixed by the "key" in manifest.json

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir   = Split-Path -Parent $ScriptDir
$HostEntry = Join-Path $RepoDir "host\footagegrab_host.py"
$AppHome   = Join-Path $env:APPDATA "FootageGrab"
$Launcher  = Join-Path $AppHome "bin\footagegrab-host.bat"

# UTF-8 *without* BOM — Chrome rejects a BOM'd native messaging manifest,
# and PowerShell 5.1's Set-Content -Encoding utf8 writes one.
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

Write-Host "FootageGrab installer (Windows)" -ForegroundColor White

# 1. python 3 — prefer the py launcher (ships with python.org installs);
#    bare "python" may be the Microsoft Store stub, so verify the output.
$PythonExe = $null
$PythonArgs = @()
foreach ($c in @(
    @{ exe = "py";     args = @("-3") },
    @{ exe = "python"; args = @() }
)) {
    try {
        $out = & $c.exe ($c.args + @("--version")) 2>&1
        if ("$out" -match "^Python 3") { $PythonExe = $c.exe; $PythonArgs = $c.args; break }
    } catch { }
}
if (-not $PythonExe) {
    Write-Host "  ! Python 3 not found. Install it from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "    (tick 'Add python.exe to PATH' in the installer), then re-run." -ForegroundColor Yellow
    exit 1
}
$PythonCmd = ("$PythonExe " + ($PythonArgs -join " ")).Trim()
Write-Host "  + python: $PythonCmd"

# 2. yt-dlp / ffmpeg (warn only — the extension popup reports these too)
foreach ($tool in @("yt-dlp", "ffmpeg")) {
    if (Get-Command $tool -ErrorAction SilentlyContinue) {
        Write-Host "  + ${tool}: found"
    } else {
        Write-Host "  ! $tool not found - install with: winget install $tool" -ForegroundColor Yellow
    }
}

# 3. launcher (absolute paths baked in; re-run install.bat if the folder moves)
New-Item -ItemType Directory -Force -Path (Join-Path $AppHome "bin"), (Join-Path $AppHome "logs") | Out-Null
[System.IO.File]::WriteAllText($Launcher, "@echo off`r`n$PythonCmd `"$HostEntry`"`r`n", $Utf8NoBom)
Write-Host "  + launcher: $Launcher"

# 4. native messaging manifest + registry for every Chromium-based browser
$ManifestPath = Join-Path $AppHome "com.footagegrab.host.json"
$Manifest = [ordered]@{
    name            = "com.footagegrab.host"
    description     = "FootageGrab native host - runs yt-dlp/ffmpeg for the extension"
    path            = $Launcher
    type            = "stdio"
    allowed_origins = @("chrome-extension://$ExtId/")
} | ConvertTo-Json
[System.IO.File]::WriteAllText($ManifestPath, $Manifest, $Utf8NoBom)
Write-Host "  + manifest: $ManifestPath"

foreach ($root in @(
    "HKCU:\Software\Google\Chrome\NativeMessagingHosts",
    "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts",
    "HKCU:\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
    "HKCU:\Software\Chromium\NativeMessagingHosts"
)) {
    $key = "$root\com.footagegrab.host"
    New-Item -Path $key -Force | Out-Null
    Set-ItemProperty -Path $key -Name "(default)" -Value $ManifestPath
    Write-Host "  + registered: $key"
}

# 5. self-test: spawn the host through the launcher, speak native messaging
Write-Host ""
Write-Host "Self-test" -ForegroundColor White
& $PythonExe ($PythonArgs + @((Join-Path $RepoDir "host\selftest.py"), "--roundtrip", $Launcher))
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  ! self-test failed - check $AppHome\logs\host.log" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Done. Next steps:" -ForegroundColor White
Write-Host "  1. Open chrome://extensions (or edge/brave), enable Developer mode"
Write-Host "  2. 'Load unpacked' -> select: $RepoDir\extension"
Write-Host "     (the extension ID must be $ExtId - pinned by the manifest key)"
Write-Host "  3. Fully close and reopen the browser so it picks up the host"
Write-Host "  4. Open a YouTube video, press I then O then G"
Write-Host "  5. For Premiere auto-import, run install\install-premiere.bat"
