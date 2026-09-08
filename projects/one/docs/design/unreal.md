# Unreal Engine 5.8 project + Streetscape plugin — file-by-file design

Design-phase output for BRIEF.md section 4.4 (binding) and questions 1, 2, 3, 8, 9, 10 of section 6.
Every engine API below was verified by grepping the installed 5.8.2 headers on 2026-09-07; every
citation is `path:line` under the roots in the table below. Repo facts are cited the same way.

| Alias | Root |
|---|---|
| `UE` | `C:/Program Files/Epic Games/UE_5.8/Engine` |
| `ENG` | `UE/Source/Runtime/Engine` |
| `LS` | `UE/Source/Runtime/Landscape` |
| `LSE` | `UE/Source/Editor/LandscapeEditor` |
| `UED` | `UE/Source/Editor/UnrealEd` |
| `GF` | `UE/Source/Runtime/GeometryFramework/Public` |
| `GC` | `UE/Source/Runtime/GeometryCore/Public` |
| `CORE` | `UE/Source/Runtime/Core/Public` |
| `PSP` | `UE/Plugins/Experimental/PythonScriptPlugin/Source/PythonScriptPlugin` |
| `EI` | `UE/Plugins/EnhancedInput/Source/EnhancedInput/Public` |
| `MCP` | `C:/UnrealProjects/unreal-mcp/MCPGameProject/Plugins/UnrealMCP` |
| `P1` | `C:/Users/Shadow/code/3duk/projects/one` |

Frame conventions used throughout (BRIEF 4.2, binding): the plugin computes all geometry in the
**Streetscape-JSON frame** (local metres from the site origin, X east, Y north, Z ODN metres,
right-handed) and converts to Unreal exactly once, `FVector(100*x, -100*y, 100*z)`, inside
`FStreetscapeJson` (splines/profiles) and `UStreetscapeLandscapeImporter` (heightfield). The
mirror in Y flips handedness, so triangle winding is reversed at that conversion point (see 2.7).
GeoReferencing's FlatPlanet mode does the same multiply (`UE/Plugins/Runtime/GeoReferencing/Source/GeoReferencing/Private/GeoReferencingSystem.cpp:235` and `:292`, `FVector(100.0, -100.0, 100.0)`); we do not depend on that plugin (justified in 1.1).

---

## 0. Decisions in one screen

| # | Decision | Why (details in the section given) |
|---|---|---|
| D1 | Landscape: **one `ALandscapeProxy::Import` call** for the whole padded heightfield, then `ULandscapeSubsystem::ChangeGridSize`. | Import writes component textures CPU-side and requires an empty landscape (`LS/Private/LandscapeEdit.cpp:3155 check(LandscapeComponents.Num()==0)`), so it cannot be split; memory fits (3.4). The editor's "regions" flow needs `FEdModeLandscape` (not available in a commandlet). §3 |
| D2 | Component config **127 quads/section x 2 sections = 254 quads (256-texel textures)**, 53 x 39 = 2067 components, padded 13463 x 9907, padding on the **east and north**, filled with water level h16 = 32691 and visibility 255. | Epic's documented large-world configuration; finer LOD/culling than the 255x2 the helper picks (§3.2 explains what `ChooseBestComponentSizeForImport` returns and why we override). |
| D3 | World Partition landscape grid size **4 components** (1016 m proxies, 14 x 10 = 140 streaming proxies). | 140 OFPA actors instead of 540; each proxy ~1 km matches two pipeline tiles. §3.3 |
| D4 | Hole mask via the engine **visibility layer**: weight **255 = hole**, 0 = visible; material mask = `1 - weight` (`LS/Private/Materials/MaterialExpressionLandscapeVisibilityMask.cpp:46`), mesh/collision threshold 2/3 (`LS/Public/LandscapeDataAccess.h:19`). | Closes Q2. §3.5 |
| D5 | Terrain sampling for splines: **`IStreetTerrainSource` with the heightfield-file implementation as primary**, landscape implementation for validation. | Deterministic, identical to Blender, works before/without WP cells loaded (commandlets skip region loading, `ENG/Private/WorldPartition/WorldPartition.cpp:880`). Closes Q3. §2.5 |
| D6 | Renderers **subclass `UDynamicMeshComponent`** (not a UActorComponent owning a child). | The constructor is exported (`UE/Intermediate/Build/Win64/UnrealEditor/Inc/GeometryFramework/UHT/DynamicMeshComponent.generated.h:62`), so subclassing links; no instanced-child lifetime/undo problems; material slots editable in details. §2.6 |
| D7 | **One `AStreetscapeActor` per Streetscape-JSON spline** (= one per step-06 tile-split way segment), meshes **rebuilt on load**, not serialized. | ~30k small actors is inside WP design range; serialized DynamicMeshes would cost ~2 GB on disk. Closes Q8. §2.9 |
| D8 | Spline: **wrap `USplineComponent`** for gizmos/editing, per-point attributes in a `USplineMetadata` subclass (the Water plugin pattern), **resampling is our own code** shared 1:1 with the numpy prototype. | Guarantees Blender/Unreal geometry parity; FInterpCurve internals never define the road. §2.4 |
| D9 | Debug overlay: persistent **line batcher with a per-actor BatchID**, re-issued in `OnRegister`, cleared in `OnUnregister`. | Zero geometry, survives save/reload because the polyline is a UPROPERTY, toggleable. §2.8 |
| D10 | UnrealMCP: source-only copy; port from a `UDeveloperSettings` (`Port=55558` for Thanet), **no server in commandlets**, and **remove `SetReuseAddr(true)`** so a real conflict fails loudly and the editor continues. | Closes Q10. §6 |
| D11 | Explorer: `ACharacter` with `MOVE_Flying` toggle; Enhanced Input assets **built in C++ at runtime** (no binary assets). | Closes Q9. §7 |
| D12 | Every editor step runs headless via `UnrealEditor-Cmd.exe ... -run=pythonscript -script=...`; landscape import and screenshots run with `-AllowCommandletRendering`. | Edit-layer GPU merge requires `FApp::CanEverRender()` (`LS/Private/LandscapeEditLayers.cpp:7051`). §5 |

---

## 1. The Unreal project (`P1/`)

### 1.1 `P1/Thanet.uproject`

```json
{
	"FileVersion": 3,
	"EngineAssociation": "5.8",
	"Category": "",
	"Description": "Isle of Thanet explorer - Project One (3duk)",
	"Modules": [
		{ "Name": "Thanet", "Type": "Runtime", "LoadingPhase": "Default" }
	],
	"Plugins": [
		{ "Name": "Streetscape", "Enabled": true },
		{ "Name": "UnrealMCP", "Enabled": true, "TargetAllowList": [ "Editor" ] },
		{ "Name": "PythonScriptPlugin", "Enabled": true },
		{ "Name": "EditorScriptingUtilities", "Enabled": true },
		{ "Name": "ModelingToolsEditorMode", "Enabled": true, "TargetAllowList": [ "Editor" ] },
		{ "Name": "EnhancedInput", "Enabled": true },
		{ "Name": "GeometryScripting", "Enabled": false },
		{ "Name": "GeoReferencing", "Enabled": false },
		{ "Name": "Water", "Enabled": false }
	]
}
```

Rationale per plugin:
- `Streetscape`, `UnrealMCP`: ours / our copy (§2, §6). `UnrealMCP.uplugin` declares an Editor module (`MCP/UnrealMCP.uplugin` lines 18-27), so `TargetAllowList: Editor` keeps it out of any future game build.
- `PythonScriptPlugin` (Experimental): the headless driver. `EditorScriptingUtilities`: `UEditorLevelLibrary`/`UEditorAssetLibrary` used by the bootstrap (`UE/Plugins/Editor/EditorScriptingUtilities/Source/EditorScriptingUtilities/Public/EditorAssetLibrary.h:281 SaveAsset`, `:292 SaveDirectory`).
- `ModelingToolsEditorMode`: as the blank template (`UE/Templates/TP_Blank/TP_Blank.uproject`), editor only; handy for inspecting DynamicMeshes.
- `EnhancedInput`: the pawn (§7). Listed explicitly even though the engine enables it by default.
- `GeometryScripting`: **not needed** — the plugin builds meshes against `FDynamicMesh3` (GeometryCore) and `UDynamicMeshComponent` (GeometryFramework), both core engine modules (BRIEF 4.4). Left disabled so a later Python-side mesh experiment can flip one flag.
- `GeoReferencing`: **not enabled.** It would add an `AGeoReferencingSystem` actor + PROJ dependency to express what is a one-line multiply in our loader; nothing in stage 1-8 needs geodetic conversions in-engine (the pipeline already emits EPSG:27700 metres). Revisit when a coordinates HUD or real-world camera placement is wanted.
- `Water`: not yet (BRIEF).

### 1.2 `P1/Source/Thanet.Target.cs` and `P1/Source/ThanetEditor.Target.cs`

Copied from the proven 5.8 skeleton (`C:/UnrealProjects/unreal-mcp/MCPGameProject/Source/MCPGameProject.Target.cs`, `MCPGameProjectEditor.Target.cs`; identical to `UE/Templates/TP_Blank/Source/TP_Blank.Target.cs`). `V7` + `Unreal5_8` are mandatory: the memory notes record that `V5`/`Unreal5_5` fail against the installed shared build environment.

```csharp
// Thanet.Target.cs
using UnrealBuildTool;
using System.Collections.Generic;
public class ThanetTarget : TargetRules
{
	public ThanetTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.V7;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_8;
		ExtraModuleNames.Add("Thanet");
	}
}
// ThanetEditor.Target.cs
public class ThanetEditorTarget : TargetRules
{
	public ThanetEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.V7;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_8;
		ExtraModuleNames.Add("Thanet");
	}
}
```

### 1.3 `P1/Source/Thanet/Thanet.Build.cs`

```csharp
using UnrealBuildTool;
public class Thanet : ModuleRules
{
	public Thanet(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] {
			"Core", "CoreUObject", "Engine", "InputCore", "EnhancedInput" });
		PrivateDependencyModuleNames.AddRange(new string[] { });
	}
}
```
The game module deliberately does **not** depend on `Streetscape`: the explorer needs only a
`PlayerStart`, which the import script places (§7.4). Files: `Thanet.h/.cpp`
(`IMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, Thanet, "Thanet")`, as
`UE/Templates/TP_Blank/Source/TP_Blank/TP_Blank.cpp`), `ThanetGameMode.h/.cpp`,
`ThanetExplorerPawn.h/.cpp`, `ThanetExplorerInput.h/.cpp` (§7).

C4459 note (memory): under V7 a file-scope `const int32 BufferSize` collided with a local in
`StringConv.h`. Rule for all our code: no file-scope non-`static`/non-namespaced constants; use
`namespace Streetscape::Private { constexpr ... }`.

### 1.4 `P1/Config/DefaultEngine.ini`

```ini
[/Script/EngineSettings.GameMapsSettings]
EditorStartupMap=/Game/Thanet/Maps/Thanet.Thanet
GameDefaultMap=/Game/Thanet/Maps/Thanet.Thanet
GlobalDefaultGameMode=/Script/Thanet.ThanetGameMode

[/Script/Engine.RendererSettings]
r.AllowStaticLighting=False
r.Shadow.Virtual.Enable=1
r.DynamicGlobalIlluminationMethod=1
r.ReflectionMethod=1
r.GenerateMeshDistanceFields=True
r.RayTracing=False
r.DefaultFeature.AutoExposure.ExtendDefaultLuminanceRange=True

[/Script/WindowsTargetPlatform.WindowsTargetSettings]
DefaultGraphicsRHI=DefaultGraphicsRHI_DX12
-D3D12TargetedShaderFormats=PCD3D_SM5
+D3D12TargetedShaderFormats=PCD3D_SM6
-D3D11TargetedShaderFormats=PCD3D_SM5
+D3D11TargetedShaderFormats=PCD3D_SM5
Compiler=Default
AudioSampleRate=48000
AudioCallbackBufferFrameSize=1024

[/Script/LinuxTargetPlatform.LinuxTargetSettings]
-TargetedRHIs=SF_VULKAN_SM5
+TargetedRHIs=SF_VULKAN_SM6

[/Script/HardwareTargeting.HardwareTargetingSettings]
TargetedHardwareClass=Desktop
AppliedTargetedHardwareClass=Desktop
DefaultGraphicsPerformance=Maximum
AppliedDefaultGraphicsPerformance=Maximum

[/Script/PythonScriptPlugin.PythonScriptPluginSettings]
+AdditionalPaths=(Path="Tools/ue")
bDeveloperMode=True

[/Script/UnrealMCP.UnrealMCPSettings]
Port=55558
bStartInEditor=True
bStartInCommandlets=False
```

Why each block:
- **Maps**: `GameDefaultMap`/`EditorStartupMap`/`GlobalDefaultGameMode` are the `UGameMapsSettings` properties (`UE/Source/Runtime/EngineSettings/Classes/GameMapsSettings.h:159, :209, :217`). The template points `GameDefaultMap` at `/Engine/Maps/Templates/OpenWorld` (`UE/Templates/TP_Blank/Config/DefaultEngine.ini`); we point straight at the map the bootstrap generates. Until `01_bootstrap.py` has run the editor opens an empty level with a "map not found" warning — acceptable, and commandlets never load the startup map. The map is created as an **empty** World Partition world (`ULevelEditorSubsystem::NewLevel(path, bIsPartitionedWorld=true)`, `UE/Source/Editor/LevelEditor/Public/LevelEditorSubsystem.h:146-147`, UFUNCTION → `UEditorEngine::NewMap(true)` `UED/Private/EditorServer.cpp:2187`, `Factory->bCreateWorldPartition` `:2212`, `UED/Classes/Factories/WorldFactory.h:24`) rather than from the OpenWorld template, because that template ships 138 external actors (`UE/Content/__ExternalActors__/Maps/Templates/OpenWorld`, counted) including its own landscape that we would have to delete.
- **Renderer**: DX12 + SM6 + VSM exactly as the blank template; Lumen GI/reflections (`=1`) written explicitly rather than relying on defaults so the base is deterministic; mesh distance fields on for Lumen software tracing of DynamicMeshes; hardware ray tracing **off** for the base (one fewer moving part; A4500 supports it, flip later).
- **Python**: `UPythonScriptPluginSettings` is `config=Engine, defaultconfig` (`PSP/Private/PythonScriptPluginSettings.h:48-49`); `AdditionalPaths` (`:70-71`, `RelativePath` meta → relative to the project) puts `Tools/ue` on `sys.path` so scripts can `import ue_common`; `bDeveloperMode` (`:90-91`) generates the `unreal.py` stub into `Intermediate/PythonStub/` — the way to look up exact Python method names (they are the UFUNCTION names pythonized to snake_case by `PSP/Private/PyGenUtil.cpp:1859 PythonizeName`).
- **UnrealMCP**: our new settings class (§6).

### 1.5 `P1/Config/DefaultGame.ini`

```ini
[/Script/EngineSettings.GeneralProjectSettings]
ProjectID=<GUID: generate once with PowerShell [guid]::NewGuid() and paste>
ProjectName=Thanet
CompanyName=3duk
Description=Isle of Thanet explorer base (Project One)
```

### 1.6 `P1/Config/DefaultInput.ini`

```ini
[/Script/Engine.InputSettings]
DefaultPlayerInputClass=/Script/EnhancedInput.EnhancedPlayerInput
DefaultInputComponentClass=/Script/EnhancedInput.EnhancedInputComponent
bEnableMouseSmoothing=True
```
Required: the engine's own defaults are the legacy classes (`ENG/Private/UserInterface/InputSettings.cpp:52-53`); without these two lines `CastChecked<UEnhancedInputComponent>(PlayerInputComponent)` in the pawn fails.

### 1.7 `P1/Config/DefaultEditor.ini`

Empty apart from a header comment. Nothing project-wide is needed; per-user editor prefs
(autosave, WP "load last regions") stay out of the repo. Kept so the four-file layout in BRIEF 4.3 exists.

---

## 2. `P1/Plugins/Streetscape`

### 2.1 `Streetscape.uplugin`

```json
{
	"FileVersion": 3,
	"Version": 1,
	"VersionName": "0.1",
	"FriendlyName": "Streetscape",
	"Description": "Data-driven procedural streetscape: shared splines + profile assets -> road, edge (kerb/pavement/barriers) and hedge renderers on UDynamicMeshComponent; JSON interchange with the Blender prototype; landscape importer.",
	"Category": "Procedural",
	"CreatedBy": "3duk / Project One",
	"CanContainContent": false,
	"IsBetaVersion": true,
	"Installed": false,
	"Modules": [
		{ "Name": "Streetscape",       "Type": "Runtime", "LoadingPhase": "Default",  "PlatformAllowList": [ "Win64" ] },
		{ "Name": "StreetscapeEditor", "Type": "Editor",  "LoadingPhase": "Default",  "PlatformAllowList": [ "Win64" ] }
	],
	"Plugins": [
		{ "Name": "PythonScriptPlugin", "Enabled": true },
		{ "Name": "EditorScriptingUtilities", "Enabled": true }
	]
}
```
`PlatformAllowList` is the current key; `WhitelistPlatforms` is only accepted as a deprecated fallback (`UE/Source/Runtime/Projects/Private/ModuleDescriptor.cpp:197`). `CanContainContent:false` — all assets live under the project (`/Game/Thanet/...`) and are regenerated by scripts.

### 2.2 `Source/Streetscape/Streetscape.Build.cs` (runtime)

```csharp
public class Streetscape : ModuleRules
{
	public Streetscape(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		IWYUSupport = IWYUSupport.Full;
		PublicDependencyModuleNames.AddRange(new string[] {
			"Core", "CoreUObject", "Engine",
			"GeometryCore",        // FDynamicMesh3, FMeshNormals (GC/DynamicMesh/*)
			"GeometryFramework",   // UDynamicMeshComponent, UDynamicMesh (GF/*)
			"Json", "JsonUtilities",
			"Landscape"            // ALandscapeProxy::GetHeightAtLocation for UStreetLandscapeTerrain (LS/Classes/LandscapeProxy.h:1101)
		});
		PrivateDependencyModuleNames.AddRange(new string[] { "RenderCore", "RHI" });
	}
}
```
`Landscape` is a runtime module, so sampling the landscape at runtime is legitimate; everything that needs `LandscapeEditor` lives in the editor module.

### 2.3 `Source/StreetscapeEditor/StreetscapeEditor.Build.cs` (editor)

```csharp
public class StreetscapeEditor : ModuleRules
{
	public StreetscapeEditor(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		IWYUSupport = IWYUSupport.Full;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "Streetscape" });
		PrivateDependencyModuleNames.AddRange(new string[] {
			"UnrealEd",            // FEditorFileUtils/UEditorLoadingAndSavingUtils (UED/Public/FileHelpers.h), FActorLabelUtilities (UED/Classes/Editor/EditorEngine.h:3429)
			"LevelEditor", "ToolMenus", "PropertyEditor", "EditorSubsystem", "EditorFramework",
			"Slate", "SlateCore",
			"Landscape", "LandscapeEditor",   // FLandscapeImportHelper (LSE/Public/LandscapeImportHelper.h), LandscapeEditorUtils (LSE/Public/LandscapeEditorUtils.h)
			"AssetRegistry", "AssetTools",
			"Json", "JsonUtilities", "Projects"
		});
	}
}
```

### 2.4 File tree

```
Plugins/Streetscape/
  Streetscape.uplugin
  Source/Streetscape/
    Streetscape.Build.cs
    Public/
      StreetscapeModule.h                 IModuleInterface, log category LogStreetscape
      StreetTypes.h                       enums + USTRUCT rows (2.5.1)
      StreetProfiles.h                    UStreetProfileBase/URoadProfile/UEdgeProfile/UHedgeProfile + payload structs (2.5.2)
      StreetMaterialTable.h               UStreetMaterialTable (id -> material) (2.5.3)
      StreetSpline.h                      UStreetSplineMetadata, UStreetSplineComponent, FStreetSample(s), FStreetSamplingParams (2.5.4)
      StreetTerrainSource.h               IStreetTerrainSource, UStreetHeightfieldTerrain, UStreetLandscapeTerrain (2.5.5)
      StreetGeometry.h                    FStreetMeshBuffers, FStreetSweep, FStreetStations (pure C++, no UObject) (2.7)
      StreetRenderers.h                   UStreetRendererBase, UStreetRoadRenderer, UStreetEdgeRenderer, UStreetHedgeRenderer (2.6)
      StreetOverlayComponent.h            OSM polyline overlay (2.8)
      StreetscapeActor.h                  AStreetscapeActor (2.9)
      StreetscapeSiteActor.h              AStreetscapeSiteActor (site origin, terrain source, tables) (2.10)
      StreetscapeJson.h                   FStreetscapeJson: load/save, the frame conversion (2.11)
    Private/  (one .cpp per header) + Tests/StreetSplineTests.cpp, StreetRoadTests.cpp, StreetEdgeTests.cpp, StreetJsonTests.cpp (2.13)
  Source/StreetscapeEditor/
    StreetscapeEditor.Build.cs
    Public/
      StreetscapeEditorModule.h           FStreetscapeEditorModule: ToolMenus entry (2.12)
      StreetscapeLandscapeImporter.h      UStreetscapeLandscapeImporter (UBlueprintFunctionLibrary) (§3, 2.12)
      StreetscapeEditorLibrary.h          UStreetscapeEditorLibrary: ImportProfiles, ImportStreetscapeJson, LoadRegion, probes (2.12)
    Private/ (matching .cpp)
```

### 2.5 Runtime classes

#### 2.5.1 `StreetTypes.h` — enums and USTRUCT rows

All distances are metres (`...M`), angles degrees (`...Deg`), arc-length `S...M` along the shared
spline, lateral offsets positive to the **right** of travel direction. Fields are `UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Streetscape")` unless noted; JSON keys are the snake_case of the property name without the `b` prefix (2.11).

```cpp
UENUM(BlueprintType) enum class EStreetRoadKind : uint8 { Road, Rail };
UENUM(BlueprintType) enum class EStreetMarkingPattern : uint8 { None, Solid, Dashed, Double };
UENUM(BlueprintType) enum class EStreetMarkingAnchor : uint8 { Centre, LeftEdge, RightEdge }; // OffsetM measured from this line; edge anchors track width changes
UENUM(BlueprintType) enum class EStreetBarrierType : uint8 { BrickWall, RetainingWall, Fence, ChainLink, Railing };
UENUM(BlueprintType) enum class EStreetEmbankmentType : uint8 { Slope, RetainingWall };
UENUM(BlueprintType) enum class EStreetSide : uint8 { Left, Right };

USTRUCT(BlueprintType) struct FStreetMarking {
	FName Id;                                   // "double_yellow_left"
	EStreetMarkingAnchor Anchor = Centre;
	double OffsetM = 0.0;                       // from Anchor line; for edge anchors: inward distance from the carriageway edge
	double WidthM = 0.10;                       // TSRGD standard 100 mm line
	EStreetMarkingPattern Pattern = Solid;
	double DashM = 2.0, GapM = 7.0, PhaseM = 0.0;   // TSRGD diag. 1004 centre line: 2 m mark / 7 m gap
	double DoubleGapM = 0.10;                   // clear gap between the two lines of a Double
	FName Material = "paint_white";             // id in UStreetMaterialTable
	double S0M = 0.0, S1M = -1.0;               // arc-length range; S1M < 0 = to end
};
USTRUCT(BlueprintType) struct FStreetDropKerb {
	double SM = 0.0;            // centre of the dropped run
	double FlatLengthM = 2.4;   // length at TargetHeight
	double RampLengthM = 1.0;   // each side
	double TargetHeightM = 0.0; // kerb upstand at the drop (0 = flush; UK vehicle crossings often 0.025)
};
USTRUCT(BlueprintType) struct FStreetBarrierSegment {
	double S0M = 0.0, S1M = 0.0;
	EStreetBarrierType Type = BrickWall;
	double HeightM = 1.2, ThicknessM = 0.225;   // 225 mm = one brick
	double LateralOffsetM = 0.0;                // outward from the pavement's outer edge (or kerb outer face if no pavement)
	double PostPitchM = 2.5;                    // Railing/ChainLink/Fence posts
	FName Material = "brick_red";               // secondary material (mesh/rails) from the table: "<Material>_secondary" if present
};
USTRUCT(BlueprintType) struct FStreetEmbankment {
	double S0M = 0.0, S1M = 0.0;
	EStreetEmbankmentType Type = Slope;
	double MaxSlopeDeg = 34.0;                  // 1:1.5 grass batter
	double WallThicknessM = 0.30;
	double MinHeightDiffM = 0.15;               // below this difference nothing is generated
	FName Material = "grass";
};
USTRUCT(BlueprintType) struct FStreetHedgeSegment {
	double S0M = 0.0, S1M = 0.0;
	double WidthM = 0.9, HeightM = 1.6;
	double LateralOffsetM = 0.0;                // outward from the pavement's outer edge, like barriers (so it stacks beside a wall)
	double CornerRadiusM = 0.15;                // rounded box
	double NoiseAmpM = 0.04, NoiseScaleM = 0.35;// surface displacement
	int32 LeafCardsPerM2 = 40;                  // instanced leaf cards on the surface (Renderer C, stage 6)
	FName Material = "privet";
};
USTRUCT(BlueprintType) struct FStreetRailSpec {
	double GaugeM = 1.435;
	double RailHeadWidthM = 0.072, RailHeightM = 0.159, RailFootWidthM = 0.140;   // BS 113A / 56E1
	double SleeperLengthM = 2.5, SleeperWidthM = 0.25, SleeperHeightM = 0.15, SleeperPitchM = 0.65;
	double BallastTopWidthM = 3.4, BallastDepthM = 0.30, BallastShoulderSlope = 1.5; // horizontal:vertical
	FName RailMaterial = "steel_rail", SleeperMaterial = "concrete_sleeper", BallastMaterial = "ballast";
};
```

#### 2.5.2 `StreetProfiles.h` — profile DataAssets

```cpp
USTRUCT(BlueprintType) struct FRoadProfileData {
	EStreetRoadKind Kind = Road;
	int32 Lanes = 2;
	TArray<double> LaneWidthsM = {3.0, 3.0};    // used when WidthM <= 0
	double WidthM = 6.0;                         // total carriageway; a spline waypoint width overrides it per segment
	bool bCrowned = true; double CamberPct = 2.5; // crossfall from crown to each edge (UK 2.5 %)
	FName SurfaceMaterial = "tarmac";
	TArray<FStreetMarking> Markings;
	FStreetRailSpec Rail;                        // used when Kind == Rail
	double OverlapM = 0.03;                      // road extends this far past the kerb face line (seam rule, >= 3 cm)
	double UvScaleM = 4.0;                       // world metres per UV unit along s
};
USTRUCT(BlueprintType) struct FEdgeProfileData {
	double KerbWidthM = 0.125, KerbHeightM = 0.125, KerbTuckM = 0.02, KerbLipChamferM = 0.02;
	double PavementWidthM = 1.8, PavementCrossfallPct = 2.0;  // falls towards the kerb
	bool bSplitMaterial = false;                 // half-grass/half-tarmac: outer face + pavement top use OuterMaterial, inner face InnerMaterial, both flush at the top
	FName KerbMaterialInner = "kerb_concrete", KerbMaterialOuter = "kerb_concrete", PavementMaterial = "paving";
	TArray<FStreetDropKerb> DropKerbs;           // normally empty in a reusable profile; the spline's per-side spec carries s-lists (2.9)
	TArray<FStreetBarrierSegment> Barriers;
	TArray<FStreetEmbankment> Embankments;
};
USTRUCT(BlueprintType) struct FHedgeProfileData {
	double WidthM = 0.9, HeightM = 1.6, CornerRadiusM = 0.15, NoiseAmpM = 0.04, NoiseScaleM = 0.35;
	int32 LeafCardsPerM2 = 40; FName Material = "privet";
	TArray<FStreetHedgeSegment> Segments;
};

UCLASS(Abstract, BlueprintType) class STREETSCAPE_API UStreetProfileBase : public UDataAsset {   // ENG/Classes/Engine/DataAsset.h:17
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, Category="Streetscape") FName ProfileId;    // "uk_residential"; the key JSON splines reference
	UPROPERTY(EditAnywhere, Category="Streetscape") FString Notes;
	virtual bool ToJson(TSharedRef<FJsonObject> Out) const PURE_VIRTUAL(UStreetProfileBase::ToJson, return false;);
	virtual bool FromJson(const TSharedRef<FJsonObject>& In, FText* OutError) PURE_VIRTUAL(UStreetProfileBase::FromJson, return false;);
};
UCLASS(BlueprintType) class STREETSCAPE_API URoadProfile  : public UStreetProfileBase { UPROPERTY(EditAnywhere, meta=(ShowOnlyInnerProperties)) FRoadProfileData Data;  /* ToJson/FromJson via FStreetscapeJson::StructToJson<FRoadProfileData> */ };
UCLASS(BlueprintType) class STREETSCAPE_API UEdgeProfile  : public UStreetProfileBase { UPROPERTY(...) FEdgeProfileData Data; };
UCLASS(BlueprintType) class STREETSCAPE_API UHedgeProfile : public UStreetProfileBase { UPROPERTY(...) FHedgeProfileData Data; };
```
`UDataAsset` rather than `UPrimaryDataAsset` (`DataAsset.h:47`): no AssetManager bundles needed; assets are looked up by `ProfileId` through `AStreetscapeSiteActor::Profiles` (2.10).

#### 2.5.3 `StreetMaterialTable.h`

```cpp
UCLASS(BlueprintType) class STREETSCAPE_API UStreetMaterialTable : public UDataAsset {
	UPROPERTY(EditAnywhere, Category="Streetscape") TMap<FName, TSoftObjectPtr<UMaterialInterface>> Materials;  // "tarmac" -> MI_Tarmac
	UPROPERTY(EditAnywhere, Category="Streetscape") TSoftObjectPtr<UMaterialInterface> Fallback;                  // magenta checker
	UMaterialInterface* Resolve(FName Id) const;  // LoadSynchronous, Fallback + LogStreetscape Warning once per id
};
```
Keeps JSON engine-neutral: profiles name materials by id, never by asset path.

#### 2.5.4 `StreetSpline.h` — the shared spline

Pattern: exactly the Water plugin's (`UE/Plugins/Experimental/Water/Source/Runtime/Public/WaterSplineMetadata.h:58 class UWaterSplineMetadata : public USplineMetadata`, `:83 FInterpCurveFloat Depth`, `WaterSplineComponent.h:48-49 GetSplinePointsMetadata overrides`). The base contract is `USplineMetadata` (`ENG/Classes/Components/SplineComponent.h:57-72`: `InsertPoint, UpdatePoint, AddPoint, RemovePoint, DuplicatePoint, CopyPoint, Reset, Fixup` — all pure virtual; `USplineComponent` calls them from its point-editing paths, e.g. `ENG/Private/Components/SplineComponent.cpp:1539, :1622, :1708, :1774, :1837, :1888`). `USplineComponent` is `MinimalAPI` but its constructor is exported (`UE/Intermediate/Build/Win64/UnrealEditor/Inc/Engine/UHT/SplineComponent.generated.h:248 ENGINE_API USplineComponent(const FObjectInitializer&)`), and the editor's spline visualizer applies to subclasses because `FindComponentVisualizer` walks `GetSuperClass()` (`UED/Private/UnrealEdEngine.cpp:1492-1495`) — gizmos for free.

```cpp
UCLASS() class STREETSCAPE_API UStreetSplineMetadata : public USplineMetadata {
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, Category="Streetscape") FInterpCurveFloat WidthOverrideM;  // <= 0 => use profile width; interpolated (Linear) between points
	UPROPERTY(EditAnywhere, Category="Streetscape") FInterpCurveFloat RollDeg;         // manual bank; added to terrain-derived bank
	UPROPERTY(EditAnywhere, Category="Streetscape") TArray<FName>    ProfileId;        // per point; NAME_None = inherit from previous / actor default
	UPROPERTY(EditAnywhere, Category="Streetscape") TArray<FString>  Tags;             // comma-joined per point ("bridge,lit")
	// USplineMetadata: keep the four arrays the same length as the spline's point count; lerp curves, copy nearest for FName/FString
	virtual void InsertPoint(int32 Index, float t, bool bClosedLoop) override; virtual void UpdatePoint(int32 Index, float t, bool bClosedLoop) override;
	virtual void AddPoint(float InputKey) override; virtual void RemovePoint(int32 Index) override; virtual void DuplicatePoint(int32 Index) override;
	virtual void CopyPoint(const USplineMetadata* From, int32 FromIndex, int32 ToIndex) override; virtual void Reset(int32 NumPoints) override;
	virtual void Fixup(int32 NumPoints, USplineComponent* SplineComp) override;
};

USTRUCT(BlueprintType) struct FStreetSamplingParams {
	double DsMinM = 0.5, DsMaxM = 4.0;   // rail: 0.5 / 3.0
	double MaxTurnDeg = 2.0;             // sample spacing ds = clamp(radians(MaxTurnDeg)/|kappa|, DsMinM, DsMaxM); rail: 1.0
	double SmoothWindowM = 15.0;         // moving average of terrain z along s (centered); rail: 40.0
	bool   bBankFromTerrain = true; double MaxBankDeg = 6.0; double BankSampleLateralM = 2.0;  // cross-slope from z(+/-lateral)
	bool   bLinear = false;              // true: polyline (no Catmull-Rom); barriers from OSM default true
};
USTRUCT() struct FStreetSample {
	double S = 0;                        // arc length, metres, monotone
	FVector3d P;                         // JSON frame, metres; Z = smoothed
	FVector3d T, R, U;                   // unit tangent (3D), right (banked), up (banked) — right-handed in the JSON frame: R = normalize(T x Zup) rotated by bank about T
	double WidthM = 0;                   // carriageway total width at S (profile or override)
	double BankDeg = 0, ZSmooth = 0, ZTerrain = 0, Curvature = 0;  // Curvature: signed horizontal, 1/m (+ = turning left)
	int32 SegmentIndex = 0;              // waypoint segment
	uint8 bIsStation : 1;                // inserted breakpoint (dash edge, width change, drop-kerb edge, barrier s0/s1)
};
USTRUCT() struct FStreetSamples { TArray<FStreetSample> Samples; double LengthM = 0; TArray<double> StationsM; uint32 Hash = 0; };

UCLASS(ClassGroup=Streetscape, meta=(BlueprintSpawnableComponent))
class STREETSCAPE_API UStreetSplineComponent : public USplineComponent {
	GENERATED_BODY()
public:
	UStreetSplineComponent(const FObjectInitializer&);   // ReparamStepsPerSegment = 32 (SplineComponent.h:256); SetSplinePointType default CurveClamped (SplineComponent.h:25, :601)
	UPROPERTY(Instanced, EditAnywhere, Category="Streetscape") TObjectPtr<UStreetSplineMetadata> Metadata;
	UPROPERTY(EditAnywhere, Category="Streetscape") FStreetSamplingParams Sampling;
	UPROPERTY(EditAnywhere, Category="Streetscape") FName DefaultProfileId;      // road/rail profile
	UPROPERTY(VisibleAnywhere, Category="Streetscape") FString SourceLayer; UPROPERTY(VisibleAnywhere) int64 SourceOsmId = 0;
	virtual USplineMetadata* GetSplinePointsMetadata() override { return Metadata; }          // SplineComponent.h:414
	virtual const USplineMetadata* GetSplinePointsMetadata() const override { return Metadata; }
	// The authoritative sampler (mirrors Tools/blender/streetscape/spline.py):
	const FStreetSamples& GetSamples(const IStreetTerrainSource* Terrain, const TArray<double>& ExtraStationsM, double ProfileWidthM);  // cached by hash of (points, metadata, params, stations)
	void MarkSamplesDirty();
	// JSON-frame accessors (positions are stored in the component in UE cm; these undo the x100/-y):
	int32 NumWaypoints() const; FVector3d WaypointJson(int32 i) const; void SetWaypointsJson(const TArray<FVector3d>& P, const TArray<double>& Width, const TArray<double>& Roll, const TArray<FName>& Profile, const TArray<FString>& Tags);
private:
	FStreetSamples Cached; uint32 CachedHash = 0;
};
```

**Resampling algorithm** (identical in `spline.py`; this is the contract):
1. Waypoints `W[i]` (JSON frame, metres, z = raw terrain/OSM z ignored). Interpolation: piecewise cubic Hermite with Catmull-Rom tangents `T_i = (W[i+1]-W[i-1])/2`, one-sided at ends, evaluated in XY only (`bLinear` → straight segments). The `USplineComponent` curves are rebuilt from the same waypoints for display/editing only.
2. Fine polyline: 64 sub-samples per segment → cumulative arc length → curvature by finite differences of heading.
3. Adaptive sample positions: walk `s` with `ds = clamp(radians(MaxTurnDeg)/max(|kappa|,1e-6), DsMinM, DsMaxM)`; always include `s=0`, `s=L`, every waypoint `s`, and every `ExtraStationsM` (from 2.7 station merge) so both renderers see identical stations (BRIEF seam rule: "both renderers must re-sample the same edge offset").
4. Terrain: `ZTerrain = Terrain->SampleHeight(x,y)`; `ZSmooth` = centred moving average over samples within `±SmoothWindowM/2` of `s` (weights 1; ends clamp). Rail uses the wider window.
5. Bank: `slopeDeg = atan((z(P + R0*BankSampleLateralM) - z(P - R0*BankSampleLateralM)) / (2*BankSampleLateralM))` with `R0 = normalize(T x Zup)`; `BankDeg = clamp(slopeDeg, ±MaxBankDeg) + RollDeg(s)`. `R = rotate(R0, T, BankDeg)`, `U = T x R` (right-handed).
6. `WidthM(s)`: metadata override where `> 0` (linear between points), else profile width.

#### 2.5.5 `StreetTerrainSource.h`

```cpp
UINTERFACE(MinimalAPI) class UStreetTerrainSource : public UInterface { GENERATED_BODY() };
class STREETSCAPE_API IStreetTerrainSource {
	GENERATED_BODY()
public:
	// JSON frame in, ODN metres out. false = no ground here (clip hole, missing tile, outside extent).
	virtual bool SampleHeight(double XM, double YM, double& OutZM) const = 0;
	virtual bool IsInside(double XM, double YM) const = 0;
	virtual FString Describe() const = 0;
};

UCLASS(BlueprintType) class STREETSCAPE_API UStreetHeightfieldTerrain : public UObject, public IStreetTerrainSource {
	UPROPERTY(EditAnywhere) FFilePath ManifestPath;        // landscape_manifest.json (§4)
	// parsed from the manifest:
	int32 TileM = 512, GridRes = 513, Nx = 26, Ny = 19; double ZScale = 128.0, ZOffset = 32768.0; uint16 FillH16 = 32691;
	TMap<FIntPoint, FString> HeightFiles, ClipFiles;       // (i,j) -> path
	mutable TMap<FIntPoint, TArray<uint16>> HeightCache; mutable TMap<FIntPoint, TArray<uint8>> ClipCache;   // lazy, LRU cap 64 tiles (34 MB)
	bool Load(FText* OutError);
	// SampleHeight: i=floor(x/512), j=floor(y/512); u=x-512i, v=y-512j; col=u, row=512-v (north row first);
	// bilinear over the 4 samples (shared edges make tile borders exact); clip: reject if any of the 4 clip bytes == 0;
	// z = (h16 - ZOffset)/ZScale.  Reads: fopen/fread of exactly GridRes*GridRes*2 bytes little-endian (FFileHelper::LoadFileToArray).
};

UCLASS(BlueprintType) class STREETSCAPE_API UStreetLandscapeTerrain : public UObject, public IStreetTerrainSource {
	UPROPERTY(EditAnywhere) TWeakObjectPtr<ALandscapeProxy> Landscape;
	// SampleHeight: FVector Loc(100*x, -100*y, 0); TOptional<float> H = Landscape->GetHeightAtLocation(Loc, EHeightfieldSource::Complex);
	//   (LS/Classes/LandscapeProxy.h:1101; enum LS/Classes/LandscapeHeightfieldCollisionComponent.h:32-38: None, Simple, Complex, Editor)
	//   if unset: try each proxy via Landscape->GetLandscapeInfo()->ForEachLandscapeProxy (LS/Classes/LandscapeInfo.h:441). OutZM = H/100.
};
```
Both return ODN metres so `ZTerrain`/`ZSmooth` are datum-true and match the JSON file.

### 2.6 Renderers (`StreetRenderers.h`)

```cpp
UCLASS(Abstract, ClassGroup=Streetscape)
class STREETSCAPE_API UStreetRendererBase : public UDynamicMeshComponent {     // GF/Components/DynamicMeshComponent.h:171; ctor exported: DynamicMeshComponent.generated.h:62
	GENERATED_BODY()
public:
	UStreetRendererBase(const FObjectInitializer&);
	UPROPERTY(EditAnywhere, Category="Streetscape") bool bRebuildOnLoad = true;      // mesh is NOT saved when true (2.9)
	UPROPERTY(EditAnywhere, Category="Streetscape") bool bCollision = true;          // complex-as-simple
	UPROPERTY(VisibleAnywhere, Category="Streetscape") TArray<FName> MaterialSlotIds;  // slot index -> material id (filled by Rebuild)
	UPROPERTY(VisibleAnywhere, Category="Streetscape") int32 LastVertexCount = 0, LastTriangleCount = 0; UPROPERTY(VisibleAnywhere) double LastBuildMs = 0;
	UFUNCTION(CallInEditor, BlueprintCallable, Category="Streetscape") void Rebuild();   // CallInEditor: CORE.. UObject/ObjectMacros.h:1047 -> details-panel button, no customization needed
	UFUNCTION(BlueprintCallable, Category="Streetscape") void Clear();
protected:
	UStreetSplineComponent* FindSpline() const;             // Owner->FindComponentByClass<UStreetSplineComponent>()
	AStreetscapeSiteActor* FindSite() const;                // via UWorld actor iterator, cached weak ptr
	virtual void Build(FStreetMeshBuffers& Out, const FStreetSamples& S, TArray<FName>& OutSlotIds) PURE_VIRTUAL(...);
	virtual void CollectStations(TArray<double>& OutStationsM) const {}   // each renderer contributes breakpoints; the actor unions them (2.9)
	void Commit(FStreetMeshBuffers&& Buffers, const TArray<FName>& SlotIds);   // 2.7 ToDynamicMesh + SetMesh + ConfigureMaterialSet + collision
	virtual void OnRegister() override;   // if (bRebuildOnLoad && (!GetDynamicMesh() || GetDynamicMesh()->IsEmpty())) Rebuild();   UDynamicMesh::IsEmpty GF/UDynamicMesh.h:154
	virtual void PreSave(FObjectPreSaveContext) override;   // if (bRebuildOnLoad) GetDynamicMesh()->Reset();  (GF/UDynamicMesh.h:132) so the level stays small; OnRegister rebuilds
};
```
`Commit` (all APIs cited):
```cpp
FDynamicMesh3 Mesh; FStreetGeometry::ToDynamicMesh(Buffers, Mesh);           // 2.7
SetMesh(MoveTemp(Mesh));                                                       // GF/Components/DynamicMeshComponent.h:210 (notifies proxy)
TArray<UMaterialInterface*> Mats; for (FName Id : SlotIds) Mats.Add(Site->Materials->Resolve(Id));
ConfigureMaterialSet(Mats);                                                    // :619
SetTangentsType(EDynamicMeshComponentTangentsMode::AutoCalculated);            // :649 (enum GF/Components/BaseDynamicMeshComponent.h:47)
SetComplexAsSimpleCollisionEnabled(bCollision, /*bImmediateUpdate*/true);     // :722 (sets bEnableComplexCollision :784 + CollisionType :751 = CTF_UseComplexAsSimple)
SetMeshDrawPath(EDynamicMeshDrawPath::StaticDraw);                             // BaseDynamicMeshComponent.h:631, enum :81-87 (meshes change rarely)
SetEnableRaytracing(false);                                                    // BaseDynamicMeshComponent.h:594 (r.RayTracing is off anyway)
```
There is no Nanite path for `UDynamicMeshComponent` in 5.8 (only `DynamicDraw/StaticDraw`, `BaseDynamicMeshComponent.h:81-87`); Nanite/HLOD for streetscape is a later conversion to static meshes, out of scope.

**`UStreetRoadRenderer`** (Renderer A): `UPROPERTY(EditAnywhere) FName ProfileIdOverride;` Build:
- Resolve `URoadProfile` (spline `DefaultProfileId`, or override). `w(s) = S.WidthM`, half `h = w/2`.
- Lateral partition of the carriageway at each station into strips: `[-h-Overlap, ...marking edges..., +h+Overlap]`. Marking edges come from `Markings[]`: anchor line `a0` (`Centre`: 0; `LeftEdge`: `-h + OffsetM`; `RightEdge`: `+h - OffsetM`), then `[a0-W/2, a0+W/2]` (Double: two strips `[a0-DoubleGap/2-W, a0-DoubleGap/2]`, `[a0+DoubleGap/2, a0+DoubleGap/2+W]`). Sorted unique lateral breakpoints per section; because widths vary with `s`, lateral partition is computed per section but the **count** of strips is constant along the spline (strips may have zero width where a marking is off) — constant topology, testable vertex counts.
- Surface height at lateral `a`: `z = ZSmooth - CamberPct/100 * (bCrowned ? |a| : (a + h))` (crowned: both sides fall from the centre).
- Dashes: strip material along `s` alternates per `Dashed` pattern: the renderer's `CollectStations` emits every dash edge `S0 + Phase + k*(Dash+Gap)` and `+Dash` for k while `< min(S1, L)`; the actor unions these into the sampler's stations, so a triangle never straddles a dash edge and dash quads are exact. Between stations the strip's material = paint if inside a dash else surface material (gaps get the road material: no lift, no z-fight — closes Q5 with "same-plane split geometry", not overlapping strips).
- Emit: for each strip `k` a ribbon via `FStreetSweep::Strip(...)` (2.7) with material slot = strip material id, UV `u = s/UvScaleM`, `v = (a - aLeft)/UvScaleM`.
- Rail (`Kind == Rail`): ballast = the ribbon with lateral profile `[-top/2 - depth*slope, -top/2, +top/2, +top/2+depth*slope]` heights `[-depth, 0, 0, -depth]` (shoulders via the same lateral-height machinery); two rails = closed cross-section (I-shape simplified to 6 points: foot, web, head) swept at `±Gauge/2` with `FStreetSweep::Sweep(..., bClosed=true)`; sleepers = swept boxes of length `SleeperWidthM` starting at stations `k*SleeperPitchM` (stations added via `CollectStations`), spanning `±SleeperLengthM/2`. All in one build pass, three material slots. Rail profiles use `Sampling.MaxTurnDeg=1.0`, `DsMaxM=3.0`, `SmoothWindowM=40`.

**`UStreetEdgeRenderer`** (Renderer B): `UPROPERTY(EditAnywhere) EStreetSide Side; UPROPERTY(EditAnywhere) FName ProfileIdOverride; UPROPERTY(EditAnywhere) TArray<FStreetDropKerb> DropKerbs; TArray<FStreetBarrierSegment> Barriers; TArray<FStreetEmbankment> Embankments;` (per-spline lists; concatenated with the profile's lists). Build, per section `k`, sign `σ = (Side==Right ? +1 : -1)`:
- Kerb face line `f = σ·h(s)` (the **same** `h` as the road: shared samples, D8). Kerb upstand `u(s)` = `KerbHeightM`, lowered by drop kerbs: for each drop, `u = lerp(KerbHeight, TargetHeight, ramp)` with `ramp = 1` inside `|s - SM| <= Flat/2`, linear to 0 over `RampLengthM`; edges of flat/ramp are stations (via `CollectStations`).
- Kerb cross-section (open polyline, lateral `a` from `f`, vertical `b` from road surface `z_road(f)`): `(0, -KerbTuckM)` → `(0, u - Chamfer)` → `(Chamfer, u)` → `(KerbWidthM, u)` → `(KerbWidthM + PavementWidthM, u + PavementWidthM*PavementCrossfallPct/100)` [pavement top rises away from the kerb] → `(KerbWidthM + PavementWidthM, -0.15)` [outer skirt into the ground]. Material per profile segment: inner face `KerbMaterialInner`; lip/top and pavement `bSplitMaterial ? KerbMaterialOuter : KerbMaterialInner` / `PavementMaterial`; outer skirt `PavementMaterial`. Half-grass: `bSplitMaterial=true`, `KerbMaterialOuter="grass"` — inner face tarmac-grey, top and outer grass, both flush at `u` (no step). Drop ramps carry both materials down because materials are per profile segment, not per height.
- Seam rule realised: the road's ribbon extends to `f + σ·OverlapM` (3 cm beyond the face) and the kerb's inner face starts `KerbTuckM` **below** the road surface, so the road's last strip lies inside the kerb volume. Test: for every section, `roadEdge - f = OverlapM` exactly (shared `h`), including across width changes (`h(s)` is one function).
- Barriers: each `FStreetBarrierSegment` sweeps a closed rectangle `(LateralOffset .. +Thickness) x (0 .. Height)` standing on the pavement's outer edge height over `[S0,S1]` (stations) — `BrickWall`/`RetainingWall` solid; `Railing`/`ChainLink`/`Fence`: two rails (top, mid) as closed 4-point sections + posts every `PostPitchM` as swept boxes over one sample; infill panel as a single-quad strip with the `"<Material>_secondary"` material (alpha-masked chain-link). Switching brick → chain-link → railing is three rows of data.
- Embankments: `dz = ZSmooth - ZTerrain` at the outer edge; where `|dz| > MinHeightDiffM` over `[S0,S1]`: `Slope` → a ribbon from the outer edge down/up to the terrain at `MaxSlopeDeg` (lateral run `|dz|/tan`), 3 lateral steps sampling the terrain; `RetainingWall` → a vertical closed box from terrain to edge.

**`UStreetHedgeRenderer`** (Renderer C, stage 6): reads the **same** `Barriers`-style segment list (`FStreetHedgeSegment`, s-ranges, same lateral anchor as barriers so it stacks beside them). Volume = rounded box cross-section (12-point closed profile with `CornerRadiusM`) swept over `[S0,S1]` with per-vertex radial displacement `NoiseAmpM * simplex3(P/NoiseScaleM)` (deterministic seed = hash(actor id)); end caps closed. Leaf cards: `UHierarchicalInstancedStaticMeshComponent` sibling (`ENG/Classes/Components/HierarchicalInstancedStaticMeshComponent.h`) with `LeafCardsPerM2 * area` instances on the surface (random-in-triangle, aligned to the surface normal) — real volume + foliage, no thin wall. Density knobs: `LeafCardsPerM2`, `NoiseAmpM`, `NoiseScaleM`.

### 2.7 Geometry core (`StreetGeometry.h`) — shared with numpy (closes Q4)

Pure C++ (no UObject) so tests run without a world. Mirrors `Tools/blender/streetscape/{sweep.py,stations.py,mesh.py}` function for function; vertex ordering is normative so vertex counts and indices match across the two implementations.

```cpp
struct FStreetMeshBuffers {          // JSON frame, doubles
	TArray<FVector3d> V; TArray<FVector2f> UV; TArray<FIndex3i> F; TArray<int32> FMat;   // one material slot index per triangle
	TArray<FName> SlotIds;           // slot index -> material id
	int32 Slot(FName Id);            // find-or-add
};
struct FStreetProfilePoint { double A; double B; int32 Slot; double VCoord; };   // lateral, vertical, material of the segment starting here, v texture coordinate
struct FStreetSweep {
	// Sweep an open/closed 2D profile along samples [K0..K1]. Section k origin = S.P[k] + LateralAt(k)*S.R[k] + HeightAt(k)*S.U[k];
	// profile point (A,B) -> origin + A*S.R[k] + B*S.U[k]. Each profile SEGMENT j gets its own vertex rows (hard edges by construction):
	// vertex index = Base + (j*(K1-K0+1) + (k-K0))*2 + {0,1}; two triangles per (j,k<K1): (a,b,d),(a,d,c) with a=row k pt j, b=row k pt j+1, c=row k+1 pt j, d=row k+1 pt j+1.
	// UV: u = S.S[k]/UScaleM, v = VCoord of the profile point.
	static void Sweep(const FStreetSamples& S, int32 K0, int32 K1, TFunctionRef<double(int32)> LateralAt, TFunctionRef<double(int32)> HeightAt,
	                  TConstArrayView<FStreetProfilePoint> Profile, bool bClosed, double UScaleM, FStreetMeshBuffers& Out);
	// Ribbon between two lateral functions with a height function: the special case used by road strips, pavement tops, embankment slopes.
	static void Strip(const FStreetSamples& S, int32 K0, int32 K1, TFunctionRef<double(int32)> ALeft, TFunctionRef<double(int32)> ARight,
	                  TFunctionRef<double(int32,double)> HeightAt /*(k, a)*/, int32 Slot, double UScaleM, double VScaleM, FStreetMeshBuffers& Out);
	// Box of length [S0,S1] (snapped to stations), lateral [A0,A1], vertical [B0,B1]: closed 4-point profile via Sweep.
	static void Box(const FStreetSamples& S, double S0, double S1, double A0, double A1, double B0, double B1, int32 Slot, FStreetMeshBuffers& Out);
};
struct FStreetStations {           // union of breakpoints, sorted, deduplicated with tolerance 1e-6 m, clamped to [0, L]
	static void Merge(TArray<double>& InOut, TConstArrayView<double> Add);
	static void DashEdges(double S0, double S1, double L, double Dash, double Gap, double Phase, TArray<double>& Out);
	static int32 SectionAt(const FStreetSamples& S, double s);   // index of the sample with S.S == s (stations are guaranteed samples)
};
namespace FStreetGeometry {
	// The ONE conversion point for meshes. Positions x(100,-100,100); winding reversed (mirror) by emitting (a,c,b).
	void ToDynamicMesh(const FStreetMeshBuffers& In, UE::Geometry::FDynamicMesh3& Out);
}
```
`ToDynamicMesh` body (all cited):
```cpp
Out.Clear();                                        // GC/DynamicMesh/DynamicMesh3.h:350
Out.EnableAttributes();                             // :1048
Out.Attributes()->EnableMaterialID();               // GC/DynamicMesh/DynamicMeshAttributeSet.h:360
Out.Attributes()->SetNumUVLayers(1);                // :175
FDynamicMeshUVOverlay* UV = Out.Attributes()->PrimaryUV();            // :198
FDynamicMeshNormalOverlay* N = Out.Attributes()->PrimaryNormals();     // :250
FDynamicMeshMaterialAttribute* Mat = Out.Attributes()->GetMaterialID(); // :364
for (i) { vid[i] = Out.AppendVertex(FVector3d(100*V.X, -100*V.Y, 100*V.Z)); uvid[i] = UV->AppendElement(In.UV[i]); }   // DynamicMesh3.h:668; GC/DynamicMesh/DynamicMeshOverlay.h:755
for (t) { int tid = Out.AppendTriangle(FIndex3i(vid[a], vid[c], vid[b]), /*GroupID*/ In.FMat[t]);   // DynamicMesh3.h:677 — (a,c,b): the Y mirror flips handedness
          UV->SetTriangle(tid, FIndex3i(uvid[a], uvid[c], uvid[b]));                                  // DynamicMeshOverlay.h:342
          Mat->SetValue(tid, In.FMat[t]); }                                                            // GC/DynamicMesh/DynamicMeshTriangleAttribute.h:294
FMeshNormals::InitializeOverlayToPerVertexNormals(N, /*bUseMeshVertexNormalsIfAvailable*/false);      // GC/DynamicMesh/MeshNormals.h:188 — per-vertex; strips own their vertices, so profile edges are hard, along-s is smooth
```
Material IDs index the component's material slots (`ConfigureMaterialSet` order = `SlotIds` order).

### 2.8 `UStreetOverlayComponent` — the OSM reference overlay

Requirements: survives save/reload, toggleable, no z-fighting mesh. Options weighed: `DrawDebugLine` (transient, `ENG/Public/DrawDebugHelpers.h:22`); a thin DynamicMesh ribbon (survives, but is geometry that shadows/collides unless configured); `ULineBatchComponent` subclass — **not possible** from a plugin: it is `UCLASS(MinimalAPI)` with `GENERATED_UCLASS_BODY` and no exported constructor (`ENG/Classes/Components/LineBatchComponent.h:126-129`). Chosen: a `USceneComponent` that stores the polyline and pushes it into the world's **persistent** line batcher with its own batch id.

```cpp
UCLASS(ClassGroup=Streetscape, meta=(BlueprintSpawnableComponent))
class STREETSCAPE_API UStreetOverlayComponent : public USceneComponent {
	UPROPERTY(EditAnywhere, Category="Streetscape") TArray<FVector> PointsUE;     // converted once at import (cm), stored
	UPROPERTY(EditAnywhere, Category="Streetscape") FLinearColor Color = FLinearColor(1, 0.3, 0, 1);
	UPROPERTY(EditAnywhere, Category="Streetscape") float ThicknessCm = 12.f, LiftCm = 15.f;
	UPROPERTY(EditAnywhere, Category="Streetscape") bool bShow = true;
	UFUNCTION(CallInEditor, BlueprintCallable) void Toggle();
	virtual void OnRegister() override;    // Draw()
	virtual void OnUnregister() override;  // Clear()
	void Draw()  { if (ULineBatchComponent* LB = GetWorld()->GetLineBatcher(UWorld::ELineBatcherType::WorldPersistent))   // ENG/Classes/Engine/World.h:1023, enum :1011-1020
	               for (i) LB->DrawLine(P[i]+Lift, P[i+1]+Lift, Color, SDPG_World, ThicknessCm, /*LifeTime*/0.f, BatchId()); }   // LineBatchComponent.h:178-186; LifeTime 0 = persistent (FBatchedLine default :30-31)
	void Clear() { LB->ClearBatch(BatchId()); }                                                                              // :216
	uint32 BatchId() const { return GetTypeHash(GetOwner()->GetActorGuid()); }   // never 0 (INVALID_ID, :143)
};
```
Also present in `-game` and screenshots (the batcher is a normal primitive). Overlay toggle for the whole level: `AStreetscapeSiteActor::bShowOverlay` iterates actors.

### 2.9 `AStreetscapeActor` and streaming granularity (closes Q8)

```cpp
UCLASS() class STREETSCAPE_API AStreetscapeActor : public AActor {
	UPROPERTY(VisibleAnywhere) TObjectPtr<UStreetSplineComponent> Spline;        // root
	UPROPERTY(VisibleAnywhere) TObjectPtr<UStreetRoadRenderer>   Road;
	UPROPERTY(VisibleAnywhere) TObjectPtr<UStreetEdgeRenderer>   EdgeLeft, EdgeRight;
	UPROPERTY(VisibleAnywhere) TObjectPtr<UStreetHedgeRenderer>  HedgeLeft, HedgeRight;   // created only when the JSON has hedge segments for that side
	UPROPERTY(VisibleAnywhere) TObjectPtr<UStreetOverlayComponent> Overlay;
	UPROPERTY(EditAnywhere, Category="Streetscape") FString StreetId;             // JSON "id" (e.g. "w123_t17_16"); also the actor label
	UPROPERTY(EditAnywhere, Category="Streetscape") FName EdgeProfileLeft, EdgeProfileRight, HedgeProfileLeft, HedgeProfileRight;
	UFUNCTION(CallInEditor, BlueprintCallable, Category="Streetscape") void RebuildAll();
	// RebuildAll: stations = union(Road->CollectStations, EdgeL/R->CollectStations, Hedge->...); Spline->GetSamples(Site->Terrain, stations, profileWidth); then each renderer Build+Commit from the SAME FStreetSamples.
	UFUNCTION(BlueprintCallable) bool ToJson(TSharedRef<FJsonObject> Out) const; bool FromJson(const TSharedRef<FJsonObject>& In, FText* Err);
};
```
Defaults: `bIsSpatiallyLoaded = true` (WP grid streaming, `ENG/Classes/GameFramework/Actor.h:2650 SetIsSpatiallyLoaded`), `RuntimeGrid = NAME_None` (main grid, `:818`), `bEnableAutoLODGeneration = false` (`:559`; HLOD later).

**Granularity decision (D7):** one actor per Streetscape-JSON spline. Step 06 already splits ways at tile borders and junctions (`sources/OUTPUT.md`, networks section: "split at tile boundaries with the seam vertex duplicated"), so a spline is at most ~512 m and typically ~60 m (Margate: 317 km / 5,001 segments). Thanet estimate: 494/91 x Margate ≈ 5.4x → ~27k road actors + ~2.5k barrier + rail ≈ 30k actors. WP handles that; the alternative (one actor per tile with ~50 spline components) yields the same number of primitive components (one per renderer per spline is mandated) but coarser 512 m streaming units and worse editing ergonomics. Cost control: meshes are **not serialized** (`bRebuildOnLoad`, `PreSave` resets the `UDynamicMesh`; `UPROPERTY(Instanced) MeshObject` at `DynamicMeshComponent.h:258-259` would otherwise store ~70 KB per actor ≈ 2 GB for Thanet) and are rebuilt in `OnRegister` as cells stream in (~1 ms per component; a 768 m loading radius ≈ 500 actors ≈ 1.5 s spread across streaming). Collision: complex-as-simple trimesh per component (Chaos cook at rebuild) — small meshes, acceptable; if profiling disagrees, the fallback is to serialize meshes for the loaded region only (flip `bRebuildOnLoad` per actor) or bake to static meshes.

### 2.10 `AStreetscapeSiteActor` (one per level; replaces a subsystem so it persists with the map)

```cpp
UCLASS() class STREETSCAPE_API AStreetscapeSiteActor : public AActor {
	UPROPERTY(EditAnywhere, Category="Site") FString SiteName = "thanet";
	UPROPERTY(EditAnywhere, Category="Site") FString Crs = "EPSG:27700", VerticalDatum = "ODN";
	UPROPERTY(EditAnywhere, Category="Site") FVector2D OriginEN = FVector2D(627680, 163080);   // documentation + validation: every JSON must match
	UPROPERTY(EditAnywhere, Instanced, Category="Terrain") TObjectPtr<UObject> TerrainSourceObject;   // UStreetHeightfieldTerrain (default) or UStreetLandscapeTerrain
	UPROPERTY(EditAnywhere, Category="Profiles") TArray<TObjectPtr<UStreetProfileBase>> Profiles;    // resolved to TMap<FName,...> on load
	UPROPERTY(EditAnywhere, Category="Profiles") TObjectPtr<UStreetMaterialTable> Materials;
	UPROPERTY(EditAnywhere, Category="Debug") bool bShowOverlay = true;
	const IStreetTerrainSource* Terrain() const; UStreetProfileBase* FindProfile(FName Id) const;
	static AStreetscapeSiteActor* Get(UWorld*);   // TActorIterator, cached
};
```
`bIsSpatiallyLoaded=false` so it is always loaded.

### 2.11 `FStreetscapeJson` — the loader/saver and the one frame conversion for splines

```cpp
struct STREETSCAPE_API FStreetscapeJson {
	// Frame conversion (BRIEF 4.2). The ONLY place besides the landscape importer.
	static FVector ToUE(const FVector3d& M)  { return FVector(100.0*M.X, -100.0*M.Y, 100.0*M.Z); }
	static FVector3d ToJson(const FVector& C){ return FVector3d(C.X/100.0, -C.Y/100.0, C.Z/100.0); }
	static double YawFromBearingDeg(double BearingDeg) { return BearingDeg - 90.0; }
	// Files
	static bool LoadFile(const FString& Path, TSharedPtr<FJsonObject>& Out, FText* Err);   // FFileHelper::LoadFileToString + FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Str), Out)  UE/Source/Runtime/Json/Public/Serialization/JsonSerializer.h:301, JsonReader.h:1078
	static bool SaveFile(const FString& Path, const TSharedRef<FJsonObject>& In);          // FJsonSerializer::Serialize(In, TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Str))  JsonSerializer.h:377, JsonWriter.h:778, Policies/PrettyJsonPrintPolicy.h:14
	// Struct <-> JSON with snake_case keys
	template<typename T> static TSharedPtr<FJsonObject> StructToJson(const T& S);       // FJsonObjectConverter::UStructToJsonObject (UE/Source/Runtime/JsonUtilities/Public/JsonObjectConverter.h:101/124) then PascalToSnakeKeys()
	template<typename T> static bool JsonToStruct(const TSharedRef<FJsonObject>& J, T& Out, FText* Err); // SnakeToPascalKeys() then FJsonObjectConverter::JsonObjectToUStruct (:239/255) with bStrictMode=false
	static void PascalToSnakeKeys(TSharedRef<FJsonObject>); static void SnakeToPascalKeys(TSharedRef<FJsonObject>);   // recursive over objects/arrays; "KerbWidthM"<->"kerb_width_m", "bSplitMaterial"->"split_material"; handles the converter's lower-cased first letter
	// Site file
	static bool LoadSite(const FString& Path, UWorld* World, AStreetscapeSiteActor* Site, TArray<AStreetscapeActor*>& OutActors, FText* Err);
	static bool SaveSite(const FString& Path, UWorld* World, FText* Err);
};
```
`FJsonObjectConverter` matches property names case-insensitively but not snake_case, hence the key-renaming pass; enums round-trip as strings; `FName` as strings. The round trip is unit-tested (2.13). What `LoadSite` reads is specified in §4.3; it validates `origin == Site->OriginEN` (hard error otherwise: mixing origins is the classic 1.8 m/8 km class bug).

### 2.12 Editor module

**`FStreetscapeEditorModule`** (`StartupModule`): `UToolMenus::RegisterStartupCallback(...)` (`UE/Source/Developer/ToolMenus/Public/ToolMenus.h:145`) → `UToolMenu* Menu = UToolMenus::Get()->ExtendMenu("LevelEditor.MainMenu.Tools")` (`:169`; the menu name is registered at `UE/Source/Editor/LevelEditor/Private/LevelEditorMenu.cpp:372`) → `FToolMenuSection& Sec = Menu->AddSection("Streetscape", LOCTEXT(...))` (`ToolMenu.h:73`) → `Sec.AddMenuEntry("ImportSite", ..., FUIAction(...))` (`ToolMenuSection.h:62`). Entries: *Import landscape site…* (file dialog → `UStreetscapeLandscapeImporter::ImportSite`), *Import streetscape JSON…*, *Rebuild all streetscape actors*, *Toggle OSM overlay*. `ShutdownModule`: `UToolMenus::UnregisterOwner(this)` (`ToolMenus.h:123`). The details-panel Rebuild buttons come from `UFUNCTION(CallInEditor)` on the components/actor (no `IDetailCustomization` needed; one can be added later for a richer panel).

**`UStreetscapeEditorLibrary`** (`UBlueprintFunctionLibrary`, all `UFUNCTION(BlueprintCallable, Category="Streetscape|Editor")`, callable from Python as `unreal.StreetscapeEditorLibrary.<snake_case>`):
- `static int32 ImportProfiles(const FString& JsonDir, const FString& PackagePath)` — for each `*.json`: class by `"type"` field (`road|edge|hedge`), `UPackage* Pkg = CreatePackage(*PkgName)` (`UE/Source/Runtime/CoreUObject/Public/UObject/UObjectGlobals.h:1225`), `NewObject<URoadProfile>(Pkg, Name, RF_Public|RF_Standalone)`, `FromJson`, `FAssetRegistryModule::AssetCreated(Obj)` (`UE/Source/Runtime/AssetRegistry/Public/AssetRegistry/AssetRegistryModule.h:61`), `UEditorLoadingAndSavingUtils::SavePackages({Pkg}, false)` (`UED/Public/FileHelpers.h:86`). Returns count.
- `static int32 ImportStreetscapeJson(const FString& JsonPath, bool bPlacePlayerStart)` — `FStreetscapeJson::LoadSite`, spawns actors via `World->SpawnActor<AStreetscapeActor>`, labels = `StreetId`, then `RebuildAll` each; optional `APlayerStart` at the first spline's start (§7.4).
- `static bool LoadRegion(FVector CenterUE, float RadiusCm)` — `FLoaderAdapterShape(World, FBox(...), TEXT("Streetscape"))` + `Load()` (`ENG/Public/WorldPartition/LoaderAdapter/LoaderAdapterShape.h:12`, `ENG/Public/WorldPartition/WorldPartitionActorLoaderInterface.h:35`); kept alive in a module-static array. Needed because commandlets skip `LoadLastLoadedRegions` (`ENG/Private/WorldPartition/WorldPartition.cpp:876-888`).
- `static bool SaveAll()` — `UEditorLoadingAndSavingUtils::SaveDirtyPackages(true, true)` (`FileHelpers.h:108`; saves map + OFPA external actors + content).
- `static FString ExportSiteJson(const FString& Path)` — `FStreetscapeJson::SaveSite`.

**`UStreetscapeLandscapeImporter`** — §3.6.

### 2.13 Automation tests (`Source/Streetscape/Private/Tests/`)

Guarded by `#if WITH_DEV_AUTOMATION_TESTS`; `IMPLEMENT_SIMPLE_AUTOMATION_TEST(FClass, "Streetscape.<Area>.<Name>", EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)` (`CORE/Misc/AutomationTest.h:4297`; flags `:93`, `:133`; `RunTest(const FString&)` `:2653`). They read the same fixtures the numpy tests use (`P1/Tools/blender/tests/fixtures/*.json`, produced by the numpy designer) so both implementations are checked against one set of numbers:

| Test | Asserts (mirrors numpy test) |
|---|---|
| `Streetscape.Spline.Resample` | synthetic sine road: `S` strictly increasing; mean `ds` on bends `<` mean `ds` on straights; every waypoint and station is a sample; `L` within 0.1 % of the fixture. |
| `Streetscape.Spline.Smoothing` | step-profile terrain: `ZSmooth` within fixture tolerance; unchanged with `SmoothWindowM=0`. |
| `Streetscape.Road.Markings` | double yellow + centre dash profile: strip count constant; lateral positions of paint strips equal `OffsetM ± WidthM/2` at every section; dash quads start/end at exact stations. |
| `Streetscape.Edge.Overlap` | width change 6→8 m mid-spline: `roadEdge(s) - kerbFace(s) == OverlapM` at every section; no zero-width strip; kerb top height `== KerbHeightM` outside drops, `== TargetHeightM` inside the flat, monotone on ramps. |
| `Streetscape.Edge.SplitMaterial` | half-grass profile: inner-face triangles have slot `kerb_concrete`, top/outer `grass`, top edge single (no step). |
| `Streetscape.Json.RoundTrip` | profile structs → JSON → struct equality; site file → actors → JSON byte-equal after canonical ordering. |
| `Streetscape.Geometry.ToDynamicMesh` | a right-handed JSON triangle maps to a UE triangle whose normal points +Z (winding fix); vertex count == input. |

Run: `UnrealEditor-Cmd.exe Thanet.uproject -ExecCmds="Automation RunTests Streetscape; Quit" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=tests.log`.

---

## 3. Landscape (closes Q1, Q2, Q3)

### 3.1 Data → array

Site grid (BRIEF 4.1): origin E 627680 N 163080, 26 x 19 tiles of 512 m, 513 samples per tile edge (shared edge). Heightfield: **W = 26·512+1 = 13313** columns (x east), **H = 19·512+1 = 9729** rows, **north row first** (row 0 = y = 9728 m). Tile `(i,j)` sample `(c,r)` (r north-first) → global col `512·i + c`, global row `512·(18−j) + r`. Shared edge samples are written twice and asserted equal (the adapter guarantees it; the importer logs the max discrepancy).

Z encoding (verified `LS/Public/LandscapeDataAccess.h:13 LANDSCAPE_ZSCALE (1/128)`, `:27 MidValue 32768`, `:30-33 GetLocalHeight = (h − 32768)·(1/128)`, `:35-38 GetTexHeight = round(clamp(h_local·128 + 32768, 0, 65535))`): with actor Z scale 100, local height units are metres, so
`h16 = clamp(round(z_m·128) + 32768, 0, 65535)`, inverse `z_m = (h16 − 32768)/128`; window −256 .. +255.992 m, step 0.78125 cm. Thanet −3..+60 m → h16 32384..40448. Water level −0.6 m → **32691** (decodes to −0.6016 m).

### 3.2 Component size (Q1)

Valid quads per component are `ss·ns` with `ss ∈ {7,15,31,63,127,255}`, `ns ∈ {1,2}` (`LS/Private/LandscapeConfigHelper.cpp:24-25`). 13312 = 2¹⁰·13 and 9728 = 2⁹·19 share no such divisor, so no exact fit exists; padding is unavoidable.

What `FLandscapeImportHelper::ChooseBestComponentSizeForImport(13313, 9729, ss=127, ns=2, out)` (`LSE/Public/LandscapeImportHelper.h:140`) returns: the exact-match loop fails (`LSE/Private/LandscapeImportHelper.cpp:441-467`); the fallback keeps the passed-in valid values and increases `ss` until both component counts are ≤ 32 (`:484-500`): `ss=127` gives 53 x 39 (rejected, > 32), `ss=255` gives ceil(13312/510)=27 x ceil(9728/510)=20 → **255 x 2 = 510 quads, 27 x 20 components, padded 13771 x 10201** (pad 458 E, 472 N, 9.3 % waste). That ≤32 rule exists for the editor UI's component clamp, not for rendering quality.

**Chosen (D2): ss = 127, ns = 2 → 254 quads/component, component textures 256 x 256; 53 x 39 = 2067 components; padded W' = 53·254+1 = 13463, H' = 39·254+1 = 9907; padding 150 columns east, 178 rows north (4.6 % waste).** Reasons: Epic's documented large-landscape configurations (8k/16k) use 127x2; LOD and culling are per component, and 254 m components let LOD0 (the only LOD that shows 1 m cliff faces faithfully) be held near the viewer without dragging 510 m of terrain along; 256² textures are the most exercised path (heightmap mips, Nanite landscape later). The importer logs the helper's answer for the record; `--quads-per-section/--sections` are script flags.

Padding placement and fill: north and east so the site origin stays a landscape vertex at UE (0,0). Padded row `r' = r + 178` for data rows, columns unchanged. Actor placed at **`FVector(0, −100·(9728+178), 0) = (0, −990600, 0)` cm, rotation zero, scale (100,100,100)**; then vertex `(c, r')` sits at UE `(100·c, 100·r' − 990600)`; the site origin `(x=0,y=0)` is `r' = 9906`, i.e. data row 9728 = the southernmost row → `Y = 0` ✓; north data row `r=0` → `Y = −972800`. Landscape extent X ∈ [0, 1,346,200], Y ∈ [−990,600, 0] cm. Fill: `h16 = 32691` (water level), visibility = 255 (hole), weights water = 255 — padding is invisible and collision-free. Tiles the pipeline excluded (103) or found missing get the same fill; the manifest's `tiles_excluded`/`tiles_missing` lists drive this (§4).

### 3.3 World Partition grid (Q1)

`ULandscapeSubsystem::ChangeGridSize(Info, N)` (`LS/Public/LandscapeSubsystem.h:153`; body `LS/Private/LandscapeSubsystem.cpp:1297-1310` → `FLandscapeConfigHelper::ChangeGridSize` `LS/Public/LandscapeConfigHelper.h:71`, body `LandscapeConfigHelper.cpp:96-170` moving components into `ALandscapeStreamingProxy` actors per `UActorPartitionSubsystem` cell) requires a partitioned world (`IsGridBased` ⇔ `UWorld::IsPartitionedWorld`, `LandscapeSubsystem.cpp:1292-1295`, `ENG/Classes/Engine/World.h:2968`). Editor default is 2 (`LSE/Public/LandscapeEditorObject.h:657`). **Chosen: 4** → proxy cell = 4·254 m = **1016 m**, **ceil(53/4) x ceil(39/4) = 14 x 10 = 140 streaming proxies** (each ≤ 16 components), plus the always-loaded `ALandscape` parent. Grid 2 (540 proxies of 508 m) is the fallback knob if 1 km proxies stream too coarsely for the walk mode.

### 3.4 Memory / disk estimate (2067 components, 256² textures)

| Item | Size |
|---|---|
| Source arrays (transient, CPU) | heights 13463·9907·2 B = 267 MB; 5 weight layers x 133 MB = 667 MB |
| Component heightmaps (BGRA8, height + packed normal) | 2067 x 256² x 4 B = 542 MB, +mips ≈ 722 MB |
| Weightmaps (RGBA8; 4 ground layers in one texture, visibility in a 2nd only where the clip/padding touches ≈ 200 components) | ≈ 594 MB, +mips ≈ 790 MB |
| Edit-layer copies of the above (default layer, 5.8 always has edit layers: `LS/Classes/Landscape.h:662 bCanHaveLayersContent_DEPRECATED`) | ≈ 1.5 GB |
| Collision heightfields (uint16) + dominant-layer bytes | 271 MB + 135 MB |
| **Peak CPU during import** | **≈ 4.5 GB** (28 GB machine) ; GPU copies ≈ 2.5 GB when rendering is enabled (20 GB) |
| Disk (`Content/__ExternalActors__`, regenerated, not committed) | ≈ 2.7 GB |

Import time is the unknown (see §9); the editor's own regions flow exists to bound *undo/transaction* and per-save size, not memory — we run without a transaction.

### 3.5 Visibility (hole) layer and weightmaps in the same Import call (Q2)

Convention, verified: the material node `LandscapeVisibilityMask` compiles to `1 − weight(__LANDSCAPE_VISIBILITY__)` (`LS/Private/Materials/MaterialExpressionLandscapeVisibilityMask.cpp:20, :45-46`), so **weight 255 → opacity mask 0 → hole; weight 0 → visible.** Hole meshing/collision use the threshold `LANDSCAPE_VISIBILITY_THRESHOLD = 2/3` (`LS/Public/LandscapeDataAccess.h:19`, applied in `LS/Private/LandscapeEdit.cpp:4411 GenerateMarchingSquaresGeometry`) — so a byte mask of {0,255} gives an edge interpolated at the 2/3 iso-line between vertices, i.e. the hard line at 1 m resolution. Collision holes follow the dominant-layer data built at import (`LS/Private/LandscapeCollision.cpp:1174-1178`). The clip mask from the adapter is `255 = keep` (§4) → `visibility = 255 − clip`.

The layer info object for visibility is the engine's static `ALandscapeProxy::VisibilityLayer` (`LS/Classes/LandscapeProxy.h:1002`, `WITH_EDITOR`); its entry uses `LayerName = VisibilityLayer->GetLayerName()` (`LS/Classes/LandscapeLayerInfoObject.h:135`) — the editor identifies the visibility import layer by that name (`LSE/Private/LandscapeEditorDetailCustomization_NewLandscape.cpp:1020`).

Ground-cover layers `grass, sand, rock, water` need `ULandscapeLayerInfoObject` assets. Created **in C++ by the importer** (not by Python — Python cannot call the un-exposed helper) with `UE::Landscape::CreateTargetLayerInfo(FName("grass"), TEXT("/Game/Thanet/Landscape/Layers"), TEXT("LI_grass"))` (`LS/Public/LandscapeUtils.h:34 namespace, :330`; it does `NewObject<ULandscapeLayerInfoObject>(Package, Name, RF_Public|RF_Standalone)` + asset-registry notification, `LS/Private/LandscapeUtils.cpp:307`), reused if the asset already exists (`FindObject`/`LoadObject` by path), then saved with `UEditorLoadingAndSavingUtils::SavePackages`. Layer names must equal the `LandscapeLayerBlend` layer names in the landscape material (§5, bootstrap): `FLayerBlendInput::LayerName` is `UPROPERTY(EditAnywhere)` (`LS/Classes/Materials/MaterialExpressionLandscapeLayerBlend.h:31-32`), so Python can set them.

Alphamap type: `ELandscapeImportAlphamapType::Additive` (`LS/Classes/LandscapeProxy.h:178-183`): per vertex the four ground weights sum to 255 (the importer renormalises after resampling; rounding residue goes to the largest layer); visibility is independent (not part of the sum). Weightmap `LayerData` must be `W'·H'` bytes per layer (indexed identically to the heights, `LandscapeEdit.cpp:3277`).

### 3.6 The import sequence (`UStreetscapeLandscapeImporter`, editor module)

```cpp
UCLASS() class UStreetscapeLandscapeImporter : public UBlueprintFunctionLibrary {
	UFUNCTION(BlueprintCallable, Category="Streetscape|Landscape")
	static ALandscape* ImportSite(const FString& ManifestPath, int32 QuadsPerSection /*127*/, int32 SectionsPerComponent /*2*/,
	                              int32 WorldPartitionGridSize /*4*/, const FString& MaterialPath /*"/Game/Thanet/Materials/M_Thanet_Landscape"*/,
	                              const FString& LayerInfoPackagePath /*"/Game/Thanet/Landscape/Layers"*/, FString& OutReportJson);
	UFUNCTION(BlueprintCallable) static float ProbeHeightM(ALandscapeProxy* Landscape, double XM, double YM);   // JSON-frame metres in, ODN metres out, NaN if no ground
	UFUNCTION(BlueprintCallable) static int32 CountLandscapeComponents(ALandscapeProxy* Landscape);
	UFUNCTION(BlueprintCallable) static int32 CountStreamingProxies(ALandscapeProxy* Landscape);
};
```
`ImportSite` body, in order, mirroring the editor's own create path (`LSE/Private/LandscapeEditorDetailCustomization_NewLandscape.cpp:1150-1290`):

1. `UWorld* World = GEditor->GetEditorWorldContext().World(); checkf(UWorld::IsPartitionedWorld(World))` — the bootstrap created and **saved** the WP map first (the editor also insists on a saved package before large WP landscapes: `NewLandscape.cpp:1161-1177`).
2. Parse manifest (§4) with `FJsonSerializer::Deserialize`; compute `W,H`; log `ChooseBestComponentSizeForImport`'s suggestion; `Cx = ceil((W−1)/Q)`, `Cy = ceil((H−1)/Q)` with `Q = QuadsPerSection·SectionsPerComponent`; `W' = Cx·Q+1`, `H' = Cy·Q+1`; `padN = H'−H`.
3. Allocate `TArray<uint16> Heights(W'·H')` = `FillH16`; `TArray<uint8> Vis = 255, Grass=Sand=Rock=0, Water=255`. For each manifest tile: read `.r16` (exactly `513·513·2` bytes, little-endian → `uint16`), copy into rows `512·(18−j)+r+padN`, cols `512·i+c`; read `.r8` clip → `Vis = 255 − clip`; read the four `.r8` weight tiles (256²) → bilinear-resample to 513² → normalise to 255 → write. Missing/excluded tiles keep the fill.
4. Layer infos: `ULandscapeLayerInfoObject* LI[4]` via `UE::Landscape::CreateTargetLayerInfo` (3.5); `ULandscapeLayerInfoObject* VisLI = ALandscapeProxy::VisibilityLayer`.
5. ```cpp
   TArray<FLandscapeImportLayerInfo> Layers;                          // LS/Classes/LandscapeProxy.h:193-222 (LayerName, LayerInfo, SourceFilePath, LayerData)
   for (k) { FLandscapeImportLayerInfo L(LI[k]->GetLayerName()); L.LayerInfo = LI[k]; L.LayerData = MoveTemp(Weight[k]); Layers.Add(L); }
   { FLandscapeImportLayerInfo L(VisLI->GetLayerName()); L.LayerInfo = VisLI; L.LayerData = MoveTemp(Vis); Layers.Add(L); }
   TMap<FGuid, TArray<uint16>> HeightPerLayer;  HeightPerLayer.Add(FGuid(), MoveTemp(Heights));      // keyed by the empty GUID: NewLandscape.cpp:1208-1210; Import reads FindChecked(FGuid()) at LandscapeEdit.cpp:3229-3231
   TMap<FGuid, TArray<FLandscapeImportLayerInfo>> WeightPerLayer; WeightPerLayer.Add(FGuid(), MoveTemp(Layers));
   ```
6. ```cpp
   ALandscape* L = World->SpawnActor<ALandscape>(FVector(0, -100.0*(9728 + padN), 0), FRotator::ZeroRotator);   // NewLandscape.cpp:1221
   L->LandscapeMaterial = LoadObject<UMaterialInterface>(nullptr, *MaterialPath);                                  // LS/Classes/LandscapeProxy.h:603-604; :1222
   L->SetActorRelativeScale3D(FVector(100, 100, 100));                                                              // :1223
   L->StaticLightingLOD = FMath::DivideAndRoundUp(FMath::CeilLogTwo((W'*H')/(2048*2048) + 1), 2u);                  // :1230 (harmless; static lighting is off)
   L->LOD0ScreenSize = 0.5f; L->LOD0DistributionSetting = 1.25f; L->LODDistributionSetting = 3.0f;                 // LandscapeProxy.h:546, :554, :558 — defaults, recorded so cliff-LOD tuning has a baseline
   L->Import(FGuid::NewGuid(), 0, 0, W'-1, H'-1, SectionsPerComponent, QuadsPerSection, HeightPerLayer, TEXT(""), WeightPerLayer,
             ELandscapeImportAlphamapType::Additive, TArrayView<const FLandscapeLayer>());                            // LandscapeProxy.h:1418-1420; NewLandscape.cpp:1238
   ```
   Inside `Import` (`LS/Private/LandscapeEdit.cpp:3123`): `check(InGuid.IsValid())` (:3128), `check(LandscapeComponents.Num()==0)` (:3155), sets `ComponentSizeQuads/NumSubsections/SubsectionSizeQuads` and `SetLandscapeGuid` (:3141-3144), creates components and writes their heightmap/weightmap texture data **on the CPU** (:3532 heights + normals; weight rows read at :3277), creates the `ULandscapeInfo` (:3708 `CreateLandscapeInfo()`), creates the default edit layer if none (:3717 `CreateDefaultLayer()`), and copies the same data into that layer with `FLandscapeEditDataInterface::SetHeightData` (:3784) / `SetAlphaData` (:3795), adding target layers for every weight layer with data (:3798-3800). Nothing here needs a GPU.
7. ```cpp
   ULandscapeInfo* Info = L->GetLandscapeInfo(); check(Info);                                        // LandscapeProxy.h:1243; NewLandscape.cpp:1240-1241
   FActorLabelUtilities::SetActorLabelUnique(L, TEXT("Landscape_Thanet"));                            // UED/Classes/Editor/EditorEngine.h:3429; NewLandscape.cpp:1243
   Info->UpdateLayerInfoMap(L);                                                                       // LS/Classes/LandscapeInfo.h:286; NewLandscape.cpp:1245
   for (k) if (!L->HasTargetLayer(LI[k]->GetLayerName())) L->AddTargetLayer(LI[k]->GetLayerName(), FLandscapeTargetLayerSettings(LI[k]));   // LandscapeProxy.h:1622, :1609, :119-134
   World->GetSubsystem<ULandscapeSubsystem>()->ChangeGridSize(Info, WorldPartitionGridSize);          // LandscapeSubsystem.h:153; NewLandscape.cpp:1286
   if (FApp::CanEverRender()) { Info->ForceLayersFullUpdate(); }                                     // LandscapeInfo.h:502 → ALandscape::ForceLayersFullUpdate (LandscapeEditLayers.cpp:7619-7629): GPU merge of edit layers into the final textures
   ```
   `ChangeGridSize` itself calls `ForceLayersFullUpdate` (`LandscapeConfigHelper.cpp:240`); the layer machinery is gated on `FApp::CanEverRender()` (`LandscapeEditLayers.cpp:7051 CanUpdateLayersContent`, `:1748`, `:1835`). **Therefore the import commandlet always runs with `-AllowCommandletRendering`** (`UE/Source/Runtime/Launch/Private/LaunchEngineLoop.cpp:2246`; Epic's own WP builders that render declare it, e.g. `UED/Public/WorldPartition/WorldPartitionMiniMapBuilder.h:20`). The no-RHI path is documented as untested (§9).
8. Save: `UEditorLoadingAndSavingUtils::SaveDirtyPackages(true, true)` (`UED/Public/FileHelpers.h:108`) — writes the map, the 140 proxy OFPA packages, the layer infos.
9. Report (`OutReportJson`): `components = Info->XYtoComponentMap.Num()` (`LandscapeInfo.h:189`), proxies via `Info->ForEachLandscapeProxy` (`:441`), `Info->GetLandscapeExtent(MinX,MinY,MaxX,MaxY)` (`:249`) expected `(0,0,13462,9906)`, bounds `Info->GetCompleteBounds()` (`:234`), the helper's suggested config, padding, fill, and the height probes of §8 evaluated with `ProbeHeightM` (which calls `GetHeightAtLocation(FVector(100x, -100y, 0), EHeightfieldSource::Editor)` on the parent and falls back to each proxy).

Closing Q3: the plugin's spline sampler uses `UStreetHeightfieldTerrain` by default (deterministic, identical to Blender, no dependency on loaded WP cells); `UStreetLandscapeTerrain` exists for validation (the probe compares both at the same points — they must agree to < 1 cm at vertices, since Import does not resample).

---

## 4. Adapter contract (`sources/adapters/unreal.py` → `data/thanet/out/unreal/`) — to reconcile with the adapter designer

### 4.1 Landscape tiles
- `landscape/hm_x{i}_y{j}.r16`: **513 x 513 little-endian uint16**, **north row first** (row 0 = northern edge, same as the GeoTIFF; no flip — the Unity adapter's `np.flipud` at `sources/adapters/unity.py:69` is exactly what we do *not* want), `h16 = clip(round(z_m*128) + 32768, 0, 65535)`; cells that are nodata **because of the clip** get `fill_h16` (water level); coverage gaps are already filled by step 05. File size exactly 526,338 bytes.
- `landscape/clip_x{i}_y{j}.r8`: 513 x 513 uint8, **255 = keep, 0 = clipped**; may be omitted for fully-kept tiles (then the manifest says `"clip": null`). Same row order.
- `landscape/w_{grass|sand|rock|water}_x{i}_y{j}.r8`: `weight_res x weight_res` uint8 (expected 256, from step 09's class fractions), north row first, the four layers summing to ≤ 255 per cell (importer renormalises after bilinear resampling to 513²).
- Only tiles the pipeline produced are written; excluded (outside clip) and missing tiles are listed, not written.

### 4.2 `landscape/landscape_manifest.json` — every field the importer reads
```json
{
  "site": "thanet", "crs": "EPSG:27700", "vertical_datum": "ODN",
  "origin": {"E": 627680, "N": 163080},
  "tile_m": 512, "grid_res": 513, "nx": 26, "ny": 19,
  "encoding": {"format": "r16", "byte_order": "little", "row_order": "north_first",
               "z_scale": 128, "z_offset": 32768, "formula": "h16 = round(z_m*128) + 32768",
               "z_window_m": [-256.0, 255.9921875]},
  "water_level_m": -0.6, "fill_h16": 32691,
  "clip": {"type": "halfplane", "line": [[628514, 169681], [635498, 163610]], "keep": "left"},
  "range_m": [-2.91, 60.0],
  "slope_qa": {"max_deg": 84.0, "pct_cells_over_45deg": 0.4},
  "tiles": [
    {"x": 17, "y": 16, "heightmap": "landscape/hm_x17_y16.r16", "clip": null,
     "weights": {"grass": "landscape/w_grass_x17_y16.r8", "sand": "...", "rock": "...", "water": "..."},
     "weight_res": 256, "clipped_cells": 0, "slope_max_deg": 83.6}
  ],
  "tiles_excluded": [[0, 0], [1, 0]],
  "tiles_missing": [],
  "frames": {"streetscape_json": "local metres from origin; x east, y north, z ODN",
             "unreal": "X_ue = 100*x, Y_ue = -100*y, Z_ue = 100*z — applied only by the Unreal plugin"}
}
```
Paths are relative to the manifest. The importer hard-fails if `grid_res != 513`, `row_order != "north_first"`, `z_scale != 128`, or a tile file size is wrong; it warns if `slope_qa` is absent (the in-engine cliff check then has no reference).

### 4.3 Streetscape JSON (BRIEF 4.2) — what `FStreetscapeJson::LoadSite` reads
Header: `schema_version` ("1.x" accepted), `site`, `crs`, `vertical_datum`, `origin {E,N}` (must equal the site actor's), `units: "m"`. Body:
- `profiles`: optional inline `{ "road": {id: FRoadProfileData…}, "edge": {…}, "hedge": {…} }` (snake_case keys, 2.11) — imported as DataAssets if not already present by id; normally the site references the shared `schema/profiles/*.json` by id only.
- `splines[]`: `id` (string, unique), `kind` (`road|rail|barrier|path`), `profile` (road/rail profile id), `edges: {"left": {"profile": id, "drop_kerbs": [FStreetDropKerb…], "barriers": [FStreetBarrierSegment…], "embankments": [FStreetEmbankment…], "hedge": {"profile": id, "segments": [FStreetHedgeSegment…]} | null}, "right": {…}}`, `points[]: {"p": [x,y,z], "width_m": 6.0|null, "roll_deg": 0|null, "profile": id|null, "tags": ["…"]}`, `sampling` (FStreetSamplingParams, optional), `source: {"osm_id": int, "layer": "roads|rail|barriers"}`, `overlay: [[x,y,z], …]` (raw OSM polyline, draped).
- `junctions[]` (Q7): passed through untouched and re-emitted by `SaveSite`; ignored by the v1 loader.
Everything is doubles in the JSON frame; the loader converts with `ToUE` when filling the spline component and the overlay component; `SaveSite` converts back with `ToJson` and rounds to 1e-4 m so round trips are byte-stable.

---

## 5. `P1/Tools/ue/*.py`, `P1/Tools/build.ps1`, command lines

### 5.1 Toolchain facts (verified present)
`UE/Binaries/Win64/UnrealEditor-Cmd.exe`, `UE/Binaries/Win64/UnrealEditor.exe`, `UE/Binaries/ThirdParty/DotNet/10.0/win-x64/dotnet.exe`, `UE/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll`, `UE/Binaries/ThirdParty/Python3/Win64/python.exe` (3.11, no numpy — scripts are stdlib + `unreal`).

### 5.2 Build — `Tools/build.ps1`
```powershell
param([string]$Config = "Development", [switch]$ProjectFiles)
$UE = "C:\Program Files\Epic Games\UE_5.8\Engine"
$Proj = Resolve-Path "$PSScriptRoot\..\Thanet.uproject"
$dotnet = "$UE\Binaries\ThirdParty\DotNet\10.0\win-x64\dotnet.exe"
$ubt = "$UE\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.dll"
if ($ProjectFiles) { & $dotnet $ubt -projectfiles -project="$Proj" -game -engine -progress; exit $LASTEXITCODE }
& $dotnet $ubt ThanetEditor Win64 $Config -Project="$Proj" -WaitMutex -FromMsBuild 2>&1 | Tee-Object -FilePath "$PSScriptRoot\..\Saved\Logs\build.log"
exit $LASTEXITCODE
```
This is byte-for-byte what `Build.bat` runs (`UE/Build/BatchFiles/Build.bat:48, :78`; the proven invocation is line 2 of `C:/UnrealProjects/build6.log`: `dotnet "...UnrealBuildTool.dll" MCPGameProjectEditor Win64 Development -Project=... -WaitMutex -FromMsBuild`). **Success = exit code 0 and a `Result: Succeeded` line** (`build6.log:32`). `-WaitMutex` waits if another UBT (e.g. Alex's editor's Live Coding) holds the mutex. Output binaries: `P1/Binaries/Win64/UnrealEditor-Thanet.dll`, `P1/Plugins/Streetscape/Binaries/Win64/UnrealEditor-Streetscape.dll`, `-StreetscapeEditor.dll`, `-UnrealMCP.dll`. `Tools/build.sh` is a Git-Bash wrapper calling `powershell -File build.ps1`. Project files (`.sln`) are optional and git-ignored (root `.gitignore` covers `projects/*/*.sln`).

### 5.3 Headless runner — `Tools/ue/run_ue_python.ps1`
```powershell
param([Parameter(Mandatory)][string]$Script, [string]$Args = "", [switch]$Render, [string]$Log = "")
$UE = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$Proj = Resolve-Path "$PSScriptRoot\..\..\Thanet.uproject"
$Py = Resolve-Path "$PSScriptRoot\$Script"
if (-not $Log) { $Log = "$([IO.Path]::GetFileNameWithoutExtension($Script)).log" }
$flags = @("-run=pythonscript", "-script=`"$Py $Args`"", "-unattended", "-nopause", "-nosplash", "-stdout", "-FullStdOutLogOutput", "-NoLiveCoding", "-log=$Log")
if ($Render) { $flags += "-AllowCommandletRendering" }
& $UE "$Proj" @flags
exit $LASTEXITCODE
```
How the arguments travel: `UPythonScriptCommandlet::Main` extracts `-Script=` itself, accepting a quoted value (`PSP/Private/PythonScriptCommandlet.cpp:17-33`), and runs it in `ExecuteFile` mode (`PythonScriptTypes.h:78` default); the plugin splits the command at the first `.py` into file + argument string (`PSP/Private/PythonScriptPlugin.cpp:815-826`) and sets `sys.argv` from the tokens (`:196-210`, `FParse::Token` per token → `sys.argv`). Scripts therefore parse `sys.argv` with `argparse` on the tokens that start with `--` (`ue_common.parse_args()` filters positionally so the script path, if present as `argv[0]`, is ignored). Success: exit code 0 and the log line `Python script executed successfully` (`PythonScriptCommandlet.cpp:72`); an exception yields `Python script executed with errors` (`:67`) and a non-zero exit. Every script prints a final machine-readable line `THANET_OK <script> <json>` or `THANET_FAIL <script> <reason>` and raises on failure.

### 5.4 Scripts, in run order

| # | Script | Responsibility | Needs `-Render` |
|---|---|---|---|
| 0 | `ue_common.py` | paths (`project_dir()`, `data_dir()` = `C:/Users/Shadow/code/3duk/data/thanet/out/unreal`), `parse_args`, `log`, `save_all()` → `unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)`, `level()` helpers, `report(...)` | – |
| 1 | `01_bootstrap.py` | folders under `/Game/Thanet/{Maps,Materials,Profiles,Landscape/Layers}` (`unreal.EditorAssetLibrary.make_directory`, `EditorAssetLibrary.h:317`); **materials**: `M_Thanet_Landscape` = `unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_Thanet_Landscape", "/Game/Thanet/Materials", unreal.Material, unreal.MaterialFactoryNew())` (`UE/Source/Developer/AssetTools/Public/IAssetTools.h:349, :898`; `UED/Classes/Factories/MaterialFactoryNew.h:15`), `blend_mode = BLEND_MASKED` (`UE/Source/Runtime/Engine/Public/Materials/Material.h:486`; `ENG/Classes/Engine/EngineTypes.h:248`), nodes via `unreal.MaterialEditingLibrary.create_material_expression(mat, unreal.MaterialExpressionLandscapeLayerBlend, -600, 0)` (`UE/Source/Editor/MaterialEditor/Public/MaterialEditingLibrary.h:168`) with `layers = [unreal.LayerBlendInput(layer_name="grass", blend_type=LB_WEIGHT_BLEND, preview_weight=1), …sand, rock, water]` each fed by a `MaterialExpressionVectorParameter` colour (flat colours for the base; textures later), `connect_material_property(blend, "", MP_BASE_COLOR)` (`:232`), `MaterialExpressionLandscapeVisibilityMask` → `MP_OPACITY_MASK`, `recompile_material` (`:267`), `layout_material_expressions` (`:292`); `M_Street_Base` (parameters BaseColor/Roughness) + `MaterialInstanceConstant`s per material id via `unreal.MaterialInstanceConstantFactoryNew()` (`UED/Classes/Factories/MaterialInstanceConstantFactoryNew.h:15, :20 InitialParent`) and `set_material_instance_vector_parameter_value` (`:457`): tarmac, paint_white, paint_yellow, kerb_concrete, paving, grass, brick_red, steel, chainlink(_secondary), privet, steel_rail, concrete_sleeper, ballast; **`DT_StreetMaterials`** `UStreetMaterialTable` via `create_asset(..., unreal.StreetMaterialTable, unreal.DataAssetFactory())` with `factory.set_editor_property("data_asset_class", unreal.StreetMaterialTable)` (`UED/Classes/Factories/DataAssetFactory.h:19 UPROPERTY`); **profiles**: `unreal.StreetscapeEditorLibrary.import_profiles(str(schema/profiles), "/Game/Thanet/Profiles")`; **map**: `unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).new_level("/Game/Thanet/Maps/Thanet", True)` (`LevelEditorSubsystem.h:146-147`; `PSP/Private/PyEditor.cpp:180 get_editor_subsystem`), spawn `DirectionalLight` (pitch −45, yaw 30, 10 lux-ish intensity), `SkyLight` (real-time capture), `SkyAtmosphere`, `ExponentialHeightFog`, `VolumetricCloud`, and the `StreetscapeSiteActor` (TerrainSource = heightfield, ManifestPath, Profiles, Materials) via `unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(cls, loc, rot)` (`UED/Public/Subsystems/EditorActorSubsystem.h:228`); `save_current_level()` (`LevelEditorSubsystem.h:174`) + `save_all()`. | – |
| 2 | `02_import_landscape.py --manifest <path> [--wp-grid 4] [--qps 127] [--sections 2]` | `unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level("/Game/Thanet/Maps/Thanet")` (`:167`), `unreal.StreetscapeLandscapeImporter.import_site(...)`, prints the report, runs the §8 probes, `save_all()`. | **yes** |
| 3 | `03_import_streetscape.py --json <site.json> [--player-start]` | `load_level`, `unreal.StreetscapeEditorLibrary.import_streetscape_json(path, True)`, `save_all()`. Used for `schema/examples/test_stretch.json` first, then Thanet's `streetscape/*.json`. | – |
| 4 | `04_probe.py --points <csv> [--landscape]` | height/slope/clip probes (§8) through `StreetscapeLandscapeImporter.probe_height_m` (landscape) and a `StreetscapeEditorLibrary.probe_heightfield_m` wrapper around `UStreetHeightfieldTerrain`; `unreal.SystemLibrary.line_trace_single` for hole proof; CSV to stdout. | yes if landscape probes are wanted after a fresh load (needs `load_region`) |
| 5 | `05_screenshot.py --x --y --z --yaw --pitch --out <png> [--w 1920 --h 1080]` | `StreetscapeEditorLibrary.load_region(center, 1500 m)`; `rt = unreal.KismetRenderingLibrary.create_render_target_2d(world, w, h, RTF_RGBA8)` (`ENG/Classes/Kismet/KismetRenderingLibrary.h:48`); spawn `unreal.SceneCapture2D`, `cap = actor.get_capture_component2d()` (`ENG/Classes/Engine/SceneCapture2D.h:32`), `cap.texture_target = rt` (`ENG/Classes/Components/SceneCaptureComponent2D.h:80`), `capture_source = SCS_FINAL_COLOR_LDR`, `cap.capture_scene()` twice (`:299`; the second lets Lumen/VSM settle), `unreal.KismetRenderingLibrary.export_render_target(world, rt, dir, name)` (`:144`). Fallback if the commandlet has no viewport-dependent features: `UnrealEditor.exe Thanet.uproject -game -windowed -ResX=1920 -ResY=1080 -ExecCmds="HighResShot 1920x1080"` driven by the pawn after 3 s. | **yes** |

Interactive alternative: the same calls are available in the editor's Python console and through the MCP bridge (§6), never the only path.

### 5.5 Opening the project in the GUI
`& "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" "C:\Users\Shadow\code\3duk\projects\one\Thanet.uproject"` (after `build.ps1`; first launch compiles shaders for minutes). Safe alongside Alex's `MCPGameProject` editor because our MCP port is 55558 (§6). Do not use the running editor to open Thanet (BRIEF 4.5).

---

## 6. UnrealMCP plugin copy (closes Q10)

**Copy** from `MCP/`: `UnrealMCP.uplugin` and `Source/` (247 KB: `Source/UnrealMCP/UnrealMCP.Build.cs`, `Public/{UnrealMCPBridge.h, MCPServerRunnable.h, UnrealMCPModule.h, Commands/*.h}`, `Private/{UnrealMCPBridge.cpp, MCPServerRunnable.cpp, UnrealMCPModule.cpp, Commands/*.cpp}`) → `P1/Plugins/UnrealMCP/`. **Do not copy** `Binaries/` (67 MB) or `Intermediate/` (14 MB) — they are rebuilt by `build.ps1` and git-ignored (root `.gitignore`, `projects/*/Plugins/*/Binaries/`). Keep the local `spawn_actor` basic-shape addition (memory notes, `UnrealMCPEditorCommands.cpp`).

**What happens today when two editors run:** `UUnrealMCPBridge::Initialize` (`MCP/Source/UnrealMCP/Private/UnrealMCPBridge.cpp:84-97`) hard-codes `MCP_SERVER_PORT 55557` (`:63`, `:92`) and calls `StartServer()` unconditionally — also in commandlets, since it is a `UEditorSubsystem` (`UnrealMCPBridge.h:27-28`). `StartServer` creates the listener, then **`SetReuseAddr(true)`** (`:132`), then `Bind` (`:136-141`) — on failure it logs `Error` and returns without asserting (`:139-140`), and `Deinitialize`/`StopServer` cope with a null listener (`:170-200`). So a bind *failure* is benign. The real problem is that with `SO_REUSEADDR` set (`UE/Source/Runtime/Sockets/Private/BSDSockets/SocketsBSD.cpp:593-604`; no Windows override in `Runtime/Sockets/Private/Windows/SocketsWindows.cpp`) Windows lets a second socket bind the same `127.0.0.1:55557` when the first also set it — which Alex's running editor did — so the Thanet editor would **silently succeed** and start stealing connections meant for Alex's bridge.

**Changes in our copy** (all small, in `P1/Plugins/UnrealMCP/Source/UnrealMCP/`):
1. New `Public/UnrealMCPSettings.h`: `UCLASS(config=Engine, defaultconfig) class UUnrealMCPSettings : public UDeveloperSettings { UPROPERTY(config, EditAnywhere) int32 Port = 55557; UPROPERTY(config, EditAnywhere) bool bStartInEditor = true; UPROPERTY(config, EditAnywhere) bool bStartInCommandlets = false; }` — same pattern as `PSP/Private/PythonScriptPluginSettings.h:48-49`; the module already lists `DeveloperSettings` (`MCP/Source/UnrealMCP/UnrealMCP.Build.cs`, public deps). Environment override `UNREAL_MCP_PORT` via `FPlatformMisc::GetEnvironmentVariable` (`CORE/GenericPlatform/GenericPlatformMisc.h:619`). Thanet's `DefaultEngine.ini` sets `Port=55558` (1.4).
2. `UnrealMCPBridge.cpp:Initialize`: `if (IsRunningCommandlet() && !Settings->bStartInCommandlets) { UE_LOG(..., Display, "UnrealMCPBridge: commandlet, server not started"); return; }` (`CORE/CoreGlobals.h:234`); `Port = Settings->Port` (env wins).
3. **Delete `NewListenerSocket->SetReuseAddr(true);`** (`:132`). A genuine conflict now fails at `Bind` → existing `Error` log + return → editor continues. Add the port to the success/failure log lines (already there: `:139`, `:152`).
4. `UnrealMCP.uplugin`: `WhitelistPlatforms` → `PlatformAllowList` (deprecated fallback at `ModuleDescriptor.cpp:197`); add `"EnabledByDefault": false`.
5. `MCPServerRunnable.cpp`: unchanged apart from the C4459 fix already applied (memory).

The Python MCP server registered as `unrealMCP` still targets 55557 (Alex's editor). Driving Thanet interactively later means running a second server instance with the port as an argument — out of scope for this phase and noted in README.

---

## 7. Explorer pawn (closes Q9)

### 7.1 `AThanetExplorerPawn : ACharacter` (`ENG/Classes/GameFramework/Character.h:338`)
- Components: default capsule (radius 34, half-height 88) and `UCharacterMovementComponent`; `UCameraComponent* Camera` (`ENG/Classes/Camera/CameraComponent.h:32`) at `(0,0,64)` (eye ≈ 1.6 m), `bUsePawnControlRotation = true` (`:205`); `bUseControllerRotationYaw = true` (`ENG/Classes/GameFramework/Pawn.h:77`).
- Movement defaults: `MaxWalkSpeed 300` cm/s (`ENG/Classes/GameFramework/CharacterMovementComponent.h:275`), sprint multiplier 2.5; `MaxFlySpeed 1500`, sprint 6000 (`:287`); `BrakingDecelerationFlying 2000` (`:353`); `MaxStepHeight 45` (kerbs are 12.5 cm); `JumpZVelocity 420`.
- Fly toggle: `GetCharacterMovement()->SetMovementMode(bFly ? MOVE_Flying : MOVE_Walking)` (`:1276`; enum `ENG/Classes/Engine/EngineTypes.h:1039`, `:1023`); in flying mode `IA_Ascend` adds `FVector::UpVector` movement.
- Input (`ThanetExplorerInput.h/.cpp`, D11 — **built in C++ at runtime, no `.uasset`**): in `SetupPlayerInputComponent`, `UInputMappingContext* IMC = NewObject<UInputMappingContext>(this)` (`EI/InputMappingContext.h:87`, a `UDataAsset` — any outer works), `UInputAction* IA_Move = NewObject<UInputAction>(this); IA_Move->ValueType = EInputActionValueType::Axis2D` (`EI/InputAction.h:55`, `:116` public UPROPERTY; enum `EI/InputActionValue.h:10-16`); `FEnhancedActionKeyMapping& M = IMC->MapKey(IA_Move, EKeys::W)` (`InputMappingContext.h:228`), `M.Modifiers.Add(NewObject<UInputModifierSwizzleAxis>(this))` (`EI/EnhancedActionKeyMapping.h:90`; `EI/InputModifiers.h:412`, default order `YXZ` `:420`), `S`: Swizzle + `UInputModifierNegate` (`:253`), `A`: Negate, `D`: none; `IA_Look` ← `EKeys::Mouse2D` with Negate(Y only, `:260-264`); `IA_Jump`/`IA_Ascend` ← `EKeys::SpaceBar`; `IA_Descend` ← `EKeys::LeftControl`; `IA_Sprint` ← `EKeys::LeftShift`; `IA_FlyToggle` ← `EKeys::F`; `IA_ToggleOverlay` ← `EKeys::O` (keys: `UE/Source/Runtime/InputCore/Classes/InputCoreTypes.h:416, :351, :369, :455, :399`). Then `ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>()->AddMappingContext(IMC, 0)` (`EI/EnhancedInputSubsystems.h:21, :37`) and `CastChecked<UEnhancedInputComponent>(PlayerInputComponent)->BindAction(IA_Move, ETriggerEvent::Triggered, this, &AThanetExplorerPawn::Move)` (`EI/EnhancedInputComponent.h:373, :482`; `ETriggerEvent` `EI/InputTriggers.h:34`). Rationale: reproducible from source, no binary assets to commit or regenerate; the objects are owned by the pawn and garbage-collected with it.
- Handlers: `Move(const FInputActionValue& V)` → `AddMovementInput(GetActorForwardVector(), V.Y); AddMovementInput(GetActorRightVector(), V.X)` (`Pawn.h:499`); `Look` → `AddControllerYawInput(V.X); AddControllerPitchInput(V.Y)` (`:548`, `:539`); `Jump` → `ACharacter::Jump()` (`Character.h:828`) when walking, else ascend.

### 7.2 `AThanetGameMode : AGameModeBase` (`ENG/Classes/GameFramework/GameModeBase.h:47`)
Constructor: `DefaultPawnClass = AThanetExplorerPawn::StaticClass()` (`:108`); `PlayerControllerClass` default; no HUD yet (minimap later).

### 7.3 Spawn
`03_import_streetscape.py --player-start` places one `APlayerStart` 2 m above the first waypoint of the first spline in the file (the test stretch), yaw `= bearing(p0→p1) − 90°` (BRIEF 4.2). `GlobalDefaultGameMode` in `DefaultEngine.ini` (1.4) selects the game mode; PIE/`-game` spawn there.

### 7.4 In-editor convenience
`Play` in the editor or `UnrealEditor.exe Thanet.uproject -game -windowed -ResX=1920 -ResY=1080`.

---

## 8. Build / verification checklist

1. **Compiles**: `Tools/build.ps1` → exit 0, `Result: Succeeded`; DLLs listed in 5.2 exist; zero warnings treated as errors under V7 (watch C4459 and deprecation warnings from `ULandscapeLayerInfoObject` public members — use the getters `GetLayerName()` `LandscapeLayerInfoObject.h:135`).
2. **Tests**: automation command of 2.13 prints `Test Completed. Result={Passed}` for all `Streetscape.*` tests.
3. **Bootstrap** (`run_ue_python.ps1 01_bootstrap.py`): log contains `Python script executed successfully`; `THANET_OK 01_bootstrap {"materials": 15, "profiles": 8, "map": "/Game/Thanet/Maps/Thanet"}`; files exist: `P1/Content/Thanet/Maps/Thanet.umap`, `P1/Content/Thanet/Profiles/*.uasset`, `P1/Content/Thanet/Materials/*.uasset`.
4. **Landscape** (`run_ue_python.ps1 02_import_landscape.py -Render -Args "--manifest ..."`): report shows `components: 2067`, `proxies: 140`, `extent: [0,0,13462,9906]`, `pad: {"east":150,"north":178}`, `fill_h16: 32691`, `helper_suggestion: {"qps":255,"sections":2,"components":[27,20]}`; `Content/__ExternalActors__/Thanet/Maps/Thanet/` holds 140+ packages.
5. **Cliffs in-engine** (in the same run, so nothing needs re-loading): probe the Cliftonville cliff around **E 636500 N 171700** = local `(8820, 8620)` = tile `x17_y16` (Margate `x7_y6`), i.e. UE `(882000, −862000)`. Sample `z` at integer-metre positions along the north-south line `x = 8820, y = 8570 … 8670` (101 points) with both `probe_height_m` (landscape) and the heightfield source; compute `slope_deg = atan(|z[k+1] − z[k]| / 1)`. Pass: landscape and heightfield agree within 0.01 m at every point (no resampling), and `max(slope_deg) ≥ 65°` and within 2° of the manifest tile's `slope_max_deg`. Repeat along 5 parallel lines (`x = 8800..8840` step 10) and report the maximum; expected 65–83° per `sources/OUTPUT.md` (the EA DTM shows 8.6 m in one cell at the steepest).
6. **Clip edge in-engine**: line midpoint `M = (632006, 166645.5)` → local `(4326, 3565.5)`; unit normal toward the kept side `n = (6071, 6984)/9254.4 = (0.6560, 0.7547)`. `P+ = M + 2n`, `P− = M − 2n` (local `(4327.31, 3567.01)` and `(4324.69, 3563.99)`). Pass: heightfield source returns a height at `P+` and "no ground" at `P−`; `unreal.SystemLibrary.line_trace_single(world, (X, Y, 20000), (X, Y, −20000), TRACE_TYPE_QUERY1, False, [], NONE, True, …)` blocks at `P+` and does **not** block at `P−` (hole in collision, `LandscapeCollision.cpp:1174`); repeat at 20 points spread along the 9,254 m line; the visible edge in `05_screenshot.py` from `(4326, 3565, 60)` looking down is a straight line.
7. **Streetscape** (`03_import_streetscape.py --json schema/examples/test_stretch.json --player-start`): one `AStreetscapeActor` labelled with the stretch id, components `Road, EdgeLeft, EdgeRight, Overlay`; `LastVertexCount`/`LastTriangleCount` equal the numpy fixture; `THANET_OK` line lists them; the map saves; reopening in a fresh commandlet and calling `rebuild_all` produces identical counts (rebuild-on-load path).
8. **Screenshot** (`05_screenshot.py -Render`): PNG written; visually shows the overlay line over the road.
9. **GUI**: `UnrealEditor.exe Thanet.uproject` opens to `/Game/Thanet/Maps/Thanet`; the Output Log shows `UnrealMCPBridge: Server started on 127.0.0.1:55558` while Alex's editor still answers on 55557 (`C:/UnrealProjects/test_bridge.py`).
10. **Pawn**: PIE — WASD walks on the road mesh (complex collision), `F` toggles fly, `Shift` sprints, `O` toggles the overlay.

---

## 9. Risks, ordered, with mitigations

1. **World Partition landscape import from a commandlet** (Import → ChangeGridSize → save, with the edit-layer GPU merge). Mitigations: always `-AllowCommandletRendering` (D12); prove the path first on a **2 x 2-tile Margate cutout** (1025 x 1025, 4 x 4 components of 254, same code) and then on a **non-WP level** (`new_level(path, False)`: `ChangeGridSize` no-ops because `IsGridBased()` is false, `LandscapeSubsystem.cpp:1301-1304`) to separate WP problems from import problems; if `Import` of 2067 components proves too slow or unstable, fall back to **two or four independent `ALandscape` actors** (separate GUIDs, split on tile boundaries — heights match exactly on shared edges, only material blending stops at the seam), or, last resort, run the import once through the editor GUI's Landscape mode with the same numbers.
2. **`ChangeGridSize`/`ForceLayersFullUpdate` behaviour without an RHI is unverified** — never run the landscape import without `-Render`; the heightfield terrain source keeps every other step independent of the landscape.
3. **Blender/Unreal geometry drift** (different interpolation, winding, station sets). Mitigations: our own resampler/stations/sweep in both languages (D8), shared fixtures (2.13), `ToDynamicMesh` winding test, and a `SaveSite` byte-stable round trip.
4. **Actor count and rebuild-on-load cost at Thanet scale** (~30k actors, three DynamicMesh rebuilds each as cells stream). Mitigations: measure on one tile first (`Streetscape.Perf.Tile` automation test logging ms/actor); knobs: serialize meshes for selected actors, per-tile actor grouping (one flag in the importer), static-mesh bake + HLOD later.
5. **Python API name drift**: exact `unreal.*` names are only knowable from the generated stub (`bDeveloperMode`, 1.4); the bootstrap must be written against `Intermediate/PythonStub/unreal.py` after the first build, not from memory.
6. **Screenshots headless**: SceneCapture in a commandlet may render before Lumen/VSM converge or WP cells finish loading. Mitigations: `load_region` first, capture twice, fall back to `-game` + `HighResShot`.
7. **Landscape material/layer name mismatch** (material layer names vs. layer-info names) yields black terrain or missing holes: the importer asserts that every `LandscapeLayerBlend` layer name in `LandscapeMaterial` (`ALandscapeProxy::RetrieveTargetLayerNamesFromMaterials`, `LandscapeProxy.h:1365`) has a matching import layer.
8. **Port hijack of Alex's MCP bridge** — fixed by design (D10); verify with the test in checklist 9 *before* opening the Thanet editor GUI.
9. **Deprecation churn in 5.8 Landscape** (`ULandscapeLayerInfoObject` members deprecated, `bCanHaveLayersContent` gone): use only the getters/APIs cited here; treat warnings as errors early.
10. **Disk**: ~2.7 GB landscape packages + ~1 GB DDC per full import; all under git-ignored paths; keep `data/` and `Content/__ExternalActors__` out of the repo.

---

## Appendix A — API citation index (all verified 2026-09-07)

| API | Location |
|---|---|
| `ALandscapeProxy::Import(...)` | `LS/Classes/LandscapeProxy.h:1418-1420`; body `LS/Private/LandscapeEdit.cpp:3123` |
| `FLandscapeImportLayerInfo`, `ELandscapeImportAlphamapType` | `LS/Classes/LandscapeProxy.h:193-222`, `:178-183` |
| `ALandscapeProxy::VisibilityLayer` | `LS/Classes/LandscapeProxy.h:1002` |
| `LandscapeMaterial`, `LandscapeHoleMaterial` | `LS/Classes/LandscapeProxy.h:603-608` |
| `GetHeightAtLocation`, `EHeightfieldSource` | `LS/Classes/LandscapeProxy.h:1101`; `LS/Classes/LandscapeHeightfieldCollisionComponent.h:32-38` |
| `AddTargetLayer`, `HasTargetLayer`, `FLandscapeTargetLayerSettings` | `LS/Classes/LandscapeProxy.h:1609, :1622, :119-134` |
| `CreateLandscapeInfo`, `GetLandscapeInfo` | `LS/Classes/LandscapeProxy.h:1242-1243` |
| `RetrieveTargetLayerNamesFromMaterials` | `LS/Classes/LandscapeProxy.h:1365` |
| LOD settings | `LS/Classes/LandscapeProxy.h:546, :554, :558` |
| `ULandscapeInfo::UpdateLayerInfoMap / GetLandscapeExtent / GetCompleteBounds / ForEachLandscapeProxy / ForceLayersFullUpdate / XYtoComponentMap` | `LS/Classes/LandscapeInfo.h:286, :249, :234, :441, :502, :189` |
| `ALandscape` edit layers (`CreateLayer`, `GetEditLayersConst`, `ForceUpdateLayersContent`, `ForceLayersFullUpdate`) | `LS/Classes/Landscape.h:276, :431, :462, :539-541`; `LS/Private/LandscapeEditLayers.cpp:7608, :7619-7629` |
| `Import` internals (GUID key, default layer, CPU writes) | `LS/Private/LandscapeEdit.cpp:3128, :3144, :3155, :3229, :3277, :3532, :3708, :3717, :3784, :3795, :3798-3800` |
| `CanUpdateLayersContent` requires `FApp::CanEverRender()` | `LS/Private/LandscapeEditLayers.cpp:7045-7054` |
| `FLandscapeConfigHelper::ChangeGridSize / PartitionLandscape`, valid sizes | `LS/Public/LandscapeConfigHelper.h:71-72`; `LS/Private/LandscapeConfigHelper.cpp:24-25, :96-170, :240` |
| `ULandscapeSubsystem::ChangeGridSize`, `IsGridBased` | `LS/Public/LandscapeSubsystem.h:152-153`; `LS/Private/LandscapeSubsystem.cpp:1292-1310` |
| `LANDSCAPE_ZSCALE`, `MidValue`, `GetLocalHeight`, `GetTexHeight`, `LANDSCAPE_VISIBILITY_THRESHOLD` | `LS/Public/LandscapeDataAccess.h:13, :27, :30-38, :19` |
| Visibility mask compile `1 − weight` | `LS/Private/Materials/MaterialExpressionLandscapeVisibilityMask.cpp:20, :45-46` |
| `FLayerBlendInput::LayerName` | `LS/Classes/Materials/MaterialExpressionLandscapeLayerBlend.h:31-32` |
| `UE::Landscape::CreateTargetLayerInfo` | `LS/Public/LandscapeUtils.h:34, :321, :330`; `LS/Private/LandscapeUtils.cpp:307` |
| `ULandscapeLayerInfoObject::GetLayerName / SetLayerName` | `LS/Classes/LandscapeLayerInfoObject.h:135, :143` |
| `ULandscapeSettings::MaxComponents = 256` | `LS/Public/LandscapeSettings.h:105` |
| `FLandscapeImportHelper::ChooseBestComponentSizeForImport / TransformHeightmapImportData` | `LSE/Public/LandscapeImportHelper.h:140, :138`; `LSE/Private/LandscapeImportHelper.cpp:432-515` |
| `LandscapeEditorUtils::SetHeightmapData` | `LSE/Public/LandscapeEditorUtils.h:18` |
| Editor's New Landscape sequence (temp-package check, GUID keys, spawn/material/scale, Import, info, layer map, ChangeGridSize, regions) | `LSE/Private/LandscapeEditorDetailCustomization_NewLandscape.cpp:1161-1177, :1208-1210, :1221-1223, :1238, :1240-1245, :1286, :1300-1390, :1020 (visibility layer by name)` |
| `ULandscapeEditorObject::WorldPartitionGridSize = 2`, `WorldPartitionRegionSize = 16` | `LSE/Public/LandscapeEditorObject.h:657, :660` |
| `UDynamicMeshComponent` (SetMesh, EditMesh, NotifyMeshUpdated, ConfigureMaterialSet, SetTangentsType, collision) | `GF/Components/DynamicMeshComponent.h:171, :210, :220, :275, :619, :649, :714, :722, :729, :747, :751, :784, :258-259` |
| exported ctor | `UE/Intermediate/Build/Win64/UnrealEditor/Inc/GeometryFramework/UHT/DynamicMeshComponent.generated.h:62` |
| `UBaseDynamicMeshComponent` (draw path, shadows, raytracing, materials) | `GF/Components/BaseDynamicMeshComponent.h:47, :81-87, :381, :594, :631, :675, :680` |
| `UDynamicMesh` (Reset, IsEmpty, SetMesh, EditMesh, ProcessMesh) | `GF/UDynamicMesh.h:132, :154, :187-190, :201, :195` |
| `FDynamicMesh3` (Clear, AppendVertex, AppendTriangle, EnableAttributes, ReverseOrientation, CheckValidity) | `GC/DynamicMesh/DynamicMesh3.h:350, :668, :677, :1048, :1349, :1741` |
| `FDynamicMeshAttributeSet` (EnableMaterialID, GetMaterialID, PrimaryUV, PrimaryNormals, SetNumUVLayers) | `GC/DynamicMesh/DynamicMeshAttributeSet.h:360, :364, :198, :250, :175` |
| Overlays (`AppendElement`, `SetTriangle`), triangle attribute `SetValue` | `GC/DynamicMesh/DynamicMeshOverlay.h:755, :342`; `GC/DynamicMesh/DynamicMeshTriangleAttribute.h:294` |
| `FMeshNormals` | `GC/DynamicMesh/MeshNormals.h:141, :188, :219` |
| `USplineComponent` (metadata hooks, points, distance queries) | `ENG/Classes/Components/SplineComponent.h:57-72, :214, :256, :414-415, :528-556, :601, :605, :684, :727, :743, :762-770`; ctor export `Engine/UHT/SplineComponent.generated.h:248` |
| Water plugin metadata pattern | `UE/Plugins/Experimental/Water/Source/Runtime/Public/WaterSplineMetadata.h:58-118`, `WaterSplineComponent.h:48-49` |
| Component visualizer walks super classes | `UED/Private/UnrealEdEngine.cpp:1492-1495` |
| `UDataAsset`, `UPrimaryDataAsset` | `ENG/Classes/Engine/DataAsset.h:17, :47` |
| `FJsonObjectConverter` | `UE/Source/Runtime/JsonUtilities/Public/JsonObjectConverter.h:101, :124, :140, :239, :255, :313` |
| `FJsonSerializer`, readers/writers, print policies | `UE/Source/Runtime/Json/Public/Serialization/JsonSerializer.h:301, :377`; `JsonReader.h:1078`; `JsonWriter.h:778`; `Policies/PrettyJsonPrintPolicy.h:14`, `CondensedJsonPrintPolicy.h:14` |
| `ULineBatchComponent` (MinimalAPI, DrawLine, ClearBatch, INVALID_ID), `UWorld::GetLineBatcher`, `ELineBatcherType` | `ENG/Classes/Components/LineBatchComponent.h:126-129, :178-186, :216, :143`; `ENG/Classes/Engine/World.h:1023, :1011-1020` |
| `DrawDebugLine` (transient; rejected) | `ENG/Public/DrawDebugHelpers.h:22` |
| `AActor` WP/HLOD props, `AddInstanceComponent` | `ENG/Classes/GameFramework/Actor.h:559, :818, :2650, :4348` |
| `UPythonScriptCommandlet::Main` (`-Script=` parsing, result logs) | `PSP/Private/PythonScriptCommandlet.cpp:15-75` |
| file/args split, `sys.argv`, execution mode default | `PSP/Private/PythonScriptPlugin.cpp:815-826, :196-210`; `PSP/Public/PythonScriptTypes.h:36-44, :78` |
| `PythonizeName`, `get_editor_subsystem`, `new_object/load_asset/log` | `PSP/Private/PyGenUtil.cpp:1859`; `PSP/Private/PyEditor.cpp:180`; `PSP/Private/PyCore.cpp:1416, :1571, :2066` |
| `UPythonScriptPluginSettings` (`StartupScripts`, `AdditionalPaths`, `bDeveloperMode`) | `PSP/Private/PythonScriptPluginSettings.h:48-49, :66-71, :90-91` |
| `ULevelEditorSubsystem::NewLevel/NewLevelFromTemplate/LoadLevel/SaveCurrentLevel/SaveAllDirtyLevels` | `UE/Source/Editor/LevelEditor/Public/LevelEditorSubsystem.h:146-147, :157-158, :166-167, :173-174, :180-181` |
| `UEditorEngine::NewMap(bool)`, `UWorldFactory::bCreateWorldPartition` | `UED/Classes/Editor/EditorEngine.h:2041`; `UED/Private/EditorServer.cpp:2187, :2212`; `UED/Classes/Factories/WorldFactory.h:24` |
| `UEditorLoadingAndSavingUtils` (NewMapFromTemplate, LoadMap, SaveMap, SavePackages, SaveDirtyPackages) | `UED/Public/FileHelpers.h:48, :64, :75, :86, :108` |
| `UEditorActorSubsystem::SpawnActorFromClass` | `UED/Public/Subsystems/EditorActorSubsystem.h:228` |
| `UEditorAssetLibrary` (SaveAsset, SaveDirectory, MakeDirectory) | `UE/Plugins/Editor/EditorScriptingUtilities/Source/EditorScriptingUtilities/Public/EditorAssetLibrary.h:281, :292, :317` |
| `IAssetTools::CreateAsset`, `UAssetToolsHelpers::GetAssetTools` | `UE/Source/Developer/AssetTools/Public/IAssetTools.h:349, :898` |
| `UDataAssetFactory::DataAssetClass`, `UMaterialFactoryNew`, `UMaterialInstanceConstantFactoryNew::InitialParent` | `UED/Classes/Factories/DataAssetFactory.h:19`; `MaterialFactoryNew.h:15`; `MaterialInstanceConstantFactoryNew.h:15, :20` |
| `UMaterialEditingLibrary` | `UE/Source/Editor/MaterialEditor/Public/MaterialEditingLibrary.h:168, :232, :242, :267, :292, :408, :421, :457, :490` |
| `UMaterial::BlendMode`, `BLEND_Masked` | `UE/Source/Runtime/Engine/Public/Materials/Material.h:486`; `ENG/Classes/Engine/EngineTypes.h:248` |
| `CreatePackage`, `FAssetRegistryModule::AssetCreated`, `UPackage::SavePackage` | `UE/Source/Runtime/CoreUObject/Public/UObject/UObjectGlobals.h:1225`; `UE/Source/Runtime/AssetRegistry/Public/AssetRegistry/AssetRegistryModule.h:61`; `CoreUObject/Public/UObject/Package.h:1204` |
| `UKismetRenderingLibrary::CreateRenderTarget2D / ExportRenderTarget` | `ENG/Classes/Kismet/KismetRenderingLibrary.h:48, :144` |
| `USceneCaptureComponent2D::TextureTarget / CaptureScene`, `ASceneCapture2D::GetCaptureComponent2D` | `ENG/Classes/Components/SceneCaptureComponent2D.h:80, :299`; `ENG/Classes/Engine/SceneCapture2D.h:32` |
| `UAutomationBlueprintFunctionLibrary::TakeHighResScreenshot` (fallback) | `UE/Source/Developer/FunctionalTesting/Public/AutomationBlueprintFunctionLibrary.h:143` |
| `-AllowCommandletRendering`, `IsAllowCommandletRendering`, `FApp::CanEverRender` | `UE/Source/Runtime/Launch/Private/LaunchEngineLoop.cpp:2246`; `CORE/CoreGlobals.h:296`; `CORE/Misc/App.h:406` |
| WP skips region loading in commandlets; `FLoaderAdapterShape`; `UWorldPartitionBlueprintLibrary::LoadActors` | `ENG/Private/WorldPartition/WorldPartition.cpp:876-888`; `ENG/Public/WorldPartition/LoaderAdapter/LoaderAdapterShape.h:12`; `ENG/Public/WorldPartition/WorldPartitionActorLoaderInterface.h:35-37`; `ENG/Public/WorldPartition/WorldPartitionBlueprintLibrary.h:119` |
| `UWorld::IsPartitionedWorld` | `ENG/Classes/Engine/World.h:2968, :2973` |
| Enhanced Input (`UInputMappingContext::MapKey`, `UInputAction::ValueType`, modifiers, triggers, subsystem, `BindAction`) | `EI/InputMappingContext.h:87, :228`; `EI/InputAction.h:55, :116`; `EI/InputModifiers.h:213, :253, :260-264, :412, :420`; `EI/InputTriggers.h:34`; `EI/EnhancedActionKeyMapping.h:37, :80, :90`; `EI/EnhancedInputSubsystems.h:21, :37`; `EI/EnhancedInputComponent.h:373, :482, :497`; `EI/InputActionValue.h:10-16` |
| Input default classes are legacy unless overridden | `ENG/Private/UserInterface/InputSettings.cpp:52-53` |
| Character/movement/pawn/camera/game mode | `ENG/Classes/GameFramework/Character.h:338, :498, :828`; `CharacterMovementComponent.h:275, :287, :353, :1276`; `EngineTypes.h:1023, :1039`; `Pawn.h:77, :499, :539, :548`; `Camera/CameraComponent.h:32, :205`; `GameModeBase.h:47, :108` |
| `EKeys` | `UE/Source/Runtime/InputCore/Classes/InputCoreTypes.h:349, :351, :369, :399, :416, :455` |
| Automation macros/flags | `CORE/Misc/AutomationTest.h:88-133, :4297, :2653` |
| `CallInEditor`, `IsRunningCommandlet` | `UE/Source/Runtime/CoreUObject/Public/UObject/ObjectMacros.h:1047`; `CORE/CoreGlobals.h:234` |
| ToolMenus | `UE/Source/Developer/ToolMenus/Public/ToolMenus.h:123, :145, :169`; `ToolMenu.h:73`; `ToolMenuSection.h:62`; menu name `UE/Source/Editor/LevelEditor/Private/LevelEditorMenu.cpp:372` |
| `FActorLabelUtilities` | `UED/Classes/Editor/EditorEngine.h:3429` |
| `FPlatformMisc::GetEnvironmentVariable` | `CORE/GenericPlatform/GenericPlatformMisc.h:619` |
| `SO_REUSEADDR` in `FSocketBSD::SetReuseAddr`; no Windows override | `UE/Source/Runtime/Sockets/Private/BSDSockets/SocketsBSD.cpp:593-604`; `Runtime/Sockets/Private/Windows/` |
| Plugin descriptor `PlatformAllowList` (deprecated `WhitelistPlatforms`) | `UE/Source/Runtime/Projects/Private/ModuleDescriptor.cpp:197, :202` |
| GeoReferencing FlatPlanet multiply | `UE/Plugins/Runtime/GeoReferencing/Source/GeoReferencing/Private/GeoReferencingSystem.cpp:235, :292` |
| UnrealMCP port, bind path, `SetReuseAddr` | `MCP/Source/UnrealMCP/Private/UnrealMCPBridge.cpp:63, :84-97, :132, :136-141, :152`; `MCP/Source/UnrealMCP/Public/UnrealMCPBridge.h:27-28` |
| UBT invocation and success line | `UE/Build/BatchFiles/Build.bat:48, :78`; `C:/UnrealProjects/build6.log:2, :32` |
| Template conventions | `UE/Templates/TP_Blank/TP_Blank.uproject`, `Config/DefaultEngine.ini`, `Source/TP_Blank.Target.cs`, `Source/TP_Blank/TP_Blank.Build.cs` |
| Repo facts | `sources/OUTPUT.md` (terrain/networks sections), `sources/adapters/unity.py:69-71`, `sources/config/sites/margate.json` (origin, water_level), root `.gitignore` (projects/ ignores) |
