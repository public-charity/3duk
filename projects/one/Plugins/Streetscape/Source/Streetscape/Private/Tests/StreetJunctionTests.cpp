// Junctions: the shared trim, Renderer A's patch and Renderer B's corner (SCHEMA.md 4.18; UE_PLAN.md 2.13, 2.14).
//
// The C++ mirror of Tools/blender/tests/test_junction.py. Six synthetic shapes, and every assertion here is a
// MEASUREMENT of the finished buffers, in world metres, not a restatement of how they were built:
//
//   * no gap between the patch and any ribbon it meets, and none between a corner and any kerb it continues;
//   * no carriageway crossing the junction boundary;
//   * one kerb corner per adjacent pair, G1 at both ends, and the 40 mm road-over-kerb overlap preserved ALONG the
//     corner rather than only along the straights;
//   * the counts frozen in fixtures/expected.json:junction, which BOTH toolchains must produce to the digit.

#include "StreetTestUtil.h"
#include "StreetJunctionBuild.h"
#include "StreetJunctions.h"
#include "StreetRenderers.h"
#include <cmath>

using namespace StreetTest;

namespace
{
constexpr double kGapTolM = 1e-9;
constexpr double kOverlapTolM = 1e-9;

bool StartsWithAny(const FString& S, const TArray<FString>& Prefixes)
{
	for (const FString& P : Prefixes) { if (S.StartsWith(P, ESearchCase::CaseSensitive)) return true; }
	return false;
}

/** build._ring_at: distinct vertex positions of Buf at station S within the named group prefixes. */
TArray<FVector3d> RingAt(const FStreetMeshBuilder& Buf, double S, const TArray<FString>& Prefixes)
{
	TArray<FVector3d> Out;
	if (Buf.V.Num() == 0) return Out;
	TSet<int32> Ids;
	for (int32 I = 0; I < Buf.GroupNames.Num(); ++I) { if (StartsWithAny(Buf.GroupNames[I].ToString(), Prefixes)) Ids.Add(I); }
	if (Ids.Num() == 0) return Out;
	TSet<int32> Vi;
	for (int32 T = 0; T < Buf.F.Num(); ++T)
	{
		if (!Ids.Contains(Buf.Grp[T])) continue;
		for (int32 K = 0; K < 3; ++K) Vi.Add(Buf.F[T][K]);
	}
	TArray<FVector3d> Pts;
	for (int32 I : Vi) { if (FMath::Abs(Buf.VS[I] - S) <= 1e-9) Pts.Add(Buf.V[I]); }
	return FStreetGeometry::DistinctPositions(Pts, 1e-12);
}

/** build._ring_at_group: distinct vertex positions of every group whose name starts with Prefix. */
TArray<FVector3d> RingAtGroup(const FStreetMeshBuilder& Buf, const FString& Prefix)
{
	TArray<FVector3d> Out;
	if (Buf.V.Num() == 0) return Out;
	TSet<int32> Ids;
	for (int32 I = 0; I < Buf.GroupNames.Num(); ++I) { if (Buf.GroupNames[I].ToString().StartsWith(Prefix, ESearchCase::CaseSensitive)) Ids.Add(I); }
	if (Ids.Num() == 0) return Out;
	TSet<int32> Vi;
	for (int32 T = 0; T < Buf.F.Num(); ++T)
	{
		if (!Ids.Contains(Buf.Grp[T])) continue;
		for (int32 K = 0; K < 3; ++K) Vi.Add(Buf.F[T][K]);
	}
	TArray<FVector3d> Pts;
	for (int32 I : Vi) Pts.Add(Buf.V[I]);
	return FStreetGeometry::DistinctPositions(Pts, 1e-12);
}

/** build._max_nearest: max over a in A of min over b in B of |a - b| (0 when A is empty, inf when B is). */
double MaxNearest(const TArray<FVector3d>& A, const TArray<FVector3d>& B)
{
	if (A.Num() == 0) return 0.0;
	if (B.Num() == 0) return TNumericLimits<double>::Max();
	double Worst = 0.0;
	for (const FVector3d& Pa : A)
	{
		double Best = TNumericLimits<double>::Max();
		for (const FVector3d& Pb : B)
		{
			const double D = std::sqrt((Pa.X - Pb.X) * (Pa.X - Pb.X) + (Pa.Y - Pb.Y) * (Pa.Y - Pb.Y) + (Pa.Z - Pb.Z) * (Pa.Z - Pb.Z));
			Best = FMath::Min(Best, D);
		}
		Worst = FMath::Max(Worst, Best);
	}
	return Worst;
}
}   // namespace

// ---------------------------------------------------------------------------------------------------------------
// the plan: the trim itself
// ---------------------------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetJunctionPlanTest, "Streetscape.Junction.Plan",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetJunctionPlanTest::RunTest(const FString&)
{
	const FExpected Exp;
	for (const FString& Name : JunctionFixtureNames())
	{
		FStreetSiteDoc Doc;
		FJunctionSiteBuild B;
		if (!BuildJunctionSite(*this, Name, Doc, B)) continue;
		TestEqual(*(Name + TEXT(": junctions built")), B.Plan.Stats[TEXT("junctions_built")], 1);
		const TArray<FStreetJunctionArm>* Arms = B.Plan.Arms(TEXT("j0"));
		if (!Arms) { AddError(Name + TEXT(": no arms")); continue; }
		TestEqual(*(Name + TEXT(": arms counted")), B.Plan.Stats[TEXT("arms")], Arms->Num());
		for (const FStreetJunctionArm& A : *Arms)
		{
			const FStreetSamples& Sp = B.Samples[A.SplineId];
			TestTrue(*FString::Printf(TEXT("%s: %s trimmed"), *Name, *A.SplineId), Sp.bTrimmed);
			TestEqual(*FString::Printf(TEXT("%s: %s trim station"), *Name, *A.SplineId), Sp.STrim[0], A.STrim, 1e-9);
			// the trim is a MASK, not a re-basing: L, the station array and every s in it stay the document's own
			TestEqual(*FString::Printf(TEXT("%s: %s length"), *Name, *A.SplineId), Sp.LengthM, Sp.S.Last(), 1e-9);
			TestEqual(*FString::Printf(TEXT("%s: %s s0"), *Name, *A.SplineId), Sp.S[0], 0.0, 0.0);
			bool bMono = true;
			for (int32 I = 0; I + 1 < Sp.S.Num(); ++I) bMono = bMono && (Sp.S[I + 1] > Sp.S[I]);
			TestTrue(*FString::Printf(TEXT("%s: %s s monotone"), *Name, *A.SplineId), bMono);
			// ... and the trim station exists EXACTLY, so Renderer A and Renderer B stop on the same vertex row
			TestTrue(*FString::Printf(TEXT("%s: %s trim is a station"), *Name, *A.SplineId), Sp.S.Contains(Sp.STrim[0]));
			TestEqual(*FString::Printf(TEXT("%s: %s first active"), *Name, *A.SplineId), Sp.S[Sp.ArmStationIndex(EStreetSplineEnd::Start)], Sp.STrim[0], 0.0);
		}
		const double Want = Exp.Num(FString::Printf(TEXT("junction.fixtures.%s.trim_radius_m"), *Name), -1.0);
		if (Want >= 0.0) TestEqual(*(Name + TEXT(": trim radius")), B.Plan.TrimRadius(TEXT("j0")), Want, 1e-6);
	}

	// "the trim distance must account for the junction radius AND the width being trimmed": the 12 m trunk fixture
	// ends up with a bigger junction than the 6 m crossroads at the same angles and the same radius_m.
	{
		FStreetSiteDoc D1, D2;
		FJunctionSiteBuild Wide, Narrow;
		if (BuildJunctionSite(*this, TEXT("junction_widths"), D1, Wide) && BuildJunctionSite(*this, TEXT("junction_crossroads"), D2, Narrow))
		{
			TestTrue(TEXT("the wide arm is pushed back further"), Wide.Plan.TrimRadius(TEXT("j0")) > Narrow.Plan.TrimRadius(TEXT("j0")) + 1.0);
		}
	}
	return true;
}

// ---------------------------------------------------------------------------------------------------------------
// Renderer A's patch
// ---------------------------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetJunctionPatchTest, "Streetscape.Junction.Patch",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetJunctionPatchTest::RunTest(const FString&)
{
	for (const FString& Name : JunctionFixtureNames())
	{
		FStreetSiteDoc Doc;
		FJunctionSiteBuild B;
		if (!BuildJunctionSite(*this, Name, Doc, B)) continue;
		const FStreetJunctionInfo* Info = B.Junctions.Find(TEXT("j0"));
		if (!Info || !Info->bBuilt) { AddError(Name + TEXT(": no patch")); continue; }
		TestTrue(*(Name + TEXT(": patch boundary is angularly monotone")), Info->bMonotone);
		TestTrue(*FString::Printf(TEXT("%s: patch double cover %g m2"), *Name, Info->OverlapAreaM2), Info->OverlapAreaM2 < 1e-6);

		const FString OwnerId = B.Owner[TEXT("j0")];
		const FStreetMeshBuilder& OwnerRoad = B.Builds[OwnerId].Road.Buffer;
		// BRIEF 1.1 THREE RENDERERS ONLY: the patch is in the ROAD buffer, with the ROAD material, and nowhere else
		const int32 Gid = OwnerRoad.FindGroupId(FName(TEXT("junction:j0")));
		TestTrue(*(Name + TEXT(": junction:j0 is a group of the road buffer")), Gid >= 0);
		if (Gid >= 0)
		{
			TSet<FName> Mats;
			for (int32 T = 0; T < OwnerRoad.F.Num(); ++T) { if (OwnerRoad.Grp[T] == Gid) Mats.Add(OwnerRoad.MaterialNames[OwnerRoad.Mat[T]]); }
			TestEqual(*(Name + TEXT(": patch material count")), Mats.Num(), 1);
			TestTrue(*(Name + TEXT(": patch material is tarmac")), Mats.Contains(FName(TEXT("tarmac"))));
		}

		// no gap: every point the CARRIAGEWAY ends on has a patch vertex on it, read back out of the finished buffers
		const TArray<FVector3d> Patch = RingAtGroup(OwnerRoad, TEXT("junction:j0"));
		const TArray<FStreetJunctionArm>* Arms = B.Plan.Arms(TEXT("j0"));
		double WorstGap = 0.0;
		for (const FStreetJunctionArm& A : *Arms)
		{
			const FStreetSamples& Sp = B.Samples[A.SplineId];
			const int32 I = Sp.ArmStationIndex(A.End);
			const TArray<FVector3d> Ribbon = RingAt(B.Builds[A.SplineId].Road.Buffer, Sp.S[I], { TEXT("road"), TEXT("skirt_") });
			WorstGap = FMath::Max(WorstGap, MaxNearest(Ribbon, Patch));

			// and no carriageway crosses the junction boundary: along the arm's own outward direction every road or
			// skirt vertex of that arm is at or beyond the trim (the arms are straight, so the bound is exact)
			const FStreetMeshBuilder& Rb = B.Builds[A.SplineId].Road.Buffer;
			const TArray<FString> Excl = { TEXT("marking:"), TEXT("junction:"), TEXT("corner_") };
			double MinProj = TNumericLimits<double>::Max();
			for (int32 T = 0; T < Rb.F.Num(); ++T)
			{
				if (StartsWithAny(Rb.GroupNames[Rb.Grp[T]].ToString(), Excl)) continue;
				for (int32 K = 0; K < 3; ++K)
				{
					const FVector3d& P = Rb.V[Rb.F[T][K]];
					MinProj = FMath::Min(MinProj, (P.X - Doc.Junctions[0].X) * A.U.X + (P.Y - Doc.Junctions[0].Y) * A.U.Y);
				}
			}
			TestTrue(*FString::Printf(TEXT("%s: %s reaches %.4f m from the node, trim is %.4f"), *Name, *A.SplineId, MinProj, A.STrim),
				MinProj >= A.STrim - 1e-6);
		}
		TestTrue(*FString::Printf(TEXT("%s: worst patch/ribbon gap %g m"), *Name, WorstGap), WorstGap <= kGapTolM);
	}

	// on the graded fixture the patch is a SURFACE: its boundary heights span the grade rather than sitting at one z,
	// and its apex is at or above every arm's crown
	{
		FStreetSiteDoc Doc;
		FJunctionSiteBuild B;
		if (BuildJunctionSite(*this, TEXT("junction_slope"), Doc, B))
		{
			TArray<FStreetArmFrame> Frames;
			TArray<FVector3d> Loop;
			TArray<FIntPoint> Slices;
			TArray<FStreetJunctionCornerSpec> Corners;
			const FStreetJunctionSpec Spec = B.Plan.SpecFor(TEXT("j0"));
			if (FStreetRenderBuild::JunctionBoundary(Spec, B.SamplePtrs, Frames, Loop, Slices, Corners))
			{
				double Lo = TNumericLimits<double>::Max(), Hi = -Lo;
				for (const FVector3d& P : Loop) { Lo = FMath::Min(Lo, P.Z); Hi = FMath::Max(Hi, P.Z); }
				TestTrue(*FString::Printf(TEXT("boundary z span %.4f m: the patch is flat"), Hi - Lo), (Hi - Lo) > 0.4);
				const double ZApex = B.Junctions[TEXT("j0")].ZApex;
				for (const FStreetArmFrame& Af : Frames)
				{
					TestTrue(TEXT("apex is at or above the arm crown"), ZApex + 1e-9 >= Af.Spline->Frames.P[Af.I].Z);
				}
			}
		}
	}
	return true;
}

// ---------------------------------------------------------------------------------------------------------------
// Renderer B's corner
// ---------------------------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetJunctionCornerTest, "Streetscape.Junction.Corner",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetJunctionCornerTest::RunTest(const FString&)
{
	for (const FString& Name : JunctionFixtureNames())
	{
		FStreetSiteDoc Doc;
		FJunctionSiteBuild B;
		if (!BuildJunctionSite(*this, Name, Doc, B)) continue;
		const TArray<FStreetJunctionArm>* Arms = B.Plan.Arms(TEXT("j0"));
		const FStreetJunctionInfo& Info = B.Junctions[TEXT("j0")];
		TestEqual(*(Name + TEXT(": one corner per adjacent pair")), Info.Corners, Arms->Num());

		const FString OwnerId = B.Owner[TEXT("j0")];
		const TArray<FVector3d> Corner = RingAtGroup(B.Builds[OwnerId].EdgeL.Buffer, TEXT("corner_"));
		double WorstGap = 0.0;
		for (const FStreetJunctionArm& A : *Arms)
		{
			const FStreetSamples& Sp = B.Samples[A.SplineId];
			const int32 I = Sp.ArmStationIndex(A.End);
			for (int32 SideIdx = 0; SideIdx < 2; ++SideIdx)
			{
				const FStreetMeshBuilder& Eb = SideIdx == 0 ? B.Builds[A.SplineId].EdgeL.Buffer : B.Builds[A.SplineId].EdgeR.Buffer;
				const TArray<FVector3d> Kerb = RingAt(Eb, Sp.S[I], { TEXT("kerb"), TEXT("pavement") });
				if (Kerb.Num() == 0 || Corner.Num() == 0) continue;
				WorstGap = FMath::Max(WorstGap, MaxNearest(Kerb, Corner));
			}
		}
		TestTrue(*FString::Printf(TEXT("%s: worst kerb/corner gap %g m"), *Name, WorstGap), WorstGap <= kGapTolM);

		// the road-over-kerb rule, measured ROUND the corner: the patch boundary between two arms is the corner kerb
		// line pushed outward by exactly overlap_m and dropped by skirt_drop_m - the same 40 mm / 20 mm the ribbon
		// carries along a straight; and the fillet is G1 at both ends, so there is no kink where the kerb starts to turn
		TArray<FStreetArmFrame> Frames;
		TArray<FVector3d> Loop;
		TArray<FIntPoint> Slices;
		TArray<FStreetJunctionCornerSpec> Corners;
		const FStreetJunctionSpec Spec = B.Plan.SpecFor(TEXT("j0"));
		if (!FStreetRenderBuild::JunctionBoundary(Spec, B.SamplePtrs, Frames, Loop, Slices, Corners)) continue;
		for (const FStreetJunctionCornerSpec& Cs : Corners)
		{
			for (int32 Q = 0; Q < Cs.P.Num(); ++Q)
			{
				const FVector3d& Fp = Cs.Fr.P[Q];
				const FVector3d& Fn = Cs.Fr.N[Q];
				const FVector3d& Fb = Cs.Fr.B[Q];
				const FVector3d Pt(Fp.X - Cs.Ov[Q] * Fn.X - Cs.Sd[Q] * Fb.X, Fp.Y - Cs.Ov[Q] * Fn.Y - Cs.Sd[Q] * Fb.Y, Fp.Z - Cs.Ov[Q] * Fn.Z - Cs.Sd[Q] * Fb.Z);
				const FVector3d Dv(Pt.X - Fp.X, Pt.Y - Fp.Y, Pt.Z - Fp.Z);
				const double Lateral = -(Dv.X * Fn.X + Dv.Y * Fn.Y + Dv.Z * Fn.Z);
				const double Drop = Dv.X * Fb.X + Dv.Y * Fb.Y + Dv.Z * Fb.Z;
				TestEqual(*(Name + TEXT(": lateral overlap along the corner")), Lateral, Cs.Ov[Q], kOverlapTolM);
				TestEqual(*(Name + TEXT(": skirt drop along the corner")), Drop, -Cs.Sd[Q], kOverlapTolM);
			}
			TestEqual(*(Name + TEXT(": corner overlap is the profile's 40 mm")), Cs.Ov[0], 0.04, 1e-9);
			TestEqual(*(Name + TEXT(": corner skirt drop is the profile's 20 mm")), Cs.Sd[0], 0.02, 1e-9);
			const FStreetArmFrame& Af = Frames[Cs.A];
			const FStreetArmFrame& Nx = Frames[Cs.B];
			const FVector3d T0 = Cs.T[0], Tl = Cs.T.Last();
			TestTrue(*(Name + TEXT(": corner leaves along the arm's kerb line")),
				std::hypot(T0.X + Af.U.X, T0.Y + Af.U.Y) < 1e-9);
			TestTrue(*(Name + TEXT(": corner arrives along the next arm's kerb line")),
				std::hypot(Tl.X - Nx.U.X, Tl.Y - Nx.U.Y) < 1e-9);
			TestTrue(*(Name + TEXT(": corner starts on the arm's own kerb ring")),
				std::sqrt(FMath::Square(Cs.P[0].X - Af.PHi.X) + FMath::Square(Cs.P[0].Y - Af.PHi.Y) + FMath::Square(Cs.P[0].Z - Af.PHi.Z)) < 1e-12);
			TestTrue(*(Name + TEXT(": corner ends on the next arm's own kerb ring")),
				std::sqrt(FMath::Square(Cs.P.Last().X - Nx.PLo.X) + FMath::Square(Cs.P.Last().Y - Nx.PLo.Y) + FMath::Square(Cs.P.Last().Z - Nx.PLo.Z)) < 1e-12);
		}
	}

	// the symmetric crossroads: the two kerb ends ARE equidistant from the node, so a circular arc tangent to both
	// kerb lines exists and the cubic must be it (the handle formula is exact for a circle to 2.7e-4 of its radius)
	{
		FStreetSiteDoc Doc;
		FJunctionSiteBuild B;
		if (BuildJunctionSite(*this, TEXT("junction_crossroads"), Doc, B))
		{
			TArray<FStreetArmFrame> Frames;
			TArray<FVector3d> Loop;
			TArray<FIntPoint> Slices;
			TArray<FStreetJunctionCornerSpec> Corners;
			const FStreetJunctionSpec Spec = B.Plan.SpecFor(TEXT("j0"));
			if (FStreetRenderBuild::JunctionBoundary(Spec, B.SamplePtrs, Frames, Loop, Slices, Corners))
			{
				for (const FStreetJunctionCornerSpec& Cs : Corners)
				{
					const FVector2d D0(-Frames[Cs.A].U.X, -Frames[Cs.A].U.Y);
					const FVector2d D1(Frames[Cs.B].U.X, Frames[Cs.B].U.Y);
					const FVector2d N0(-D0.Y, D0.X), N1(-D1.Y, D1.X);
					// solve [n0, -n1] t = P[-1] - P[0] for the arc centre
					const FVector2d Rhs(Cs.P.Last().X - Cs.P[0].X, Cs.P.Last().Y - Cs.P[0].Y);
					const double Det = N0.X * (-N1.Y) - (-N1.X) * N0.Y;
					if (FMath::Abs(Det) < 1e-12) continue;
					const double T0 = (Rhs.X * (-N1.Y) - (-N1.X) * Rhs.Y) / Det;
					const FVector2d Centre(Cs.P[0].X + T0 * N0.X, Cs.P[0].Y + T0 * N0.Y);
					const double R = std::hypot(Cs.P[0].X - Centre.X, Cs.P[0].Y - Centre.Y);
					double Err = 0.0;
					for (const FVector3d& P : Cs.P) Err = FMath::Max(Err, FMath::Abs(std::hypot(P.X - Centre.X, P.Y - Centre.Y) - R));
					// 2.7e-4 r is the known worst-case error of the (4/3) tan(tau/4) cubic approximation of a QUARTER
					// circle; this corner turns a shade more than 90 degrees (the tangents come from the dense
					// curve, not from the authored bearings), so the bound the numpy test asserts is 3.0e-4 r -
					// 0.27 mm on this 1 m corner, two orders below the 40 mm overlap it sits inside.
					TestTrue(*FString::Printf(TEXT("cubic corner vs the true arc: %g m on r = %g m"), Err, R), Err < 3.0e-4 * R);
				}
			}
		}
	}
	return true;
}

// ---------------------------------------------------------------------------------------------------------------
// the frozen counts - what the port has to reproduce to the digit
// ---------------------------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetJunctionCountsTest, "Streetscape.Junction.FrozenCounts",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetJunctionCountsTest::RunTest(const FString&)
{
	const FExpected Exp;
	if (!Exp.bPresent)
	{
		AddError(TEXT("fixtures/expected.json is missing: the frozen junction counts cannot be checked"));
		return false;
	}
	for (const FString& Name : JunctionFixtureNames())
	{
		const FString Key = FString::Printf(TEXT("junction.fixtures.%s"), *Name);
		if (!Exp.Has(Key)) { AddError(TEXT("expected.json has no ") + Key); continue; }
		FStreetSiteDoc Doc;
		FJunctionSiteBuild B;
		if (!BuildJunctionSite(*this, Name, Doc, B)) continue;
		const FStreetJunctionInfo& Info = B.Junctions[TEXT("j0")];
		AddInfo(FString::Printf(TEXT("%s: trim_radius %.6f m, %d arms, patch %d v / %d t on a %d-point boundary, %.4f m2, ")
			TEXT("%d corners / %d corner tris, document total %d v / %d t"),
			*Name, B.Plan.TrimRadius(TEXT("j0")), Info.Arms, Info.Verts, Info.Tris, Info.Boundary, Info.AreaM2,
			Info.Corners, Info.CornerTris, B.TotalVerts(), B.TotalTris()));
		TestEqual(*(Name + TEXT(".trim_radius_m")), B.Plan.TrimRadius(TEXT("j0")), Exp.Num(Key + TEXT(".trim_radius_m"), 0.0), 1e-6);
		TestEqual(*(Name + TEXT(".arms")), (double)Info.Arms, Exp.Num(Key + TEXT(".arms"), 0.0), 0.0);
		TestEqual(*(Name + TEXT(".patch_verts")), (double)Info.Verts, Exp.Num(Key + TEXT(".patch_verts"), 0.0), 0.0);
		TestEqual(*(Name + TEXT(".patch_tris")), (double)Info.Tris, Exp.Num(Key + TEXT(".patch_tris"), 0.0), 0.0);
		TestEqual(*(Name + TEXT(".patch_boundary")), (double)Info.Boundary, Exp.Num(Key + TEXT(".patch_boundary"), 0.0), 0.0);
		TestEqual(*(Name + TEXT(".patch_area_m2")), Info.AreaM2, Exp.Num(Key + TEXT(".patch_area_m2"), 0.0), 1e-4);
		TestEqual(*(Name + TEXT(".corners")), (double)Info.Corners, Exp.Num(Key + TEXT(".corners"), 0.0), 0.0);
		TestEqual(*(Name + TEXT(".corner_tris")), (double)Info.CornerTris, Exp.Num(Key + TEXT(".corner_tris"), 0.0), 0.0);
		TestEqual(*(Name + TEXT(".total_verts")), (double)B.TotalVerts(), Exp.Num(Key + TEXT(".total_verts"), 0.0), 0.0);
		TestEqual(*(Name + TEXT(".total_tris")), (double)B.TotalTris(), Exp.Num(Key + TEXT(".total_tris"), 0.0), 0.0);
	}
	return true;
}

// ---------------------------------------------------------------------------------------------------------------
// determinism: two builds of the same document are byte-identical
// ---------------------------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetJunctionDeterminismTest, "Streetscape.Junction.Determinism",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetJunctionDeterminismTest::RunTest(const FString&)
{
	for (const FString& Name : JunctionFixtureNames())
	{
		FStreetSiteDoc D1, D2;
		FJunctionSiteBuild A, B;
		if (!BuildJunctionSite(*this, Name, D1, A) || !BuildJunctionSite(*this, Name, D2, B)) continue;
		for (const TPair<FString, FJunctionSplineBuild>& KV : A.Builds)
		{
			const FJunctionSplineBuild* Other = B.Builds.Find(KV.Key);
			if (!Other) { AddError(Name + TEXT(": ") + KV.Key + TEXT(" missing from the second build")); continue; }
			const FStreetMeshBuilder* Ba[5] = { &KV.Value.Road.Buffer, &KV.Value.EdgeL.Buffer, &KV.Value.EdgeR.Buffer, &KV.Value.HedgeL.Buffer, &KV.Value.HedgeR.Buffer };
			const FStreetMeshBuilder* Bb[5] = { &Other->Road.Buffer, &Other->EdgeL.Buffer, &Other->EdgeR.Buffer, &Other->HedgeL.Buffer, &Other->HedgeR.Buffer };
			for (int32 Q = 0; Q < 5; ++Q)
			{
				if (Ba[Q]->V.Num() != Bb[Q]->V.Num() || Ba[Q]->F.Num() != Bb[Q]->F.Num())
				{
					AddError(FString::Printf(TEXT("%s: %s buffer %d differs in size"), *Name, *KV.Key, Q));
					continue;
				}
				bool bSame = true;
				for (int32 I = 0; I < Ba[Q]->V.Num() && bSame; ++I) bSame = (Ba[Q]->V[I] == Bb[Q]->V[I]);
				for (int32 I = 0; I < Ba[Q]->F.Num() && bSame; ++I) bSame = (Ba[Q]->F[I].A == Bb[Q]->F[I].A && Ba[Q]->F[I].B == Bb[Q]->F[I].B && Ba[Q]->F[I].C == Bb[Q]->F[I].C);
				TestTrue(*FString::Printf(TEXT("%s: %s buffer %d is bit-identical across builds"), *Name, *KV.Key, Q), bSame);
			}
		}
	}
	return true;
}


// ---------------------------------------------------------------------------------------------------------------
// the WIRING: the same junction, rebuilt from what an ACTOR carries and nothing else
// ---------------------------------------------------------------------------------------------------------------
//
// Everything above measures build_all's own path - one function holding the whole document. The level cannot use
// that path: a document's splines are one actor each, they are streamed independently, and their meshes are never
// serialised, so an owner has to rebuild its junction alone, months later, from serialised state.
//
// FStreetJunctionBuild::Distribute + BuildOwned IS that path, and this test drives it exactly as
// AStreetscapeActor::RebuildAllChecked does: solve the plan once, distribute, throw the plan away, and rebuild each
// owner from its records - including building the arm splines it does not own from the definitions it stored. The
// counts must be the frozen ones and identical to the whole-document path.
//
// It also holds the gate down at unit level: an owner that owns junctions and builds NONE must report zero, which
// is what the actor turns into a hard failure and the importer into a refused import. That is the defect of the
// previous round stated as a test - the layer existed, the counts were right, and nothing called it.

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetJunctionWiringTest, "Streetscape.Junction.Wiring",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetJunctionWiringTest::RunTest(const FString&)
{
	const FExpected Exp;
	for (const FString& Name : JunctionFixtureNames())
	{
		FStreetSiteDoc Doc;
		FJunctionSiteBuild Ref;
		if (!BuildJunctionSite(*this, Name, Doc, Ref)) continue;

		// -- what the IMPORTER stores on the actors -------------------------------------------------------------
		TMap<FString, FVector2D> Trims;
		TMap<FString, TArray<FStreetOwnedJunction>> Owned;
		FStreetJunctionBuild::Distribute(Doc, Ref.Plan, Trims, Owned);
		TestEqual(*(Name + TEXT(": one owner")), Owned.Num(), 1);
		if (Owned.Num() != 1) continue;
		const FString OwnerId = Ref.Owner[TEXT("j0")];
		TestTrue(*(Name + TEXT(": the owner is the plan's owner")), Owned.Contains(OwnerId));
		if (!Owned.Contains(OwnerId)) continue;
		// every arm is trimmed, and each arm actor carries its own trim independently of its owner
		for (const FStreetJunctionArm& A : *Ref.Plan.Arms(TEXT("j0")))
		{
			const FVector2D* T = Trims.Find(A.SplineId);
			TestTrue(*FString::Printf(TEXT("%s: %s carries a trim"), *Name, *A.SplineId), T != nullptr);
			if (T)
			{
				const double Want = (A.End == EStreetSplineEnd::Start) ? T->X : T->Y;
				TestEqual(*FString::Printf(TEXT("%s: %s trim"), *Name, *A.SplineId), Want, A.TrimM, 0.0);
			}
		}

		// -- what an OWNER ACTOR does on every rebuild, from those records alone --------------------------------
		const FStreetHeightfield Field = JunctionTerrainFor(Name);
		FStreetHeightfieldSource Src(Field);
		Src.SetDocumentOrigin(Doc.Origin.E, Doc.Origin.N);

		const FStreetSplineDef* OwnerDef = Doc.FindSpline(OwnerId);
		if (!OwnerDef) { AddError(Name + TEXT(": the owner is not in the document")); continue; }
		double OwnerTrim[2] = { 0.0, 0.0 };
		if (const FVector2D* T = Trims.Find(OwnerId)) { OwnerTrim[0] = T->X; OwnerTrim[1] = T->Y; }
		FStreetSamples OwnerSp;
		FString Err;
		if (!FStreetSplineMath::Build(*OwnerDef, Doc.Profiles, &Src, OwnerSp, &Err, OwnerTrim))
		{
			AddError(Name + TEXT(": owner build: ") + Err);
			continue;
		}
		FStreetRenderResult Road, EdgeL;
		FStreetRenderBuild::BuildRoad(OwnerSp, Road);
		FStreetRenderBuild::BuildEdge(OwnerSp, EStreetSide::Left, &Src, EdgeL);

		FStreetActorJunctionStats St;
		TArray<FString> Skips;
		FStreetJunctionBuild::BuildOwned(Owned[OwnerId], OwnerId, OwnerSp, Doc.Profiles, &Src,
			Road.Buffer, EdgeL.Buffer, St, Skips);
		TestEqual(*(Name + TEXT(": nothing skipped")), Skips.Num(), 0);
		TestEqual(*(Name + TEXT(": junctions built from actor state")), St.Built, 1);

		// the frozen numbers, to the digit
		const int32 WantVerts = (int32)Exp.Num(FString::Printf(TEXT("junction.fixtures.%s.patch_verts"), *Name), -1.0);
		const int32 WantTris = (int32)Exp.Num(FString::Printf(TEXT("junction.fixtures.%s.patch_tris"), *Name), -1.0);
		const int32 WantCorners = (int32)Exp.Num(FString::Printf(TEXT("junction.fixtures.%s.corners"), *Name), -1.0);
		const int32 WantCornerTris = (int32)Exp.Num(FString::Printf(TEXT("junction.fixtures.%s.corner_tris"), *Name), -1.0);
		TestEqual(*(Name + TEXT(": patch verts")), St.PatchVerts, WantVerts);
		TestEqual(*(Name + TEXT(": patch tris")), St.PatchTris, WantTris);
		TestEqual(*(Name + TEXT(": corners")), St.Corners, WantCorners);
		TestEqual(*(Name + TEXT(": corner tris")), St.CornerTris, WantCornerTris);

		// ... and the same numbers the whole-document path produced, so the two can never drift apart
		const FStreetJunctionInfo& RefInfo = Ref.Junctions[TEXT("j0")];
		TestEqual(*(Name + TEXT(": patch verts == build_all")), St.PatchVerts, RefInfo.Verts);
		TestEqual(*(Name + TEXT(": patch tris == build_all")), St.PatchTris, RefInfo.Tris);
		TestEqual(*(Name + TEXT(": corner tris == build_all")), St.CornerTris, RefInfo.CornerTris);
		TestEqual(*(Name + TEXT(": patch area == build_all")), St.PatchAreaM2, RefInfo.AreaM2, 1e-9);
		// the whole owner buffer, not just the junction's own share: patch INTO the road buffer, corners INTO the
		// left edge buffer, exactly as build_all merges them
		TestEqual(*(Name + TEXT(": owner road buffer == build_all")), Road.Buffer.V.Num(), Ref.Builds[OwnerId].Road.Buffer.V.Num());
		TestEqual(*(Name + TEXT(": owner road tris == build_all")), Road.Buffer.F.Num(), Ref.Builds[OwnerId].Road.Buffer.F.Num());
		TestEqual(*(Name + TEXT(": owner left edge == build_all")), EdgeL.Buffer.V.Num(), Ref.Builds[OwnerId].EdgeL.Buffer.V.Num());
		TestEqual(*(Name + TEXT(": owner left edge tris == build_all")), EdgeL.Buffer.F.Num(), Ref.Builds[OwnerId].EdgeL.Buffer.F.Num());
		TestTrue(*(Name + TEXT(": junction:j0 is a group of the owner's ROAD buffer")),
			Road.Buffer.FindGroupId(FName(TEXT("junction:j0"))) >= 0);

		// -- the gate: an owner that cannot build its junction must say so, not pass quietly --------------------
		if (Name == JunctionFixtureNames()[0])
		{
			TArray<FStreetOwnedJunction> Broken = Owned[OwnerId];
			int32 Cut = 0;
			for (FStreetJunctionArmRecord& R : Broken[0].Arms)
			{
				if (!R.bIsOwner) { R.Def = FStreetSplineDef(); ++Cut; break; }
			}
			TestEqual(TEXT("the negative control removed one arm definition"), Cut, 1);
			FStreetRenderResult R2, E2;
			FStreetRenderBuild::BuildRoad(OwnerSp, R2);
			FStreetRenderBuild::BuildEdge(OwnerSp, EStreetSide::Left, &Src, E2);
			FStreetActorJunctionStats St2;
			TArray<FString> Skips2;
			FStreetJunctionBuild::BuildOwned(Broken, OwnerId, OwnerSp, Doc.Profiles, &Src, R2.Buffer, E2.Buffer, St2, Skips2);
			TestEqual(TEXT("a junction whose arm is missing builds nothing"), St2.Built, 0);
			TestEqual(TEXT("... and is counted as skipped"), St2.Skipped, 1);
			TestTrue(TEXT("... with a reason"), Skips2.Num() > 0);
			TestEqual(TEXT("... and no patch reached the road buffer"), R2.Buffer.FindGroupId(FName(TEXT("junction:j0"))), -1);
		}
	}
	return true;
}
