# Unreal Engine 5.8 project + Streetscape plugin — normative file-by-file plan

Supersedes `docs/design/unreal.md` (design phase, 2026-09-07) with every critique fix folded in
(§0). Engine citations are `path:line` under the roots below, verified 2026-09-07/08 on the installed
5.8.2. Repo facts likewise. Conventions: BRIEF 4.2 frames (DESIGN.md 2); schema names SCHEMA.md.

| Alias | Root |
|---|---|
| `UE` | `C:/Program Files/Epic Games/UE_5.8/Engine` |
| `TPL` | `C:/Program Files/Epic Games/UE_5.8/Templates` |
| `ENG` | `UE/Source/Runtime/Engine` |
| `LS` | `UE/Source/Runtime/Landscape` |
| `LSE` | `UE/Source/Editor/LandscapeEditor` |
| `UED` | `UE/Source/Editor/UnrealEd` |
| `GF` | `UE/Source/Runtime/GeometryFramework/Public` |
| `GC` | `UE/Source/Runtime/GeometryCore/Public` |
| `CORE` | `UE/Source/Runtime/Core/Public` |
| `COU` | `UE/Source/Runtime/CoreUObject/Public` |
| `PSP` | `UE/Plugins/Experimental/PythonScriptPlugin/Source/PythonScriptPlugin` |
| `EI` | `UE/Plugins/EnhancedInput/Source/EnhancedInput/Public` |
| `MCP` | `C:/UnrealProjects/unreal-mcp/MCPGameProject/Plugins/UnrealMCP` |
| `P1` | `C:/Users/Shadow/code/3duk/projects/one` |
| `DATA` | `C:/Users/Shadow/code/3duk/data/<site>/out/unreal` |

---

## 0. Decisions (final) and what changed from unreal.md

| # | Decision |
|---|---|
| D1 | Landscape import: **gated**. Prove a 2×2-tile Margate cutout, then a 16×16-component import, then attempt one `ALandscapeProxy::Import` of all 2067 components with memory logged; fall back to the engine's region flow (§3.7). Not "settled". |
| D2 | 127 quads/section × 2 sections = 254 quads, 53 × 39 = 2067 components, padded 13463 × 9907, padding **north and east**, fill h16 32691 / visibility 255 / water 255. |
| D3 | World Partition landscape grid size 4 → 140 streaming proxies. |
| D4 | Hole mask from the adapter's `vis_*.r8` (exact line, DESIGN.md 16); `clip_*.r8` for verification only. |
| D5 | Terrain sampling: `UStreetHeightfieldTerrain` reads the adapter's `landscape_manifest.json` + `hm_*.r16` + `clip_*.r8` (bit-identical to Blender); `UStreetLandscapeTerrain` for in-editor checks (±1 cm). |
| D6 | Renderers subclass `UDynamicMeshComponent`. `UProceduralMeshComponent` is the fallback only if DynamicMesh proves unworkable in a specific case, and that case must be recorded here (BRIEF 4.4). |
| D7 | One `AStreetscapeActor` per spline (≈ 24k for Thanet); meshes not serialised; `PreSave` stash + `PostSaveRoot` restore. |
| D8 | Spline: wrap `USplineComponent` for gizmos; **resampling, smoothing, banking and frames are a verbatim port of the numpy `spline.py`** (SCHEMA.md 3); parameters are the schema's `Sampling` keys. |
| D9 | Overlay: persistent line batcher with a stored `OverlayBatchId = FCrc::StrCrc32(*StreetId) \|\| 1`. |
| D10 | UnrealMCP: source-only copy, `UDeveloperSettings` port 55558, no server in commandlets, `SetReuseAddr` removed. |
| D11 | Explorer: `ACharacter` with fly toggle; Enhanced Input built in C++. |
| D12 | Every editor step headless via `-run=pythonscript`; landscape import / probes / screenshots with `-AllowCommandletRendering`. |
| D13 | JSON: hand-written strict serialisers (`FStreetscapeJson`), schema keys and enum strings verbatim, unknown keys rejected, nullables honoured; **no `FJsonObjectConverter`** (it cannot express nullable numbers, rejects/ignores unknown keys inconsistently, and writes enum names in PascalCase). |
| D14 | Markings: lifted strips (`lift_m`), DESIGN.md 4.1. Lateral `d` positive to the **left** (schema convention) throughout the C++ core. |
| D15 | Massing: `ImportMassing` builds grey extrusions per tile (`AStreetscapeMassingActor`). Furniture out of scope. |

Changed from unreal.md: USTRUCT fields renamed to the schema (§2.5); enums lower-snake in JSON; the
resampler (§2.5.4); left-positive lateral; lifted markings and dash frames (§2.6); rail rails at
`±(gauge/2 + head/2)`, ballast depth 0.45; `FStreetSegment` + timelines added (§2.5.6); importer reads
the adapter's manifest and file names (§4); D1 gated with the region fallback (§3.7); OSTN15 probes
(§8.6); PreSave/PostSaveRoot (§2.9); overlay batch id (§2.8); `TPL` paths (§1); actor count 24k;
collision citations (§3.5); `FStreetHedgeSegment` reduced; `EditInlineNew` terrain sources (§2.5.5);
rebuild-on-load prerequisites (§2.9); `ImportMassing` (§2.12); material names = SCHEMA.md 7;
`ImportProfiles` reads `{kind, id, profile}` and expects 20; fixtures come from the geometry task;
1004 = 4 m / 2 m.

---

## 1. The Unreal project (`P1/`)

### 1.1 `P1/Thanet.uproject`

```json
{ "FileVersion": 3, "EngineAssociation": "5.8", "Category": "", "Description": "Isle of Thanet explorer - Project One (3duk)",
  "Modules": [ { "Name": "Thanet", "Type": "Runtime", "LoadingPhase": "Default" } ],
  "Plugins": [
    { "Name": "Streetscape", "Enabled": true },
    { "Name": "UnrealMCP", "Enabled": true, "TargetAllowList": [ "Editor" ] },
    { "Name": "PythonScriptPlugin", "Enabled": true },
    { "Name": "EditorScriptingUtilities", "Enabled": true },
    { "Name": "ModelingToolsEditorMode", "Enabled": true, "TargetAllowList": [ "Editor" ] },
    { "Name": "EnhancedInput", "Enabled": true },
    { "Name": "GeometryScripting", "Enabled": false },
    { "Name": "GeoReferencing", "Enabled": false },
    { "Name": "Water", "Enabled": false } ] }
```

GeoReferencing stays off (the frame conversion is one multiply, DESIGN.md 2); GeometryScripting is not
needed (meshes are built on `FDynamicMesh3` / `UDynamicMeshComponent`, core modules).

### 1.2 `P1/Source/Thanet.Target.cs`, `ThanetEditor.Target.cs`

As `TPL/TP_Blank/Source/TP_Blank.Target.cs:10-12` (`TargetType.Game`, `BuildSettingsVersion.V7`,
`EngineIncludeOrderVersion.Unreal5_8`) with `ExtraModuleNames.Add("Thanet")`; the editor target
`TargetType.Editor`. `V7`/`Unreal5_8` are mandatory on this install (memory notes on the MCP port).

### 1.3 `P1/Source/Thanet/Thanet.Build.cs` + module files

Public deps `Core, CoreUObject, Engine, InputCore, EnhancedInput`; no dependency on `Streetscape`.
Files: `Thanet.h/.cpp` (`IMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, Thanet, "Thanet")`),
`ThanetGameMode.h/.cpp`, `ThanetExplorerPawn.h/.cpp`, `ThanetExplorerInput.h/.cpp` (§7). Rule (C4459
under V7): no file-scope non-static constants; use `namespace Thanet::Private { constexpr ... }`.

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

[/Script/HardwareTargeting.HardwareTargetingSettings]
TargetedHardwareClass=Desktop
AppliedTargetedHardwareClass=Desktop
DefaultGraphicsPerformance=Maximum
AppliedDefaultGraphicsPerformance=Maximum

[/Script/PythonScriptPlugin.PythonScriptPluginSettings]
+AdditionalPaths=(Path="Tools/ue")
bDeveloperMode=True

[/Script/Streetscape.StreetscapeSettings]
DataDir=../../data/thanet/out/unreal

[/Script/UnrealMCP.UnrealMCPSettings]
Port=55558
bStartInEditor=True
bStartInCommandlets=False
```

Renderer/RHI lines are the blank template's (`TPL/TP_Blank/Config/DefaultEngine.ini:6-15`; its
`GameDefaultMap` at `:4` points at the OpenWorld template, which we do not use — the map is created
empty by the bootstrap). `UPythonScriptPluginSettings` is `config=Engine, defaultconfig`
(`PSP/Private/PythonScriptPluginSettings.h:48-49`; `AdditionalPaths :70-71`, `bDeveloperMode :90-91`
generates `Intermediate/PythonStub/unreal.py`, the authority for Python names, `PSP/Private/PyGenUtil.cpp:1859 PythonizeName`).
`DataDir` is project-relative (resolved against `FPaths::ProjectDir()`).

### 1.5 `P1/Config/DefaultGame.ini`, `DefaultInput.ini`, `DefaultEditor.ini`

`DefaultGame.ini`: `ProjectID` (generate once), `ProjectName=Thanet`, `CompanyName=3duk`.
`DefaultInput.ini`: `DefaultPlayerInputClass=/Script/EnhancedInput.EnhancedPlayerInput`,
`DefaultInputComponentClass=/Script/EnhancedInput.EnhancedInputComponent` (as
`TPL/TP_Blank/Config/DefaultInput.ini:79-80`; the engine defaults are the legacy classes,
`ENG/Private/UserInterface/InputSettings.cpp:52-53`), `bEnableMouseSmoothing=True`.
`DefaultEditor.ini`: header comment only.

---

## 2. `P1/Plugins/Streetscape`

### 2.1 `Streetscape.uplugin`

Modules `Streetscape` (Runtime, Default, `PlatformAllowList: [Win64]`) and `StreetscapeEditor`
(Editor, Default, Win64); `CanContainContent: false`; depends on `PythonScriptPlugin`,
`EditorScriptingUtilities`. `PlatformAllowList` is the current key (`UE/Source/Runtime/Projects/Private/ModuleDescriptor.cpp:197`).

### 2.2 Build files

`Streetscape.Build.cs`: public `Core, CoreUObject, Engine, GeometryCore, GeometryFramework, Json,
Landscape, DeveloperSettings`; private `RenderCore, RHI`. `StreetscapeEditor.Build.cs`: public `Core,
CoreUObject, Engine, Streetscape`; private `UnrealEd, LevelEditor, ToolMenus, PropertyEditor,
EditorSubsystem, EditorFramework, Slate, SlateCore, Landscape, LandscapeEditor, AssetRegistry,
AssetTools, Json, Projects`. `PCHUsage = UseExplicitOrSharedPCHs`, `IWYUSupport = Full`.

### 2.3 File tree

```
Plugins/Streetscape/
  Streetscape.uplugin
  Source/Streetscape/Streetscape.Build.cs
    Public/StreetscapeModule.h            IModuleInterface; DEFINE_LOG_CATEGORY LogStreetscape
    Public/StreetscapeSettings.h          UStreetscapeSettings : UDeveloperSettings {DataDir, SiteName, OverlayLiftM 0.3}
    Public/StreetTypes.h                  enums + every schema USTRUCT (2.5.1)
    Public/StreetProfiles.h               URoadProfile / UEdgeProfile / UHedgeProfile DataAssets (2.5.2)
    Public/StreetMaterialTable.h          UStreetMaterialTable (2.5.3)
    Public/StreetSplineMath.h             FStreetSplineMath, FStreetFrames (pure C++) (2.5.4)
    Public/StreetSpline.h                 UStreetSplineMetadata, UStreetSplineComponent, FStreetSamples (2.5.4)
    Public/StreetTerrainSource.h          IStreetTerrainSource, UStreetTerrainSourceBase, UStreetHeightfieldTerrain, UStreetLandscapeTerrain (2.5.5)
    Public/StreetTimelines.h              FStreetRoadTimeline, FStreetSideTimeline, FStreetSideSpec (2.5.6)
    Public/StreetGeometry.h               FStreetMeshBuilder, FStreetSection, FStreetSweep, FStreetNoise, FStreetGeometry::ToDynamicMesh (2.7)
    Public/StreetRenderers.h              UStreetRendererBase, UStreetRoadRenderer, UStreetEdgeRenderer, UStreetHedgeRenderer (2.6)
    Public/StreetOverlayComponent.h       (2.8)
    Public/StreetscapeActor.h             AStreetscapeActor (2.9)
    Public/StreetscapeMassingActor.h      AStreetscapeMassingActor (2.12)
    Public/StreetscapeSiteActor.h         AStreetscapeSiteActor (2.10)
    Public/StreetscapeJson.h              FStreetscapeJson (2.11)
    Private/*.cpp (one per header) + Private/Tests/{StreetSpline,StreetSweep,StreetRoad,StreetEdge,StreetSeam,StreetHedge,StreetRail,StreetNoise,StreetJson,StreetGeometry,StreetPerf}Tests.cpp (2.13)
  Source/StreetscapeEditor/StreetscapeEditor.Build.cs
    Public/StreetscapeEditorModule.h      ToolMenus entry (2.12)
    Public/StreetscapeLandscapeImporter.h UStreetscapeLandscapeImporter (§3)
    Public/StreetscapeEditorLibrary.h     UStreetscapeEditorLibrary (2.12)
    Private/*.cpp
```

### 2.5 Runtime types

#### 2.5.1 `StreetTypes.h` — enums and USTRUCTs (fields = schema keys in PascalCase)

Every enumerator is named so that PascalCase → lower_snake gives the schema string; the JSON layer
serialises through explicit tables (§2.11). Nullable schema numbers are `TOptional<double>` members
(UHT accepts `TOptional` UPROPERTYs in 5.8: `UE/Source/Programs/Shared/EpicGames.UHT/Types/Properties/UhtOptionalProperty.cs`
exists and the engine itself declares `UPROPERTY() TOptional<bool> CachedHasVertexColors`,
`ENG/Classes/Engine/SkeletalMeshSourceModel.h:219-220`; if a specific member type is refused by UHT,
the fallback is `double X; bool bHasX;` with the same JSON behaviour). Units: `...M` metres, `...Deg` degrees, `...Pct` percent.

```cpp
UENUM() enum class EStreetRoadKind : uint8 { Road, Rail };
UENUM() enum class EStreetCamberKind : uint8 { Parabolic, Planar, None };
UENUM() enum class EStreetMarkingAnchor : uint8 { Centre, EdgeLeft, EdgeRight };
UENUM() enum class EStreetMarkingPattern : uint8 { Solid, Dashed, Double, None };
UENUM() enum class EStreetLipKind : uint8 { Radius, Chamfer, None };
UENUM() enum class EStreetBarrierType : uint8 { BrickWall, StoneWall, ConcreteWall, RetainingWall, ChainLink, WoodFence, Railing, GuardRail, None };
UENUM() enum class EStreetEmbankmentSide : uint8 { Left, Right, Both, Downhill, Uphill, Auto };
UENUM() enum class EStreetEmbankmentKind : uint8 { Batter, RetainingWall, Auto };
UENUM() enum class EStreetSide : uint8 { Left, Right };                 // sigma = +1 left, -1 right
UENUM() enum class EStreetSegmentSide : uint8 { Left, Right, Both, Centre };
UENUM() enum class EStreetSideOrBoth : uint8 { Left, Right, Both };
UENUM() enum class EStreetTopProfile : uint8 { Flat, Rounded, Domed };
UENUM() enum class EStreetFoliageMode : uint8 { None, Cards, Instances };
UENUM() enum class EStreetSleeperMode : uint8 { Instances, Merged };
UENUM() enum class EStreetSourceLayer : uint8 { Roads, Rail, Barriers, Authored };
UENUM() enum class EStreetOverlayKind : uint8 { OsmWay, Step06Smoothed, Other };
UENUM() enum class EStreetContinuation : uint8 { Seam, Way, Gap, None };   // None <-> null
UENUM() enum class EStreetSplineEnd : uint8 { Start, End };

USTRUCT() struct FStreetSampling {            // schema Sampling; every member optional -> TOptional, resolved by FStreetSampling::Resolve(spline, profile, kind)
  TOptional<double> StepM, MinStepM, CurvatureGain, SmoothingWindowM, WidthRampM, BankMaxDeg, BankProbeMinHalfWidthM, BankRateMaxDegPerM, PinBlendM;
  TOptional<int32> SmoothingPasses; TArray<double> ExtraStationsM; };
USTRUCT() struct FStreetSamplingResolved { double StepM = 2.0, MinStepM = 0.25, CurvatureGain = 20.0, SmoothingWindowM = 20.0, WidthRampM = 5.0, BankMaxDeg = 4.0,
  BankProbeMinHalfWidthM = 1.5, BankRateMaxDegPerM = 0.25, PinBlendM = 10.0; int32 SmoothingPasses = 1; TArray<double> ExtraStationsM;
  static FStreetSamplingResolved Defaults(EStreetRoadKind K); };   // rail: 1.0/0.25/60/40/2 passes/6 deg
USTRUCT() struct FStreetCamber { EStreetCamberKind Kind = Parabolic; TOptional<double> CrossfallPct, CamberM; };
USTRUCT() struct FStreetMarking { FString Id; EStreetMarkingAnchor Anchor = Centre; double OffsetM = 0, WidthM = 0.10; EStreetMarkingPattern Pattern = Solid;
  TOptional<double> DashM, GapM, DoubleGapM; double PhaseM = 0; FName Material; double LiftM = 0.004; TOptional<double> S0M, S1M; };   // S1M unset -> to L
USTRUCT() struct FStreetRailSection { FString ProfileId; double HeightM, HeadWidthM, FootWidthM, WebThicknessM, HeadDepthM, FootThicknessM; FName Material; };
USTRUCT() struct FStreetSleeper { double LengthM, WidthM, HeightM, PitchM, PhaseM = 0, EmbedM = 0.10; EStreetSleeperMode Mode = Instances; FName Material; };
USTRUCT() struct FStreetBallast { double ShoulderSlope = 1.5, DepthM = 0.45; FName Material; };
USTRUCT() struct FStreetRailSpec { double GaugeM = 1.435, PadM = 0.005; FStreetRailSection Rail; FStreetSleeper Sleeper; FStreetBallast Ballast; };
USTRUCT() struct FStreetLip { EStreetLipKind Kind = Radius; double SizeM = 0.02; int32 ArcPoints = 3; };
USTRUCT() struct FStreetSplitMaterial { bool bEnabled = false; FName Inner, Outer; double BoundaryFrac = 0.5; };
USTRUCT() struct FStreetDropKerb { double SM; double LengthM = 1.83, RampM = 0.915, TargetHeightM = 0.006; };
USTRUCT() struct FStreetSplineDropKerb { EStreetSideOrBoth Side; double SM; TOptional<double> LengthM, RampM, TargetHeightM; };
USTRUCT() struct FStreetBarrier {                 // BarrierSegment and BarrierInline (S0M/S1M unset for inline)
  TOptional<double> S0M, S1M; EStreetBarrierType Type = BrickWall; TOptional<double> HeightM, ThicknessM; FName Material;
  FName CopingMaterial = "coping_concrete"; double CopingOverhangM = 0.025, CopingHeightM = 0.05; TOptional<double> PostPitchM; double PostSizeM = 0.06;
  FName PostMaterial = "post_steel"; TArray<double> RailsM; double RailSizeM = 0.04, OffsetM = 0.0, SkirtM = 0.30; };
USTRUCT() struct FStreetEmbankment { TOptional<double> S0M, S1M; EStreetEmbankmentSide Side = Auto; EStreetEmbankmentKind Kind = Auto;
  double SlopeRatio = 1.5, WallThicknessM = 0.30, WallCopingM = 0.10, ThresholdM = 0.35, ToeExtraM = 0.30; FName Material; };
USTRUCT() struct FStreetEdgeMaterials { FName Kerb, Pavement; };
USTRUCT() struct FStreetFoliage { EStreetFoliageMode Mode = None; double DensityPerM2 = 12, CardSizeM = 0.25; FName Material; FString MeshId; int32 Seed = 1; };
USTRUCT() struct FStreetHedgeSegment { double S0M; TOptional<double> S1M; double OffsetM = 0.1; TOptional<double> HeightOverrideM, WidthOverrideM; };
USTRUCT() struct FStreetPoint { double X, Y; TOptional<double> Z, RollDeg, WidthM; TArray<FString> Tags; };
USTRUCT() struct FStreetSegmentRoad { TOptional<double> WidthM; FString ProfileId; double EdgeExtraLeftM = 0, EdgeExtraRightM = 0; TOptional<TArray<FStreetMarking>> Markings, MarkingsAdd; };
USTRUCT() struct FStreetSegmentEdge { FString ProfileId; TOptional<double> KerbWidthM, KerbHeightM, PavementWidthM, PavementCrossfallPct; TOptional<FStreetSplitMaterial> SplitMaterial;
  bool bBarrierSet = false; TOptional<FStreetBarrier> Barrier;          // set && !Barrier  <=>  JSON null ("none")
  bool bEmbankmentSet = false; TOptional<FStreetEmbankment> Embankment; };
USTRUCT() struct FStreetSegmentHedge { bool bPresent = true; FString ProfileId; TOptional<double> OffsetM, HeightM, WidthM; };
USTRUCT() struct FStreetSegment { FString Id; double S0M; TOptional<double> S1M; EStreetSegmentSide Side; TOptional<double> RampM;
  TOptional<FStreetSegmentRoad> Road; TOptional<FStreetSegmentEdge> Edge; TOptional<FStreetSegmentHedge> Hedge; };
USTRUCT() struct FStreetSource { EStreetSourceLayer Layer = Authored; FString OsmId, Name, Cls; TArray<FString> OsmIds; TMap<FString, FString> Tags;
  TOptional<FIntPoint> Tile; TOptional<int32> SegmentIndex, SegmentCount; };
USTRUCT() struct FStreetOverlay { EStreetOverlayKind Kind = OsmWay; TArray<FVector3d> Pts; TArray<bool> PtsHaveZ; FString OsmId; };
USTRUCT() struct FStreetProfileIds { FString Road, EdgeLeft, EdgeRight, HedgeLeft, HedgeRight; };   // empty = null
USTRUCT() struct FStreetFlags { bool bBridge = false, bTunnel = false, bZGap = false, bSteps = false, bDisused = false, bGaugeUnmapped = false, bClosedLoop = false; TOptional<int32> Tracks; };
USTRUCT() struct FStreetSplineDef { FString Id; FStreetSource Source; FStreetProfileIds ProfileIds; TArray<FStreetPoint> Points; FStreetSampling Sampling;
  TArray<FStreetSegment> Segments; TArray<FStreetSplineDropKerb> DropKerbs; TOptional<FStreetOverlay> Overlay; FString JunctionStart, JunctionEnd, ContinuesFrom, ContinuesTo;
  EStreetContinuation ContinuationFrom = None, ContinuationTo = None; TOptional<FVector3d> OverrunBefore, OverrunAfter; FStreetFlags Flags; TMap<FString, FString> Notes; };
USTRUCT() struct FStreetJunctionEnd { FString SplineId; EStreetSplineEnd End; };
USTRUCT() struct FStreetJunction { FString Id; double X, Y; TOptional<double> Z; double RadiusM = 0; bool bDisc = true; TArray<FStreetJunctionEnd> Ends; };
```

`Notes` keeps `_`-prefixed keys verbatim so `SaveSite` round-trips them.

#### 2.5.2 `StreetProfiles.h`

```cpp
USTRUCT() struct FRoadProfileData { EStreetRoadKind Kind = Road; int32 Lanes = 0; TArray<double> LaneWidthsM; double WidthM = 6.0; FName SurfaceMaterial = "tarmac";
  FStreetCamber Camber; double OverlapM = 0.04, SkirtDropM = 0.02, LateralStationSpacingM = 1.0; TArray<FStreetMarking> Markings; TOptional<FStreetRailSpec> Rail; FStreetSampling SamplingDefaults; };
USTRUCT() struct FEdgeProfileData { double KerbWidthM = 0.125, KerbHeightM = 0.125; FStreetLip Lip; double PavementWidthM = 1.8, PavementCrossfallPct = 2.5, PavementMaxCrossfallPct = 8.0,
  TuckDepthM = 0.03, TuckInM = 0.02, SkirtM = 0.30; FStreetEdgeMaterials Materials; FStreetSplitMaterial SplitMaterial; TArray<FStreetDropKerb> DropKerbs; TArray<FStreetBarrier> Barriers; TArray<FStreetEmbankment> Embankments; };
USTRUCT() struct FHedgeProfileData { double WidthM = 0.8, HeightM = 1.5; EStreetTopProfile TopProfile = Flat; double CornerRadiusM = 0.15; int32 CornerPoints = 4;
  double NoiseAmplitudeM = 0.06, NoiseScaleM = 0.6; int32 NoiseSeed = 1; double BaseSinkM = 0.10; FName Material = "privet_leaf"; FStreetFoliage Foliage; TArray<FStreetHedgeSegment> Segments; };

UCLASS(Abstract, BlueprintType) class UStreetProfileBase : public UDataAsset {   // ENG/Classes/Engine/DataAsset.h:17
  UPROPERTY(EditAnywhere) FName ProfileId; UPROPERTY(EditAnywhere) FString Notes;
  virtual bool ToJson(TSharedRef<FJsonObject>) const = 0; virtual bool FromJson(const TSharedRef<FJsonObject>&, FText* Err) = 0; };
UCLASS(BlueprintType) class URoadProfile  : public UStreetProfileBase { UPROPERTY(EditAnywhere, meta=(ShowOnlyInnerProperties)) FRoadProfileData Data; };
UCLASS(BlueprintType) class UEdgeProfile  : public UStreetProfileBase { UPROPERTY(EditAnywhere, meta=(ShowOnlyInnerProperties)) FEdgeProfileData Data; };
UCLASS(BlueprintType) class UHedgeProfile : public UStreetProfileBase { UPROPERTY(EditAnywhere, meta=(ShowOnlyInnerProperties)) FHedgeProfileData Data; };
```

Defaults are the schema's (SCHEMA.md 4). Assets are created by `ImportProfiles` from the 20 library
files (`{kind, id, profile}`); the loader prefers the document's inline profiles and falls back to the
site actor's assets by id only when a document lacks one.

#### 2.5.3 `StreetMaterialTable.h`

`UStreetMaterialTable : UDataAsset { TMap<FName, TSoftObjectPtr<UMaterialInterface>> Materials; TSoftObjectPtr<UMaterialInterface> Fallback; UMaterialInterface* Resolve(FName) const; }`
— keys are exactly the SCHEMA.md 7 names; `Resolve` warns once per unknown id and returns the magenta
fallback.

#### 2.5.4 `StreetSplineMath.h` / `StreetSpline.h` — the shared spline

`FStreetFrames { TArray<double> S; TArray<FVector3d> P, Th, NFlat, N, B; FStreetFrames At(TConstArrayView<double> SQuery) const; FStreetFrames Insert(TConstArrayView<double> SExtra) const; }`
(`TFrame3d` in `GC/FrameTypes.h:26` is reference only).

`FStreetSplineMath` (pure, JSON frame, doubles) — one static per numpy function, same names:
`MergeDuplicatePoints`, `CatmullRomDense(P, alpha 0.5, max_chord 0.1) → (s_d, xy_d, s_knots)`,
`Curvature`, `StepFor`, `AdaptiveStations(s_d, kappa_d, sampling, mandatory)`, `WidthFunction`,
`ApplyRampedOverride`, `RollMask`, `FillGapsAlong`, `MovingAverageArcLength(s, z, W, passes)` (shrinking
symmetric window), `ApplyPins`, `TerrainBankDeg`, `RateLimitBank(beta, s, r)` (forward then backward
pass), `BuildFrames`. The algorithm is SCHEMA.md 3, verbatim; **no `USplineComponent` curve is ever
used for geometry**.

```cpp
UCLASS() class UStreetSplineMetadata : public USplineMetadata {          // ENG/Classes/Components/SplineComponent.h:57-72 (pure virtuals :63-71)
  UPROPERTY(EditAnywhere) TArray<FStreetPoint> Points;                     // the schema points, JSON frame; the USplineComponent points mirror them in UE cm for gizmos
  // InsertPoint/UpdatePoint/AddPoint/RemovePoint/DuplicatePoint/CopyPoint/Reset/Fixup keep Points in step with the component's point count
};
USTRUCT() struct FStreetSamples {                                          // == numpy Spline results
  double LengthM = 0; TArray<double> S; TArray<FVector2d> XY; TArray<double> Kappa, Width, ExtraLeft, ExtraRight, ZRaw, ZRef, BankDeg; TArray<bool> Mandatory;
  FStreetFrames Frames; FStreetSamplingResolved Sampling; EStreetRoadKind Kind; uint32 Hash = 0;
  TArray<double> EdgeOffset(EStreetSide) const; TArray<double> EdgeHeight(EStreetSide) const; TArray<double> SurfaceH(TConstArrayView<double> D) const; };
UCLASS(ClassGroup=Streetscape, meta=(BlueprintSpawnableComponent)) class UStreetSplineComponent : public USplineComponent {   // ctor exported: UE/Intermediate/Build/Win64/UnrealEditor/Inc/Engine/UHT/SplineComponent.generated.h:248
  UPROPERTY(Instanced, EditAnywhere) TObjectPtr<UStreetSplineMetadata> Metadata;
  UPROPERTY(EditAnywhere) FStreetSplineDef Def;                             // the whole schema Spline (points duplicated in Metadata for editing)
  virtual USplineMetadata* GetSplinePointsMetadata() override;              // SplineComponent.h:414
  const FStreetSamples& Build(const IStreetTerrainSource* Terrain, const FStreetRoadTimeline& Road, const FStreetSideTimeline& Left, const FStreetSideTimeline& Right);  // cached by hash(Def, terrain id)
  void MarkDirty();
  int32 NumWaypoints() const; FVector3d WaypointJson(int32) const; void SetWaypointsJson(const TArray<FStreetPoint>&);   // sync the USplineComponent (cm) from Def.Points (m)
};
```

`Build` order = SCHEMA.md 3.1 → 3.6 with mandatory stations collected from the two timelines (§2.5.6).

#### 2.5.5 `StreetTerrainSource.h`

```cpp
UINTERFACE(MinimalAPI) class UStreetTerrainSource : public UInterface { GENERATED_BODY() };
class IStreetTerrainSource { public: virtual bool SampleHeight(double XM, double YM, double& OutZM) const = 0;   // JSON frame in, ODN metres out; false = no ground
                             virtual FString Describe() const = 0; };
UCLASS(Abstract, EditInlineNew, DefaultToInstanced, BlueprintType) class UStreetTerrainSourceBase : public UObject, public IStreetTerrainSource {};   // COU/UObject/ObjectMacros.h:237 CLASS_EditInlineNew, :260 CLASS_DefaultToInstanced
UCLASS(EditInlineNew, DefaultToInstanced, BlueprintType) class UStreetHeightfieldTerrain : public UStreetTerrainSourceBase {
  UPROPERTY(EditAnywhere) FString LandscapeDir;   // default: UStreetscapeSettings::DataDir / "landscape"
  // parsed from landscape_manifest.json (PIPELINE_CHANGES.md 13.3): TileM, Res, Nx, Ny, PerUnit (128), Offset (32768), Tiles{(i,j) -> files.heightmap, files.clip}, TilesMissing, TilesClipped
  mutable TMap<FIntPoint, TArray<uint16>> HeightCache; mutable TMap<FIntPoint, TArray<uint8>> ClipCache;   // LRU 64 tiles ~ 34 MB
  bool Load(FText* Err);
  // SampleHeight: i = floor(x/TileM), j = floor(y/TileM); tile absent -> false; cx = x - i*TileM, ry = (j+1)*TileM - y (px_m = TileM/(Res-1) = 1);
  //   x0 = min(floor(cx), Res-2), y0 = min(floor(ry), Res-2); bilinear over T[y0..y0+1][x0..x0+1]; false if any of the 4 clip bytes == 0; z = (h16 - Offset)/PerUnit
};
UCLASS(EditInlineNew, DefaultToInstanced, BlueprintType) class UStreetLandscapeTerrain : public UStreetTerrainSourceBase {
  UPROPERTY(EditAnywhere) TWeakObjectPtr<ALandscapeProxy> Landscape;
  // SampleHeight: TOptional<float> H = Landscape->GetHeightAtLocation(FVector(100*x, -100*y, 0), EHeightfieldSource::Complex);  LS/Classes/LandscapeProxy.h:1101; OutZM = H / 100. Tolerance vs heightfield: 1 cm at vertices.
};
```

`UStreetHeightfieldTerrain::SampleHeight` is a literal transcription of `terrain.Heightfield.sample`
(itself a transcription of `sources/derive/06_build_networks.py:54-69`); `Streetscape.Terrain.Bilinear`
asserts equality with the numpy fixture to 1e-9.

#### 2.5.6 `StreetTimelines.h` — segments resolution (SCHEMA.md 5)

`FStreetRoadTimeline::Resolve(const FStreetSplineDef&, const FStreetSiteProfiles&)` → profile intervals,
width knots, width overrides, extra overrides, painted markings, per-interval camber/overlap/skirt/material;
`FStreetSideTimeline::Resolve(def, EStreetSide, profiles)` → scalar overrides, material intervals,
painted barriers/embankments/hedges, drop kerbs; `MandatoryStations()`; `Evaluate(S) → FStreetSideSpec`
(arrays over stations: `KerbWidth, KerbHeight, PavementWidth, Crossfall, LipSize, Present, MatKerb,
MatPavement, MatInner, MatOuter, SplitFrac, DropFactor, DropTarget`, plus the interval lists and the
scalars `TuckDepth, TuckIn, Skirt, MaxCrossfall`). Free functions `PaintIntervals`,
`ApplyRampedOverride` mirror `schema.py`.

### 2.6 Renderers (`StreetRenderers.h`)

```cpp
UCLASS(Abstract, ClassGroup=Streetscape) class UStreetRendererBase : public UDynamicMeshComponent {   // GF/Components/DynamicMeshComponent.h; ctor exported (UHT DynamicMeshComponent.generated.h:62)
  UPROPERTY(EditAnywhere) bool bRebuildOnLoad = true; UPROPERTY(EditAnywhere) bool bCollision = true;
  UPROPERTY(VisibleAnywhere) TArray<FName> MaterialSlotIds; UPROPERTY(VisibleAnywhere) int32 LastVertexCount = 0, LastTriangleCount = 0; UPROPERTY(VisibleAnywhere) double LastBuildMs = 0;
  UPROPERTY(VisibleAnywhere) FStreetBuildStats Stats;                       // the stats.json keys of DESIGN.md 14
  UFUNCTION(CallInEditor, BlueprintCallable) void Rebuild(); UFUNCTION(BlueprintCallable) void Clear();
protected:
  virtual void Build(FStreetMeshBuilder& Out, TArray<FStreetInstance>& OutInstances) = 0;
  void Commit(FStreetMeshBuilder&&, TArray<FStreetInstance>&&);
  virtual void OnRegister() override;                                      // ENG/Classes/Components/ActorComponent.h:830: if (bRebuildOnLoad && GetDynamicMesh()->IsEmpty()) Rebuild()   (GF/UDynamicMesh.h:154)
  virtual void PreSave(FObjectPreSaveContext) override;                     // COU/UObject/Object.h:278: if (bRebuildOnLoad && Ctx.IsSaving persistent) { Stash = MoveTemp(mesh); GetDynamicMesh()->Reset(); }   (GF/UDynamicMesh.h:132)
  void RestoreAfterSave();                                                  // called from AStreetscapeActor::PostSaveRoot: SetMesh(MoveTemp(Stash)) + collision
  TUniquePtr<UE::Geometry::FDynamicMesh3> Stash;
};
```

`Commit`: `FStreetGeometry::ToDynamicMesh(Builder, Mesh)`; `SetMesh(MoveTemp(Mesh))`
(`DynamicMeshComponent.h:210`); `ConfigureMaterialSet(Mats)` (`:619`) from `Site->Materials->Resolve`;
`SetTangentsType(AutoCalculated)`; `SetComplexAsSimpleCollisionEnabled(bCollision, true)` (`:722`);
`SetMeshDrawPath(StaticDraw)` (`GF/Components/BaseDynamicMeshComponent.h:631`); instances →
`UInstancedStaticMeshComponent::AddInstances` (`ENG/Classes/Components/InstancedStaticMeshComponent.h:275`)
per `(kind, size, material)` on sibling ISM components owned by the actor.

**`UStreetRoadRenderer`** = `road.py`: ribbon rows per DESIGN.md 4.1 (`n_int`, edge rows at
`±EdgeOffset`, skirts), camber per station, markings as lifted strips over `Frames.Insert(dash ends)`
with dash-end heights on the road triangles, groups `road`, `skirt_left`, `skirt_right`,
`marking:<id>`; `Kind == Rail` → ballast/sleepers/rails per DESIGN.md 6. **No stations are added for
dashes.**

**`UStreetEdgeRenderer`** (`UPROPERTY EStreetSide Side`) = `edge.py`: kerb+pavement section, drop
factor, split materials, barriers (all nine types), embankments, groups `kerb`, `pavement`,
`barrier:<type>:<s0>`, `embankment:<kind>:<s0>`; reads `FStreetSideSpec`, never raw lists.

**`UStreetHedgeRenderer`** (`Side`) = `hedge.py`: volume sweep, `FStreetNoise::Fbm3` displacement
seeded from the profile, leaf-card instances → `UHierarchicalInstancedStaticMeshComponent`
(`ENG/Classes/Components/HierarchicalInstancedStaticMeshComponent.h:135`).

### 2.7 Geometry core (`StreetGeometry.h`) — pure C++, JSON frame, doubles

```cpp
struct FStreetSectionPoint { double O, H; FName Mat; double V; bool bSmooth; };
struct FStreetSection { TArray<FStreetSectionPoint> Points; bool bClosed; };
struct FStreetSweepParams { int32 Side = +1; TConstArrayView<double> Lateral, Height; TOptional<TArrayView<const double>> PointO, PointH /* N x P */; TConstArrayView<bool> Mask; bool bCapStart = true, bCapEnd = true; FName CapMat; FName Group; };
struct FStreetSweepResult { TArray<int32> VIdx /* N x R, -1 masked */; FIntPoint TriRange; int32 GroupId; };
struct FStreetMeshBuilder {                                  // == mesh.MeshBuffer
  TArray<FVector3d> V; TArray<FIndex3i> F; TArray<FVector2d> UV; TArray<int32> Mat, Grp; TArray<double> VS, VD, VH; TArray<FName> MaterialNames, GroupNames; TSet<FName> TwoSided;
  int32 MaterialId(FName); int32 GroupId(FName); int32 AppendVertices(...); void AppendTriangles(...); void AppendQuadStrip(...); void AppendPolygon(ring, mat, grp, normalHint);   // ear clipping, Newell normal
  TArray<FString> Validate() const; bool IsClosedManifold(const TSet<FName>* MatFilter) const; FStreetBuildStats Stats() const; };
struct FStreetSweep { static FStreetSweepResult Sweep(FStreetMeshBuilder&, const FStreetSection&, const FStreetFrames&, const FStreetSweepParams&); };   // rows/quads/winding/caps = DESIGN.md 4
struct FStreetNoise { static uint32 LowBias32(uint32); static double UnitNoise(uint32 i, uint32 seed); static double ValueNoise3(const FVector3d&, uint32 seed); static double Fbm3(const FVector3d&, uint32 seed); };
namespace FStreetGeometry { void ToDynamicMesh(const FStreetMeshBuilder& In, UE::Geometry::FDynamicMesh3& Out);
  double MeasureLateralOverlap(...); int32 CoincidentXYPositions(...); }   // test helpers = mesh.measure_lateral_overlap / coincident_xy_pairs (distinct positions)
```

`ToDynamicMesh` is **the** frame conversion for meshes: `Out.EnableAttributes()` (`GC/DynamicMesh/DynamicMesh3.h:1048`),
`Attributes()->EnableMaterialID()` (`GC/DynamicMesh/DynamicMeshAttributeSet.h:360`), `EnableTriangleGroups`
(`DynamicMesh3.h:1015`); vertices `AppendVertex(FVector3d(100X, −100Y, 100Z))` (`:668`); triangles
`AppendTriangle(FIndex3i(a, c, b), Grp)` (`:677`) — reversed because the Y mirror flips handedness;
UVs via `PrimaryUV()->AppendElement/SetTriangle`; material ids via `GetMaterialID()->SetValue`; normals
`FMeshNormals::InitializeOverlayToPerVertexNormals` (`GC/DynamicMesh/MeshNormals.h:188`) — duplicated
hard rows give crease edges. `Streetscape.Geometry.ToDynamicMesh` asserts a left-side kerb built from
`synthetic_straight.json` lands at UE `Y < 0`... precisely: the left kerb (JSON `y > 0`) has UE `Y < 0`
and its face normal, after conversion, points toward the carriageway.

### 2.8 `UStreetOverlayComponent`

`USceneComponent` storing `TArray<FVector3d> PtsJson` (from `overlay.pts`), colour, `ThicknessCm 12`,
`bShow`; `OnRegister` re-drapes on the site terrain source, lifts by `UStreetscapeSettings::OverlayLiftM`
(0.3), converts with `ToUE` and draws into the persistent batcher:
`GetWorld()->GetLineBatcher(UWorld::ELineBatcherType::WorldPersistent)` (`ENG/Classes/Engine/World.h:1023`,
enum `:1011`) → `DrawLine(..., LifeTime 0, BatchId)` (`ENG/Classes/Components/LineBatchComponent.h:178`);
`OnUnregister` → `ClearBatch(BatchId)` (`:216`). `UPROPERTY() uint32 OverlayBatchId` is assigned at
import as `FCrc::StrCrc32(*StreetId)` (`CORE/Misc/Crc.h:43`) or 1 if that is 0 (`INVALID_ID = 0`,
`LineBatchComponent.h:143`). Works in editor and `-game` (no `GetActorGuid`, which is `WITH_EDITOR`
only, `ENG/Classes/GameFramework/Actor.h:1147, :1180`).

### 2.9 `AStreetscapeActor`

```cpp
UCLASS() class AStreetscapeActor : public AActor {
  UPROPERTY(VisibleAnywhere) TObjectPtr<UStreetSplineComponent> Spline;   // root; holds FStreetSplineDef
  UPROPERTY(VisibleAnywhere) TObjectPtr<UStreetRoadRenderer> Road; TObjectPtr<UStreetEdgeRenderer> EdgeLeft, EdgeRight; TObjectPtr<UStreetHedgeRenderer> HedgeLeft, HedgeRight; TObjectPtr<UStreetOverlayComponent> Overlay;
  UPROPERTY(EditAnywhere) FString StreetId;                               // = Def.Id, also the label
  UFUNCTION(CallInEditor, BlueprintCallable) void RebuildAll();            // timelines -> Spline->Build(terrain, road, left, right) -> each renderer Build + Commit from the SAME FStreetSamples
  virtual void PostSaveRoot(FObjectPostSaveRootContext) override;          // ENG/Classes/GameFramework/Actor.h:2380: every renderer RestoreAfterSave()
  bool ToJson(TSharedRef<FJsonObject>) const; bool FromJson(const TSharedRef<FJsonObject>&, FText*);
};
```

`bIsSpatiallyLoaded = true`, main runtime grid, `bEnableAutoLODGeneration = false`. Components exist
only for non-null `profile_ids` slots. Rebuild-on-load needs `UStreetscapeSettings::DataDir` to exist
(DESIGN.md 10).

### 2.10 `AStreetscapeSiteActor` (one per level, `bIsSpatiallyLoaded = false`)

`SiteName`, `Crs`, `VerticalDatum`, `FVector2D OriginEN` (every document must match),
`UPROPERTY(EditAnywhere, Instanced) TObjectPtr<UStreetTerrainSourceBase> TerrainSource`, `TArray<TObjectPtr<UStreetProfileBase>> Profiles`,
`TObjectPtr<UStreetMaterialTable> Materials`, `bShowOverlay`; `PostLoad` pre-resolves every material
id; `FindProfile(FName)`; `static Get(UWorld*)`.

### 2.11 `FStreetscapeJson` — loader/saver and the frame conversion for points

```cpp
struct FStreetscapeJson {
  static FVector ToUE(const FVector3d& M)   { return FVector(100*M.X, -100*M.Y, 100*M.Z); }
  static FVector3d ToJson(const FVector& C) { return FVector3d(C.X/100, -C.Y/100, C.Z/100); }
  static double YawFromBearingDeg(double B) { return B - 90.0; }
  static bool LoadFile(const FString& Path, TSharedPtr<FJsonObject>& Out, FText* Err);   // FFileHelper + FJsonSerializer::Deserialize (UE/Source/Runtime/Json/Public/Serialization/JsonSerializer.h:301)
  static bool SaveFile(const FString& Path, const TSharedRef<FJsonObject>& In);          // FJsonSerializer::Serialize, pretty policy (:377)
  // Strict schema readers/writers, one pair per $def, hand-written with the STREET_JSON_* macros: unknown non-'_' key -> error naming the path; missing required -> error; null honoured for nullable fields; enums via explicit string tables (BrickWall <-> "brick_wall", None <-> "none", EdgeLeft <-> "edge_left", ...)
  static bool ReadSite(const TSharedRef<FJsonObject>&, FStreetSiteDoc& Out, FText* Err);  static TSharedRef<FJsonObject> WriteSite(const FStreetSiteDoc&);
  static bool ValidateStructure(const TSharedRef<FJsonObject>&, TArray<FString>& Problems);   // == io_json.validate_structure (SCHEMA.md 8)
  static bool LoadSite(const FString& FileOrDir, UWorld*, AStreetscapeSiteActor*, TArray<AStreetscapeActor*>& Out, FText* Err);   // a file, or a directory of site_x*_y*.json
  static bool SaveSite(const FString& Path, UWorld*, FText* Err);   // rounds to 1e-6 m; canonical key order = schema order
};
```

`LoadSite` refuses when `frame` ≠ const, `schema_version` not 1.x, `origin` ≠ site actor, or a profile
id is unresolved (inline first, site assets second). `Streetscape.Json.RoundTrip`:
`examples/test_stretch.json` → structs → JSON is equal after canonical ordering and 1e-6 rounding.

### 2.12 Editor module

`FStreetscapeEditorModule::StartupModule`: `UToolMenus::RegisterStartupCallback` →
`ExtendMenu("LevelEditor.MainMenu.Tools")` → section "Streetscape" with entries *Import landscape site…*,
*Import streetscape JSON…*, *Import massing…*, *Rebuild all streetscape actors*, *Toggle OSM overlay*
(`UE/Source/Developer/ToolMenus/Public/ToolMenus.h:145, :169`; `ToolMenu.h:73`; `ToolMenuSection.h:62`).

`UStreetscapeEditorLibrary : UBlueprintFunctionLibrary` (Python `unreal.StreetscapeEditorLibrary.*`):

| function | behaviour |
|---|---|
| `int32 ImportProfiles(FString JsonDir, FString PackagePath)` | for each `*.json`: read `{kind, id, profile}`; class by `kind`; `CreatePackage` (`COU/UObject/UObjectGlobals.h:1225`), `NewObject<U*Profile>(Pkg, *id, RF_Public\|RF_Standalone)`, `FromJson(profile)`, `FAssetRegistryModule::AssetCreated`, `UEditorLoadingAndSavingUtils::SavePackages` (`UED/Public/FileHelpers.h:86`); returns the count (**20**) |
| `int32 ImportStreetscapeJson(FString FileOrDir, bool bPlacePlayerStart)` | `FStreetscapeJson::LoadSite`; spawns one `AStreetscapeActor` per spline, label = id; `RebuildAll`; optional `APlayerStart` at the first spline's first point, yaw = bearing − 90 |
| `int32 ImportMassing(FString MassingDir)` | per `buildings_x*_y*.jsonl`: one `AStreetscapeMassingActor` with a `UDynamicMeshComponent`; per record extrude every ring from `base_z − skirt` to `base_z + h` (walls = quad strips, caps = `AppendPolygon` ear clipping), material `massing_grey`, `ToDynamicMesh`; `bIsSpatiallyLoaded` |
| `bool LoadRegion(FVector CenterUE, float RadiusCm)` | `FLoaderAdapterShape` (`ENG/Public/WorldPartition/LoaderAdapter/LoaderAdapterShape.h:9`) + `Load()`; needed because commandlets skip `LoadLastLoadedRegions` (`ENG/Private/WorldPartition/WorldPartition.cpp:880-886`) |
| `bool SaveAll()` | `UEditorLoadingAndSavingUtils::SaveDirtyPackages(true, true)` (`FileHelpers.h:108`) |
| `FString ExportSiteJson(FString Path)` | `FStreetscapeJson::SaveSite` |
| `float ProbeHeightfieldM(double XM, double YM)` | `UStreetHeightfieldTerrain::SampleHeight`; NaN if no ground |
| `FString ActorStatsJson(AStreetscapeActor*)` | the `stats.json` keys (DESIGN.md 14) |

### 2.13 Automation tests (`Private/Tests/`, `IMPLEMENT_SIMPLE_AUTOMATION_TEST`, `CORE/Misc/AutomationTest.h:4297`, flags `EditorContext | ProductFilter`)

All read `P1/Tools/blender/tests/fixtures/*.json` and `fixtures/expected.json` (geometry task,
DESIGN.md 3.10) so both toolchains assert one set of numbers:

| test | asserts |
|---|---|
| `Streetscape.Spline.Stations` | `straight_100` N = 54, gaps as SCHEMA.md 9.3; `sine_5_50`, `curve_R20_200` spacing ratios; `s` monotone; mandatory stations bitwise present |
| `Streetscape.Spline.Smoothing` | factor ≥ 2.5 with the `unit_noise(i, 7)` sequence, ends pinned, grade, ripple, W = 10 / two passes |
| `Streetscape.Spline.Bank` | 5.71° → 4.00° clamp; roll mask blend; rate limit 0.25°/m |
| `Streetscape.Spline.Frames` | `t_h·n = 0`, `b·Z = cos β`, `n·Z = sin β`; left kerb from `synthetic_straight` has JSON `y > 0` and UE `Y < 0` |
| `Streetscape.Terrain.Bilinear` | equals the numpy `Heightfield.sample` transcription on 10 000 hashed points incl. tile borders and clip NaN |
| `Streetscape.Sweep.Manifold` | closed square manifold, outward normals, triangle count `2·4·(N−1) + 2·2`; kerb section winding; caps |
| `Streetscape.Road.Markings` | strip centres/widths/dash ends/lift 0.004/double gap/edge anchor follows the 6→8 ramp |
| `Streetscape.Edge.Overlap` | 0.040 at every station both sides; coincident positions 2·N; height coherence 1e-9; flush split top |
| `Streetscape.Edge.DropKerb` | 0.006 / 0.0655 / back edge 0.150; both materials on the ramp |
| `Streetscape.Edge.Barriers` | wall manifold; 19 chain-link posts on [45, 100]/3; railing rails 3 |
| `Streetscape.Hedge.Volume` | manifold before/after noise; displacement ≤ 0.06; inner-face offsets |
| `Streetscape.Rail.Gauge` | 1.435 ± 0.001 inner faces, 1.5049 centres, rail top 0.21375, sleeper count/pitch, toe 4.75, bend spacing 0.83 |
| `Streetscape.Noise.KnownAnswer` | `lowbias32(1) = 0x688990c0` etc.; `unit_noise(0..4, 7)` |
| `Streetscape.Json.SchemaFixtures` / `RoundTrip` | `examples/test_stretch.json` and `synthetic_straight.json` load unchanged; save round-trips byte-equal |
| `Streetscape.Geometry.ToDynamicMesh` | winding flip; vertex count == input |
| `Streetscape.Perf.Tile` | ms per actor for one tile of adapter output (informational, logged) |

Run: `UnrealEditor-Cmd.exe Thanet.uproject -ExecCmds="Automation RunTests Streetscape; Quit" -unattended -nopause -nullrhi -stdout -FullStdOutLogOutput -log=tests.log`.

### 2.14 numpy ↔ C++ mirror (condensed)

`schema.py` → `StreetTypes.h`/`StreetProfiles.h`; `resolve_*`/`paint_intervals`/`apply_ramped_override`
→ `StreetTimelines.h`; `io_json.py` → `FStreetscapeJson`; `terrain.Heightfield` → `UStreetHeightfieldTerrain`;
`spline.py` → `FStreetSplineMath` + `UStreetSplineComponent::Build`; `sweep.py` → `FStreetSweep`;
`mesh.py` → `FStreetMeshBuilder`; `noise.py` → `FStreetNoise`; `road/edge/hedge.py` → the three
renderers; `bpy_bridge` → `Commit`; `tests/*` → `Private/Tests/*`.

---

## 3. Landscape (BRIEF 6 Q1–Q3; DESIGN.md 8–9)

### 3.1 Data → array

W = 13313, H = 9729 (north row first). Tile `(i, j)` sample `(c, r)` → column `512·i + c`, data row
`512·(18 − j) + r`. Shared edge samples are written twice and asserted equal (max discrepancy logged).
Encoding per DESIGN.md 2 (`LS/Public/LandscapeDataAccess.h:13, :19, :27, :30-38`).

### 3.2 Component size — 127 × 2 (D2)

Valid sizes `LS/Private/LandscapeConfigHelper.cpp:24-25`. `ChooseBestComponentSizeForImport(13313, 9729,
127, 2, out)` (`LSE/Public/LandscapeImportHelper.h:140`, `LSE/Private/LandscapeImportHelper.cpp:432-492`)
returns 255 × 2 (27 × 20) by its ≤ 32 rule; the importer logs it and uses 127 × 2: 2067 components,
padded W′ = 13463, H′ = 9907, padding 150 E / 178 N.

### 3.3 Padding and placement

Padded row `r′ = r + 178`, columns unchanged; actor at `FVector(0, −100·(9728 + 178), 0) = (0, −990600, 0)`,
rotation zero, scale (100, 100, 100); vertex `(c, r′)` at UE `(100c, 100r′ − 990600)`; site origin ↔
`r′ = 9906`. Fill: `h16 32691`, visibility 255, water 255, others 0 — for padding, `tiles_missing` and
`tiles_clipped`. The manifest's `ue_import_unpadded` block is informational; the importer computes the
placement itself.

### 3.4 World Partition grid 4 (D3)

`ULandscapeSubsystem::ChangeGridSize(Info, 4)` (`LS/Public/LandscapeSubsystem.h:153`; requires a
partitioned world, `ENG/Classes/Engine/World.h:2968`, and returns silently when `!IsGridBased()`,
`LS/Private/LandscapeSubsystem.cpp:1301-1304`) — it is the wrapper around BRIEF 4.4's
`FLandscapeConfigHelper::ChangeGridSize` (`LS/Public/LandscapeConfigHelper.h:71`, called at
`LandscapeSubsystem.cpp:1307`) → 14 × 10 = 140 proxies of 1016 m. Editor default
is 2 (`LSE/Public/LandscapeEditorObject.h:657`); region size 16 (`:660`).

### 3.5 Visibility and weightmaps (Q2)

Convention (verified): `LandscapeVisibilityMask` = `1 − weight(__LANDSCAPE_VISIBILITY__)`
(`LS/Private/Materials/MaterialExpressionLandscapeVisibilityMask.cpp:20, :45-46`) — weight 255 = hole;
render threshold 2/3 (`LandscapeDataAccess.h:19`); collision hole where the dominant layer is the
visibility layer (`LS/Private/LandscapeCollision.cpp:1276-1279`; hole index skips the triangle
`:644-654`); `LandscapeEdit.cpp:4411` is the Nanite/export marching-squares path. Visibility data =
the adapter's `vis_*.r8` (0 where absent, 255 for missing/excluded/padding). Layer infos for
`grass, sand, rock, water` via `UE::Landscape::CreateTargetLayerInfo(Name, "/Game/Thanet/Landscape/Layers", "LI_<name>")`
(`LS/Public/LandscapeUtils.h:330`), reused if present; visibility uses `ALandscapeProxy::VisibilityLayer`
(`LS/Classes/LandscapeProxy.h:1002`), entry name `VisibilityLayer->GetLayerName()`. Weights: assemble
the site mosaic `(26·256) × (19·256)` of 09 cells (centres at odd metres), resample **once** with
cell-centre-aware bilinear to `13313 × 9729`, pad, renormalise the four to 255 (residue to the largest;
all-zero stays zero). `ELandscapeImportAlphamapType::Additive` (`LandscapeProxy.h:178`). The landscape
material's `LandscapeLayerBlend` layer names must equal these (`ALandscapeProxy::RetrieveTargetLayerNamesFromMaterials`
check, `LandscapeProxy.h:1365`).

### 3.6 `UStreetscapeLandscapeImporter::ImportSite` sequence

```cpp
UFUNCTION(BlueprintCallable) static ALandscape* ImportSite(const FString& ManifestPath, int32 QuadsPerSection /*127*/, int32 SectionsPerComponent /*2*/, int32 WorldPartitionGridSize /*4*/,
                                                            const FString& MaterialPath, const FString& LayerInfoPackagePath, int32 MaxComponentsPerImport /*0 = all*/, FString& OutReportJson);
UFUNCTION(BlueprintCallable) static float ProbeHeightM(ALandscapeProxy*, double XM, double YM);   // GetHeightAtLocation(FVector(100x,-100y,0), EHeightfieldSource::Editor)/100
UFUNCTION(BlueprintCallable) static int32 CountLandscapeComponents(ALandscapeProxy*); static int32 CountStreamingProxies(ALandscapeProxy*);
```

1. `World = GEditor->GetEditorWorldContext().World()`; require `UWorld::IsPartitionedWorld(World)` and a
   saved package (`LSE/Private/LandscapeEditorDetailCustomization_NewLandscape.cpp:1161-1177`).
2. Parse `landscape_manifest.json` (§4.1); **hard-fail** on `res != 513`, `heightmap.row0 != "north"`,
   `heightmap.row_flip_for_ue != false`, `heightmap.z_encoding.per_unit != 128`, `offset != 32768`,
   `scale_z_cm != 100`, `weightmaps.alphamap_type != "Additive"`, a heightmap file size `≠ 2·res·res`,
   a clip/vis file size `≠ res·res`; warn if `slope_qa` absent. Compute `Q = qps·sections`, `Cx = ceil((W−1)/Q)`,
   `Cy`, `W′, H′, padN, padE`; log the helper's suggestion.
3. Allocate `TArray<uint16> Heights(W′·H′) = pad_value_h16`, `TArray<uint8> Vis = 255`, `Grass = Sand
   = Rock = 0`, `Water = 255`; per manifest tile copy the r16 rows into `512·(ny−1−j) + r + padN`, the
   vis bytes (or 0), and the mosaic-resampled weights; missing/excluded tiles keep the fill.
4. Layer infos (3.5); `TArray<FLandscapeImportLayerInfo> Layers` (`LS/Classes/LandscapeProxy.h:193`),
   `HeightPerLayer.Add(FGuid(), Heights)`, `WeightPerLayer.Add(FGuid(), Layers)` (empty-GUID key as
   `NewLandscape.cpp:1208-1210`).
5. `ALandscape* L = World->SpawnActor<ALandscape>(FVector(0, −100·(9728 + padN), 0), FRotator::ZeroRotator)`;
   `L->LandscapeMaterial = LoadObject<UMaterialInterface>(nullptr, *MaterialPath)` (`LandscapeProxy.h:604`);
   `SetActorRelativeScale3D(FVector(100,100,100))`; LOD defaults logged.
6. **Gate** (D1): if `MaxComponentsPerImport == 0` or `Cx·Cy ≤ MaxComponentsPerImport`:
   `L->Import(FGuid::NewGuid(), 0, 0, W′−1, H′−1, sections, qps, HeightPerLayer, TEXT(""), WeightPerLayer, Additive, {})`
   (`LandscapeProxy.h:1418`; body `LS/Private/LandscapeEdit.cpp:3155 check(LandscapeComponents.Num()==0)`,
   `:3708 CreateLandscapeInfo`, `:3717 CreateDefaultLayer`, `:3784 SetHeightData`, `:3795 SetAlphaData`).
   Otherwise the region path (3.7). Record RSS (`FPlatformMemory::GetStats().UsedPhysical`) and wall
   time before/after.
7. `Info = L->GetLandscapeInfo()` (`LandscapeProxy.h:1243`); `FActorLabelUtilities::SetActorLabelUnique(L, "Landscape_Thanet")`;
   `Info->UpdateLayerInfoMap(L)`; `AddTargetLayer` for each ground layer if absent (`LandscapeProxy.h:1609, :1622`);
   `World->GetSubsystem<ULandscapeSubsystem>()->ChangeGridSize(Info, grid)`; `Info->ForceLayersFullUpdate()`
   (needs rendering: `LandscapeEditLayers.cpp:7051`; commandlet runs with `-AllowCommandletRendering`,
   `UE/Source/Runtime/Launch/Private/LaunchEngineLoop.cpp:2246`).
8. `UEditorLoadingAndSavingUtils::SaveDirtyPackages(true, true)`.
9. Report JSON: `components`, `proxies`, `extent` (expected `[0, 0, 13462, 9906]`), `padding {east, north}`,
   `fill_h16`, `helper_suggestion`, `component_size {qps, sections}`, `regions_used`, `rss_mb {before,
   after_import, after_grid, after_save}`, `seconds {...}`, `probes[]` (§8.5–8.6), `weight_sum_histogram`.

### 3.7 Region fallback (when the single `Import` fails the gate)

Initial `Import` covers the first `min(16, Cx) × min(16, Cy)` components; then for each remaining
16×16 block: `ALandscapeProxy* P = Subsystem->FindOrAddLandscapeProxy(Info, SectionBase)`
(`LS/Public/LandscapeSubsystem.h:154`) → add the block's components (as `AddComponents`,
`NewLandscape.cpp:1058`) → `FLandscapeEditDataInterface Edit(Info); Edit.SetHeightData(minX, minY, maxX,
maxY, heights, 0, false, nullptr)` and `Edit.SetAlphaData(LayerInfo, …)` for the block rect (the calls
`Import` makes, `LandscapeEdit.cpp:3784, :3795`) → `Info->ForceLayersFullUpdate()` → save the new
proxies (`LandscapeEditorUtils::SaveLandscapeProxies`, `NewLandscape.cpp:1353`) → unload them before
the next block. This is the editor's own flow (`NewLandscape.cpp:1314-1362`).

### 3.8 Memory (2067 components, 256² textures)

Source arrays 267 MB + 5 × 133 MB; component heightmaps ≈ 722 MB with mips; weightmaps ≈ 790 MB; edit-layer
copies ≈ 1.5 GB; collision ≈ 0.4 GB; **peak ≈ 4.5 GB CPU** (28 GB machine), GPU ≈ 2.5 GB. Disk
≈ 2.7 GB of OFPA proxies (regenerated, ignored).

---

## 4. Adapter contract as read by Unreal (owned by the adapter, PIPELINE_CHANGES.md 13)

### 4.1 `landscape/landscape_manifest.json` — fields the importer and `UStreetHeightfieldTerrain` read

`site, crs, origin{E,N}, vertical_datum, tile_m, res, nx, ny, weight_res, frame`,
`heightmap{file, dtype, shape, row0, col0, row_flip_for_ue, z_encoding{formula, per_unit, offset, scale_z_cm, decode, quantum_m}, range_limit_m}`,
`clip_mask{file, semantics}`, `visibility{file, semantics, formula}`, `weightmaps{files, res, row0, bands, sum, alphamap_type}`,
`range_m, water_level, pad_value_h16, pad_visibility, clip, tiles_clipped, clipped_cells_total, slope_qa, tiles_missing, water_tiles, tiles_without_ground_raster, ue_import_unpadded`,
`tiles[] {x, y, files{heightmap, clip, vis, weights{grass, sand, rock, water}}, min_m, max_m, h16_min, h16_max, clip_state, clipped_cells, slope_max_deg, quad_origin}`.
All file names are bare and relative to the manifest's directory (`landscape/`). Weight files are
`weight_{band}_x{i}_y{j}.r8`.

### 4.2 Streetscape documents

`streetscape/site_x{i}_y{j}.json` per tile, schema 1.0.0, profiles inline; `LoadSite(dir)` loads all;
`streetscape/streetscape_manifest.json` for counts. `massing/buildings_x*_y*.jsonl` for `ImportMassing`.

---

## 5. Tools: build, headless runner, scripts

### 5.1 `Tools/build.ps1` (and `Tools/build.sh` wrapper)

```powershell
param([string]$Config = "Development", [switch]$ProjectFiles)
$UE = "C:\Program Files\Epic Games\UE_5.8\Engine"; $Proj = Resolve-Path "$PSScriptRoot\..\Thanet.uproject"
$dotnet = "$UE\Binaries\ThirdParty\DotNet\10.0\win-x64\dotnet.exe"; $ubt = "$UE\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.dll"
if ($ProjectFiles) { & $dotnet $ubt -projectfiles -project="$Proj" -game -engine -progress; exit $LASTEXITCODE }
& $dotnet $ubt ThanetEditor Win64 $Config -Project="$Proj" -WaitMutex -FromMsBuild 2>&1 | Tee-Object -FilePath "$PSScriptRoot\..\Saved\Logs\build.log"
exit $LASTEXITCODE
```

Byte-for-byte the proven invocation (`C:/UnrealProjects/build6.log:2`, `UE/Build/BatchFiles/Build.bat:48, :78`).
Success = exit 0 and `Result: Succeeded`. Outputs `P1/Binaries/Win64/UnrealEditor-Thanet.dll`,
`P1/Plugins/Streetscape/Binaries/Win64/UnrealEditor-Streetscape.dll`, `-StreetscapeEditor.dll`,
`P1/Plugins/UnrealMCP/Binaries/Win64/UnrealEditor-UnrealMCP.dll`.

### 5.2 `Tools/ue/run_ue_python.ps1`

```powershell
param([Parameter(Mandatory)][string]$Script, [string]$Args = "", [switch]$Render, [string]$Log = "")
$UE = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$Proj = Resolve-Path "$PSScriptRoot\..\..\Thanet.uproject"; $Py = Resolve-Path "$PSScriptRoot\$Script"
if (-not $Log) { $Log = "$([IO.Path]::GetFileNameWithoutExtension($Script)).log" }
$flags = @("-run=pythonscript", "-script=`"$Py $Args`"", "-unattended", "-nopause", "-nosplash", "-stdout", "-FullStdOutLogOutput", "-NoLiveCoding", "-log=$Log")
if ($Render) { $flags += "-AllowCommandletRendering" }
& $UE "$Proj" @flags; exit $LASTEXITCODE
```

`UPythonScriptCommandlet` parses `-Script=` (`PSP/Private/PythonScriptCommandlet.cpp:15-33`), logs
`Python script executed successfully` (`:72`) or `... with errors` (`:67`, non-zero exit). Scripts are
stdlib + `unreal` (UE's Python 3.11 has no numpy), parse `sys.argv`, and end with
`THANET_OK <script> <json>` or raise.

### 5.3 Scripts (`P1/Tools/ue/`), in run order

| # | script | command | needs `-Render` |
|---|---|---|---|
| 0 | `ue_common.py` | helpers: `project_dir()`, `data_dir()` (from `StreetscapeSettings.DataDir`), `parse_args`, `save_all()`, `report()` | – |
| 1 | `01_bootstrap.py` | `run_ue_python.ps1 01_bootstrap.py` — folders `/Game/Thanet/{Maps,Materials,Profiles,Landscape/Layers}`; `M_Thanet_Landscape` (Masked; `LandscapeLayerBlend` grass/sand/rock/water → BaseColor; `LandscapeVisibilityMask` → OpacityMask; `UMaterialEditingLibrary`, `UE/Source/Editor/MaterialEditor/Public/MaterialEditingLibrary.h:168, :232, :267`); `M_Street_Base` + one `MaterialInstanceConstant` per SCHEMA.md 7 name (20); `DT_StreetMaterials` (`UStreetMaterialTable`, keys = those names); `import_profiles(<schema/profiles>, "/Game/Thanet/Profiles")` → 20; empty WP map `new_level("/Game/Thanet/Maps/Thanet", True)` (`UE/Source/Editor/LevelEditor/Public/LevelEditorSubsystem.h:147`); lights, sky, fog; `StreetscapeSiteActor`; save. Prints `THANET_OK 01_bootstrap {"materials": 21, "profiles": 20, "map": "/Game/Thanet/Maps/Thanet"}` | – |
| 2 | `02_import_landscape.py --manifest <DATA>/landscape/landscape_manifest.json [--wp-grid 4] [--qps 127] [--sections 2] [--max-components 0]` | `load_level`, `StreetscapeLandscapeImporter.import_site(...)`, print the report, run the §8.5–8.6 probes, `save_all()` | yes |
| 3 | `03_import_streetscape.py --json <file-or-dir> [--player-start]` | `import_streetscape_json`; first `schema/examples/test_stretch.json`, then `<DATA>/streetscape` | – |
| 4 | `04_probe.py --points <csv> [--landscape]` | height/slope/clip probes through `probe_heightfield_m` / `probe_height_m` and `unreal.SystemLibrary.line_trace_single`; CSV to stdout | if landscape probes |
| 5 | `05_screenshot.py --x --y --z --yaw --pitch --out <png> [--w 1920 --h 1080]` | `load_region`, `SceneCapture2D` → render target → `export_render_target` (`ENG/Classes/Kismet/KismetRenderingLibrary.h:48, :144`; `SceneCaptureComponent2D.h:80, :299`); fallback `UnrealEditor.exe -game -ExecCmds="HighResShot 1920x1080"` | yes |
| 6 | `06_import_massing.py --dir <DATA>/massing` | `import_massing(dir)`; `save_all()` | – |

GUI: `UnrealEditor.exe P1/Thanet.uproject` after `build.ps1`; never Alex's running editor (BRIEF 4.5).

---

## 6. UnrealMCP copy (DESIGN.md 12)

Copy `MCP/UnrealMCP.uplugin` + `MCP/Source/**` → `P1/Plugins/UnrealMCP/`. Edits: new
`Public/UnrealMCPSettings.h` (`UCLASS(config=Engine, defaultconfig) UUnrealMCPSettings : UDeveloperSettings
{ int32 Port = 55557; bool bStartInEditor = true; bool bStartInCommandlets = false; }`, env
`UNREAL_MCP_PORT` via `FPlatformMisc::GetEnvironmentVariable`, `CORE/GenericPlatform/GenericPlatformMisc.h:619`);
`UnrealMCPBridge.cpp::Initialize` returns early in commandlets (`IsRunningCommandlet()`,
`CORE/CoreGlobals.h:234`) and reads the port from settings; **delete `SetReuseAddr(true)`**
(`MCP/Source/UnrealMCP/Private/UnrealMCPBridge.cpp:132`; `SO_REUSEADDR` semantics
`UE/Source/Runtime/Sockets/Private/BSDSockets/SocketsBSD.cpp:593-604`); `.uplugin` → `PlatformAllowList`,
`EnabledByDefault: false`. The Python MCP server still targets 55557 (Alex's editor); driving Thanet
interactively needs a second server instance with the port argument — out of scope, noted in README.

---

## 7. Explorer pawn (DESIGN.md 11)

`AThanetExplorerPawn : ACharacter` (`ENG/Classes/GameFramework/Character.h:338`): capsule 34/88, camera
`(0,0,64)` with `bUsePawnControlRotation`; `MaxWalkSpeed 300`, sprint ×2.5; `MaxFlySpeed 1500`, sprint
6000; `BrakingDecelerationFlying 2000`; `MaxStepHeight 45`; `JumpZVelocity 420`; fly toggle
`SetMovementMode(MOVE_Flying)` (`CharacterMovementComponent.h:1276`). Input objects created in
`SetupPlayerInputComponent`: `NewObject<UInputMappingContext>`, `NewObject<UInputAction>` (Axis2D for
move/look), `IMC->MapKey(IA, EKeys::W)` with `UInputModifierSwizzleAxis` / `UInputModifierNegate`
(`EI/InputMappingContext.h:228`, `EI/InputModifiers.h:253, :412`), `AddMappingContext(IMC, 0)`,
`BindAction(IA_Move, ETriggerEvent::Triggered, this, &AThanetExplorerPawn::Move)`
(`EI/EnhancedInputComponent.h`). Keys: WASD, Mouse2D, Space, LeftControl, LeftShift, F, O.
`AThanetGameMode::DefaultPawnClass = AThanetExplorerPawn`.

---

## 8. Verification checklist (every item is a command and an expected output)

1. **Compiles**: `Tools/build.ps1` → exit 0, `Result: Succeeded`, the four DLLs exist; no C4459.
2. **Tests**: §2.13 command prints `Test Completed. Result={Passed}` for every `Streetscape.*` test.
3. **Bootstrap**: `THANET_OK 01_bootstrap {"materials": 21, "profiles": 20, "map": "/Game/Thanet/Maps/Thanet"}`; `Content/Thanet/Profiles/*.uasset` = 20 files.
4. **Landscape (gated)**: (a) Margate 2×2 cutout manifest → `components: 16`; (b) `--max-components 256` run → 256 components, region path exercised; (c) full → `components: 2067`, `proxies: 140`, `extent: [0, 0, 13462, 9906]`, `padding: {"east": 150, "north": 178}`, `fill_h16: 32691`, `helper_suggestion: {"qps": 255, "sections": 2, "components": [27, 20]}`, `rss_mb` per step; `Content/__ExternalActors__/Thanet/Maps/Thanet/` ≥ 140 packages.
5. **Cliffs in-engine**: Cliftonville cliff around E 636500 N 171700 = local `(8820, 8620)`, tile (17, 16): sample `z` at integer metres along `x = 8820, y = 8570 … 8670` and four parallel lines `x = 8800 … 8840` step 10 with both `probe_height_m` and `probe_heightfield_m`; pass when the two agree within 0.01 m at every point and `max(atan(|Δz|))` ≥ 65° and within 2° of the tile's `slope_max_deg`.
6. **Clip edge**: line midpoint local `(4324.0, 3564.5)`, `P+ = (4325.31, 3566.01)`, `P− = (4322.69, 3562.99)` (read `clip.line` from the manifest, never hard-coded); pass when the heightfield returns a height at `P+` and none at `P−`, and `line_trace_single` from `(X, Y, 20000)` to `(X, Y, −20000)` blocks at `P+` and not at `P−`; repeat at 20 points along the line; the screenshot from `(4324, 3564.5, 60)` looking down shows a straight edge.
7. **Streetscape**: `03_import_streetscape.py --json schema/examples/test_stretch.json --player-start` → one `AStreetscapeActor` `authored:trinity_square` with `Road, EdgeLeft, EdgeRight, HedgeRight, Overlay`; `ActorStatsJson` equals the numpy `stats.json` of the Blender build on `length_m` (±0.05), `n_samples`, `overlap_min/max` (0.040), per-buffer vertex/triangle counts of `road`/`kerb`/`pavement` groups, marking strip count, instance counts; **save, then** trace from above the road blocks (mesh restored after save); reopen in a fresh commandlet → identical counts.
8. **Screenshot**: PNG written; overlay visible 0.3 m over the road.
9. **GUI + MCP**: Output Log `UnrealMCPBridge: Server started on 127.0.0.1:55558`; `C:/UnrealProjects/test_bridge.py` still answers on 55557.
10. **Pawn**: PIE — WASD walks on the road (complex collision), kerb step 12.5 cm climbed, `F` flies, `O` toggles the overlay.
11. **Massing**: `06_import_massing.py` → actor count = tiles with buildings; grey boxes visible over the landscape.

---

## 9. Risks, ordered

1. Single-call WP landscape import at 2067 components is unproven → gated proofs + region fallback (§3.7).
2. `ForceLayersFullUpdate` without an RHI is unverified → always `-Render`; heightfield source keeps everything else independent.
3. Blender/Unreal drift → one algorithm (SCHEMA.md 3), one fixture set, `SchemaFixtures`/`RoundTrip` tests.
4. 24k actors rebuilding on load → `Streetscape.Perf.Tile`; knobs: serialise selected actors, per-tile grouping, static bake.
5. Python name drift → write scripts against `Intermediate/PythonStub/unreal.py` after the first build.
6. Headless screenshots → `load_region`, capture twice, `-game` fallback.
7. Layer-name mismatch → the importer asserts material layer names against import layers.
8. MCP port hijack → fixed by design; verify checklist 9 before opening the GUI.
9. 5.8 Landscape deprecations → use only the cited getters; warnings as errors early.
10. `TOptional` UPROPERTY corner cases → the `double + bool` fallback stated in §2.5.1.
