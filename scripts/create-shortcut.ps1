[CmdletBinding()]
param(
    [switch]$Desktop,
    [switch]$Source,
    [string]$Name = '',
    [ValidateSet('brief','full')][string]$Edition = 'full',
    [ValidateSet('brief','full')][string]$Mode,
    [ValidateSet('amber','green','cyan','white')][string]$Color
)
$ErrorActionPreference = 'Stop'
# source-note: dhdhd723
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$bundleExecutable = Join-Path $projectRoot 'dist\Codex550CLauncher\Codex550CLauncher.exe'
$editionName = if ($Edition -eq 'brief') { '550W简洁版' } else { '550W完整版' }
$portableEditions = @(@('550W简洁版','550W完整版') | Where-Object { Test-Path -LiteralPath (Join-Path $projectRoot ($_ + '.exe')) })
if (@($portableEditions).Count -eq 1) {
    if ($PSBoundParameters.ContainsKey('Edition') -and $portableEditions[0] -ne $editionName) {
        throw 'The selected edition does not match this portable directory.'
    }
    $bundleExecutable = Join-Path $projectRoot ($portableEditions[0] + '.exe')
} else {
    $selectedBuild = Join-Path $projectRoot ('dist\' + $editionName + '\' + $editionName + '.exe')
    if (Test-Path -LiteralPath $selectedBuild) { $bundleExecutable = $selectedBuild }
    elseif ($PSBoundParameters.ContainsKey('Edition') -and -not $Source) { throw 'Build the selected edition first.' }
}
if (-not (Test-Path -LiteralPath $bundleExecutable)) {
    $portableExecutable = Join-Path $projectRoot 'Codex550CLauncher.exe'
    if (Test-Path -LiteralPath $portableExecutable) { $bundleExecutable = $portableExecutable }
}
if (-not $Name) {
    if (Test-Path -LiteralPath $bundleExecutable) { $Name = [IO.Path]::GetFileNameWithoutExtension($bundleExecutable) }
    else { $Name = $editionName }
}
$argumentParts = @()
if ($Mode) { $argumentParts += @('--mode', $Mode) }
if ($Color) { $argumentParts += @('--color', $Color) }
$arguments = $argumentParts -join ' '
if (-not $Source -and (Test-Path -LiteralPath $bundleExecutable)) {
    $target = $bundleExecutable
    $workingDirectory = Split-Path -Parent $bundleExecutable
} else {
    $target = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path -LiteralPath $target)) { throw 'Run Install.cmd or Build.cmd first.' }
    $arguments = '"' + (Join-Path $projectRoot 'main.py') + '" ' + $arguments
    $workingDirectory = $projectRoot
}
if ($Name.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) { throw 'Shortcut name contains an invalid filename character.' }
$shortcutDirectory = $projectRoot
if ($Desktop) { $shortcutDirectory = [Environment]::GetFolderPath('Desktop') }
$shortcutPath = Join-Path $shortcutDirectory ($Name + '.lnk')
if (Test-Path -LiteralPath $shortcutPath) { throw "Shortcut already exists; choose -Name to create another: $shortcutPath" }
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $workingDirectory
$shortcut.WindowStyle = 1
$shortcut.Description = '550W animation followed by official Codex, without changing official application files.'
$iconPath = Join-Path $projectRoot 'assets\launcher.ico'
if (Test-Path -LiteralPath $iconPath) { $shortcut.IconLocation = $iconPath + ',0' }
elseif (-not $Source -and $target -eq $bundleExecutable) { $shortcut.IconLocation = $bundleExecutable + ',0' }
$shortcut.Save()
Write-Host "Created: $shortcutPath"
