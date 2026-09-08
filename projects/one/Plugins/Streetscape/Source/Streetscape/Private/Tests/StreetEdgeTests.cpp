// Streetscape.Edge.* (UE_PLAN.md 2.13; DESIGN.md 4.2) - Renderer B on straight_100 against
// Tools/blender/tests/fixtures/expected.json: the A-B-C-lip-D-S-E-F-G rows, the drop-kerb heights, the flush split
// boundary, and the barrier post rule / railing rails.

#include "StreetRenderTestUtil.h"

using namespace StreetTest;

constexpr EAutomationTestFlags kEdgeFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

namespace
{
/** rows_at of tests/test_edge.py: section (o, h) of one group's vertices at a station, plus their ids. */
void RowsAt(const FStreetMeshBuilder& Buf, const FStreetSamples& Sp, EStreetSide Side, double S, FName Group,
	TArray<double>& OutO, TArray<double>& OutH, TArray<int32>& OutIdx)
{
	const TArray<int32> Vi = Buf.VerticesOfGroups(FString(), &Group);
	int32 I = 0;
	for (int32 K = 0; K < Sp.Num(); ++K) { if (FMath::Abs(Sp.S[K] - S) < FMath::Abs(Sp.S[I] - S)) I = K; }
	const TArray<double> O0 = Sp.EdgeOffset(Side);
	const TArray<double> H0 = Sp.EdgeHeight(Side);
	const double Sigma = (double)StreetSideSigma(Side);
	for (int32 V : Vi)
	{
		if (FMath::Abs(Buf.VS[V] - S) >= 1e-9) continue;
		OutO.Add(Sigma * Buf.VD[V] - O0[I]);
		OutH.Add(Buf.VH[V] - H0[I]);
		OutIdx.Add(V);
	}
}
double MinOf(const TArray<double>& A) { double M = A.Num() ? A[0] : 0; for (double X : A) M = FMath::Min(M, X); return M; }
double MaxOf(const TArray<double>& A) { double M = A.Num() ? A[0] : 0; for (double X : A) M = FMath::Max(M, X); return M; }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetEdgeOverlapTest, "Streetscape.Edge.Overlap", kEdgeFlags)
bool FStreetEdgeOverlapTest::RunTest(const FString& Parameters)
{
	const FExpected X;
	const TSharedPtr<FJsonObject> DocObj = Fixture(*this, TEXT("straight_100"));
	if (!DocObj.IsValid()) return false;
	const FStreetHeightfield Terrain = TerrainFor(TEXT("straight_100"));
	FBuiltStreet B;
	if (!B.Build(*this, DocObj.ToSharedRef(), &Terrain)) return false;

	const double Ov = X.Num(TEXT("straight_100.overlap_m"), 0.04);
	const FName Kerb(TEXT("kerb")), Pav(TEXT("pavement"));
	for (int32 K = 0; K < 2; ++K)
	{
		const EStreetSide Side = K == 0 ? EStreetSide::Left : EStreetSide::Right;
		const FStreetMeshBuilder& E = B.EdgeBuf(Side);
		const FString Label = K == 0 ? TEXT("left") : TEXT("right");
		TArray<double> O, H;
		TArray<int32> Idx;
		RowsAt(E, B.Sp, Side, 20.0, Kerb, O, H, Idx);
		TestEqual(Label + TEXT(": row A o = -0.02"), MinOf(O), X.Num(TEXT("straight_100.kerb.row_A_o"), -0.02), 1e-12);
		TestEqual(Label + TEXT(": row B h = -0.03"), MinOf(H), X.Num(TEXT("straight_100.kerb.row_B_h"), -0.03), 1e-12);
		// D, S and E share one height -> the split boundary is flush by construction
		TArray<double> TopZ;
		int32 NLip = 0;
		for (int32 I = 0; I < H.Num(); ++I)
		{
			if (FMath::Abs(H[I] - 0.125) < 1e-12) TopZ.Add(E.V[Idx[I]].Z);
			if (O[I] > 0 && O[I] < 0.02 && H[I] > 0.105 && H[I] < 0.125)
			{
				++NLip;
				TestEqual(Label + TEXT(": lip point on the r = 0.02 arc"), std::hypot(O[I] - 0.02, H[I] - 0.105), 0.02, 1e-12);
			}
		}
		TestTrue(Label + TEXT(": at least 3 rows at the kerb top"), TopZ.Num() >= 3);
		TestEqual(Label + TEXT(": lip arc points"), NLip, 3);
		TestTrue(Label + TEXT(": kerb top flush (max |dz| < 1e-12)"), (MaxOf(TopZ) - MinOf(TopZ)) < X.Num(TEXT("straight_100.kerb.flush_tol"), 1e-12));

		TArray<double> Op, Hp;
		TArray<int32> Ip;
		RowsAt(E, B.Sp, Side, 20.0, Pav, Op, Hp, Ip);
		TestEqual(Label + TEXT(": pavement back edge at kw + pw"), MaxOf(Op), 0.125 + 1.8, 1e-12);
		TestEqual(Label + TEXT(": pavement back height 0.17"), MaxOf(Hp), X.Num(TEXT("straight_100.drop_kerb.hk_back_nominal"), 0.17), 1e-12);
		TestEqual(Label + TEXT(": pavement skirt -0.30"), MinOf(Hp), -0.30, 1e-12);
		TestEqual(Label + TEXT(" edge validates clean: ") + FString::Join(E.Validate(), TEXT(" | ")), E.Validate().Num(), 0);

		const FStreetSideSpec& Spec = B.Sp.SideSpec[StreetSideIndex(Side)];
		double Td = Spec.TuckDepth.Num() ? Spec.TuckDepth[0] : 0.03;
		for (double V : Spec.TuckDepth) Td = FMath::Min(Td, V);
		const FStreetGeometry::FOverlap M = FStreetGeometry::MeasureLateralOverlap(B.RoadBuf(), E, StreetSideSigma(Side), Td);
		TestEqual(Label + TEXT(": overlap measured at every station"), M.PerStation.Num(), B.Sp.Num());
		TestEqual(Label + TEXT(": overlap min = 0.040"), M.MinM, Ov, 1e-9);
		TestEqual(Label + TEXT(": overlap max = 0.040"), M.MaxM, Ov, 1e-9);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetEdgeDropKerbTest, "Streetscape.Edge.DropKerb", kEdgeFlags)
bool FStreetEdgeDropKerbTest::RunTest(const FString& Parameters)
{
	const FExpected X;
	const TSharedPtr<FJsonObject> DocObj = Fixture(*this, TEXT("straight_100"));
	if (!DocObj.IsValid()) return false;
	const FStreetHeightfield Terrain = TerrainFor(TEXT("straight_100"));
	FBuiltStreet B;
	if (!B.Build(*this, DocObj.ToSharedRef(), &Terrain)) return false;

	const double Tol = X.Num(TEXT("straight_100.drop_kerb.tol"), 1e-6);
	const TArray<double> Q = {
		X.Num(TEXT("straight_100.drop_kerb.flat_centre_s"), 70.915),
		X.Num(TEXT("straight_100.drop_kerb.ramp_mid_down_s"), 69.5425),
		X.Num(TEXT("straight_100.drop_kerb.ramp_mid_up_s"), 72.2875),
		20.0 };
	const FStreetSideSpec Spec = B.Sp.Sides[0].Evaluate(Q);
	TestEqual(TEXT("hk on the flat run = 0.006"), Spec.Hk[0], X.Num(TEXT("straight_100.drop_kerb.hk_flat"), 0.006), Tol);
	TestEqual(TEXT("hk at the down-ramp midpoint = 0.0655"), Spec.Hk[1], X.Num(TEXT("straight_100.drop_kerb.hk_ramp_mid"), 0.0655), Tol);
	TestEqual(TEXT("hk at the up-ramp midpoint = 0.0655"), Spec.Hk[2], X.Num(TEXT("straight_100.drop_kerb.hk_ramp_mid"), 0.0655), Tol);
	TestEqual(TEXT("hk away from the drop kerb = 0.125"), Spec.Hk[3], 0.125, Tol);
	TestEqual(TEXT("back edge on the flat run = 0.150"), Spec.HkBack[0], X.Num(TEXT("straight_100.drop_kerb.hk_back_flat"), 0.15), Tol);
	TestEqual(TEXT("back edge nominal = 0.170"), Spec.HkBack[3], X.Num(TEXT("straight_100.drop_kerb.hk_back_nominal"), 0.17), Tol);

	// the mesh at the flat station 70.0
	{
		TArray<double> O, H;
		TArray<int32> Idx;
		RowsAt(B.EdgeBuf(EStreetSide::Left), B.Sp, EStreetSide::Left, 70.0, FName(TEXT("kerb")), O, H, Idx);
		TestEqual(TEXT("kerb face at s = 70 is 6 mm"), MaxOf(H), X.Num(TEXT("straight_100.drop_kerb.hk_flat"), 0.006), Tol);
		TArray<double> Op, Hp;
		TArray<int32> Ip;
		RowsAt(B.EdgeBuf(EStreetSide::Left), B.Sp, EStreetSide::Left, 70.0, FName(TEXT("pavement")), Op, Hp, Ip);
		TestEqual(TEXT("back edge at s = 70 is 0.150"), MaxOf(Hp), X.Num(TEXT("straight_100.drop_kerb.hk_back_flat"), 0.15), Tol);
	}
	// the right side has no drop kerb
	{
		double Worst = 0;
		for (double V : B.Sp.SideSpec[1].Hk) Worst = FMath::Max(Worst, FMath::Abs(V - 0.125));
		TestEqual(TEXT("right side keeps 0.125"), Worst, 0.0, 1e-12);
	}
	// the drop-kerb stations are exact floats in s
	for (double M : { 69.085, 70.0, 71.83, 72.745 })
	{
		bool bFound = false;
		for (double S : B.Sp.S) { if (S == M) { bFound = true; break; } }
		TestTrue(FString::Printf(TEXT("station %g is exact"), M), bFound);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetEdgeSplitTest, "Streetscape.Edge.SplitMaterials", kEdgeFlags)
bool FStreetEdgeSplitTest::RunTest(const FString& Parameters)
{
	const TSharedPtr<FJsonObject> DocObj = FixtureCopy(*this, TEXT("straight_100"));
	if (!DocObj.IsValid()) return false;
	AddLibraryEdgeProfile(*this, DocObj, TEXT("edge_uk_half_grass"));
	SetSegments(DocObj, { TEXT("{\"id\": \"hg\", \"s0_m\": 30.0, \"s1_m\": 80.0, \"side\": \"left\", \"edge\": {\"profile_id\": \"edge_uk_half_grass\"}}") });
	const FStreetHeightfield Terrain = TerrainFor(TEXT("straight_100"));
	FBuiltStreet B;
	if (!B.Build(*this, DocObj.ToSharedRef(), &Terrain)) return false;

	const FStreetMeshBuilder& E = B.EdgeBuf(EStreetSide::Left);
	const FStreetSideSpec& Spec = B.Sp.SideSpec[0];
	const TArray<double> O0 = B.Sp.EdgeOffset(EStreetSide::Left);
	const TArray<double> H0 = B.Sp.EdgeHeight(EStreetSide::Left);
	const int32 Tarmac = E.FindMaterialId(FName(TEXT("tarmac")));
	const int32 Grass = E.FindMaterialId(FName(TEXT("grass")));
	const int32 KerbC = E.FindMaterialId(FName(TEXT("concrete_kerb")));
	TestTrue(TEXT("split materials present"), Tarmac != INDEX_NONE && Grass != INDEX_NONE && KerbC != INDEX_NONE);

	const FName KerbG(TEXT("kerb"));
	const TArray<bool> Mask = E.GroupMaskTris(FString(), &KerbG);
	int32 Inner = 0, Outer = 0, Outside = 0, Bad = 0;
	for (int32 T = 0; T < E.F.Num(); ++T)
	{
		if (!Mask[T]) continue;
		const UE::Geometry::FIndex3i& F = E.F[T];
		const double Sm = (E.VS[F.A] + E.VS[F.B] + E.VS[F.C]) / 3.0;
		double Osum = 0, Hsum = 0;
		const int32 Vs[3] = { F.A, F.B, F.C };
		for (int32 V : Vs)
		{
			Osum += E.VD[V] - FStreetSplineMath::Interp(E.VS[V], B.Sp.S, O0);
			Hsum += E.VH[V] - FStreetSplineMath::Interp(E.VS[V], B.Sp.S, H0);
		}
		const double O = Osum / 3.0, H = Hsum / 3.0;
		int32 I = 0;
		for (int32 K = 0; K < B.Sp.Num(); ++K) { if (FMath::Abs(B.Sp.S[K] - Sm) < FMath::Abs(B.Sp.S[I] - Sm)) I = K; }
		if (H < Spec.Hk[I] - 1e-6) continue;   // not the top
		if (Sm > 30.0 && Sm < 80.0)
		{
			if (O < 0.0625 - 1e-9) { if (E.Mat[T] == Tarmac) ++Inner; else ++Bad; }
			else if (O > 0.0625 + 1e-9) { if (E.Mat[T] == Grass) ++Outer; else ++Bad; }
		}
		else
		{
			if (E.Mat[T] == KerbC) ++Outside; else ++Bad;
		}
	}
	TestEqual(TEXT("no top triangle carries the wrong material"), Bad, 0);
	TestTrue(TEXT("inner (tarmac) top triangles exist"), Inner > 0);
	TestTrue(TEXT("outer (grass) top triangles exist"), Outer > 0);
	TestTrue(TEXT("plain kerb outside the split run"), Outside > 0);

	// flush: every top-row vertex at a station shares one z (max |dz| < 1e-12)
	{
		const TArray<int32> Kv = E.VerticesOfGroups(FString(), &KerbG);
		double Worst = 0;
		int32 Checked = 0;
		for (int32 I = 0; I < B.Sp.Num(); ++I)
		{
			TArray<double> Z;
			for (int32 V : Kv)
			{
				if (FMath::Abs(E.VS[V] - B.Sp.S[I]) >= 1e-9) continue;
				if (FMath::Abs(E.VH[V] - (H0[I] + Spec.Hk[I])) < 1e-12) Z.Add(E.V[V].Z);
			}
			if (Z.Num() < 3) continue;
			Worst = FMath::Max(Worst, MaxOf(Z) - MinOf(Z));
			++Checked;
		}
		TestTrue(TEXT("top rows measured at most stations"), Checked > 40);
		TestTrue(FString::Printf(TEXT("split top flush (worst dz %.3e)"), Worst), Worst < 1e-12);
	}
	// the drop kerb at 70 lies inside the split run: both materials ride the same rows down
	{
		int32 I70 = 0;
		for (int32 K = 0; K < B.Sp.Num(); ++K) { if (FMath::Abs(B.Sp.S[K] - 70.0) < FMath::Abs(B.Sp.S[I70] - 70.0)) I70 = K; }
		TestEqual(TEXT("hk at s = 70 inside the split run"), Spec.Hk[I70], 0.006, 1e-9);
		TestTrue(TEXT("split in force at s = 70"), Spec.Split[I70]);
	}
	for (double M : { 25.0, 30.0, 80.0, 85.0 })
	{
		bool bFound = false;
		for (double S : B.Sp.S) { if (S == M) { bFound = true; break; } }
		TestTrue(FString::Printf(TEXT("profile-switch ramp station %g is exact"), M), bFound);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetEdgeBarriersTest, "Streetscape.Edge.Barriers", kEdgeFlags)
bool FStreetEdgeBarriersTest::RunTest(const FString& Parameters)
{
	const FExpected X;
	// the post rule of DESIGN.md 4.2 (tests/test_edge.py post_stations)
	TestEqual(TEXT("[45, 100] pitch 3 -> 19 posts"), FStreetRenderBuild::PostStations(45.0, 100.0, 3.0).Num(), (int32)X.Num(TEXT("straight_100.posts.chain_link_45_100_pitch3"), 19));
	TestEqual(TEXT("[45, 95] pitch 3 -> 18 posts"), FStreetRenderBuild::PostStations(45.0, 95.0, 3.0).Num(), (int32)X.Num(TEXT("straight_100.posts.chain_link_45_95_pitch3"), 18));
	TestEqual(TEXT("[95, 140] pitch 2 -> 23 posts"), FStreetRenderBuild::PostStations(95.0, 140.0, 2.0).Num(), (int32)X.Num(TEXT("straight_100.posts.railing_95_140_pitch2"), 23));
	TestEqual(TEXT("[20, 60] pitch 2 -> 21 posts"), FStreetRenderBuild::PostStations(20.0, 60.0, 2.0).Num(), (int32)X.Num(TEXT("straight_100.posts.railing_20_60_pitch2"), 21));
	{
		const TArray<double> P = FStreetRenderBuild::PostStations(45.0, 100.0, 3.0);
		TestEqual(TEXT("first post at s0"), P[0], 45.0, 1e-12);
		TestEqual(TEXT("second post at s0 + pitch"), P[1], 48.0, 1e-12);
		TestEqual(TEXT("last post at s1"), P.Last(), 100.0, 1e-12);
	}

	const TSharedPtr<FJsonObject> DocObj = FixtureCopy(*this, TEXT("straight_100"));
	if (!DocObj.IsValid()) return false;
	SetSegments(DocObj, {
		TEXT("{\"id\": \"wall\", \"s0_m\": 0.0, \"s1_m\": 45.0, \"side\": \"right\", \"edge\": {\"barrier\": {\"type\": \"brick_wall\", \"height_m\": 1.2, \"thickness_m\": 0.215, \"material\": \"brick_red\"}}}"),
		TEXT("{\"id\": \"fence\", \"s0_m\": 45.0, \"s1_m\": null, \"side\": \"right\", \"edge\": {\"barrier\": {\"type\": \"chain_link\", \"height_m\": 1.2, \"thickness_m\": 0.05, \"material\": \"chain_link\", \"post_pitch_m\": 3.0}}}"),
		TEXT("{\"id\": \"railing\", \"s0_m\": 20.0, \"s1_m\": 60.0, \"side\": \"left\", \"edge\": {\"barrier\": {\"type\": \"railing\", \"height_m\": 1.0, \"thickness_m\": 0.05, \"material\": \"steel_painted_black\", \"post_pitch_m\": 2.0, \"rails_m\": [0.98, 0.5, 0.1]}}}") });
	const FStreetHeightfield Terrain = TerrainFor(TEXT("straight_100"));
	FBuiltStreet B;
	if (!B.Build(*this, DocObj.ToSharedRef(), &Terrain)) return false;

	const FStreetMeshBuilder& ER = B.EdgeBuf(EStreetSide::Right);
	const FStreetMeshBuilder& EL = B.EdgeBuf(EStreetSide::Left);
	const FName Wall(TEXT("barrier:brick_wall:0"));
	{
		TSet<FName> Grp; Grp.Add(Wall);
		TestTrue(TEXT("brick wall is a closed manifold"), ER.IsClosedManifold(nullptr, &Grp));
		const TArray<bool> Mask = ER.GroupMaskTris(FString(), &Wall);
		TSet<FName> Mats;
		for (int32 T = 0; T < ER.F.Num(); ++T) { if (Mask[T]) Mats.Add(ER.MaterialNames[ER.Mat[T]]); }
		TestTrue(TEXT("wall carries brick_red"), Mats.Contains(FName(TEXT("brick_red"))));
		TestTrue(TEXT("wall carries coping_concrete"), Mats.Contains(FName(TEXT("coping_concrete"))));
		const TArray<int32> Wv = ER.VerticesOfGroups(FString(), &Wall);
		const FStreetSideSpec& Spec = B.Sp.SideSpec[1];
		const TArray<double> O0 = B.Sp.EdgeOffset(EStreetSide::Right);
		const TArray<double> H0 = B.Sp.EdgeHeight(EStreetSide::Right);
		TArray<double> Ob, Hb, Vs;
		for (int32 V : Wv)
		{
			TArray<double> Back, HBack;
			Back.SetNum(B.Sp.Num()); HBack.SetNum(B.Sp.Num());
			for (int32 I = 0; I < B.Sp.Num(); ++I) { Back[I] = O0[I] + Spec.BackOffset[I]; HBack[I] = H0[I] + Spec.HkBack[I]; }
			Ob.Add(-ER.VD[V] - FStreetSplineMath::Interp(ER.VS[V], B.Sp.S, Back));
			Hb.Add(ER.VH[V] - FStreetSplineMath::Interp(ER.VS[V], B.Sp.S, HBack));
			Vs.Add(ER.VS[V]);
		}
		TestEqual(TEXT("wall starts at s = 0"), MinOf(Vs), 0.0, 1e-9);
		TestEqual(TEXT("wall ends at s = 45"), MaxOf(Vs), 45.0, 1e-9);
		TestEqual(TEXT("coping proud 0.025 on the inner face"), MinOf(Ob), -0.025, 1e-9);
		TestEqual(TEXT("coping proud 0.025 on the outer face"), MaxOf(Ob), 0.215 + 0.025, 1e-9);
		TestEqual(TEXT("wall top with coping = 1.25"), MaxOf(Hb), 1.25, 1e-9);
		TestEqual(TEXT("wall skirt = -0.30"), MinOf(Hb), -0.30, 1e-9);
	}
	TestEqual(TEXT("chain-link posts"), B.InstanceCount(FName(TEXT("post_round"))), (int32)X.Num(TEXT("straight_100.posts.chain_link_45_100_pitch3"), 19));
	TestEqual(TEXT("railing posts"), B.InstanceCount(FName(TEXT("post_square"))), (int32)X.Num(TEXT("straight_100.posts.railing_20_60_pitch2"), 21));
	TestTrue(TEXT("chain_link is two-sided"), ER.TwoSided.Contains(FName(TEXT("chain_link"))));
	{
		const FName Railing(TEXT("barrier:railing:20"));
		const TArray<int32> Rv = EL.VerticesOfGroups(FString(), &Railing);
		TestTrue(TEXT("railing group exists"), Rv.Num() > 0);
		const FStreetSideSpec& Spec = B.Sp.SideSpec[0];
		const TArray<double> H0 = B.Sp.EdgeHeight(EStreetSide::Left);
		TArray<double> HBack;
		HBack.SetNum(B.Sp.Num());
		for (int32 I = 0; I < B.Sp.Num(); ++I) HBack[I] = H0[I] + Spec.HkBack[I];
		TArray<double> Levels;
		for (int32 V : Rv) Levels.Add(EL.VH[V] - FStreetSplineMath::Interp(EL.VS[V], B.Sp.S, HBack));
		const TArray<double> U = UniqueRounded(Levels, 6);
		TestEqual(TEXT("three rails -> six levels"), U.Num(), 2 * (int32)X.Num(TEXT("straight_100.railing_rails"), 3));
		const double Want[6] = { 0.08, 0.12, 0.48, 0.52, 0.96, 1.0 };
		for (int32 I = 0; I < FMath::Min(6, U.Num()); ++I) TestEqual(FString::Printf(TEXT("rail level %d"), I), U[I], Want[I], 1e-9);
		TSet<FName> Grp; Grp.Add(Railing);
		TestTrue(TEXT("railing rails are closed manifolds"), EL.IsClosedManifold(nullptr, &Grp));
	}
	TestEqual(TEXT("edge_right validates clean: ") + FString::Join(ER.Validate(), TEXT(" | ")), ER.Validate().Num(), 0);
	TestEqual(TEXT("edge_left validates clean: ") + FString::Join(EL.Validate(), TEXT(" | ")), EL.Validate().Num(), 0);
	// a barrier never changes the road/kerb seam
	for (int32 K = 0; K < 2; ++K)
	{
		const EStreetSide Side = K == 0 ? EStreetSide::Left : EStreetSide::Right;
		const FStreetSideSpec& Spec = B.Sp.SideSpec[K];
		double Td = Spec.TuckDepth.Num() ? Spec.TuckDepth[0] : 0.03;
		for (double V : Spec.TuckDepth) Td = FMath::Min(Td, V);
		const FStreetGeometry::FOverlap M = FStreetGeometry::MeasureLateralOverlap(B.RoadBuf(), B.EdgeBuf(Side), StreetSideSigma(Side), Td);
		TestEqual(TEXT("overlap unchanged by barriers (min)"), M.MinM, 0.04, 1e-9);
		TestEqual(TEXT("overlap unchanged by barriers (max)"), M.MaxM, 0.04, 1e-9);
	}
	return true;
}
