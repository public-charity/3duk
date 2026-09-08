# Build ThanetEditor Win64 <Config> with the engine's bundled dotnet + UnrealBuildTool (UE_PLAN.md 5.1).
# Byte-for-byte the invocation proven on this machine for the UnrealMCP port (C:/UnrealProjects/build6.log:2,
# Engine/Build/BatchFiles/Build.bat:48, :78). Log: <project>/Saved/Logs/build.log. Success = exit 0 and
# "Result: Succeeded". -ProjectFiles regenerates the .sln instead (ignored by git).
param([string]$Config = "Development", [switch]$ProjectFiles)
$ErrorActionPreference = "Continue"
$UE = "C:\Program Files\Epic Games\UE_5.8\Engine"
$Proj = (Resolve-Path "$PSScriptRoot\..\Thanet.uproject").Path
$dotnet = "$UE\Binaries\ThirdParty\DotNet\10.0\win-x64\dotnet.exe"
$ubt = "$UE\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.dll"
$LogDir = Join-Path (Split-Path $Proj) "Saved\Logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force $LogDir | Out-Null }
if ($ProjectFiles) {
	& $dotnet $ubt -projectfiles -project="$Proj" -game -engine -progress
	exit $LASTEXITCODE
}
# Not Tee-Object: in PowerShell 5.1 it writes UTF-16 and grep cannot read the log. Echo each line and stream it
# to a UTF-8 file as it arrives, so a background build can be tailed.
& $dotnet $ubt ThanetEditor Win64 $Config -Project="$Proj" -WaitMutex -FromMsBuild 2>&1 |
	ForEach-Object { $line = "$_"; Write-Host $line; $line } |
	Out-File -Encoding utf8 -FilePath (Join-Path $LogDir "build.log")
exit $LASTEXITCODE
