@echo off
rem Download / update yt-dlp.exe and ffmpeg into the bin folder
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
pause
