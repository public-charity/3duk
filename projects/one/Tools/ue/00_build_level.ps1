# 00_build_level.ps1 - rebuild the whole Thanet level from the adapter output with ONE command, then assert what
# is in it. Before this existed the level was a hand-assembled artefact in an ignored directory: four scripts run
# by hand in an order nobody had written down, no check that the result was complete, and (measured 2026-09-08)
# an actor that vanished from it between two read-only-looking gate runs with nobody able to say when.
#
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File Tools/ue/00_build_level.ps1
#       [-Data C:/Users/Shadow/code/3duk/data/thanet/out/unreal]
#       [-Map /Game/Thanet/Maps/Thanet]
#       [-Recreate]                # delete the map first and build it from nothing (the honest full rebuild)
#       [-SkipLandscape] [-SkipStreetscape] [-SkipMassing] [-SkipTestStretch]
#       [-AllowSeamH16 <n>]        # tolerance for the shared tile edge; 0 = must be identical, <0 = waive it
#       [-StreetscapeSlices 12]    # the site import is split over this many commandlets so memory stays bounded
#       [-MaxComponents 256]       # 0 imports all 2067 components in one call, which exhausted the GPU on this box:
#                                  # 256 takes the 16x16-component region path of UE_PLAN 3.7 (12 regions for Thanet)
#       [-AllowNoTerrain <n>]      # accept up to n splines with no ground under any station (they build flat at z=0)
#       [-AssertOnly]              # run no import, only the assertion pass over the level as it stands
#
# Steps, in the only order that works (each is a separate commandlet; a step that fails stops the run):
#   1 01_bootstrap.py            materials, 20 profile DataAssets, the World Partition map, sky/sun/fog, site actor
#   2 02_import_landscape.py     the 391-tile ALandscape + weightmaps + the clip hole, then its own three gates
#   3 03_import_streetscape.py   the authored test stretch + the PlayerStart (BRIEF's first deliverable)
#   4 06_import_massing.py       one massing actor per buildings_x*_y*.jsonl
#   5 03_import_streetscape.py   every site_x*_y*.json under <Data>/streetscape, in slices (~1 h at site scale)
#   6 assert                     counts read back out of the level against the adapter's own manifests
#
# The assertion pass is the point: it re-opens the saved map in a fresh commandlet, streams the whole world in and
# compares landscape components / proxies, streetscape actor count and massing actor and building counts against
# landscape_manifest.json, streetscape_manifest.json and massing_manifest.json. Anything short of that is a
# claim, not a check.
param(
	[string]$Data = "C:/Users/Shadow/code/3duk/data/thanet/out/unreal",
	[string]$Map = "/Game/Thanet/Maps/Thanet",
	[switch]$Recreate,
	[switch]$SkipLandscape,
	[switch]$SkipStreetscape,
	[switch]$SkipMassing,
	[switch]$SkipTestStretch,
	[int]$AllowSeamH16 = 0,
	[int]$StreetscapeSlices = 12,
	[int]$MaxComponents = 256,
	[int]$AllowNoTerrain = 0,
	[switch]$AssertOnly
)
$ErrorActionPreference = "Stop"
$ToolsDir = ((Resolve-Path "$PSScriptRoot").Path -replace "\\", "/")
# Forward slashes throughout. These paths are passed on inside the runner's -script="<py> <args>" string, and a
# Windows path whose next character is a digit (this repo lives under ...\code\3duk) comes back out of that
# parsing with the backslash-3 read as an octal escape (chr(3)). It cost one 6-minute landscape import to find.
$ProjDir = ((Resolve-Path "$PSScriptRoot\..\..").Path -replace "\\", "/")
$Runner = Join-Path $ToolsDir "run_ue_python.ps1"
$T0 = Get-Date

function Step([string]$Name, [string]$Script, [string]$ScriptArgs, [switch]$Render) {
	Write-Host ""
	Write-Host "=== $Name  ($([int]((Get-Date) - $T0).TotalSeconds) s elapsed)" -ForegroundColor Cyan
	$log = "build_level_$Name.log"
	# an EMPTY -Args value is a PowerShell parameter-binding error ("Missing an argument for parameter 'ScriptArgs'"),
	# so a step with no arguments must not pass the switch at all
	$common = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Runner, "-Script", $Script, "-Log", $log)
	if ($ScriptArgs) { $common += @("-Args", $ScriptArgs) }
	if ($Render) { $common += "-Render" }
	& powershell.exe @common
	if ($LASTEXITCODE -ne 0) {
		Write-Host "00_build_level: FAILED at $Name (exit $LASTEXITCODE); see $ProjDir/Saved/Logs/$log" -ForegroundColor Red
		exit $LASTEXITCODE
	}
}

# ---- how many of everything the adapter says there should be ----------------------------------------------------
$lm = Get-Content -Raw "$Data/landscape/landscape_manifest.json" | ConvertFrom-Json
$sm = Get-Content -Raw "$Data/streetscape/streetscape_manifest.json" | ConvertFrom-Json
$mm = Get-Content -Raw "$Data/massing/massing_manifest.json" | ConvertFrom-Json
$expectSplines = 0
foreach ($p in $sm.splines_by_layer.PSObject.Properties) { $expectSplines += [int]$p.Value }
# the authored test stretch is one more actor than the adapter's site documents describe
if (-not $SkipTestStretch) { $expectSplines += 1 }
Write-Host "00_build_level: expecting landscape tiles $($lm.tiles.Count), streetscape actors $expectSplines, massing actors $($mm.files) / $($mm.buildings) buildings"

if (-not $AssertOnly) {
	$bootArgs = ""
	if ($Recreate) { $bootArgs = "--recreate" }
	Step "1_bootstrap" "01_bootstrap.py" $bootArgs

	if (-not $SkipLandscape) {
		Step "2_landscape" "02_import_landscape.py" "--manifest $Data/landscape/landscape_manifest.json --max-components $MaxComponents --max-shared-edge-h16 $AllowSeamH16 --report $ProjDir/Saved/Tests/build_level_landscape.json" -Render
	}
	if (-not $SkipTestStretch) {
		Step "3_test_stretch" "03_import_streetscape.py" "--json $ProjDir/schema/examples/test_stretch.json --player-start --save --stats-limit 1 --stats-out $ProjDir/Saved/Tests/build_level_trinity.stats.json --set-game-mode /Script/Thanet.ThanetGameMode"
	}
	if (-not $SkipMassing) {
		Step "4_massing" "06_import_massing.py" "--dir $Data/massing"
	}
	if (-not $SkipStreetscape) {
		# One commandlet per slice: every actor a run imports stays resident until it exits, and 15,422
		# UDynamicMeshComponents at once does not fit in 28 GB. Each slice preloads nothing (the level holds no
		# actor for its ids on a fresh build) and saves before it exits.
		for ($i = 1; $i -le $StreetscapeSlices; $i++) {
			Step "5_streetscape_$i" "03_import_streetscape.py" "--json $Data/streetscape --slice $i/$StreetscapeSlices --no-preload --save --stats-limit 1 --allow-no-terrain $AllowNoTerrain"
		}
	}
}

# ---- the assertion pass ------------------------------------------------------------------------------------------
# --no-load-all: the counts come from the World Partition external-actor packages, which is the only way to count
# 15,422 actors without streaming them all in. Drop it for the landscape component count.
Step "6_assert" "07_assert_level.py" "--data $Data --map $Map --expect-streetscape-actors $expectSplines --no-load-all --out $ProjDir/Saved/Tests/build_level_assert.json"
Step "7_assert_landscape" "07_assert_level.py" "--data $Data --map $Map --expect-streetscape-actors $expectSplines --census-only --out $ProjDir/Saved/Tests/build_level_assert_loaded.json" -Render
Write-Host ""
Write-Host "00_build_level: level rebuilt and asserted in $([int]((Get-Date) - $T0).TotalSeconds) s" -ForegroundColor Green
