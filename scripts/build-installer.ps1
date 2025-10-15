#!/usr/bin/env pwsh
<#
.SYNOPSIS
Build the Talks Reducer Windows installer using Inno Setup.

.DESCRIPTION
Ensures the PyInstaller bundle exists, determines the application version,
and invokes the Inno Setup compiler with the expected arguments. The resulting
installer is moved into the ``dist`` directory.
#>

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

$distRoot = [System.IO.Path]::Combine($repositoryRoot, 'dist')
$candidateDirs = @(
    [System.IO.Path]::Combine($distRoot, 'talks-reducer'),
    [System.IO.Path]::Combine($distRoot, 'talks-reducer-windows')
)

$sourceDir = $null
$executablePath = $null

foreach ($candidate in $candidateDirs) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) {
        continue
    }

    $potentialExe = [System.IO.Path]::Combine($candidate, 'talks-reducer.exe')
    if (Test-Path -LiteralPath $potentialExe -PathType Leaf) {
        $sourceDir = $candidate
        $executablePath = $potentialExe
        break
    }

    $nestedCandidate = [System.IO.Path]::Combine($candidate, 'talks-reducer')
    if (Test-Path -LiteralPath $nestedCandidate -PathType Container) {
        $potentialExe = [System.IO.Path]::Combine($nestedCandidate, 'talks-reducer.exe')
        if (Test-Path -LiteralPath $potentialExe -PathType Leaf) {
            $sourceDir = $nestedCandidate
            $executablePath = $potentialExe
            break
        }
    }
}

if (-not $sourceDir -or -not $executablePath) {
    $searched = $candidateDirs -join ', '
    throw "PyInstaller output not found. Checked: $searched. Run scripts/build-gui.sh first."
}

Write-Host "ℹ️  Using PyInstaller executable at $executablePath"

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

$isccExitCode = $null
Push-Location -LiteralPath $scriptDirectory
try {
    & $isccPath "/DAPP_VERSION=$AppVersion" 'talks-reducer-installer.iss'
    $isccExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($isccExitCode -ne 0) {
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
