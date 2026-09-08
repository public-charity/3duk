# Headless editor-Python runner (UE_PLAN.md 5.2, STAGES.md command conventions).
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File Tools/ue/run_ue_python.ps1 -Script 01_bootstrap.py [-Args "<args>"] [-Render] [-Log name.log]
# Pass = exit 0, the log line "Python script executed successfully" (PythonScriptCommandlet.cpp:72) and the script's
# final line "THANET_OK <script> <json>". Log goes to <project>/Saved/Logs/<Log> (default <script>.log).
# Tools/ue is put on sys.path through UE_PYTHONPATH (PythonScriptPlugin.cpp:1281). -Render adds
# -AllowCommandletRendering for steps that need an RHI (landscape import, probes, screenshots).
# Never points at another project: the .uproject is always this repo's Thanet.uproject (BRIEF 4.5).
param(
	[Parameter(Mandatory)][string]$Script,
	[Alias("Args")][string]$ScriptArgs = "",
	[switch]$Render,
	[string]$Log = ""
)
$ErrorActionPreference = "Continue"
$UE = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$ToolsDir = (Resolve-Path "$PSScriptRoot").Path
$Proj = (Resolve-Path "$PSScriptRoot\..\..\Thanet.uproject").Path
$Py = (Resolve-Path (Join-Path $ToolsDir $Script)).Path -replace '\\', '/'
if (-not $Log) { $Log = "$([IO.Path]::GetFileNameWithoutExtension($Script)).log" }
$env:UE_PYTHONPATH = $ToolsDir
$ScriptArg = ("$Py $ScriptArgs").Trim()
$flags = @("-run=pythonscript", "-script=`"$ScriptArg`"", "-unattended", "-nopause", "-nosplash", "-stdout", "-FullStdOutLogOutput", "-NoLiveCoding", "-log=$Log")
if ($Render) { $flags += "-AllowCommandletRendering" }
Write-Host "run_ue_python: $Proj -> $ScriptArg (log Saved/Logs/$Log)"
& $UE "$Proj" @flags
$code = $LASTEXITCODE

# Verdict from the log. On this machine the editor logs "Visual C++ redistributable version 14.44.35211.0 is
# outdated" at Error severity (Engine/Source/Runtime/ApplicationCore/Private/Windows/WindowsPlatformApplicationMisc.cpp:121,
# unconditional under WITH_EDITOR, advisory only - the memory note says the editor runs fine; updating the redist needs
# admin), and the commandlet framework then reports "Failure - 1 error(s)" and exits 1 even when the Python script
# succeeded. So: when the script succeeded and that advisory is the ONLY error the engine counted, the exit code is 0.
# Any other error, a Python failure ("Python script executed with errors"), or a crash without a summary keeps it non-zero.
$LogPath = Join-Path (Split-Path $Proj) "Saved\Logs\$Log"
if ($code -ne 0 -and (Test-Path $LogPath)) {
	$text = Get-Content -Raw $LogPath
	$pyOk = $text -match "Python script executed successfully"
	$parts = $text -split "Warning/Error Summary"
	if ($pyOk -and $parts.Count -gt 1) {
		$summary = $parts[-1]
		$otherErrors = @($summary -split "`n" | Where-Object { $_ -match "Error: " } | Where-Object { $_ -notmatch "Visual C\+\+ redistributable" })
		if ($otherErrors.Count -eq 0) {
			Write-Host "run_ue_python: engine exit code $code overridden to 0 - the script succeeded and the only counted error is the VC++ redistributable advisory"
			$code = 0
		}
	}
}
exit $code
