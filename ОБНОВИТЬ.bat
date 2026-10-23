@echo off
rem TwitchTTS updater. Keep it on one line: this file may be replaced while updating.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" & exit /b
