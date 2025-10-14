#!/usr/bin/env pwsh
<#!
.SYNOPSIS
Build the Talks Reducer Windows installer using Inno Setup.

.DESCRIPTION
Ensures the PyInstaller bundle exists, determines the application version,
and invokes the Inno Setup compiler with the expected arguments. The resulting
installer is moved into the ``dist`` directory.
!>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]
    $AppVersion
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$repositoryRoot = Resolve-Path (Join-Path $scriptDirectory '..')
Set-Location $repositoryRoot

function Get-VersionFromScripts {
    <#
    .SYNOPSIS
    Retrieve the Talks Reducer version via the helper Python script.
    #>
    param()

    $pythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { 'python' }
    $result = & $pythonBin 'scripts/get-version.py' 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to determine package version. Set APP_VERSION explicitly.'
    }
    return $result.Trim()
}

if (-not $AppVersion) {
    $AppVersion = Get-VersionFromScripts
}

if (-not $AppVersion) {
    throw 'Unable to determine package version. Set APP_VERSION explicitly.'
}

$sourceDir = Join-Path $repositoryRoot 'dist/talks-reducer'
if (-not (Test-Path -Path $sourceDir -PathType Container)) {
    throw "PyInstaller output not found at $sourceDir. Run scripts/build-gui.sh first."
}

$executablePath = Join-Path $sourceDir 'talks-reducer.exe'
if (-not (Test-Path -Path $executablePath -PathType Leaf)) {
    throw "Expected PyInstaller executable at $executablePath. Run scripts/build-gui.sh first."
}

$isccPath = $null
if ($env:ISCC_BIN) {
    $isccPath = $env:ISCC_BIN
} else {
    $isccCommand = Get-Command -Name 'iscc' -ErrorAction SilentlyContinue
    if ($isccCommand) {
        $isccPath = $isccCommand.Source
    } else {
        $fallbacks = @(
            'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
            'C:\Program Files\Inno Setup 6\ISCC.exe'
        )
        foreach ($candidate in $fallbacks) {
            if (Test-Path -Path $candidate -PathType Leaf) {
                $isccPath = $candidate
                break
            }
        }
    }
}

if (-not $isccPath -or -not (Test-Path -Path $isccPath -PathType Leaf)) {
    throw 'Inno Setup compiler (ISCC) is not available. Install Inno Setup before running this script.'
}

$installerScript = 'scripts/talks-reducer-installer.iss'
if (-not (Test-Path -Path $installerScript -PathType Leaf)) {
    throw "Installer script $installerScript missing"
}

$outputName = "talks-reducer-$AppVersion-setup.exe"

& $isccPath "/DAPP_VERSION=$AppVersion" $installerScript
if ($LASTEXITCODE -ne 0) {
    throw 'Inno Setup failed to build the installer.'
}

$outputPath = Join-Path $repositoryRoot $outputName
if (-not (Test-Path -Path $outputPath -PathType Leaf)) {
    throw "Expected Inno Setup to produce $outputName"
}

$distDir = Join-Path $repositoryRoot 'dist'
if (-not (Test-Path -Path $distDir -PathType Container)) {
    New-Item -ItemType Directory -Path $distDir | Out-Null
}

$destination = Join-Path $distDir $outputName
Move-Item -Path $outputPath -Destination $destination -Force

Write-Host "✅ Created dist/$outputName"
