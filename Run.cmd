@echo off
if exist "%~dp0dist\Codex550CLauncher\Codex550CLauncher.exe" (
    start "" "%~dp0dist\Codex550CLauncher\Codex550CLauncher.exe" %*
    exit /b
)
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Run Install.cmd or Build.cmd first.
    pause
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py" %*
