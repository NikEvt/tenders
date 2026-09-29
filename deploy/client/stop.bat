@echo off
rem ASCII only, no chcp. Reason is in _common.ps1: cmd.exe recomputes byte
rem offsets by the active code page, so Cyrillic text plus "chcp 65001" makes
rem it resume parsing mid-word and fail with "'m' is not recognized".
rem All messages live in the PowerShell script this launcher calls.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
if errorlevel 9009 (
    echo PowerShell not found. Open PowerShell manually and run: .\stop.ps1
    pause
)
