// StreetProfiles - RoadProfile / EdgeProfile / HedgeProfile data (SCHEMA.md 4.4-4.12), the DataAsset wrappers
// (UE_PLAN.md 2.5.2) and the site document (FStreetSiteDoc = a whole Streetscape JSON file, SCHEMA.md 4.1).
//
// Assets are created by UStreetscapeEditorLibrary::ImportProfiles from the 20 library files ({kind, id, profile});
// the loader prefers a document's inline profiles and falls back to the site actor's assets by id only when a
// document lacks one. ToJson/FromJson go through FStreetscapeJson (the one strict reader/writer).

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "StreetTypes.h"
#include "StreetProfiles.generated.h"

class FJsonObject;

USTRUCT(BlueprintType)
struct STREETSCAPE_API FRoadProfileData : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetRoadKind Kind = EStreetRoadKind::Road;
	/**
	 * BRIEF 1.1 names "lane count, per-lane widths" among Renderer A's profile fields, and they are carried,
	 * schema-validated and exposed here - but NO geometry code on either side reads them. The ribbon is built
	 * from WidthM alone and every marking anchor is centre / edge_left / edge_right, never lane-relative
	 * (SCHEMA.md $defs/Marking). They are informational metadata for downstream traffic use, and the only
	 * consumer today is io_json.py's warning when sum(lane_widths_m) > width_m. The natural way to make them
	 * load-bearing is a `lane` marking anchor measured from a lane boundary; until that exists, treat a change
	 * to these fields as changing nothing about the mesh.
	 */
	UPROPERTY() TOptional<int32> Lanes;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasLaneWidthsM = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<double> LaneWidthsM;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double WidthM = 6.0;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName SurfaceMaterial = TEXT("tarmac");
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetCamber Camber;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double OverlapM = 0.04;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double SkirtDropM = 0.02;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double LateralStationSpacingM = 1.0;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetMarking> Markings;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasRail = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetRailSpec Rail;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bHasSamplingDefaults = false;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetSampling SamplingDefaults;
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FEdgeProfileData : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") double KerbWidthM = 0.125;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double KerbHeightM = 0.125;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetLip Lip;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double PavementWidthM = 1.8;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double PavementCrossfallPct = 2.5;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double PavementMaxCrossfallPct = 8.0;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double TuckDepthM = 0.03;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double TuckInM = 0.02;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double SkirtM = 0.30;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetEdgeMaterials Materials;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetSplitMaterial SplitMaterial;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetDropKerb> DropKerbs;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetBarrier> Barriers;       // BarrierSegment rows (S0M set)
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetEmbankment> Embankments; // Embankment rows (S0M set)
};

USTRUCT(BlueprintType)
struct STREETSCAPE_API FHedgeProfileData : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") double WidthM = 0.8;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double HeightM = 1.5;
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetTopProfile TopProfile = EStreetTopProfile::Flat;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double CornerRadiusM = 0.15;
	UPROPERTY(EditAnywhere, Category = "Streetscape") int32 CornerPoints = 4;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double NoiseAmplitudeM = 0.06;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double NoiseScaleM = 0.6;
	UPROPERTY(EditAnywhere, Category = "Streetscape") int32 NoiseSeed = 1;
	UPROPERTY(EditAnywhere, Category = "Streetscape") double BaseSinkM = 0.10;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName Material = TEXT("privet_leaf");
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetFoliage Foliage;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetHedgeSegment> Segments;
};

/** profiles: {road: {}, edge: {}, hedge: {}} of a document (or a site actor's library). Key order preserved. */
USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetSiteProfiles : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") TMap<FString, FRoadProfileData> Road;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TMap<FString, FEdgeProfileData> Edge;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TMap<FString, FHedgeProfileData> Hedge;
};

/** A whole Streetscape document (SCHEMA.md 4.1). */
USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetSiteDoc : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString SchemaVersion = TEXT("1.0.0");
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString Site;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString Crs = TEXT("EPSG:27700");
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetOrigin Origin;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString VerticalDatum = TEXT("ODN");
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString Frame = TEXT("local-metres, X east, Y north, Z up");
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString Generator;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TMap<FString, FStreetMaterialHint> Materials;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetSiteProfiles Profiles;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetSplineDef> Splines;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetJunction> Junctions;

	const FStreetSplineDef* FindSpline(const FString& Id) const;
};

/** A schema/profiles/<id>.json file: {kind, id, profile}. */
USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetProfileFile : public FStreetJsonBase
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetProfileKind Kind = EStreetProfileKind::Road;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString Id;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FRoadProfileData Road;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FEdgeProfileData Edge;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FHedgeProfileData Hedge;
};

UCLASS(Abstract, BlueprintType)
class STREETSCAPE_API UStreetProfileBase : public UDataAsset   // ENG/Classes/Engine/DataAsset.h:17
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, Category = "Streetscape") FName ProfileId;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString Notes;

	virtual EStreetProfileKind GetProfileKind() const PURE_VIRTUAL(UStreetProfileBase::GetProfileKind, return EStreetProfileKind::Road;);
	virtual bool ToJson(TSharedRef<FJsonObject> Out) const PURE_VIRTUAL(UStreetProfileBase::ToJson, return false;);
	virtual bool FromJson(const TSharedRef<FJsonObject>& In, FText* Err) PURE_VIRTUAL(UStreetProfileBase::FromJson, return false;);

	/** The profile as canonical JSON text (schema key order, shortest doubles) - what the editor shows and exports. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	FString ToJsonString() const;
	/** Parse a profile object (the 'profile' value of a library file). Returns the problems (empty = ok). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	TArray<FString> FromJsonString(const FString& Json);
};

UCLASS(BlueprintType)
class STREETSCAPE_API URoadProfile : public UStreetProfileBase
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, Category = "Streetscape", meta = (ShowOnlyInnerProperties)) FRoadProfileData Data;
	virtual EStreetProfileKind GetProfileKind() const override { return EStreetProfileKind::Road; }
	virtual bool ToJson(TSharedRef<FJsonObject> Out) const override;
	virtual bool FromJson(const TSharedRef<FJsonObject>& In, FText* Err) override;
};

UCLASS(BlueprintType)
class STREETSCAPE_API UEdgeProfile : public UStreetProfileBase
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, Category = "Streetscape", meta = (ShowOnlyInnerProperties)) FEdgeProfileData Data;
	virtual EStreetProfileKind GetProfileKind() const override { return EStreetProfileKind::Edge; }
	virtual bool ToJson(TSharedRef<FJsonObject> Out) const override;
	virtual bool FromJson(const TSharedRef<FJsonObject>& In, FText* Err) override;
};

UCLASS(BlueprintType)
class STREETSCAPE_API UHedgeProfile : public UStreetProfileBase
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, Category = "Streetscape", meta = (ShowOnlyInnerProperties)) FHedgeProfileData Data;
	virtual EStreetProfileKind GetProfileKind() const override { return EStreetProfileKind::Hedge; }
	virtual bool ToJson(TSharedRef<FJsonObject> Out) const override;
	virtual bool FromJson(const TSharedRef<FJsonObject>& In, FText* Err) override;
};
