param([switch]$Workers, [switch]$Build)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& docker volume create converza-vea-storage
if ($LASTEXITCODE -ne 0) { throw 'Persistent renderer storage could not be prepared' }
$argsList = @('compose', '--env-file', 'web/.env.local')
if ($Workers) { $argsList += @('--profile', 'workers') }
$argsList += @('up', '-d')
if ($Build) { $argsList += '--build' }
& docker @argsList
if ($LASTEXITCODE -ne 0) { throw 'Canonical stack failed to start' }
