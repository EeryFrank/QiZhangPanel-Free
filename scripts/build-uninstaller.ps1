# Copyright (c) 2026 EeryFrank - https://github.com/EeryFrank
param([string]$OutputDirectory='')
$ErrorActionPreference='Stop'
$project=Split-Path -Parent $PSScriptRoot
if(-not $OutputDirectory){$OutputDirectory=Join-Path $project 'work\uninstaller-build'}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$output=Join-Path $OutputDirectory '卸载七章控制面板.exe'
$arguments=@('/nologo','/target:winexe','/platform:x64','/optimize+','/codepage:65001','/main:QiZhang.Installer.UninstallerProgram',"/out:$output","/win32icon:$(Join-Path $project 'src\assets\QiZhang.ico')","/win32manifest:$(Join-Path $project 'src\desktop\app.manifest')",'/reference:System.dll','/reference:System.Core.dll','/reference:System.Drawing.dll','/reference:System.Windows.Forms.dll','/reference:System.Web.Extensions.dll','/reference:System.Management.dll','/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll','/reference:System.Xaml.dll')
$arguments+='/define:EDITION_FREE'
foreach($file in @('src\installer\Installer.cs','src\installer\InstallationOptions.cs','src\installer\Uninstaller.cs','src\shared\InstallationLocation.cs','src\shared\AppTheme.cs','src\native\WindowChrome.cs','src\native\VisualEffects.cs','src\native\Ui.cs','src\native\ScrollBarTheme.cs')){$arguments+=Join-Path $project $file}
$wpf=Join-Path (Split-Path -Parent $compiler) 'WPF'
foreach($assembly in @('WindowsBase.dll','PresentationCore.dll','PresentationFramework.dll','WindowsFormsIntegration.dll')){$arguments+="/reference:$(Join-Path $wpf $assembly)"}
& $compiler @arguments
if($LASTEXITCODE -ne 0){throw 'Uninstaller build failed.'}
Get-Item -LiteralPath $output | Select-Object FullName,Length
# Sources are listed explicitly to keep this distribution independent.

