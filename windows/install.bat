@echo off
REM Double-click this to install. It only bypasses the execution policy for
REM this one script, rather than changing anything on the machine.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
