param(
    [Parameter(Mandatory = $true)][string]$PackageZip,
    [string]$OutputDirectory = '',
    
    [string]$Version = '2.5.7'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$packagePath = (Resolve-Path -LiteralPath $PackageZip).Path
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $projectRoot 'work\installer-build' }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$iconPath = Join-Path $projectRoot 'src\assets\QiZhang.ico'
if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) { throw "Product icon is missing: $iconPath" }
$outputExe = Join-Path $OutputDirectory "qizhang-panel-free-$Version-setup.exe"
$arguments = @('/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/codepage:65001',
    '/main:QiZhang.Installer.InstallerProgram', '/reference:System.Management.dll',
    '/define:EDITION_FREE',
    "/out:$outputExe", "/resource:$packagePath,panel.zip", "/win32icon:$iconPath", "/win32manifest:$(Join-Path $projectRoot 'src\desktop\app.manifest')",
    '/reference:System.dll', '/reference:System.Core.dll', '/reference:System.Drawing.dll',
    '/reference:System.Windows.Forms.dll', '/reference:System.Web.Extensions.dll',
    '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
    (Join-Path $projectRoot 'src\installer\Installer.cs'),
    (Join-Path $projectRoot 'src\installer\InstallationOptions.cs'),
    (Join-Path $projectRoot 'src\installer\Uninstaller.cs'),
    (Join-Path $projectRoot 'src\shared\InstallationLocation.cs'),
    (Join-Path $projectRoot 'src\shared\AppTheme.cs'),
    (Join-Path $projectRoot 'src\native\WindowChrome.cs'),
    (Join-Path $projectRoot 'src\native\VisualEffects.cs'),
    (Join-Path $projectRoot 'src\native\Ui.cs'))
if (Test-Path -LiteralPath (Join-Path $projectRoot 'src\native\ScrollBarTheme.cs')) { $arguments += (Join-Path $projectRoot 'src\native\ScrollBarTheme.cs') }
$wpfRoot = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\WPF'
$arguments += @('/reference:System.Xaml.dll')
foreach ($assembly in @('WindowsBase.dll','PresentationCore.dll','PresentationFramework.dll','WindowsFormsIntegration.dll')) { $arguments += "/reference:$(Join-Path $wpfRoot $assembly)" }
& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw "Installer build failed: $LASTEXITCODE" }
Get-Item -LiteralPath $outputExe | Select-Object FullName, Length, LastWriteTime
