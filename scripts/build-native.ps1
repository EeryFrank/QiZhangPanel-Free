# 七章控制面板项目归属：EeryFrank。项目主页：https://github.com/EeryFrank
param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $projectRoot 'outputs/native-build' }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'

$outputExe = Join-Path $OutputDirectory '七章控制面板.exe'
$arguments = @('/nologo','/target:winexe','/platform:x64','/optimize+','/codepage:65001',
    '/define:EDITION_FREE',
    "/out:$outputExe", "/win32manifest:$(Join-Path $projectRoot 'src\desktop\app.manifest')", "/win32icon:$(Join-Path $projectRoot 'src\assets\QiZhang.ico')",
    '/reference:System.dll','/reference:System.Core.dll','/reference:System.Drawing.dll',
    '/reference:System.Windows.Forms.dll','/reference:System.Web.Extensions.dll','/reference:System.Security.dll')
$arguments += @(Get-ChildItem -LiteralPath (Join-Path $projectRoot 'src\native') -Filter '*.cs' | ForEach-Object FullName)
$arguments += @(Get-ChildItem -LiteralPath (Join-Path $projectRoot 'src\shared') -Filter '*.cs' | ForEach-Object FullName)
$wpfRoot = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\WPF'
$arguments += @('/reference:System.Xaml.dll')
foreach ($assembly in @('WindowsBase.dll','PresentationCore.dll','PresentationFramework.dll','WindowsFormsIntegration.dll')) { $arguments += "/reference:$(Join-Path $wpfRoot $assembly)" }
& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw "Native build failed: $LASTEXITCODE" }
@'
<?xml version="1.0" encoding="utf-8"?>
<configuration><startup><supportedRuntime version="v4.0" sku=".NETFramework,Version=v4.8" /></startup></configuration>
'@ | Set-Content -LiteralPath "$outputExe.config" -Encoding UTF8
Get-Item -LiteralPath $outputExe | Select-Object FullName,Length,LastWriteTime
