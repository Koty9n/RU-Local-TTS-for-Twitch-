# Обновлялка TwitchTTS. Запускается через ОБНОВИТЬ.bat:
#  - из папки, где программа уже стоит: берёт свежий TwitchTTS*.zip из «Загрузок»/рабочего стола (или спросит файл);
#  - из распакованного нового архива (первый раз, когда в старой версии обновлялки ещё нет): спросит старую папку.
# Меняет только код и документацию. НЕ трогает: config.json (вход в Twitch), data\ (словари, списки, муты),
# голоса, venv. Готовые списки data\*_twitch.txt копируются, только если их ещё нет (их могли поправить руками).
# Старый код кладётся в _backup\обновление_<дата> внутри папки программы.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$Title = 'Обновление TwitchTTS'
$Here = $PSScriptRoot
$Owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true }   # окна — поверх консоли
$Tmp = $null

function Ask($text, $buttons = 'YesNo', $icon = 'Question') {
    [string][System.Windows.Forms.MessageBox]::Show($Owner, $text, $Title, $buttons, $icon)
}
function Fail($text) { [void](Ask $text 'OK' 'Error'); exit 1 }
function IsInstalled($d) { $d -and (Test-Path -LiteralPath (Join-Path $d 'tts_core.py')) -and (Test-Path -LiteralPath (Join-Path $d 'venv\Scripts\python.exe')) }
function IsSource($d) { $d -and (Test-Path -LiteralPath (Join-Path $d 'tts_core.py')) }
function Ver($d) {
    $f = Join-Path $d 'version.txt'
    if (Test-Path -LiteralPath $f) { (Get-Content -LiteralPath $f -TotalCount 1 -Encoding UTF8).Trim() } else { 'старая (до 23.10.2026)' }
}
function PickFolder($text) {
    $fb = New-Object System.Windows.Forms.FolderBrowserDialog
    $fb.Description = $text
    if ($fb.ShowDialog($Owner) -ne 'OK') { exit 0 }
    $fb.SelectedPath
}
function Hash($f) { if (Test-Path -LiteralPath $f) { (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash } else { '' } }

try {
    Write-Host 'Обновление TwitchTTS' -ForegroundColor White
    # ---- откуда и куда ----
    if (IsInstalled $Here) {
        $Target = $Here
        $dirs = @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:USERPROFILE 'Downloads'))
        try { $dl = (New-Object -ComObject Shell.Application).NameSpace('shell:Downloads').Self.Path; if ($dl) { $dirs += $dl } } catch {}
        $zip = $dirs | Select-Object -Unique | Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
            ForEach-Object { Get-ChildItem -LiteralPath $_ -Filter 'TwitchTTS*.zip' -File -ErrorAction SilentlyContinue } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        $Src = $null
        if ($zip) {
            $r = Ask ("Нашёл архив:`n$($zip.FullName)`n(скачан $($zip.LastWriteTime.ToString('dd.MM.yyyy HH:mm')))`n`n" +
                      "Обновить из него?`n`n«Нет» — выбрать другой файл.") 'YesNoCancel'
            if ($r -eq 'Cancel') { exit 0 }
            if ($r -eq 'Yes') { $Src = $zip.FullName }
        }
        if (-not $Src) {
            $dlg = New-Object System.Windows.Forms.OpenFileDialog
            $dlg.Title = 'Выбери скачанный TwitchTTS.zip («Отмена» — выбрать уже распакованную папку)'
            $dlg.Filter = 'Архив TwitchTTS (*.zip)|*.zip'
            if ($dlg.ShowDialog($Owner) -eq 'OK') { $Src = $dlg.FileName }
            else { $Src = PickFolder 'Выбери распакованную папку с НОВОЙ версией TwitchTTS' }
        }
    } else {
        if (-not (IsSource $Here)) { Fail "Рядом с обновлялкой нет файлов программы.`nЗапусти ОБНОВИТЬ.bat из папки TwitchTTS." }
        $Src = $Here
        [void](Ask ("Сейчас выбери папку, где у тебя УЖЕ стоит TwitchTTS`n(в ней есть start_tts.bat и папка venv).`n`n" +
                    "Если программа ещё не установлена — закрой это окно и просто запусти start_tts.bat.") 'OK' 'Information')
        $Target = PickFolder 'Папка, где уже установлен TwitchTTS'
        if (-not (IsInstalled $Target)) {
            Fail "В этой папке нет установленной программы (нет tts_core.py или venv):`n$Target"
        }
    }

    # ---- распаковка ----
    if ((Test-Path -LiteralPath $Src -PathType Leaf) -and $Src -like '*.zip') {
        Write-Host "Распаковываю $Src"
        $Tmp = Join-Path $env:TEMP ('TwitchTTS_update_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
        Expand-Archive -LiteralPath $Src -DestinationPath $Tmp -Force
        $SrcRoot = Get-ChildItem -LiteralPath $Tmp -Recurse -Filter 'tts_core.py' -File | Select-Object -First 1 | ForEach-Object { $_.DirectoryName }
    } else { $SrcRoot = $Src }
    if (-not (IsSource $SrcRoot)) { Fail 'Это не архив TwitchTTS: внутри нет tts_core.py.' }
    $SrcRoot = (Resolve-Path -LiteralPath $SrcRoot).Path.TrimEnd('\')
    $Target = (Resolve-Path -LiteralPath $Target).Path.TrimEnd('\')
    if ($SrcRoot -eq $Target) { Fail 'Выбрана та же самая папка, где стоит программа. Нужен новый скачанный архив.' }

    $newVer, $oldVer = (Ver $SrcRoot), (Ver $Target)
    $r = Ask ("Обновить TwitchTTS?`n`nПапка: $Target`nСейчас: $oldVer`nНовая: $newVer`n`n" +
              "Настройки, вход в Twitch, словари, списки и голоса сохранятся.")
    if ($r -ne 'Yes') { exit 0 }

    # ---- программа запущена? ----
    $procs = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Target, 'OrdinalIgnoreCase')) -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($Target, [StringComparison]::OrdinalIgnoreCase) -ge 0) })
    if ($procs.Count) {
        $r = Ask "Программа TwitchTTS сейчас запущена.`nЗакрыть её и обновить?`n`n(Если идёт стрим — лучше «Нет» и обновиться после.)"
        if ($r -ne 'Yes') { exit 0 }
        $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 2
    }

    # ---- бэкап и замена ----
    $oldLock = Hash (Join-Path $Target 'requirements.lock')
    $Backup = Join-Path $Target ('_backup\обновление_' + (Get-Date -Format 'yyyy-MM-dd_HH-mm'))
    $copied = 0; $kept = 0
    foreach ($f in Get-ChildItem -LiteralPath $SrcRoot -Recurse -File) {
        $rel = $f.FullName.Substring($SrcRoot.Length + 1)
        if ($rel -match '^(venv|venv_tera|voices|tools|_backup)\\' -or $rel -ieq 'config.json') { continue }
        $dst = Join-Path $Target $rel
        if ($rel -like 'data\*' -and (Test-Path -LiteralPath $dst)) { $kept++; continue }   # data — только новое
        if (Test-Path -LiteralPath $dst) {
            $b = Join-Path $Backup $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $b) | Out-Null
            Copy-Item -LiteralPath $dst -Destination $b -Force
        }
        New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
        Copy-Item -LiteralPath $f.FullName -Destination $dst -Force
        $copied++
    }
    Write-Host "Обновлено файлов: $copied. Свои файлы в data не тронуты: $kept."

    # ---- поменялись библиотеки — доставляем ----
    if ((Hash (Join-Path $Target 'requirements.lock')) -ne $oldLock) {
        Write-Host 'Поменялся список библиотек — докачиваю (нужен интернет)…' -ForegroundColor Yellow
        $py = Join-Path $Target 'venv\Scripts\python.exe'
        & $py -m pip install --disable-pip-version-check -r (Join-Path $Target 'requirements.lock')
        if ($LASTEXITCODE -ne 0) {
            [void](Ask "Код обновлён, но библиотеки не докачались (нет интернета?).`nЗапусти ОБНОВИТЬ.bat ещё раз позже." 'OK' 'Warning')
        }
    }

    try {
        Add-Content -LiteralPath (Join-Path $Target 'data\update.log') -Encoding UTF8 -Value (
            "$(Get-Date -Format 'yyyy-MM-dd HH:mm')  $oldVer -> $newVer  (файлов: $copied, бэкап: $Backup)")
    } catch {}

    $tail = if ($Src -eq $Here) { "`n`nЭту распакованную папку можно удалить. В следующий раз просто запусти ОБНОВИТЬ.bat в папке программы." } else { '' }
    $r = Ask ("Готово! TwitchTTS обновлён до версии $newVer.`nСтарый код сохранён в:`n$Backup$tail`n`nЗапустить программу?")
    if ($r -eq 'Yes') { Start-Process -FilePath (Join-Path $Target 'start_tts.bat') -WorkingDirectory $Target }
    exit 0
} catch {
    Fail ("Обновление не удалось:`n$($_.Exception.Message)`n`nПрограмма не сломана: если часть файлов успела замениться, " +
          "старые лежат в папке _backup внутри программы.")
} finally {
    if ($Tmp -and (Test-Path -LiteralPath $Tmp)) { Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue }
}
