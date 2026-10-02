# Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
# SPDX-License-Identifier: GPL-3.0-only
param(
    [string]$CacheDirectory = '',
    [string]$OutputDirectory = '',
    [string]$Python = 'python.exe',
    [string]$JdkHome = $env:JAVA_HOME,
    [string]$RuntimeArchive = '',
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = '2.5.7'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $CacheDirectory) {
    $cacheBase = if ($env:QIZHANG_CACHE_ROOT) { $env:QIZHANG_CACHE_ROOT } else { [IO.Path]::GetTempPath() }
    $CacheDirectory = Join-Path $cacheBase 'QiZhangPanel-Free-build'
}
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $projectRoot 'outputs' }
if (-not $JdkHome) {
    $javacCommand = Get-Command javac.exe -ErrorAction Stop
    $JdkHome = Split-Path -Parent (Split-Path -Parent $javacCommand.Source)
}
New-Item -ItemType Directory -Force -Path $CacheDirectory | Out-Null
$CacheDirectory = (Resolve-Path -LiteralPath $CacheDirectory).Path
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:QIZHANG_CACHE_ROOT = $CacheDirectory
$env:TEMP = $CacheDirectory
$env:TMP = $CacheDirectory
& $Python -B (Join-Path $PSScriptRoot 'build-command-agent.py') --jdk $JdkHome --cache-dir $CacheDirectory
if ($LASTEXITCODE -ne 0) { throw 'Java command agent build failed.' }
$nativeBuild = Join-Path $CacheDirectory 'native'
$uninstallerBuild = Join-Path $CacheDirectory 'uninstaller'
& (Join-Path $PSScriptRoot 'build-native.ps1') -OutputDirectory $nativeBuild
& (Join-Path $PSScriptRoot 'build-uninstaller.ps1') -OutputDirectory $uninstallerBuild
$packageArgs = @('-B', (Join-Path $PSScriptRoot 'package-free.py'), '--version', $Version,
    '--output', $OutputDirectory, '--native-build', $nativeBuild, '--uninstaller-build', $uninstallerBuild,
    '--cache-dir', $CacheDirectory)
if ($RuntimeArchive) { $packageArgs += @('--runtime-archive', $RuntimeArchive) }
& $Python @packageArgs
if ($LASTEXITCODE -ne 0) { throw 'Free portable package build failed.' }
$zipPath = Join-Path $OutputDirectory "qizhang-panel-free-$Version-portable.zip"
& (Join-Path $PSScriptRoot 'build-installer.ps1') -PackageZip $zipPath -OutputDirectory $OutputDirectory -Version $Version
& $Python -B (Join-Path $PSScriptRoot 'release-checksums.py') --output $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'Release checksum generation failed.' }
