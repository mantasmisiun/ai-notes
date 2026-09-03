@echo off
REM Try a different live transcription model; it is kept only if it keeps up here.
cd /d "%~dp0.."
capture\venv\Scripts\python.exe switch_model.py %*
pause
