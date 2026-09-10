#pragma once

#include "StreetProfiles.h"

// A value snapshot keeps validation independent of actor mutation and World Partition load order.
struct FStreetDocumentActorState
{
	FString Id;
	FVector2D OriginEN;
	FStreetSplineDef Def;
	FStreetSiteProfiles Profiles;
};

namespace StreetDocumentEdit
{
// Source supplies document metadata and ALL junctions, including intentionally unbuilt kinds.
// States must cover its spline IDs exactly once. Only profiles actually referenced by a state are merged.
bool Assemble(const FStreetSiteDoc& Source, const TArray<FStreetDocumentActorState>& States,
	FStreetSiteDoc& Out, FString& Error);
}
