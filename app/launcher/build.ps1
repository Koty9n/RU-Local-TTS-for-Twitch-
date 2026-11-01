# Builds TwitchTTS.exe (launcher) into the program root. Run: powershell -ExecutionPolicy Bypass -File app\launcher\build.ps1
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path   # app\launcher
$app = Split-Path -Parent $here
$root = Split-Path -Parent $app
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
if (-not (Test-Path $csc)) { throw 'csc.exe (.NET Framework 4) not found' }
& $csc /nologo /codepage:65001 /target:winexe /optimize+ `
    "/win32icon:$app\assets\icon.ico" "/out:$root\TwitchTTS.exe" `
    /reference:System.Windows.Forms.dll "$here\TwitchTTS.cs"
if ($LASTEXITCODE -ne 0) { throw "csc failed: $LASTEXITCODE" }
Write-Host "OK: $root\TwitchTTS.exe"
