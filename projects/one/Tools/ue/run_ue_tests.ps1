# Headless Automation test runner (UE_PLAN.md 2.13, STAGES.md command conventions).
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File Tools/ue/run_ue_tests.ps1 [-Filter Streetscape] [-Log tests.log] [-ParityJson <path>]
# Runs exactly:
#   UnrealEditor-Cmd.exe Thanet.uproject -ExecCmds="Automation RunTests <Filter>; Quit" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=<Log>
# then reads Saved/Logs/<Log>: pass = at least one "Test Completed. Result={Success}" and no "Result={Fail}" for the
# filter (UE 5.8 prints Success/Fail; the Passed/Failed wording of STAGES.md is accepted too); the summary
# (one line per test) is printed and the exit code is 0 on pass, 2 on any failure, 3 when no test
# ran. The engine's own exit code is ignored on purpose: on this machine every UnrealEditor-Cmd run exits 1 because the
# VC++ redistributable advisory is logged at Error severity (see run_ue_python.ps1).
# -ParityJson sets STREETSCAPE_PARITY_JSON so Streetscape.Spline.NumpyParity compares against a numpy dump.
param(
	[string]$Filter = "Streetscape",
	[string]$Log = "tests.log",
	[string]$ParityJson = ""
)
$ErrorActionPreference = "Continue"
$UE = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$Proj = (Resolve-Path "$PSScriptRoot\..\..\Thanet.uproject").Path
if ($ParityJson) { $env:STREETSCAPE_PARITY_JSON = (Resolve-Path $ParityJson).Path }
$LogPath = Join-Path (Split-Path $Proj) "Saved\Logs\$Log"
if (Test-Path $LogPath) { Remove-Item $LogPath -Force }
$exec = "Automation RunTests $Filter; Quit"
Write-Host "run_ue_tests: $Proj -ExecCmds=`"$exec`" (log Saved/Logs/$Log)"
$t0 = Get-Date
& $UE "$Proj" "-ExecCmds=`"$exec`"" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -NoLiveCoding "-log=$Log"
$engineCode = $LASTEXITCODE
$secs = [int]((Get-Date) - $t0).TotalSeconds
if (-not (Test-Path $LogPath)) { Write-Host "run_ue_tests: no log at $LogPath (engine exit $engineCode)"; exit 3 }
$lines = Get-Content $LogPath
$completed = @($lines | Where-Object { $_ -match "Test Completed\. Result=\{(Success|Passed|Fail|Failed|Skipped)\} Name=\{([^}]*)\}" })
$passed = @($completed | Where-Object { $_ -match "Result=\{(Success|Passed)\}" })
$failed = @($completed | Where-Object { $_ -match "Result=\{(Fail|Failed)\}" })
Write-Host "run_ue_tests: $($completed.Count) test(s) completed in ${secs}s (engine exit $engineCode): $($passed.Count) passed, $($failed.Count) failed"
foreach ($l in $completed) {
	if ($l -match "Result=\{(\w+)\} Name=\{[^}]*\} Path=\{([^}]*)\}") { Write-Host ("  {0,-7} {1}" -f $matches[1], $matches[2]) }
}
$errors = @($lines | Where-Object { $_ -match "LogAutomationTest: Error:" })
foreach ($e in $errors) { Write-Host "  ERROR: $e" }
if ($completed.Count -eq 0) { exit 3 }
if ($failed.Count -gt 0) { exit 2 }
exit 0
