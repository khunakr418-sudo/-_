@echo off
rem Open the YouTube Downloader window (needs Python 3 with tkinter)
where pyw >nul 2>nul && (start "" pyw -3 "%~dp0gui.pyw" & exit /b 0)
where pythonw >nul 2>nul && (start "" pythonw "%~dp0gui.pyw" & exit /b 0)
echo Python 3 was not found. Install it from https://www.python.org/downloads/
pause
