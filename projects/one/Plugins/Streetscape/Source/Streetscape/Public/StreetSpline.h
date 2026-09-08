// StreetSpline - the spline component of a streetscape actor (UE_PLAN.md 2.5.4).
//
// UStreetSplineComponent wraps USplineComponent ONLY for the editor gizmos: the component's points mirror Def.Points
// in UE centimetres (FStreetscapeJson::ToUE) so they can be dragged, and SyncDefFromComponent() writes them back to
// the JSON frame. All geometry comes from FStreetSplineMath::Build on Def (SCHEMA.md 3), never from the Hermite
// curve of USplineComponent. Build() is cached by a hash of the definition and the terrain description.

#pragma once

#include "CoreMinimal.h"
#include "Components/SplineComponent.h"
#include "StreetTypes.h"
#include "StreetProfiles.h"
#include "StreetSplineMath.h"
#include "StreetSpline.generated.h"

class IStreetTerrainSource;

/** Per-point schema data kept in step with the USplineComponent points (SplineComponent.h:57-72). */
UCLASS()
class STREETSCAPE_API UStreetSplineMetadata : public USplineMetadata
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, Category = "Streetscape") TArray<FStreetPoint> Points;

	virtual void InsertPoint(int32 Index, float t, bool bClosedLoop) override;
	virtual void UpdatePoint(int32 Index, float t, bool bClosedLoop) override;
	virtual void AddPoint(float InputKey) override;
	virtual void RemovePoint(int32 Index) override;
	virtual void DuplicatePoint(int32 Index) override;
	virtual void CopyPoint(const USplineMetadata* FromSplineMetadata, int32 FromIndex, int32 ToIndex) override;
	virtual void Reset(int32 NumPoints) override;
	virtual void Fixup(int32 NumPoints, USplineComponent* SplineComp) override;
};

UCLASS(ClassGroup = Streetscape, meta = (BlueprintSpawnableComponent))
class STREETSCAPE_API UStreetSplineComponent : public USplineComponent
{
	GENERATED_BODY()
public:
	UStreetSplineComponent(const FObjectInitializer& ObjectInitializer);

	UPROPERTY(Instanced, EditAnywhere, Category = "Streetscape") TObjectPtr<UStreetSplineMetadata> Metadata;
	/** The whole schema Spline (points duplicated in Metadata for editing). */
	UPROPERTY(EditAnywhere, Category = "Streetscape") FStreetSplineDef Def;

	virtual USplineMetadata* GetSplinePointsMetadata() override { return Metadata; }
	virtual const USplineMetadata* GetSplinePointsMetadata() const override { return Metadata; }

	/** Build (or reuse the cached) samples: SCHEMA.md 3.1 -> 3.6 with the mandatory stations of the two timelines. */
	const FStreetSamples* Build(const IStreetTerrainSource* Terrain, const FStreetSiteProfiles& Profiles, FString* Error = nullptr, bool bForce = false);
	const FStreetSamples* GetSamples() const { return Samples.Get(); }
	void MarkDirty() { CacheKey.Reset(); }

	UFUNCTION(BlueprintCallable, Category = "Streetscape") int32 NumWaypoints() const { return Def.Points.Num(); }
	/** Waypoint in the JSON frame (z = pin or 0). */
	FVector3d WaypointJson(int32 Index) const;
	/** Replace the waypoints (JSON frame) and mirror them into the USplineComponent (UE cm). */
	void SetWaypointsJson(const TArray<FStreetPoint>& Points);
	/** USplineComponent points (cm) <- Def.Points (m). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape") void SyncComponentFromDef();
	/** Def.Points (m) <- USplineComponent points (cm), keeping width/roll/z/tags by index. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape") void SyncDefFromComponent();

private:
	TUniquePtr<FStreetSamples> Samples;
	FString CacheKey;
};
