# Compiles Scrybinder.exe (launcher with icon, no console window) into the project root. Installs nothing: uses the csc.exe that ships with Windows.
$root = Split-Path -Parent $PSScriptRoot
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { throw "csc.exe not found at $csc" }
& $csc /nologo /target:winexe /optimize+ /r:System.Windows.Forms.dll "/win32icon:$PSScriptRoot\scrybinder.ico" "/out:$root\Scrybinder.exe" "$PSScriptRoot\launcher.cs"
if ($LASTEXITCODE -ne 0) { throw "compilation failed" }
Write-Host "Scrybinder.exe created in $root"
