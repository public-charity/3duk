// StreetTypes - enums and USTRUCTs of the Streetscape interchange schema 1.0.0 (UE_PLAN.md 2.5.1; SCHEMA.md 4).
//
// Fields are the schema keys in PascalCase (s0_m -> S0M, width_m -> WidthM, crossfall_pct -> CrossfallPct). Units:
// ...M metres, ...Deg degrees, ...Pct percent. Every enumerator is named so that PascalCase -> lower_snake gives the
// schema string (EdgeLeft <-> "edge_left", BrickWall <-> "brick_wall", None <-> "none"); the explicit tables live in
// StreetTypes.cpp (FStreetEnums) and the JSON layer (StreetscapeJson.h) is the only reader/writer.
//
// Presence rules (needed for a byte-equal round trip, UE_PLAN.md 2.11): numbers whose default depends on context are
// TOptional<double> / TOptional<int32> (unset = key absent or null); numbers with a fixed schema default are plain
// members initialised to that default; every struct derives from FStreetJsonBase, which remembers the keys the
// document carried (JsonKeys), the keys that were explicitly null (NullKeys) and the '_'-prefixed notes verbatim
// (Notes, as compact JSON text), so SaveSite writes back exactly what was read and nothing that was not.

#pragma once

#include "CoreMinimal.h"
#include "StreetTypes.generated.h"

UENUM(BlueprintType) enum class EStreetRoadKind : uint8 { Road, Rail };
UENUM(BlueprintType) enum class EStreetCamberKind : uint8 { Parabolic, Planar, None };
UENUM(BlueprintType) enum class EStreetMarkingAnchor : uint8 { Centre, EdgeLeft, EdgeRight };
UENUM(BlueprintType) enum class EStreetMarkingPattern : uint8 { Solid, Dashed, Double, None };
UENUM(BlueprintType) enum class EStreetLipKind : uint8 { Radius, Chamfer, None };
UENUM(BlueprintType) enum class EStreetBarrierType : uint8 { BrickWall, StoneWall, ConcreteWall, RetainingWall, ChainLink, WoodFence, Railing, GuardRail, None };
UENUM(BlueprintType) enum class EStreetEmbankmentSide : uint8 { Left, Right, Both, Downhill, Uphill, Auto };
UENUM(BlueprintType) enum class EStreetEmbankmentKind : uint8 { Batter, RetainingWall, Auto };
/** sigma = +1 left, -1 right (schema.LEFT / RIGHT). */
UENUM(BlueprintType) enum class EStreetSide : uint8 { Left, Right };
UENUM(BlueprintType) enum class EStreetSegmentSide : uint8 { Left, Right, Both, Centre };
UENUM(BlueprintType) enum class EStreetSideOrBoth : uint8 { Left, Right, Both };
UENUM(BlueprintType) enum class EStreetTopProfile : uint8 { Flat, Rounded, Domed };
UENUM(BlueprintType) enum class EStreetFoliageMode : uint8 { None, Cards, Instances };
UENUM(BlueprintType) enum class EStreetSleeperMode : uint8 { Instances, Merged };
UENUM(BlueprintType) enum class EStreetSourceLayer : uint8 { Roads, Rail, Barriers, Authored };
UENUM(BlueprintType) enum class EStreetOverlayKind : uint8 { OsmWay, Step06Smoothed, Other };
/** None <-> JSON null. */
UENUM(BlueprintType) enum class EStreetContinuation : uint8 { Seam, Way, Gap, None };
UENUM(BlueprintType) enum class EStreetSplineEnd : uint8 { Start, End };
UENUM(BlueprintType) enum class EStreetJunctionKind : uint8 { Disc, None };
UENUM(BlueprintType) enum class EStreetProfileKind : uint8 { Road, Edge, Hedge };

/** sigma of a side: +1 left, -1 right. */
inline int32 StreetSideSigma(EStreetSide Side) { return Side == EStreetSide::Left ? 1 : -1; }
inline int32 StreetSideIndex(EStreetSide Side) { return Side == EStreetSide::Left ? 0 : 1; }

/** Common base: what the JSON layer needs to write back exactly what it read (see the file comment). */
USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetJsonBase
{
	GENERATED_BODY()

	/** '_'-prefixed keys of this object, verbatim (value as compact JSON text). */
	UPROPERTY() TMap<FString, FString> Notes;
	/** Schema keys present in the document for this object (including keys whose value was null). */
	UPROPERTY() TSet<FString> JsonKeys;
	/** Schema keys whose value was explicitly null. */
	UPROPERTY() TSet<FString> NullKeys;

	bool HasKey(const TCHAR* Key) const { return JsonKeys.Contains(Key); }
	bool IsNull(const TCHAR* Key) const { return NullKeys.Contains(Key); }
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetMaterialHint : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<double> BaseColor;   // [r, g, b] linear; empty = absent
	UPROPERTY() TOptional<double> Roughness;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bTwoSided = false;
	UPROPERTY() TOptional<double> TextureRepeatM;
};

/** schema Sampling: every member optional; resolved by FStreetSamplingResolved::Resolve (SCHEMA.md 4.3). */
USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetSampling : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY() TOptional<double> StepM;
	UPROPERTY() TOptional<double> MinStepM;
	UPROPERTY() TOptional<double> CurvatureGain;
	UPROPERTY() TOptional<double> SmoothingWindowM;
	UPROPERTY() TOptional<int32> SmoothingPasses;
	UPROPERTY() TOptional<double> WidthRampM;
	UPROPERTY() TOptional<double> BankMaxDeg;
	UPROPERTY() TOptional<double> BankProbeMinHalfWidthM;
	UPROPERTY() TOptional<double> BankRateMaxDegPerM;
	UPROPERTY() TOptional<double> PinBlendM;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasExtraStationsM = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<double> ExtraStationsM;
};

/** The resolved sampling numbers (road or rail column of SCHEMA.md 4.3). */
USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetSamplingResolved
{
	GENERATED_BODY()
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") double StepM = 2.0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") double MinStepM = 0.25;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") double CurvatureGain = 20.0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") double SmoothingWindowM = 20.0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 SmoothingPasses = 1;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") double WidthRampM = 5.0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") double BankMaxDeg = 4.0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") double BankProbeMinHalfWidthM = 1.5;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") double BankRateMaxDegPerM = 0.25;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") double PinBlendM = 10.0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TArray<double> ExtraStationsM;

	/** Built-in column: road 2.0/0.25/20/20/1/5/4/1.5/0.25/10; rail 1.0/0.25/60/40/2 passes/6 deg. */
	static FStreetSamplingResolved Defaults(EStreetRoadKind Kind);
	/** spline.sampling > RoadProfile.sampling_defaults > built-in (schema.resolve_sampling). Null pointers = absent. */
	static FStreetSamplingResolved Resolve(EStreetRoadKind Kind, const FStreetSampling* ProfileDefaults, const FStreetSampling* SplineSampling);
	void Apply(const FStreetSampling& S);
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetCamber : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetCamberKind Kind = EStreetCamberKind::Parabolic;
	UPROPERTY() TOptional<double> CrossfallPct;
	UPROPERTY() TOptional<double> CamberM;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetMarking : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString Id;
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetMarkingAnchor Anchor = EStreetMarkingAnchor::Centre;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double OffsetM = 0.0;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double WidthM = 0.10;
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetMarkingPattern Pattern = EStreetMarkingPattern::Solid;
	UPROPERTY() TOptional<double> DashM;
	UPROPERTY() TOptional<double> GapM;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double PhaseM = 0.0;
	UPROPERTY() TOptional<double> DoubleGapM;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName Material = TEXT("white_paint");
	UPROPERTY(EditAnywhere, Category = "Streetscape") double LiftM = 0.004;
	UPROPERTY() TOptional<double> S0M;
	UPROPERTY() TOptional<double> S1M;   // unset -> to L
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetRailSection : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString ProfileId;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double HeightM = 0.15875;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double HeadWidthM = 0.06985;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double FootWidthM = 0.1397;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double WebThicknessM = 0.020;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double HeadDepthM = 0.045;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double FootThicknessM = 0.011;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName Material = TEXT("rail_steel");
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetSleeper : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") double LengthM = 2.5;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double WidthM = 0.25;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double HeightM = 0.15;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double PitchM = 0.65;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double PhaseM = 0.0;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double EmbedM = 0.10;
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetSleeperMode Mode = EStreetSleeperMode::Instances;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName Material = TEXT("sleeper_concrete");
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetBallast : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") double ShoulderSlope = 1.5;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double DepthM = 0.45;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName Material = TEXT("ballast");
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetRailSpec : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") double GaugeM = 1.435;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double PadM = 0.005;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetRailSection Rail;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetSleeper Sleeper;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetBallast Ballast;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetLip : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetLipKind Kind = EStreetLipKind::Radius;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double SizeM = 0.02;
	UPROPERTY(EditAnywhere, Category = "Streetscape") int32 ArcPoints = 3;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetSplitMaterial : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bEnabled = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName Inner;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName Outer;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double BoundaryFrac = 0.5;
};

/** DropKerb of an EdgeProfile: s_m is the START of the flat run (SCHEMA.md 4.9). */
USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetDropKerb : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") double SM = 0.0;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double LengthM = 1.83;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double RampM = 0.915;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double TargetHeightM = 0.006;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetSplineDropKerb : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetSideOrBoth Side = EStreetSideOrBoth::Both;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double SM = 0.0;
	UPROPERTY() TOptional<double> LengthM;
	UPROPERTY() TOptional<double> RampM;
	UPROPERTY() TOptional<double> TargetHeightM;

	FStreetDropKerb AsDropKerb() const;
};

/** BarrierSegment (S0M/S1M carried) and BarrierInline (S0M/S1M unset) share one struct (SCHEMA.md 4.10). */
USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetBarrier : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY() TOptional<double> S0M;
	UPROPERTY() TOptional<double> S1M;   // unset with S0M set and NullKeys("s1_m") -> to L
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetBarrierType Type = EStreetBarrierType::BrickWall;
	UPROPERTY() TOptional<double> HeightM;
	UPROPERTY() TOptional<double> ThicknessM;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName Material;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName CopingMaterial = TEXT("coping_concrete");
	UPROPERTY(EditAnywhere, Category = "Streetscape") double CopingOverhangM = 0.025;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double CopingHeightM = 0.05;
	UPROPERTY() TOptional<double> PostPitchM;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double PostSizeM = 0.06;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName PostMaterial = TEXT("post_steel");
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasRailsM = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<double> RailsM;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double RailSizeM = 0.04;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double OffsetM = 0.0;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double SkirtM = 0.30;

	/** rails_m if given; guard_rail [0.75, 0.55]; else [H - 0.02, 0.5 H, 0.10] (schema.Barrier.effective_rails). */
	TArray<double> EffectiveRails() const;
	bool IsWall() const { return Type == EStreetBarrierType::BrickWall || Type == EStreetBarrierType::StoneWall || Type == EStreetBarrierType::ConcreteWall || Type == EStreetBarrierType::RetainingWall; }
	bool IsFence() const { return Type == EStreetBarrierType::ChainLink || Type == EStreetBarrierType::WoodFence; }
	bool IsRailing() const { return Type == EStreetBarrierType::Railing || Type == EStreetBarrierType::GuardRail; }
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetEmbankment : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY() TOptional<double> S0M;
	UPROPERTY() TOptional<double> S1M;
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetEmbankmentSide Side = EStreetEmbankmentSide::Auto;
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetEmbankmentKind Kind = EStreetEmbankmentKind::Auto;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double SlopeRatio = 1.5;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double WallThicknessM = 0.30;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double WallCopingM = 0.10;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double ThresholdM = 0.35;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double ToeExtraM = 0.30;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName Material = TEXT("grass");
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetEdgeMaterials : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName Kerb = TEXT("concrete_kerb");
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName Pavement = TEXT("paving_slab");
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetFoliage : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetFoliageMode Mode = EStreetFoliageMode::None;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double DensityPerM2 = 12.0;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double CardSizeM = 0.25;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName Material;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString MeshId;
	UPROPERTY(EditAnywhere, Category = "Streetscape") int32 Seed = 1;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetHedgeSegment : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") double S0M = 0.0;
	UPROPERTY() TOptional<double> S1M;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double OffsetM = 0.1;
	UPROPERTY() TOptional<double> HeightOverrideM;
	UPROPERTY() TOptional<double> WidthOverrideM;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetPoint : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") double X = 0.0;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double Y = 0.0;
	UPROPERTY() TOptional<double> Z;         // pin
	UPROPERTY() TOptional<double> RollDeg;
	UPROPERTY() TOptional<double> WidthM;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FString> Tags;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetSegmentRoad : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY() TOptional<double> WidthM;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString ProfileId;
	UPROPERTY() TOptional<double> EdgeExtraLeftM;
	UPROPERTY() TOptional<double> EdgeExtraRightM;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasMarkings = false;      // 'markings' replaces
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetMarking> Markings;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasMarkingsAdd = false;   // 'markings_add' appends
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetMarking> MarkingsAdd;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetSegmentEdge : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString ProfileId;
	UPROPERTY() TOptional<double> KerbWidthM;
	UPROPERTY() TOptional<double> KerbHeightM;
	UPROPERTY() TOptional<double> PavementWidthM;
	UPROPERTY() TOptional<double> PavementCrossfallPct;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasSplitMaterial = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetSplitMaterial SplitMaterial;
	/** bBarrierSet && !bHasBarrier  <=>  JSON "barrier": null (paints "none"). */
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bBarrierSet = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasBarrier = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetBarrier Barrier;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bEmbankmentSet = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasEmbankment = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetEmbankment Embankment;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetSegmentHedge : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bPresent = true;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString ProfileId;
	UPROPERTY() TOptional<double> OffsetM;
	UPROPERTY() TOptional<double> HeightM;
	UPROPERTY() TOptional<double> WidthM;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetSegment : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString Id;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double S0M = 0.0;
	UPROPERTY() TOptional<double> S1M;
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetSegmentSide Side = EStreetSegmentSide::Both;
	UPROPERTY() TOptional<double> RampM;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasRoad = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetSegmentRoad Road;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasEdge = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetSegmentEdge Edge;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasHedge = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetSegmentHedge Hedge;

	bool AppliesTo(EStreetSide S) const
	{
		return Side == EStreetSegmentSide::Both || (Side == EStreetSegmentSide::Left && S == EStreetSide::Left) || (Side == EStreetSegmentSide::Right && S == EStreetSide::Right);
	}
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetSource : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetSourceLayer Layer = EStreetSourceLayer::Authored;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString OsmId;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasOsmIds = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FString> OsmIds;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString Name;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString Cls;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasTags = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TMap<FString, FString> Tags;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasTile = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<int32> Tile;
	UPROPERTY() TOptional<int32> SegmentIndex;
	UPROPERTY() TOptional<int32> SegmentCount;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetOverlay : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetOverlayKind Kind = EStreetOverlayKind::OsmWay;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FVector3d> Pts;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<bool> PtsHaveZ;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString OsmId;
};

/** All five keys required; empty string = null. */
USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetProfileIds : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString Road;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString EdgeLeft;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString EdgeRight;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString HedgeLeft;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString HedgeRight;

	const FString& Edge(EStreetSide S) const { return S == EStreetSide::Left ? EdgeLeft : EdgeRight; }
	const FString& Hedge(EStreetSide S) const { return S == EStreetSide::Left ? HedgeLeft : HedgeRight; }
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetContinuationKind : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetContinuation From = EStreetContinuation::None;
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetContinuation To = EStreetContinuation::None;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetOverrunPoints : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasBefore = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FVector3d Before = FVector3d::ZeroVector;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasAfter = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FVector3d After = FVector3d::ZeroVector;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetFlags : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bBridge = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bTunnel = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bZGap = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bSteps = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bDisused = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bGaugeUnmapped = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bClosedLoop = false;
	UPROPERTY() TOptional<int32> Tracks;
};

/** schema Spline (SCHEMA.md 4.13). */
USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetSplineDef : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString Id;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetSource Source;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetProfileIds ProfileIds;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetPoint> Points;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasSampling = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetSampling Sampling;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetSegment> Segments;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetSplineDropKerb> DropKerbs;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasOverlay = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetOverlay Overlay;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString JunctionStart;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString JunctionEnd;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString ContinuesFrom;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString ContinuesTo;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasContinuationKind = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetContinuationKind ContinuationKind;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasOverrunPoints = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetOverrunPoints OverrunPoints;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasFlags = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetFlags Flags;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetJunctionEnd : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString SplineId;
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetSplineEnd End = EStreetSplineEnd::Start;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetJunction : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString Id;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double X = 0.0;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double Y = 0.0;
	UPROPERTY() TOptional<double> Z;
	UPROPERTY() TOptional<double> RadiusM;
	/** Override of the DERIVED trim radius (SCHEMA.md 4.18). The adapter always writes null: leave it unset and the
	    radius is solved from RadiusM, the arm bearings and the arm half-widths, so it cannot go stale when a profile
	    width changes. Set, it replaces the solve for every arm of this junction. */
	UPROPERTY() TOptional<double> TrimRadiusM;
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetJunctionKind Kind = EStreetJunctionKind::Disc;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetJunctionEnd> Ends;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetOrigin : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") double E = 0.0;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double N = 0.0;
};

/** Explicit enum <-> schema string tables (never rely on UEnum display names). */
struct STREETSCAPE_API FStreetEnums
{
	static const TCHAR* ToString(EStreetRoadKind V);
	static const TCHAR* ToString(EStreetCamberKind V);
	static const TCHAR* ToString(EStreetMarkingAnchor V);
	static const TCHAR* ToString(EStreetMarkingPattern V);
	static const TCHAR* ToString(EStreetLipKind V);
	static const TCHAR* ToString(EStreetBarrierType V);
	static const TCHAR* ToString(EStreetEmbankmentSide V);
	static const TCHAR* ToString(EStreetEmbankmentKind V);
	static const TCHAR* ToString(EStreetSide V);
	static const TCHAR* ToString(EStreetSegmentSide V);
	static const TCHAR* ToString(EStreetSideOrBoth V);
	static const TCHAR* ToString(EStreetTopProfile V);
	static const TCHAR* ToString(EStreetFoliageMode V);
	static const TCHAR* ToString(EStreetSleeperMode V);
	static const TCHAR* ToString(EStreetSourceLayer V);
	static const TCHAR* ToString(EStreetOverlayKind V);
	static const TCHAR* ToString(EStreetContinuation V);
	static const TCHAR* ToString(EStreetSplineEnd V);
	static const TCHAR* ToString(EStreetJunctionKind V);
	static const TCHAR* ToString(EStreetProfileKind V);

	static bool Parse(const FString& S, EStreetRoadKind& Out);
	static bool Parse(const FString& S, EStreetCamberKind& Out);
	static bool Parse(const FString& S, EStreetMarkingAnchor& Out);
	static bool Parse(const FString& S, EStreetMarkingPattern& Out);
	static bool Parse(const FString& S, EStreetLipKind& Out);
	static bool Parse(const FString& S, EStreetBarrierType& Out);
	static bool Parse(const FString& S, EStreetEmbankmentSide& Out);
	static bool Parse(const FString& S, EStreetEmbankmentKind& Out);
	static bool Parse(const FString& S, EStreetSide& Out);
	static bool Parse(const FString& S, EStreetSegmentSide& Out);
	static bool Parse(const FString& S, EStreetSideOrBoth& Out);
	static bool Parse(const FString& S, EStreetTopProfile& Out);
	static bool Parse(const FString& S, EStreetFoliageMode& Out);
	static bool Parse(const FString& S, EStreetSleeperMode& Out);
	static bool Parse(const FString& S, EStreetSourceLayer& Out);
	static bool Parse(const FString& S, EStreetOverlayKind& Out);
	static bool Parse(const FString& S, EStreetContinuation& Out);
	static bool Parse(const FString& S, EStreetSplineEnd& Out);
	static bool Parse(const FString& S, EStreetJunctionKind& Out);
	static bool Parse(const FString& S, EStreetProfileKind& Out);

	/** The normative material set (SCHEMA.md 7); names outside it are "unhinted" (warning). */
	static const TArray<FName>& MaterialNames();
	static const TCHAR* FrameConst() { return TEXT("local-metres, X east, Y north, Z up"); }
};
