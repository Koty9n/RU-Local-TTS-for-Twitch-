# Установка Twitch TTS одним окном: uv -> Python 3.12 -> пакеты -> голоса -> GLaDOS -> ярлык.
# Ничего не ставит в систему: uv и Python лежат в tools\ рядом с программой. Повторный запуск пропускает готовое.
# Прогресс: шаг, полоска, МБ/с, сколько осталось (по счётчику сетевой карты — это почти не нагружает ПК).
param([switch]$NoPause)
$ErrorActionPreference = 'Stop'
$Root  = $PSScriptRoot
$Data  = Join-Path $Root 'data'
$Tools = Join-Path $Root 'tools'
$Log   = Join-Path $Data 'install.log'
$UvVer = '0.12.21'
$Uv    = Join-Path $Tools 'uv\uv.exe'
$Py    = Join-Path $Root 'venv\Scripts\python.exe'
New-Item -ItemType Directory -Force $Data, $Tools | Out-Null
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools 'python'
$env:UV_CACHE_DIR = Join-Path $Tools 'uv-cache'
$env:UV_LINK_MODE = 'copy'
$env:PYTHONUTF8 = '1'
$Total = 6
$script:n = 0
"`n===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') установка =====" | Add-Content $Log -Encoding UTF8

function NetBytes {
    $s = 0
    foreach ($i in [Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
        if ($i.OperationalStatus -eq 'Up' -and $i.NetworkInterfaceType -ne 'Loopback') {
            try { $s += $i.GetIPStatistics().BytesReceived } catch {}
        }
    }
    return $s
}

function Fmt([double]$sec) {
    if ($sec -lt 0 -or [double]::IsInfinity($sec) -or [double]::IsNaN($sec)) { return '—' }
    # минуты — Floor: [int] в PowerShell округляет (41 с = 0,68 мин -> «1:41»)
    $t = [TimeSpan]::FromSeconds([math]::Round($sec)); return ('{0}:{1:00}' -f [math]::Floor($t.TotalMinutes), $t.Seconds)
}

function Q([string]$s) { if ($s -match '[\s"]') { return '"' + $s.Replace('"', '\"') + '"' } return $s }

# Запускает программу, раз в секунду показывает прогресс. -ExpectMB — сколько примерно скачается.
function Run([string]$Title, [int]$ExpectMB, [string]$Exe, [string[]]$Arguments, [string]$Dir = $Root) {
    $id = $script:n
    $out = Join-Path $Data 'install_step.out'; $err = Join-Path $Data 'install_step.err'
    "`n$ $Exe $($Arguments -join ' ')" | Add-Content $Log -Encoding UTF8
    $p = Start-Process -FilePath $Exe -ArgumentList (($Arguments | ForEach-Object { Q $_ }) -join ' ') -WorkingDirectory $Dir `
        -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $p.Handle   # без этого Windows PowerShell 5.1 теряет код возврата
    $b0 = NetBytes; $t0 = Get-Date; $prevB = $b0; $prevT = $t0; $speed = 0.0
    while (-not $p.WaitForExit(1000)) {
        $b = NetBytes; $now = Get-Date
        $dt = ($now - $prevT).TotalSeconds
        if ($dt -gt 0) {
            $raw = ($b - $prevB) / $dt
            $speed = if ($speed -eq 0) { $raw } else { 0.7 * $speed + 0.3 * $raw }   # сглаживаем, чтобы цифры не прыгали
        }
        $prevB = $b; $prevT = $now
        $done = [math]::Max(0, ($b - $b0) / 1MB)
        $mbs = $speed / 1MB
        $pct = -1
        $within = $ExpectMB -gt 0 -and $done -lt $ExpectMB
        if ($within) {          # пока в пределах оценки: «N из ~M», полоска и сколько осталось
            $status = ('{0:N0} из ~{1} МБ · {2:N1} МБ/с' -f $done, $ExpectMB, $mbs)
            $pct = [int][math]::Min(99, 100 * $done / $ExpectMB)
            # «осталось» — по средней скорости за шаг: в паузах (распаковка, проверка) мгновенная падает до нуля
            $avg = $done / [math]::Max(1, ($now - $t0).TotalSeconds)
            if ($avg -gt 0.05) { $status += ' · осталось ~' + (Fmt (($ExpectMB - $done) / $avg)) }
        }
        else {                  # оценки нет или её превысили (счётчик общий на ПК: чужие загрузки тоже в нём)
            $status = ('скачано {0:N0} МБ · {1:N1} МБ/с' -f $done, $mbs)
            if ($ExpectMB -gt 0) { $status += ' · почти готово'; $pct = 99 }
        }
        $status += ' · прошло ' + (Fmt ($now - $t0).TotalSeconds)
        if ($pct -ge 0) { Write-Progress -Id 1 -Activity "Шаг $id из ${Total}: $Title" -Status $status -PercentComplete $pct }
        else { Write-Progress -Id 1 -Activity "Шаг $id из ${Total}: $Title" -Status $status }
    }
    $p.WaitForExit()
    Write-Progress -Id 1 -Activity $Title -Completed
    foreach ($f in $out, $err) { if (Test-Path $f) { Get-Content $f -Encoding UTF8 | Add-Content $Log -Encoding UTF8; Remove-Item $f -Force } }
    if ($p.ExitCode -ne 0) { throw "$Title — ошибка (код $($p.ExitCode)). Подробности: data\install.log" }
    # «скачано» не пишем: счётчик сети общий на весь ПК и считает чужие загрузки тоже
    Write-Host ('      готово за {0}' -f (Fmt ((Get-Date) - $t0).TotalSeconds)) -ForegroundColor DarkGray
}

function Head([string]$Title) {
    $script:n++
    Write-Host ''
    Write-Host ("[$($script:n)/$Total] $Title") -ForegroundColor Cyan
}

function Skip([string]$Why) { Write-Host "      уже есть — $Why" -ForegroundColor DarkGray }

function PyOk([string]$Code) {
    if (-not (Test-Path $Py)) { return $false }
    $ErrorActionPreference = 'Continue'   # в PS 5.1 вывод в stderr при 'Stop' сам становится ошибкой
    & $Py -c $Code 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

try {
    Write-Host 'Twitch TTS — установка. Окно можно не трогать: всё скачается само (~1 ГБ, нужен интернет).' -ForegroundColor White
    $needEnv = -not (Test-Path $Py)

    Head 'Установщик пакетов uv'
    if (-not $needEnv) { Skip 'окружение venv уже создано' }
    elseif (Test-Path $Uv) { Skip 'tools\uv' }
    else {
        $zip = Join-Path $Tools 'uv.zip'
        Run 'uv' 17 'curl.exe' @('-L', '--fail', '-sS', '-o', $zip, "https://github.com/astral-sh/uv/releases/download/$UvVer/uv-x86_64-pc-windows-msvc.zip")
        Expand-Archive -Path $zip -DestinationPath (Join-Path $Tools 'uv') -Force
        Remove-Item $zip -Force
    }

    Head 'Python 3.12 (в папку программы, не в систему)'
    if (-not $needEnv) { Skip 'окружение venv уже создано' }
    else {
        Run 'Python 3.12' 25 $Uv @('python', 'install', '3.12')
        Run 'окружение venv' 0 $Uv @('venv', (Join-Path $Root 'venv'), '--python', '3.12', '--managed-python', '--seed')
    }

    Head 'Пакеты: Piper, ударения, GLaDOS'
    $base = 'import sounddevice, numpy, piper, ruaccent'
    $teraOld = Test-Path (Join-Path $Root 'venv_tera\Lib\site-packages\TeraTTS')   # установки до v3.7
    if ((PyOk "$base, TeraTTS") -or ($teraOld -and (PyOk $base))) { Skip 'все пакеты импортируются' }
    else {
        $req = Join-Path $Root 'requirements.lock'
        if (-not (Test-Path $req)) { $req = Join-Path $Root 'requirements.txt' }
        # ~180 МБ — сжатые пакеты (замерено на чистой установке); в распакованном виде venv ~530 МБ
        if (Test-Path $Uv) { Run 'пакеты' 180 $Uv @('pip', 'install', '--python', $Py, '-r', $req) }
        else { Run 'пакеты' 180 $Py @('-m', 'pip', 'install', '-r', $req) }
        if (-not (PyOk "$base, TeraTTS")) { throw 'Пакеты поставились, но не импортируются. Подробности: data\install.log' }
    }

    Head 'Голоса: выбор и загрузка'
    # выбор — окно voice_picker.py (один раз; ответ в data\voices.choice). Окно не открылось — берём все голоса.
    $catalog = 'GLaDOS', 'IGM', 'Mari', 'Women', 'Сказочник'
    $choiceFile = Join-Path $Data 'voices.choice'
    if (-not (Test-Path $choiceFile)) {
        Write-Host '      выбор голосов (окно откроется, если что-то ещё не скачано)…' -ForegroundColor DarkGray
        try { Run 'выбор голосов' 0 $Py @('-X', 'utf8', (Join-Path $Root 'voice_picker.py'), '--installer', $Data, $Root) }
        catch { Write-Host "      окно выбора не открылось — ставлю все голоса ($_)" -ForegroundColor Yellow }
        if (-not (Test-Path $choiceFile)) { (@('# все голоса (окно выбора не открылось)') + $catalog) | Set-Content $choiceFile -Encoding UTF8 }
    }
    $chosen = @(Get-Content $choiceFile -Encoding UTF8 | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
    Write-Host ('      выбрано: ' + ($chosen -join ', ')) -ForegroundColor DarkGray
    $piper = @($chosen | Where-Object { $_ -ne 'GLaDOS' })
    $miss = @($piper | Where-Object { -not (Test-Path (Join-Path $Root "voices\$_.onnx")) })
    if ($piper.Count -eq 0) { Skip 'голоса Piper не выбраны' }
    elseif ($miss.Count -eq 0) { Skip ('выбранные голоса Piper: ' + ($piper -join ', ')) }
    else {
        try { Run 'голоса' (61 * $miss.Count) $Py (@('-X', 'utf8', (Join-Path $Root 'install_voices.py'), (Join-Path $Root 'voices')) + $miss) }
        catch { Write-Host "      часть голосов не скачалась — докачать: «Голоса» → «Скачать голоса…» ($_)" -ForegroundColor Yellow }
    }

    Head 'GLaDOS и ударения'
    $teraDir = Join-Path $Data 'tera'
    $accDir = Join-Path $Data 'ruaccent'
    New-Item -ItemType Directory -Force $teraDir | Out-Null
    $accOk = Test-Path (Join-Path $accDir 'nn\nn_omograph')
    if ($chosen -contains 'GLaDOS') {
        if (-not ((PyOk 'import TeraTTS') -or (Test-Path (Join-Path $Root 'venv_tera\Lib\site-packages\TeraTTS')))) {
            throw 'GLaDOS выбрана, но движок TeraTTS не установился (шаг 3). Подробности: data\install.log'
        }
        if (Test-Path (Join-Path $teraDir 'model\TeraTTS\glados2-g2p-vits\exported\model.onnx')) { Skip 'модель GLaDOS' }
        else {
            $tp = if (PyOk 'import TeraTTS') { $Py } else { Join-Path $Root 'venv_tera\Scripts\python.exe' }
            try {
                # модель GLaDOS ~210 МБ + ударения ~355 (data\ruaccent 165 + ruaccent\koziev 189), если их ещё нет
                Run 'GLaDOS' $(if ($accOk) { 210 } else { 565 }) $tp @('-X', 'utf8', (Join-Path $Root 'tera_worker.py'), 'TeraTTS/glados2-g2p-vits', 'tiny2', '--warmup') $teraDir
                'done' | Set-Content (Join-Path $Data 'glados_tried.flag') -Encoding ASCII
            }
            catch { Write-Host "      GLaDOS не поставилась — остальные голоса работают. Повтор: кнопка в программе ($_)" -ForegroundColor Yellow }
        }
    }
    else { Skip 'GLaDOS не выбрана' }
    # ударения нужны любому голосу; GLaDOS качает их сама, но если её модель уже была (или GLaDOS не выбрана),
    # докачиваем здесь — чтобы программа не качала ~355 МБ молча при первом запуске
    if (Test-Path (Join-Path $accDir 'nn\nn_omograph')) { Skip 'ударения' }
    else {
        Write-Host '      качаю модели ударений' -ForegroundColor DarkGray
        try { Run 'ударения' 355 $Py @('-X', 'utf8', (Join-Path $Root 'accent.py'), '--download', $accDir) }
        catch { Write-Host "      ударения не скачались — программа скачает их сама при запуске ($_)" -ForegroundColor Yellow }
    }

    Head 'Ярлык на рабочем столе'
    if (Test-Path (Join-Path $Data 'shortcut.flag')) { Skip 'ярлык уже создавали' }
    else {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'make_shortcut.ps1') -Root $Root | Out-Null
        'done' | Set-Content (Join-Path $Data 'shortcut.flag') -Encoding ASCII
        Write-Host '      готово' -ForegroundColor DarkGray
    }

    if (-not (Test-Path (Join-Path $Root 'config.json')) -and (Test-Path (Join-Path $Root 'config.example.json'))) {
        Copy-Item (Join-Path $Root 'config.example.json') (Join-Path $Root 'config.json')
    }
    if (Test-Path $env:UV_CACHE_DIR) {   # кеш загрузок больше не нужен — освобождаем место
        Remove-Item $env:UV_CACHE_DIR -Recurse -Force -ErrorAction SilentlyContinue
    }
    '3.7' | Set-Content (Join-Path $Data 'installed.flag') -Encoding ASCII
    Write-Host ''
    Write-Host 'Готово! Программа установлена.' -ForegroundColor Green
    exit 0
}
catch {
    Write-Progress -Id 1 -Activity 'установка' -Completed
    Write-Host ''
    Write-Host "Установка не завершена: $_" -ForegroundColor Red
    Write-Host 'Последние строки журнала (data\install.log):' -ForegroundColor DarkGray
    Get-Content $Log -Tail 15 -Encoding UTF8 | ForEach-Object { Write-Host "   $_" -ForegroundColor DarkGray }
    Write-Host 'Проверь интернет и запусти start_tts.bat ещё раз — готовые шаги пропустятся.'
    if (-not $NoPause) { Read-Host 'Нажми Enter, чтобы закрыть' | Out-Null }
    exit 1
}
