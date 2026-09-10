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
#include "StreetJunctionBuild.h"
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

	/**
	 * World-space UE bounds of the last build, SERIALISED, and what GetStreamingBounds returns.
	 *
	 * World Partition places a spatially-loaded actor in a grid cell from AActor::GetStreamingBounds, which is
	 * "a valid origin and an EMPTY EXTENT if this actor doesn't have primitive components" (Actor.h:2538-2546).
	 * Our meshes are deliberately not serialised (PreSave stashes and empties them, DESIGN.md 10), so on load the
	 * DynamicMesh components have no geometry and every street whose only geometry is a mesh - i.e. every ROAD -
	 * got a degenerate box at the actor transform, which is the identity, which is UE (0, 0, 0). Measured
	 * 2026-09-09 on a level holding all 15,422 streets: a 1,400 m box loaded at Cliftonville streamed in 124
	 * actors - 113 barriers, 10 rail, the authored test stretch from 5.8 km away - and NOT ONE ROAD, because the
	 * barriers and rail have instanced-mesh components whose instance transforms ARE serialised and therefore
	 * have real bounds. The whole isle looked right only when the whole isle was streamed.
	 */
	UPROPERTY() FBox StreamingBoundsUE = FBox(ForceInit);

	/**
	 * The junction trim of THIS spline, {t_start, t_end} in metres (SCHEMA.md 4.18).
	 *
	 * Serialised, because it is the whole reason a kerb stops at a junction, and a rebuild after streaming has no
	 * document to re-solve it from. An arm that is loaded with none of its junction's other actors resident is still
	 * trimmed exactly as it was at import.
	 */
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") FVector2D JunctionTrimM = FVector2D::ZeroVector;

	/**
	 * The junctions this actor OWNS - the ones whose patch goes into its own road buffer and whose kerb corners go
	 * into its own left edge buffer (build.build_all). Empty on all but 1,642 of the isle's 15,422 actors.
	 *
	 * Each record carries the solved arms AND the definitions of the arm splines this actor does not own, so the
	 * junction is drawn in full from this actor alone. See the block comment in StreetJunctions.h for why the arms
	 * cannot be re-solved here and why the owner does not go looking for its neighbours' actors.
	 */
	UPROPERTY() TArray<FStreetOwnedJunction> OwnedJunctions;

	/** What the last rebuild's junction merge produced (0 everywhere when this actor owns none). */
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") FStreetActorJunctionStats JunctionStats;

	/** Create the components the profile_ids ask for, store the definition, densify the overlay. Does not build. */
	void ApplyDefinition(const FStreetSplineDef& Def, const FStreetSiteProfiles& Profiles, const FVector2D& OriginEN);

	/**
	 * The importer's one call: hand this actor its trim and the junctions it owns, and make the two components the
	 * merge writes into exist.
	 *
	 * The renderers are created HERE and not during the rebuild because an owner may own a junction whose corners
	 * need a left kerb it has none of itself, and a component created inside PostRegisterAllComponents on a streamed
	 * load would not be part of the saved actor. Call before RebuildAllChecked.
	 */
	void SetJunctionData(const FVector2D& Trim, TArray<FStreetOwnedJunction>&& Owned);

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

	/** Junctions skipped by the last rebuild, with the reason - a junction is never half-drawn silently. */
	const TArray<FString>& JunctionSkips() const { return LastJunctionSkips; }

	bool ToJson(TSharedRef<FJsonObject> Out) const;
	bool FromJson(const TSharedRef<FJsonObject>& In, FText* Err);

	virtual void PostSaveRoot(FObjectPostSaveRootContext ObjectSaveContext) override;
	virtual void PostRegisterAllComponents() override;
#if WITH_EDITOR
	virtual void GetStreamingBounds(FBox& OutRuntimeBounds, FBox& OutEditorBounds) const override;
#endif

	/** Recompute StreamingBoundsUE from the components that exist right now; returns false if there is nothing to measure. */
	bool UpdateStreamingBounds();

private:
	UStreetRendererBase* MakeRenderer(UClass* Class, FName Name);
	void RebuildInstanceMeshComponents();

	bool bPendingRebuild = false;
	bool bRebuilding = false;
	TArray<FString> LastJunctionSkips;
};
