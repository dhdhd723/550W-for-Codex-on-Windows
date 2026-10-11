@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0main.py" --diagnose
    pause
    exit /b
)
if exist "%~dp0dist\Codex550CLauncher\Codex550CLauncher.exe" (
    start "" "%~dp0dist\Codex550CLauncher\Codex550CLauncher.exe" --diagnose
    echo Diagnostic output: %%LOCALAPPDATA%%\Codex550CLauncher\diagnostics.json
    pause
    exit /b
)
echo Run Install.cmd or Build.cmd first.
pause
