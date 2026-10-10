@echo off
rem YouTube downloader - run without arguments for the menu
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0download.ps1" %*
