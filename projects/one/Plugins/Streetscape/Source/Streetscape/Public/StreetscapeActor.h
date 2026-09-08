// AStreetscapeActor - one actor per Streetscape-JSON spline (UE_PLAN.md 2.9; DESIGN.md 10).
//
// The spline component is the root and holds the schema FStreetSplineDef; the renderer components exist only for the
// non-null profile_ids slots. RebuildAll() builds ONE FStreetSamples and hands the same object to every renderer, so
// the road, both edges and both hedges share the station set by construction (DESIGN.md 5 rule 2).
//
// Meshes are never serialised: each renderer's PreSave stashes and empties its UDynamicMesh, and PostSaveRoot here
// puts it back, so a save leaves the road walkable; on load OnRegister finds an empty mesh and rebuilds.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "StreetProfiles.h"
#include "StreetRenderers.h"
#include "StreetTypes.h"
#include "StreetscapeActor.generated.h"

class UStreetSplineComponent;
class UStreetOverlayComponent;
class UInstancedStaticMeshComponent;
class AStreetscapeSiteActor;
class FJsonObject;

UCLASS(BlueprintType)
class STREETSCAPE_API AStreetscapeActor : public AActor
{
	GENERATED_BODY()
public:
	AStreetscapeActor();

	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TObjectPtr<UStreetSplineComponent> Spline;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TObjectPtr<UStreetRoadRenderer> Road;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TObjectPtr<UStreetEdgeRenderer> EdgeLeft;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TObjectPtr<UStreetEdgeRenderer> EdgeRight;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TObjectPtr<UStreetHedgeRenderer> HedgeLeft;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TObjectPtr<UStreetHedgeRenderer> HedgeRight;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TObjectPtr<UStreetOverlayComponent> Overlay;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TArray<TObjectPtr<UInstancedStaticMeshComponent>> InstanceMeshComponents;

	/** = Def.Id, also the actor label. */
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString StreetId;
	/** Survey origin the document was authored in (the site actor must match). */
	UPROPERTY(EditAnywhere, Category = "Streetscape") FVector2D DocOriginEN = FVector2D::ZeroVector;
	/** The document's inline profiles: they win over the site actor's assets (SCHEMA.md 4.1). */
	UPROPERTY() FStreetSiteProfiles DocProfiles;

	/** Create the components the profile_ids ask for, store the definition, densify the overlay. Does not build. */
	void ApplyDefinition(const FStreetSplineDef& Def, const FStreetSiteProfiles& Profiles, const FVector2D& OriginEN);

	/** Timelines -> spline -> every renderer, from ONE FStreetSamples. Returns false with Error on a build failure. */
	UFUNCTION(CallInEditor, BlueprintCallable, Category = "Streetscape") void RebuildAll();
	bool RebuildAllChecked(FString* Error);

	/** Called by a renderer that registered with an empty mesh; the rebuild happens once, after every component is up. */
	void RequestRebuildOnRegister() { bPendingRebuild = true; }

	/** The samples of the last build (null before the first one). */
	const FStreetSamples* GetSamples() const;
	/** Merged profiles: the document's inline ones first, the site actor's assets second. */
	FStreetSiteProfiles ResolveProfiles() const;
	/** Every non-empty buffer of the last build, keyed as in stats.json ("road", "edge_left", ...). */
	TMap<FString, const FStreetMeshBuilder*> Buffers() const;
	/** Instance counts by kind over every renderer. */
	TMap<FName, int32> InstanceCounts() const;
	int32 MarkingStrips() const;

	bool ToJson(TSharedRef<FJsonObject> Out) const;
	bool FromJson(const TSharedRef<FJsonObject>& In, FText* Err);

	virtual void PostSaveRoot(FObjectPostSaveRootContext ObjectSaveContext) override;
	virtual void PostRegisterAllComponents() override;

private:
	UStreetRendererBase* MakeRenderer(UClass* Class, FName Name);
	void RebuildInstanceMeshComponents();

	bool bPendingRebuild = false;
	bool bRebuilding = false;
};
