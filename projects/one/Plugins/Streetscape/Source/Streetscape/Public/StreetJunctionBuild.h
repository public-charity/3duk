// StreetJunctionBuild - the wiring between the solved junction plan and the actors that draw it.
//
// build.build_all does the whole document in one function because it has the whole document: solve the plan, build
// every spline with its trim already known, then merge each junction's patch into its OWNING spline's road buffer and
// its corners into that spline's LEFT edge buffer. Unreal has no such moment. A document's splines become one actor
// each, they are saved separately, World Partition streams them in and out independently, and their meshes are never
// serialised (AStreetscapeActor's class comment) - so every actor rebuilds itself, alone, whenever it is loaded.
//
// This file splits build_all in two along that seam and nowhere else:
//
//   Distribute()  runs ONCE, at import, where the whole FStreetSiteDoc exists. It hands each spline its trim and
//                 hands each OWNER the solved arms of the junctions it owns together with the definitions of the arms
//                 it does not own. Nothing is derived here that the plan did not already decide.
//   BuildOwned()  runs on EVERY rebuild of an owner, from that serialised state alone. It rebuilds the arm splines'
//                 samples itself and calls the same two renderer statics build_all calls, in the same order.
//
// The two halves are separate so that an import and a reload produce the same geometry by construction: the importer
// does not build junctions itself, it only stores what BuildOwned will need, and then rebuilds the actor exactly as a
// load would. Streetscape.Junction.Wiring measures that the counts BuildOwned produces are the frozen fixture counts.

#pragma once

#include "CoreMinimal.h"
#include "StreetJunctions.h"
#include "StreetRenderers.h"

class IStreetTerrainSource;

struct STREETSCAPE_API FStreetJunctionBuild
{
	/**
	 * Split one document's solved plan into the per-actor state the level carries.
	 *
	 * OutTrim holds only the splines that are actually trimmed; OutOwned is keyed by owning spline id, its value in
	 * the order Plan.BuiltJunctionIds() walks (sorted), which is the order build_all merges them in and therefore
	 * the order the owner's buffer receives them.
	 */
	static void Distribute(const FStreetSiteDoc& Doc, const FStreetJunctionPlan& Plan,
		TMap<FString, FVector2D>& OutTrim, TMap<FString, TArray<FStreetOwnedJunction>>& OutOwned,
		TMap<FString, TArray<FStreetJunction>>* OutInteriorBends = nullptr);

	/**
	 * Rebuild every junction an owner owns into its own two buffers - road for the patch, LEFT edge for the corners.
	 *
	 * OwnerSamples must already have been built with the owner's own trim. Every other arm's samples are built HERE,
	 * from the stored definition and the stored trim, with the same profiles and the same terrain source the arm's own
	 * actor uses, so the two agree to the bit whether or not that actor is loaded.
	 *
	 * A junction whose arms cannot all be built is SKIPPED and named in OutSkipped rather than half-drawn.
	 */
	static void BuildOwned(const TArray<FStreetOwnedJunction>& Owned, const FString& OwnerId,
		const FStreetSamples& OwnerSamples, const FStreetSiteProfiles& Profiles, const IStreetTerrainSource* Terrain,
		FStreetMeshBuilder& RoadBuf, FStreetMeshBuilder& EdgeLeftBuf,
		FStreetActorJunctionStats& OutStats, TArray<FString>& OutSkipped);
};
