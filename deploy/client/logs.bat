@echo off
rem ASCII only, no chcp - see the comment in start.bat.
rem Usage: logs.bat            all services
rem        logs.bat crawler    one service
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0logs.ps1" %*
if errorlevel 9009 (
    echo PowerShell not found. Open PowerShell manually and run: .\logs.ps1
    pause
)
