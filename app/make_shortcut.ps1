param([string]$Root)
$Root = $Root.TrimEnd('\')
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $desktop 'TwitchTTS.lnk'
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk)
$exe = Join-Path $Root 'TwitchTTS.exe'
if (Test-Path $exe) {
    $s.TargetPath = $exe
    $s.Arguments = ''
} else {
    $s.TargetPath = Join-Path $Root 'venv\Scripts\pythonw.exe'
    $s.Arguments = '"' + (Join-Path $Root 'app\tts_app.py') + '"'
}
$s.WorkingDirectory = $Root
$s.IconLocation = (Join-Path $Root 'app\assets\icon.ico') + ',0'
$s.Description = 'Twitch TTS'
$s.Save()
Write-Output ('Shortcut created: ' + $lnk)
