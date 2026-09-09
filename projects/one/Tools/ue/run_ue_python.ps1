# Headless editor-Python runner (UE_PLAN.md 5.2, STAGES.md command conventions).
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File Tools/ue/run_ue_python.ps1 -Script 01_bootstrap.py
#       [-Args "<args>"] [-Render] [-Log name.log] [-StrictExit]
# Log goes to <project>/Saved/Logs/<Log> (default <script>.log). Tools/ue is put on sys.path through
# UE_PYTHONPATH (PythonScriptPlugin.cpp:1281). -Render adds -AllowCommandletRendering for steps that need an
# RHI (landscape import, probes, screenshots). Never points at another project: the .uproject is always this
# repo's Thanet.uproject (BRIEF 4.5).
#
# WHY THIS FILE IS LONGER THAN A `& $UE ...` LINE, AND WHAT IT MAY AND MAY NOT FORGIVE
# ------------------------------------------------------------------------------------
# UnrealEditor-Cmd on this machine returns non-zero for TWO unrelated reasons, and the previous version of this
# script attributed both of them to the first. Every "THANET_OK" in this project's history was produced through
# that override, so the two are now separated, named, evidenced, and recorded:
#
#   (1) THE VC++ REDISTRIBUTABLE ADVISORY -> raw exit 1.
#       The editor logs "Visual C++ redistributable version <x> is outdated." at Error severity
#       (Engine/Source/Runtime/ApplicationCore/Private/Windows/WindowsPlatformApplicationMisc.cpp:121,
#       unconditional under WITH_EDITOR, advisory only; updating the redist needs admin). The commandlet
#       framework then counts it, prints "Failure - 1 error(s)" and returns 1 even though nothing failed.
#       Waived ONLY when: raw exit is exactly 1, the Python script succeeded, the log's Warning/Error Summary
#       exists, and the ONLY "Error: " line in that summary is that advisory. Measured 2026-09-09:
#       `-Script ue_common.py` exits 1 with and without -Render.
#
#   (2) AN ACCESS VIOLATION AT PROCESS TEARDOWN -> raw exit 0xC0000005 (-1073741819).
#       Measured 2026-09-09 on this machine: it happens when, and only when, the run streamed in a World
#       Partition region. `04_probe.py --points ... --landscape` (regions_loaded 1) dies with 0xC0000005;
#       the same script, same flags, without --landscape (regions_loaded 0) exits 1. All nine batches of
#       `render_set.ps1` at commit b1cd3e5 returned -1073741819 (renders/b1cd3e5/manifest.json) and all 45
#       images and all nine reports were written and verified. The log is COMPLETE in these runs: the
#       Warning/Error Summary, "LogExit: Exiting." and "Log file closed" are all present, and there is no
#       crash marker anywhere - the fault is after the log file is closed, in final static teardown.
#       This is waived only against positive proof that the work finished (Python succeeded, a THANET_OK line
#       is in the log, no THANET_FAIL, no crash marker, and the shutdown ran to "Log file closed"), it is
#       announced with a banner, it is written to Saved/Logs/run_ue_python_verdicts.tsv, and -StrictExit
#       refuses it. It is NEVER attributed to the VC++ advisory.
#
# Anything else - any other exit code, a Python failure, a crash marker in the log, a THANET_FAIL line, a
# missing summary, a truncated log - fails, prints the classification and a log excerpt, and returns non-zero.
#
# Pass = exit 0, the log line "Python script executed successfully" (PythonScriptCommandlet.cpp:72) and the
# script's final line "THANET_OK <script> <json>". EXIT 0 IS NOT PROOF ON ITS OWN: read the VERDICT line this
# script prints, and confirm the output files the step was asked for exist.
param(
	[Parameter(Mandatory)][string]$Script,
	[Alias("Args")][string]$ScriptArgs = "",
	[switch]$Render,
	[string]$Log = "",
	[switch]$StrictExit
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
$t0 = Get-Date
& $UE "$Proj" @flags
$code = $LASTEXITCODE
$elapsed = ((Get-Date) - $t0).TotalSeconds

# ---- the raw exit code, named -------------------------------------------------------------------------
$u = [int64]$code
if ($u -lt 0) { $u = $u + 4294967296 }
$hex = "0x" + ("{0:X8}" -f $u)
$ntstatus = @{
	3221225477 = "STATUS_ACCESS_VIOLATION"; 3221225725 = "STATUS_STACK_OVERFLOW";
	3221226356 = "STATUS_HEAP_CORRUPTION";  3221225620 = "STATUS_ILLEGAL_INSTRUCTION";
	3221225473 = "STATUS_IN_PAGE_ERROR";    3221225786 = "STATUS_CONTROL_C_EXIT";
	2147483651 = "STATUS_BREAKPOINT";       3221225501 = "STATUS_DLL_NOT_FOUND";
}
$codeName = ""
if ($ntstatus.ContainsKey([int64]$u)) { $codeName = $ntstatus[[int64]$u] }
elseif ($u -ge 3221225472 -and $u -le 3489660927) { $codeName = "NTSTATUS 0xC-class crash (unnamed)" }   # 0xC0000000-0xCFFFFFFF

# ---- the facts, read out of the log -------------------------------------------------------------------
$LogPath = Join-Path (Split-Path $Proj) "Saved\Logs\$Log"
$haveLog = Test-Path $LogPath
$pyOk = $false; $pyErr = $false; $okLines = 0; $failLine = ""; $summaryOk = $false
$otherErrors = @(); $crashMarkers = @(); $shutdownClean = $false; $tail = @()
if ($haveLog) {
	$text = Get-Content -Raw $LogPath
	$pyOk = $text -match "Python script executed successfully"
	$pyErr = $text -match "Python script executed with errors"
	$okLines = ([regex]::Matches($text, "THANET_OK ")).Count
	$fm = [regex]::Match($text, "THANET_FAIL [^\r\n]*")
	if ($fm.Success) { $failLine = $fm.Value }
	# A crash the engine itself noticed. The teardown access violation of (2) produces NONE of these.
	# no leading .* : a 10 MB import log would backtrack on every non-matching line
	$crashMarkers = @([regex]::Matches($text, "(?m)[^\r\n]*(?:=== Critical error: ===|Fatal error: \[File|appError called|Assertion failed:|Unhandled Exception|LowLevelFatalError)[^\r\n]*") |
		ForEach-Object { $_.Value.Trim() } | Select-Object -Unique -First 5)
	$parts = $text -split "Warning/Error Summary"
	if ($parts.Count -gt 1) {
		$summaryOk = $true
		$otherErrors = @($parts[-1] -split "`n" | Where-Object { $_ -match "Error: " } | Where-Object { $_ -notmatch "Visual C\+\+ redistributable" })
	}
	$tail = @(Get-Content -Tail 40 $LogPath)
	$shutdownClean = (($tail -join "`n") -match "LogExit: Exiting\.") -and (($tail -join "`n") -match "Log file closed")
}

# ---- the verdict --------------------------------------------------------------------------------------
# status is one of: ok | vcredist_advisory | teardown_crash_after_success | crash | python_error | no_log |
#                   thanet_fail | unknown_exit
$status = "unknown_exit"
$final = $code
if ($failLine -ne "") {
	$status = "thanet_fail"; if ($final -eq 0) { $final = 1 }
} elseif ($code -eq 0) {
	$status = "ok"
} elseif (-not $haveLog) {
	$status = "no_log"
} elseif ($pyErr -or (-not $pyOk)) {
	$status = "python_error"
} elseif ($crashMarkers.Count -gt 0) {
	$status = "crash"
} elseif ($code -eq 1 -and $summaryOk -and $otherErrors.Count -eq 0) {
	$status = "vcredist_advisory"; $final = 0
} elseif ($codeName -ne "" -and $summaryOk -and $otherErrors.Count -eq 0 -and $okLines -gt 0 -and $shutdownClean) {
	$status = "teardown_crash_after_success"
	if ($StrictExit) { $final = $code } else { $final = 0 }
}

$verdict = "run_ue_python: VERDICT status=$status script=$Script render=$($Render.IsPresent) raw_exit=$code ($hex $codeName) final_exit=$final python_ok=$pyOk thanet_ok_lines=$okLines crash_markers=$($crashMarkers.Count) other_errors=$($otherErrors.Count) shutdown_clean=$shutdownClean seconds=$([math]::Round($elapsed,1)) log=Saved/Logs/$Log"

if ($status -eq "teardown_crash_after_success") {
	Write-Host ""
	Write-Host "  ############################################################################" -ForegroundColor Yellow
	Write-Host "  #  UnrealEditor-Cmd CRASHED AT TEARDOWN: $hex $codeName" -ForegroundColor Yellow
	Write-Host "  #  This is NOT the VC++ advisory. The work itself finished: the Python script" -ForegroundColor Yellow
	Write-Host "  #  succeeded, $okLines THANET_OK line(s) are in the log, no crash marker was logged" -ForegroundColor Yellow
	Write-Host "  #  and the shutdown ran through to 'Log file closed'. The fault is after that." -ForegroundColor Yellow
	Write-Host "  #  On this machine it happens when the run streamed a World Partition region." -ForegroundColor Yellow
	Write-Host "  #  CHECK THE OUTPUT FILES YOURSELF. -StrictExit refuses this waiver." -ForegroundColor Yellow
	Write-Host "  ############################################################################" -ForegroundColor Yellow
	Write-Host "  last log lines:" -ForegroundColor DarkYellow
	$tail | Select-Object -Last 6 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkYellow }
	# render_set.ps1 recovers the raw code from this exact phrasing ("engine exit code (-?\d+) overridden").
	if (-not $StrictExit) { Write-Host "run_ue_python: engine exit code $code overridden to 0 - the work finished and the process then crashed at teardown ($hex $codeName)" }
} elseif ($status -eq "vcredist_advisory") {
	Write-Host "run_ue_python: engine exit code $code overridden to 0 - the script succeeded and the only counted error is the VC++ redistributable advisory"
} elseif ($final -ne 0) {
	Write-Host ""
	Write-Host "run_ue_python: FAILED ($status): raw exit $code ($hex $codeName)" -ForegroundColor Red
	if ($failLine -ne "") { Write-Host "  $failLine" -ForegroundColor Red }
	if ($crashMarkers.Count -gt 0) {
		Write-Host "  crash markers in the log:" -ForegroundColor Red
		$crashMarkers | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
	}
	if ($otherErrors.Count -gt 0) {
		Write-Host "  errors the engine counted that are NOT the VC++ advisory:" -ForegroundColor Red
		$otherErrors | Select-Object -First 10 | ForEach-Object { Write-Host "    $($_.Trim())" -ForegroundColor Red }
	}
	if (-not $haveLog) { Write-Host "  no log at $LogPath" -ForegroundColor Red }
	else {
		Write-Host "  last 40 lines of Saved/Logs/$Log :" -ForegroundColor Red
		$tail | ForEach-Object { Write-Host "    $_" }
	}
}
Write-Host $verdict

# ---- the ledger: every run, so nobody has to rediscover this ------------------------------------------
$ledger = Join-Path (Split-Path $Proj) "Saved\Logs\run_ue_python_verdicts.tsv"
try {
	if (-not (Test-Path $ledger)) {
		"utc`tscript`trender`tstatus`traw_exit`traw_hex`tcode_name`tfinal_exit`tpython_ok`tthanet_ok`tcrash_markers`tshutdown_clean`tseconds`tlog" |
			Out-File -FilePath $ledger -Encoding utf8
	}
	("{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}`t{7}`t{8}`t{9}`t{10}`t{11}`t{12}`t{13}" -f `
		(Get-Date).ToUniversalTime().ToString("s"), $Script, $Render.IsPresent, $status, $code, $hex, $codeName,
		$final, $pyOk, $okLines, $crashMarkers.Count, $shutdownClean, [math]::Round($elapsed,1), $Log) |
		Out-File -FilePath $ledger -Encoding utf8 -Append
} catch { }

exit $final
