[CmdletBinding()]
param([string]$Python = '', [switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $SkipInstall) {
    & (Join-Path $PSScriptRoot 'install.ps1') -Python $Python
    $Python = Join-Path $projectRoot '.venv\Scripts\python.exe'
} elseif (-not $Python) {
    $Python = Join-Path $projectRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $Python)) { throw "Python was not found: $Python" }
$Python = [IO.Path]::GetFullPath($Python)
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'main.py'))) { throw 'main.py is missing.' }

Write-Host 'Building a local onedir package; original animation redistribution permission remains unresolved.'
$buildArguments = @(
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
    '--name', 'Codex550CLauncher', '--contents-directory', '_internal',
    '--distpath', (Join-Path $projectRoot 'dist'),
    '--workpath', (Join-Path $projectRoot 'work\pyinstaller'),
    '--specpath', (Join-Path $projectRoot 'work'),
    '--hidden-import', 'PySide6.QtWebEngineCore',
    '--hidden-import', 'PySide6.QtWebEngineWidgets',
    '--hidden-import', 'PySide6.QtWebChannel'
)
# PyInstaller's QtWebEngine hooks collect required DLLs, helper executable,
# resource packs and locales. Avoid --collect-all PySide6 (unrelated Qt modules).
foreach ($assetDirectory in @('web', 'assets', 'third_party')) {
    $assetPath = Join-Path $projectRoot $assetDirectory
    if (Test-Path -LiteralPath $assetPath) { $buildArguments += @('--add-data', "$assetPath;$assetDirectory") }
}
$buildArguments += @('--add-data', ((Join-Path $projectRoot 'edition.json') + ';.'))
$iconPath = Join-Path $projectRoot 'assets\launcher.ico'
if (Test-Path -LiteralPath $iconPath) { $buildArguments += @('--icon', $iconPath) }
$buildArguments += (Join-Path $projectRoot 'main.py')
Push-Location -LiteralPath $projectRoot
$previousBuildPath = $env:PATH
try {
    # Qt 6 uses Windows' built-in ICU API. PDF/image runtimes on the caller's
    # PATH may ship an incompatible ICU with version-suffixed symbols. Do not
    # let dependency analysis collect those libraries into this application.
    $basePythonDirectory = (& $Python -c 'import sys; print(sys.base_prefix)').Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot locate the Python base runtime.' }
    $env:PATH = @((Split-Path -Parent ([IO.Path]::GetFullPath($Python))), $basePythonDirectory,
        (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot,
        (Join-Path $env:SystemRoot 'System32\Wbem'),
        (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')) -join ';'
    & $Python @buildArguments
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)." }
} finally {
    $env:PATH = $previousBuildPath
    Pop-Location
}

$bundleRoot = Join-Path $projectRoot 'dist\Codex550CLauncher'
if (-not (Test-Path -LiteralPath (Join-Path $bundleRoot 'Codex550CLauncher.exe'))) { throw 'Expected executable is missing.' }
foreach ($requiredResource in @('QtWebEngineProcess.exe', 'icudtl.dat', 'qtwebengine_resources.pak', 'qwindows.dll')) {
    $matches = @(Get-ChildItem -LiteralPath $bundleRoot -Filter $requiredResource -Recurse -File)
    if ($matches.Count -eq 0) { throw "Incomplete WebEngine bundle: missing $requiredResource. Do not use this build." }
}
$locales = @(Get-ChildItem -LiteralPath $bundleRoot -Directory -Recurse | Where-Object { $_.Name -eq 'qtwebengine_locales' })
if ($locales.Count -eq 0) { throw 'Incomplete WebEngine bundle: qtwebengine_locales is missing.' }
$foreignIcu = @(Get-ChildItem -LiteralPath $bundleRoot -Recurse -File | Where-Object { $_.Name -match '^icu(uc|in|dt)\d*\.dll$' })
if ($foreignIcu.Count -ne 0) { throw 'Foreign ICU libraries were collected. Qt must use the Windows system ICU; rebuild with a clean dependency search path.' }
foreach ($entry in @('Run', 'Preview', 'Settings', 'diagnostics')) {
    $option = switch ($entry) { 'Preview' {' --preview'} 'Settings' {' --settings'} 'diagnostics' {' --diagnose'} default {''} }
    $batchText = '@echo off' + "`r`n" + 'start "" "%~dp0Codex550CLauncher.exe"' + $option + ' %*' + "`r`n"
    [IO.File]::WriteAllText((Join-Path $bundleRoot ($entry + '.cmd')), $batchText, [Text.Encoding]::ASCII)
}
$portableScripts = Join-Path $bundleRoot 'scripts'
[IO.Directory]::CreateDirectory($portableScripts) | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'create-shortcut.ps1') -Destination $portableScripts -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'Create-Shortcut.cmd') -Destination $bundleRoot -Force

# Put human-readable documents next to the EXE rather than inside _internal.
foreach ($document in @('README.md', 'LICENSE', 'THIRD-PARTY-NOTICES.md')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $document) -Destination $bundleRoot -Force
}
foreach ($documentationDirectory in @('docs', 'third_party')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $documentationDirectory) -Destination $bundleRoot -Recurse -Force
}
$licenseCollector = @'
from pathlib import Path
from importlib import metadata
import json, shutil, sys
bundle = Path(sys.argv[1])
destination = bundle / 'licenses'
destination.mkdir(parents=True, exist_ok=True)
packages = ('PySide6', 'PySide6_Essentials', 'PySide6_Addons', 'shiboken6', 'PyInstaller')
inventory = {}
for name in packages:
    distribution = metadata.distribution(name)
    inventory[name] = distribution.version
    for relative in distribution.files or ():
        parts = [part.lower() for part in relative.parts]
        lower_name = relative.name.lower()
        if ('licenses' in parts or 'license' in parts or lower_name.startswith(('license', 'copying', 'notice'))):
            source = Path(distribution.locate_file(relative)).resolve()
            if source.is_file():
                # Keep package-relative paths and independent distribution notices.
                safe_parts = [part for part in relative.parts if part not in ('..', '.', '')]
                target = destination / name / Path(*safe_parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
for candidate in (Path(sys.base_prefix)/'LICENSE.txt', Path(sys.base_prefix)/'LICENSE', Path(sys.base_prefix)/'share'/'doc'/'python'/'LICENSE'):
    if candidate.is_file():
        shutil.copy2(candidate, destination / 'Python-LICENSE.txt')
        break
inventory['Python'] = sys.version
(destination/'VERSIONS.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
print('Bundled dependency notices:', destination)
'@
& $Python -c $licenseCollector $bundleRoot
if ($LASTEXITCODE -ne 0) { throw 'Dependency license collection failed.' }
Write-Host "Local build complete: $bundleRoot\Codex550CLauncher.exe"
Write-Host 'Keep the entire folder together. Animation license has not been cleared for public redistribution.'
& $Python (Join-Path $PSScriptRoot 'package-editions.py')
if ($LASTEXITCODE -ne 0) { throw 'Edition packaging failed.' }
