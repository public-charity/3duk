# render_set.ps1 - take ONE snapshot of the fixed viewpoint set at the current commit.
#
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/render_set.ps1
#       [-Only "margate,broadstairs/st_peters_high_street"]   # a town, a <town>/<slug> id, or a bare slug
#       [-PerTown]                                            # one commandlet per town: bounded memory (see below)
#       [-Out <dir>]                                          # default <repo>/renders/<short hash>
#       [-Force]                                              # overwrite an existing snapshot directory
#       [-List]                                               # print the set and exit, render nothing
#
# It resolves the commit with `git rev-parse --short HEAD`, creates renders/<hash>/<town>/, runs
# Tools/ue/07_render_set.py into it, and writes renders/<hash>/manifest.json: the commit, the full hash, the
# ISO date, the spec's own sha256, the engine version, the capture settings, and one entry per image with its
# location id, the camera transform actually used and the file's size and sha256.
#
# THE MANIFEST IS THE POINT. Two snapshots are comparable only if you can prove they were taken with the same
# camera from the same spec; per-image sha256 then clears, in one line, every frame that did not change at all.
# It only works one way - the renderer is nearly but not exactly deterministic, so a DIFFERING hash still has to
# be looked at. renders/README.md carries the measured numbers.
#
# -PerTown runs nine commandlets instead of one. World Partition has no unload from Python, so a single process
# that streams nine towns keeps every region resident and the resident set climbs all run. Nine editor starts cost
# a few minutes each; an out-of-memory kill costs the whole run. Use -PerTown for the full set, and the single
# process (the default) for a handful of locations.
param(
	[string]$Only = "",
	[switch]$PerTown,
	[string]$Out = "",
	[switch]$Force,
	[switch]$List
)
$ErrorActionPreference = "Stop"
$ToolsDir = ((Resolve-Path "$PSScriptRoot").Path -replace "\\", "/")
$ProjDir = ((Resolve-Path "$PSScriptRoot\..").Path -replace "\\", "/")
$RepoDir = ((Resolve-Path "$PSScriptRoot\..\..\..").Path -replace "\\", "/")
$Runner = Join-Path $ToolsDir "ue/run_ue_python.ps1"
$Spec = "$ToolsDir/ue/render_set.json"
$T0 = Get-Date

if (-not (Test-Path $Spec)) { throw "no spec at $Spec" }
$specDoc = Get-Content -Raw $Spec | ConvertFrom-Json
$specSha = (Get-FileHash -Algorithm SHA256 $Spec).Hash.ToLower()
$townSlugs = @($specDoc.towns | ForEach-Object { $_.slug })
$expected = @()
foreach ($t in $specDoc.towns) {
	foreach ($l in $t.locations) {
		$expected += [pscustomobject]@{ id = "$($t.slug)/$($l.slug)"; town = $t.slug; slug = $l.slug; png = "$($t.slug)/$($l.slug).png" }
	}
}
Write-Host "render_set: spec $Spec ($($expected.Count) locations, $($townSlugs.Count) towns, sha256 $($specSha.Substring(0,12)))"

if ($List) {
	$listArgs = "--list"
	if ($Only) { $listArgs = "$listArgs --only $Only" }
	& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Runner -Script "07_render_set.py" -Log "render_set_list.log" -Args $listArgs
	exit $LASTEXITCODE
}

# ---- the commit this snapshot belongs to -------------------------------------------------------------------------
Push-Location $RepoDir
try {
	$short = (& git rev-parse --short HEAD).Trim()
	$full = (& git rev-parse HEAD).Trim()
	$subject = (& git log -1 --pretty=%s).Trim()
	$commitDate = (& git log -1 --date=iso-strict --pretty=%cd).Trim()
	$branch = (& git rev-parse --abbrev-ref HEAD).Trim()
	# the outer @() matters: a clean tree makes Where-Object return $null, and $null.Count is an error
	$dirty = @(@(& git status --porcelain) | Where-Object { $_ -ne "" })
} finally { Pop-Location }
if (-not $short) { throw "git rev-parse --short HEAD produced nothing in $RepoDir" }

$OutRoot = $Out
if (-not $OutRoot) { $OutRoot = "$RepoDir/renders/$short" }
$OutRoot = $OutRoot -replace "\\", "/"
if ((Test-Path $OutRoot) -and -not $Force) {
	$have = @(Get-ChildItem -Recurse -Filter *.png -Path $OutRoot -ErrorAction SilentlyContinue)
	if ($have.Count -gt 0) {
		throw "$OutRoot already holds $($have.Count) PNG(s). A snapshot is the record of one commit: pass -Force to overwrite it, or commit first so the hash changes."
	}
}
New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null
foreach ($t in $townSlugs) { New-Item -ItemType Directory -Force -Path "$OutRoot/$t" | Out-Null }
Write-Host "render_set: commit $short ($branch) -> $OutRoot"
if ($dirty.Count -gt 0) {
	Write-Host "render_set: WARNING the worktree has $($dirty.Count) uncommitted change(s); this snapshot is NOT purely commit $short and the manifest records that." -ForegroundColor Yellow
}

# ---- render ------------------------------------------------------------------------------------------------------
$reportDir = "$ProjDir/Saved/Tests"
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
$batches = @()
if ($PerTown -and -not $Only) {
	foreach ($t in $townSlugs) { $batches += [pscustomobject]@{ name = $t; only = $t } }
} elseif ($PerTown -and $Only) {
	foreach ($t in ($Only -split ",")) { $b = $t.Trim(); if ($b) { $batches += [pscustomobject]@{ name = ($b -replace "[/,]", "_"); only = $b } } }
} else {
	$batches += [pscustomobject]@{ name = "all"; only = $Only }
}

$reports = @()
$batchInfo = @()
foreach ($b in $batches) {
	$rep = "$reportDir/render_set_$($b.name).json"
	if (Test-Path $rep) { Remove-Item $rep }
	$ueLog = "$ProjDir/Saved/Logs/render_set_$($b.name).log"
	$runnerOut = "$ProjDir/Saved/Logs/render_set_$($b.name).runner.txt"
	$a = "--out $OutRoot --report $rep"
	if ($b.only) { $a = "$a --only $($b.only)" }
	Write-Host ""
	Write-Host "=== render $($b.name)  ($([int]((Get-Date) - $T0).TotalSeconds) s elapsed)" -ForegroundColor Cyan
	& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Runner -Script "07_render_set.py" -Render -Log "render_set_$($b.name).log" -Args $a 2>&1 |
		Tee-Object -FilePath $runnerOut | Write-Host
	$exit = $LASTEXITCODE

	# run_ue_python.ps1 rewrites the engine's exit code to 0 whenever the Python script succeeded and the only
	# counted error is this machine's VC++ redistributable advisory. That override also swallows an ACCESS
	# VIOLATION at process teardown (measured 2026-09-09: raw exit -1073741819 = 0xC0000005 on a run whose images
	# and report were all present and correct, log clean, crash after "LogExit: Exiting"). So do not take exit 0
	# as proof: read the raw code back out, prove the script's own THANET_OK line is in the log, and record both.
	$rawExit = $exit
	$overridden = $false
	$m = Select-String -Path $runnerOut -Pattern "engine exit code (-?\d+) overridden" -ErrorAction SilentlyContinue | Select-Object -First 1
	if ($m) { $rawExit = [int]$m.Matches[0].Groups[1].Value; $overridden = $true }
	$crash = @()
	if (Test-Path $ueLog) {
		$crash = @(Select-String -Path $ueLog -Pattern "Critical error|Assertion failed|Fatal error|Unhandled Exception" -ErrorAction SilentlyContinue | ForEach-Object { $_.Line.Trim() })
	}
	$okLine = @(Select-String -Path $ueLog -Pattern "THANET_OK 07_render_set" -ErrorAction SilentlyContinue)
	$batchInfo += [ordered]@{
		name = $b.name; only = $b.only; ue_log = "Saved/Logs/render_set_$($b.name).log"
		exit_code = $exit; engine_exit_code_raw = $rawExit; exit_overridden_by_runner = $overridden
		thanet_ok_in_log = ($okLine.Count -gt 0); crash_markers = @($crash)
	}

	if ($exit -ne 0) {
		throw "render_set: FAILED on batch $($b.name) (exit $exit); see $ueLog"
	}
	if ($okLine.Count -eq 0) {
		throw "render_set: batch $($b.name) exited 0 but $ueLog has no THANET_OK line - the script did not finish, whatever the exit code says."
	}
	if ($crash.Count -gt 0) {
		throw "render_set: batch $($b.name) logged $($crash.Count) crash marker(s): $($crash[0]); see $ueLog"
	}
	if (-not (Test-Path $rep)) {
		throw "render_set: batch $($b.name) reported success but wrote no report at $rep - the runner's exit-code override can hide a crash, so this is treated as a failure."
	}
	if ($overridden -and $rawExit -ne 0 -and $rawExit -ne 1) {
		Write-Host "render_set: NOTE batch $($b.name) - the engine's raw exit code was $rawExit (0x$("{0:X8}" -f $rawExit)) and run_ue_python.ps1 overrode it to 0. The log is clean and every image was verified below, so this is a teardown crash after the work finished - but it is recorded in the manifest rather than hidden." -ForegroundColor Yellow
	}
	$reports += (Get-Content -Raw $rep | ConvertFrom-Json)
}

# ---- the manifest ------------------------------------------------------------------------------------------------
$images = @()
$rendered = @{}
foreach ($r in $reports) {
	foreach ($loc in $r.locations) {
		$abs = "$OutRoot/$($loc.png)"
		if (-not (Test-Path $abs)) { throw "render_set: the report claims $($loc.png) but there is no file at $abs" }
		$fi = Get-Item $abs
		$sha = (Get-FileHash -Algorithm SHA256 $abs).Hash.ToLower()
		$rendered[$loc.id] = $true
		$images += [ordered]@{
			id      = $loc.id
			town    = $loc.town
			slug    = $loc.slug
			kind    = $loc.kind
			title   = $loc.title
			png     = $loc.png
			bytes   = [int64]$fi.Length
			sha256  = $sha
			camera  = [ordered]@{
				camera_en          = $loc.camera_en
				subject_en         = $loc.subject_en
				camera_height_m    = $loc.camera_height_m
				local_m            = $loc.local_m
				ground_z_m         = $loc.ground_z_m
				ground_source      = $loc.ground_source
				eye_z_m            = $loc.eye_z_m
				eye_ue_cm          = $loc.eye_ue_cm
				bearing_deg        = $loc.bearing_deg
				yaw_deg            = $loc.yaw_deg
				pitch_deg          = $loc.pitch_applied_deg
				roll_deg           = $loc.roll_deg
				fov_deg            = $loc.fov_deg
				subject_distance_m = $loc.subject_distance_m
			}
			ground  = $loc.ground
			load    = [ordered]@{ centre_en = $loc.load_centre_en; radius_m = $loc.load_radius_m }
			guards  = [ordered]@{ distinct_rgb = $loc.distinct_rgb; mean_luminance = $loc.mean_luminance }
			# What the landscape's LOD chain was actually doing when this frame was drawn, read back off the
			# resident proxies rather than assumed from the spec. b1cd3e5's whole set was rendered with every
			# landscape component at its COARSEST LOD, because capture.landscape_lod0_screen_size 8.0 was
			# believed to mean the opposite of what it means, and nothing in that manifest could show it.
			landscape_lod = $loc.landscape_lod
		}
	}
}
# A full run must produce every location in the spec; a -Only run is asked for a subset the renderer
# resolved for itself, so "missing" is only meaningful for the full run. The renderer already fails on a
# selector that matched nothing, and the per-image existence check above already failed on a lost file.
$missing = @()
if (-not $Only) { $missing = @($expected | Where-Object { -not $rendered.ContainsKey($_.id) } | ForEach-Object { $_.id }) }
$requested = $expected.Count
if ($Only) { $requested = $images.Count }

$manifest = [ordered]@{
	schema_version   = 1
	what             = "One snapshot of projects/one/Tools/ue/render_set.json rendered at one commit. Compare two of these, never two loose directories of PNGs: identical spec sha256 plus identical camera blocks is the only proof that a visual difference is the MODEL changing rather than the camera. Per-image sha256 is a one-way filter - equal means the frame did not change, different does NOT mean it did, because the renderer is only nearly deterministic (measured 2026-09-09: an eye-level frame was byte-identical across two runs, an aerial differed in 9 of 1,440,000 pixels). See renders/README.md."
	commit           = $short
	commit_full      = $full
	commit_subject   = $subject
	commit_date_iso  = $commitDate
	branch           = $branch
	worktree_dirty   = ($dirty.Count -gt 0)
	worktree_changes = @($dirty)
	rendered_utc     = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
	render_seconds   = [int]((Get-Date) - $T0).TotalSeconds
	host             = $env:COMPUTERNAME
	engine_version   = $reports[0].engine_version
	map              = $reports[0].map
	renderer         = "projects/one/Tools/ue/07_render_set.py"
	driver           = "projects/one/Tools/render_set.ps1"
	spec             = [ordered]@{
		path           = "projects/one/Tools/ue/render_set.json"
		sha256         = $specSha
		schema_version = $specDoc.schema_version
		locations      = $expected.Count
		towns          = @($townSlugs)
	}
	landscape_dir    = $reports[0].landscape_dir
	capture          = $reports[0].capture
	origin           = $reports[0].origin
	batches          = @($batchInfo)
	batches_note     = "engine_exit_code_raw is the code UnrealEditor-Cmd actually returned; run_ue_python.ps1 rewrites it to 0 when the Python script succeeded and the only counted engine error is this machine's VC++ redistributable advisory. A non-zero raw code on a batch whose thanet_ok_in_log is true, whose crash_markers are empty and all of whose images passed the checks below is a teardown crash after the work finished. It is recorded here so nobody has to rediscover it."
	only             = $Only
	counts           = [ordered]@{
		expected_in_spec = $expected.Count
		requested        = $requested
		rendered         = $images.Count
		missing          = @($missing)
		partial          = ($images.Count -lt $expected.Count)
	}
	images           = @($images)
}
$json = ($manifest | ConvertTo-Json -Depth 12) -replace "`r`n", "`n"
if (-not $json.EndsWith("`n")) { $json = "$json`n" }
[IO.File]::WriteAllText("$OutRoot/manifest.json", $json, (New-Object Text.UTF8Encoding $false))

if ($missing.Count -gt 0) { throw "render_set: $($missing.Count) requested image(s) never appeared: $($missing -join ', ')" }
$small = @($images | Where-Object { $_.bytes -lt 51200 })
if ($small.Count -gt 0) {
	throw "render_set: $($small.Count) image(s) under 50 KB ($(($small | ForEach-Object { $_.png }) -join ', ')) - a frame that small is empty, not a render."
}
Write-Host ""
Write-Host "render_set: $($images.Count) image(s) at commit $short in $([int]((Get-Date) - $T0).TotalSeconds) s" -ForegroundColor Green
Write-Host "render_set: $OutRoot/manifest.json"
if ($images.Count -lt $expected.Count) {
	Write-Host "render_set: PARTIAL snapshot ($($images.Count) of $($expected.Count)); manifest.counts.partial is true." -ForegroundColor Yellow
}
