#include "StreetJunctionBuild.h"

#include "StreetSplineMath.h"
#include "StreetTerrainSource.h"
#include "StreetscapeModule.h"

void FStreetJunctionBuild::Distribute(const FStreetSiteDoc& Doc, const FStreetJunctionPlan& Plan,
	TMap<FString, FVector2D>& OutTrim, TMap<FString, TArray<FStreetOwnedJunction>>& OutOwned,
	TMap<FString, TArray<FStreetJunction>>* OutInteriorBends)
{
	OutTrim.Reset(); OutOwned.Reset(); if (OutInteriorBends) OutInteriorBends->Reset();
	if (!Plan.IsValid()) return;
	for (const FStreetSplineDef& Def : Doc.Splines)
	{
		double T[2] = { 0.0, 0.0 };
		Plan.TrimFor(Def.Id, T);
		if (OutInteriorBends) OutInteriorBends->Add(Def.Id,Plan.InteriorBendsFor(Def.Id));
		if (T[0] > 0.0 || T[1] > 0.0) OutTrim.Add(Def.Id, FVector2D(T[0], T[1]));
	}
	// BuiltJunctionIds() is sorted, which is build_all's `for jid in sorted(plan.arms)`
	for (const FString& Jid : Plan.BuiltJunctionIds())
	{
		const FString OwnerId = Plan.Owner(Jid);
		if (OwnerId.IsEmpty()) continue;
		const FStreetJunctionSpec Spec = Plan.SpecFor(Jid);
		FStreetOwnedJunction Rec;
		Rec.Junction = Spec.Junction;
		Rec.TrimRadiusM = Spec.TrimRadiusM;
		bool bOk = true;
		for (const FStreetJunctionArm& A : Spec.Arms)
		{
			FStreetJunctionArmRecord R;
			R.Arm = A;
			double T[2] = { 0.0, 0.0 };
			Plan.TrimFor(A.SplineId, T);
			R.TrimM = FVector2D(T[0], T[1]);
			R.InteriorBends=Plan.InteriorBendsFor(A.SplineId);
			R.bIsOwner = (A.SplineId == OwnerId);
			if (!R.bIsOwner)
			{
				const FStreetSplineDef* D = Doc.FindSpline(A.SplineId);
				// build_all: `if any(a.spline_id not in splines ...): continue` - the whole junction, not one arm
				if (!D) { bOk = false; break; }
				R.Def = *D;
			}
			Rec.Arms.Add(MoveTemp(R));
		}
		if (!bOk) continue;
		OutOwned.FindOrAdd(OwnerId).Add(MoveTemp(Rec));
	}
}

void FStreetJunctionBuild::BuildOwned(const TArray<FStreetOwnedJunction>& Owned, const FString& OwnerId,
	const FStreetSamples& OwnerSamples, const FStreetSiteProfiles& Profiles, const IStreetTerrainSource* Terrain,
	FStreetMeshBuilder& RoadBuf, FStreetMeshBuilder& EdgeLeftBuf,
	FStreetActorJunctionStats& OutStats, TArray<FString>& OutSkipped)
{
	OutStats = FStreetActorJunctionStats();
	if (Owned.Num() == 0) return;
	OutStats.Owned = Owned.Num();

	// -- every arm's samples, built once per distinct spline id -------------------------------------------------
	TArray<TUniquePtr<FStreetSamples>> Storage;
	TMap<FString, const FStreetSamples*> Ptrs;
	Ptrs.Add(OwnerId, &OwnerSamples);
	for (const FStreetOwnedJunction& J : Owned)
	{
		for (const FStreetJunctionArmRecord& R : J.Arms)
		{
			const FString& Sid = R.Arm.SplineId;
			if (R.bIsOwner || Sid == OwnerId || Ptrs.Contains(Sid)) continue;
			if (R.Def.Id.IsEmpty())
			{
				OutSkipped.Add(FString::Printf(TEXT("%s: arm %s carries no definition"), *J.Junction.Id, *Sid));
				continue;
			}
			TUniquePtr<FStreetSamples> S = MakeUnique<FStreetSamples>();
			const double Trim[2] = { R.TrimM.X, R.TrimM.Y };
			FString Err;
			if (!FStreetSplineMath::Build(R.Def, Profiles, Terrain, *S, &Err, Trim, R.InteriorBends))
			{
				OutSkipped.Add(FString::Printf(TEXT("%s: arm %s did not build: %s"), *J.Junction.Id, *Sid, *Err));
				continue;
			}
			Ptrs.Add(Sid, S.Get());
			Storage.Add(MoveTemp(S));
		}
	}

	// -- the merge, in build_all's order: patch -> the owner's ROAD, corners -> the owner's LEFT EDGE ------------
	for (const FStreetOwnedJunction& J : Owned)
	{
		bool bAll = true;
		for (const FStreetJunctionArmRecord& R : J.Arms) { if (!Ptrs.Contains(R.Arm.SplineId)) { bAll = false; break; } }
		if (!bAll)
		{
			++OutStats.Skipped;
			OutSkipped.Add(FString::Printf(TEXT("%s: an arm's samples are missing"), *J.Junction.Id));
			continue;
		}
		const FStreetJunctionSpec Spec = J.ToSpec();
		const FStreetJunctionInfo Info = FStreetRenderBuild::BuildJunctionPatch(Spec, Ptrs, RoadBuf);
		if (!Info.bBuilt)
		{
			++OutStats.Skipped;
			OutSkipped.Add(FString::Printf(TEXT("%s: no patch (%d arm(s))"), *J.Junction.Id, J.Arms.Num()));
			continue;
		}
		const FStreetJunctionInfo Corner = FStreetRenderBuild::BuildJunctionCorners(Spec, Ptrs, EdgeLeftBuf);
		++OutStats.Built;
		if (!Info.bMonotone) ++OutStats.NonMonotone;
		OutStats.PatchVerts += Info.Verts;
		OutStats.PatchTris += Info.Tris;
		OutStats.PatchAreaM2 += Info.AreaM2;
		OutStats.PatchOverlapAreaM2 += Info.OverlapAreaM2;
		OutStats.Corners += Corner.Corners;
		OutStats.CornersSkippedNoKerb += Corner.CornersSkippedNoKerb;
		OutStats.CornersSkippedIncompatible += Corner.CornersSkippedIncompatible;
		OutStats.CornerVerts += Corner.CornerVerts;
		OutStats.CornerTris += Corner.CornerTris;
	}
}
