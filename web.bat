@echo off
rem Start the YouTube Downloader web page at http://127.0.0.1:8765 (close this window to stop)
title YouTube Downloader (web)
where py >nul 2>nul && (py -3 "%~dp0web.py" %* & goto :end)
where python >nul 2>nul && (python "%~dp0web.py" %* & goto :end)
echo Python 3 was not found. Install it from https://www.python.org/downloads/
:end
pause
