@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Проверка звучания GLaDOS: WAV-варианты («р» как есть / удвоенная, скорость 1.0 / 1.1 / 1.2) в data\glados_test
set "PY=%~dp0venv\Scripts\python.exe"
if not exist "%~dp0venv\Lib\site-packages\TeraTTS" if exist "%~dp0venv_tera\Scripts\python.exe" set "PY=%~dp0venv_tera\Scripts\python.exe"
if not exist "%PY%" (
    echo Программа ещё не установлена — сначала запусти start_tts.bat
    pause
    exit /b 1
)
if not exist data\tera mkdir data\tera
echo Делаю проверочные WAV-файлы...
pushd data\tera
"%PY%" -X utf8 "%~dp0tera_worker.py" TeraTTS/glados2-g2p-vits tiny2 --variants
popd
echo.
echo Готово. Послушай файлы в data\glados_test
echo Если вариант r-double звучит лучше, поставь в config.json:  "tera_r_fix": "double"
start "" "%~dp0data\glados_test"
pause
