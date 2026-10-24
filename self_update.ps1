# Самообновление RU Local TTS for Twitch. Запускается самой программой (updater.start_update) после согласия пользователя:
#   powershell -File self_update.ps1 -Target <папка программы> -Url <ссылка на zip> -Version <версия> -WaitPid <PID программы>
# Что делает: ждёт закрытия программы -> скачивает архив -> копирует новый код в папку программы -> запускает программу снова.
# НЕ трогает: config.json (вход в Twitch, настройки), data\ (свои файлы), voices, venv, venv_tera, tools, _backup.
# Старый код кладётся в _backup\обновление_<дата>; если замена оборвалась — файлы возвращаются назад сами.
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Url,
    [string]$Version = '',
    [int]$WaitPid = 0
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # без этого Invoke-WebRequest в Windows PowerShell качает в разы медленнее
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Title = 'Обновление RU Local TTS for Twitch'
$Tmp = $null
$Backup = $null
$done = New-Object System.Collections.Generic.List[string]    # файлы, которые уже заменены (для отката)
$added = New-Object System.Collections.Generic.List[string]   # файлы, которых раньше не было

# ---- маленькое окно с ходом обновления ----
$form = New-Object System.Windows.Forms.Form -Property @{
    Text = $Title; Width = 440; Height = 150; StartPosition = 'CenterScreen'; TopMost = $true
    FormBorderStyle = 'FixedDialog'; MaximizeBox = $false; MinimizeBox = $false; ControlBox = $false }
$lbl = New-Object System.Windows.Forms.Label -Property @{ Left = 16; Top = 16; Width = 400; Height = 40; Text = 'Подготовка…' }
$bar = New-Object System.Windows.Forms.ProgressBar -Property @{ Left = 16; Top = 66; Width = 400; Height = 18; Style = 'Marquee' }
$form.Controls.AddRange(@($lbl, $bar))
$form.Show()
function Step($text) { $lbl.Text = $text; [System.Windows.Forms.Application]::DoEvents() }
function Msg($text, $icon = 'Information') {
    [void][System.Windows.Forms.MessageBox]::Show($form, $text, $Title, 'OK', $icon)
}
function Log($text) {
    try { Add-Content -LiteralPath (Join-Path $Target 'data\update.log') -Encoding UTF8 -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm')  $text" } catch {}
}
function Hash($f) { if (Test-Path -LiteralPath $f) { (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash } else { '' } }
function Rollback {
    foreach ($rel in $done) {
        $b = Join-Path $Backup $rel
        if (Test-Path -LiteralPath $b) { Copy-Item -LiteralPath $b -Destination (Join-Path $Target $rel) -Force }
    }
    foreach ($rel in $added) { Remove-Item -LiteralPath (Join-Path $Target $rel) -Force -ErrorAction SilentlyContinue }
}

try {
    $Target = (Resolve-Path -LiteralPath $Target).Path.TrimEnd('\')
    if (-not (Test-Path -LiteralPath (Join-Path $Target 'tts_core.py'))) { throw "В папке нет программы: $Target" }
    $oldVer = if (Test-Path -LiteralPath (Join-Path $Target 'version.txt')) {
        (Get-Content -LiteralPath (Join-Path $Target 'version.txt') -TotalCount 1 -Encoding UTF8).Trim() } else { '?' }

    # ---- 1. ждём, пока программа закроется ----
    Step 'Жду закрытия программы…'
    if ($WaitPid -gt 0) {
        $p = Get-Process -Id $WaitPid -ErrorAction SilentlyContinue
        if ($p) { [void]$p.WaitForExit(30000) }
    }
    # остатки программы (движок GLaDOS и т.п.) из этой же папки
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Target, 'OrdinalIgnoreCase')) -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($Target, [StringComparison]::OrdinalIgnoreCase) -ge 0) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1

    # ---- 2. скачиваем ----
    Step "Скачиваю версию $Version…"
    $Tmp = Join-Path $env:TEMP ('TTS_update_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
    $zip = Join-Path $Tmp 'new.zip'
    Invoke-WebRequest -Uri $Url -OutFile $zip -UseBasicParsing -Headers @{ 'User-Agent' = 'RU-Local-TTS-updater' }
    if ((Get-Item -LiteralPath $zip).Length -lt 10000) { throw 'Скачался слишком маленький файл — это не архив программы.' }

    Step 'Распаковываю…'
    $ex = Join-Path $Tmp 'x'
    Expand-Archive -LiteralPath $zip -DestinationPath $ex -Force
    $core = Get-ChildItem -LiteralPath $ex -Recurse -Filter 'tts_core.py' -File | Select-Object -First 1
    if (-not $core) { throw 'В скачанном архиве нет программы (tts_core.py).' }
    $Src = $core.DirectoryName.TrimEnd('\')
    $newVer = if (Test-Path -LiteralPath (Join-Path $Src 'version.txt')) {
        (Get-Content -LiteralPath (Join-Path $Src 'version.txt') -TotalCount 1 -Encoding UTF8).Trim() } else { $Version }

    # ---- 3. заменяем код ----
    Step 'Обновляю файлы…'
    $oldLock = Hash (Join-Path $Target 'requirements.lock')
    $Backup = Join-Path $Target ('_backup\обновление_' + (Get-Date -Format 'yyyy-MM-dd_HH-mm'))
    $copied = 0
    foreach ($f in Get-ChildItem -LiteralPath $Src -Recurse -File) {
        $rel = $f.FullName.Substring($Src.Length + 1)
        if ($rel -match '^(venv|venv_tera|voices|tools|_backup|docs|\.git|\.github)(\\|$)' -or $rel -ieq 'config.json' -or $rel -ieq '.gitignore') { continue }
        $dst = Join-Path $Target $rel
        if ($rel -like 'data\*' -and (Test-Path -LiteralPath $dst)) { continue }   # свои файлы в data не трогаем, берём только новые
        if (Test-Path -LiteralPath $dst) {
            $b = Join-Path $Backup $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $b) | Out-Null
            Copy-Item -LiteralPath $dst -Destination $b -Force
            $done.Add($rel)
        } else { $added.Add($rel) }
        New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
        Copy-Item -LiteralPath $f.FullName -Destination $dst -Force
        $copied++
    }

    # ---- 4. поменялся список библиотек — доставляем ----
    if ((Hash (Join-Path $Target 'requirements.lock')) -ne $oldLock) {
        Step 'Докачиваю библиотеки (может занять пару минут)…'
        $py = Join-Path $Target 'venv\Scripts\python.exe'
        if (Test-Path -LiteralPath $py) {
            & $py -m pip install --disable-pip-version-check -r (Join-Path $Target 'requirements.lock') 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Log 'pip: библиотеки не докачались'
                Msg "Код обновлён, но новые библиотеки не докачались (нет интернета?).`nЗапусти start_tts.bat при работающем интернете — недостающее поставится." 'Warning'
            }
        }
    }

    Log "$oldVer -> $newVer  (файлов: $copied, бэкап: $Backup)"
    try { Set-Content -LiteralPath (Join-Path $Target 'data\updated.flag') -Value $newVer -Encoding UTF8 } catch {}

    # ---- 5. запускаем программу ----
    Step 'Готово, запускаю программу…'
    Start-Process -FilePath (Join-Path $Target 'start_tts.bat') -WorkingDirectory $Target
    Start-Sleep -Seconds 1
    exit 0
} catch {
    $err = $_.Exception.Message
    try { if ($Backup) { Rollback } } catch {}
    Log "ОШИБКА обновления: $err"
    Msg ("Обновление не удалось:`n$err`n`nПрограмма осталась прежней версии (файлы возвращены). " +
         "Можно обновиться вручную: скачай архив со страницы проекта и запусти ОБНОВИТЬ.bat.") 'Error'
    try { Start-Process -FilePath (Join-Path $Target 'start_tts.bat') -WorkingDirectory $Target } catch {}
    exit 1
} finally {
    try { $form.Close() } catch {}
    if ($Tmp -and (Test-Path -LiteralPath $Tmp)) { Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue }
}
