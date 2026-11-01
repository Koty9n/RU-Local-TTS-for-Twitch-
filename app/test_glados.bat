@echo off
chcp 65001 >nul
rem лежит в app\ — работаем из корня программы
cd /d "%~dp0.."
set "ROOT=%CD%\"
rem Проверка звучания GLaDOS: WAV-варианты («р» как есть / удвоенная, скорость 1.0 / 1.1 / 1.2) в data\glados_test
set "PY=%ROOT%venv\Scripts\python.exe"
if not exist "%ROOT%venv\Lib\site-packages\TeraTTS" if exist "%ROOT%venv_tera\Scripts\python.exe" set "PY=%ROOT%venv_tera\Scripts\python.exe"
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
start "" "%ROOT%data\glados_test"
pause
