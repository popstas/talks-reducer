Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Set-Location -LiteralPath $PSScriptRoot
& node (Join-Path $PSScriptRoot 'process-server.js')
