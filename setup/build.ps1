# Builds TwitchTTS-Setup-<ver>.exe. Needs Inno Setup 6 (winget install JRSoftware.InnoSetup) and git.
#   powershell -ExecutionPolicy Bypass -File setup\build.ps1            -> code from git HEAD
#   powershell -ExecutionPolicy Bypass -File setup\build.ps1 -Src <dir>  -> code from a ready folder
# Output: dist\TwitchTTS-Setup-<ver>.exe (attach it to the GitHub release NEXT TO the .zip: auto-update downloads the zip).
param([string]$Src = '', [string]$OutDir = '')
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
if (-not $OutDir) { $OutDir = Join-Path $repo 'dist' }
New-Item -ItemType Directory -Force $OutDir | Out-Null

if (-not $Src) {
    $Src = Join-Path $OutDir 'src'
    if (Test-Path $Src) { Remove-Item $Src -Recurse -Force }
    $zip = Join-Path $OutDir 'src.zip'
    git -C $repo archive --format=zip -o $zip HEAD
    if ($LASTEXITCODE -ne 0) { throw 'git archive failed' }
    Expand-Archive $zip $Src; Remove-Item $zip
}
$Src = (Resolve-Path $Src).Path

# TwitchTTS.exe is committed to the repo root; build it from app\launcher only if it is missing
if (-not (Test-Path (Join-Path $Src 'TwitchTTS.exe'))) { & (Join-Path $Src 'app\launcher\build.ps1') }

$line = (Get-Content (Join-Path $Src 'version.txt') -TotalCount 1 -Encoding UTF8).Trim()
$ver = ($line -split '\s+')[0]
if ($line -match '(\d+)\.(\d+)') { $num = "$($Matches[1]).$($Matches[2]).0.0" } else { $num = '0.0.0.0' }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 not found: winget install JRSoftware.InnoSetup' }
& $iscc /Q "/DSrc=$Src" "/DAppVer=$ver" "/DNumVer=$num" "/O$OutDir" (Join-Path $here 'TwitchTTS.iss')
if ($LASTEXITCODE -ne 0) { throw "ISCC failed: $LASTEXITCODE" }
Write-Host "OK: $OutDir\TwitchTTS-Setup-$ver.exe"
