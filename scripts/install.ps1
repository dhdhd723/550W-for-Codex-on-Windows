[CmdletBinding()]
param([string]$Python = '')
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE): $Executable" }
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    if (-not $Python) {
        $pyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($pyCommand) {
            $detected = & $pyCommand.Source -3 -c 'import sys; print(sys.executable)'
            if ($LASTEXITCODE -eq 0) { $Python = ($detected | Select-Object -Last 1).Trim() }
        }
    }
    if (-not $Python) {
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($pythonCommand) { $Python = $pythonCommand.Source }
    }
    if (-not $Python) {
        throw 'Install 64-bit Python 3.11-3.14, or run install.ps1 -Python C:\path\python.exe.'
    }
    Invoke-Checked $Python @('-c', 'import sys,struct; assert (3,11)<=sys.version_info<(3,15), "Python 3.11-3.14 required"; assert struct.calcsize("P")==8, "64-bit Python required"')
    Invoke-Checked $Python @('-m', 'venv', (Join-Path $projectRoot '.venv'))
}
Invoke-Checked $venvPython @('-c', 'import sys,struct; assert (3,11)<=sys.version_info<(3,15); assert struct.calcsize("P")==8')
Invoke-Checked $venvPython @('-m', 'pip', 'install', '--upgrade', 'pip')
Invoke-Checked $venvPython @('-m', 'pip', 'install', '-r', (Join-Path $projectRoot 'requirements.txt'))
Invoke-Checked $venvPython @('-c', 'from PySide6.QtWebEngineWidgets import QWebEngineView; import PySide6; print("Qt WebEngine import OK; PySide6", PySide6.__version__)')
Write-Host 'Dependencies installed in this project .venv. Next: Preview.cmd or Run.cmd.'
