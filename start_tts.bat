@echo off
chcp 65001 >nul
set "ROOT=%~dp0"
cd /d "%ROOT%"
if not exist "%ROOT%data" mkdir "%ROOT%data"

rem ---- установка: первый запуск или чего-то не хватает. Всё в одном окне с прогрессом (install.ps1).
rem      Готовые шаги пропускаются, поэтому старые установки просто проверяются.
rem      Проверка — только по файлам, без запуска Python, чтобы обычный старт был мгновенным.
if not exist "%ROOT%data\installed.flag" goto :install
if not exist "%ROOT%venv\Scripts\pythonw.exe" goto :install
if exist "%ROOT%venv\Lib\site-packages\TeraTTS" goto :run
if exist "%ROOT%venv_tera\Lib\site-packages\TeraTTS" goto :run
rem      движка GLaDOS нигде нет (например, удалили venv_tera): ставим, если GLaDOS выбрана при установке
if exist "%ROOT%data\voices.choice" findstr /x /c:"GLaDOS" "%ROOT%data\voices.choice" >nul || goto :run

:install
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%install.ps1"
if errorlevel 1 goto :fail
echo.
echo ============================================================
echo  Приложение установлено.
echo  Нажмите любую кнопку, чтобы запустить...
echo ============================================================
pause >nul

:run
start "" "%ROOT%venv\Scripts\pythonw.exe" "%ROOT%tts_app.py"
exit /b 0

:fail
echo.
echo Установка не завершена. Проверь интернет и запусти start_tts.bat ещё раз — готовые шаги пропустятся.
echo Подробности: data\install.log
pause
exit /b 1
