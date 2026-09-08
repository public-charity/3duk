// Streetscape.Road.Markings (UE_PLAN.md 2.13; DESIGN.md 4.1) - Renderer A on straight_100 against
// Tools/blender/tests/fixtures/expected.json: ribbon rows/verts/tris, 17 centre dashes, the double yellow's line
// centres 0.35 / 0.15 inward of the LEFT kerb line and its 6 -> 8 m ramp, the 0.004 m lift measured on the road mesh.

#include "StreetRenderTestUtil.h"

using namespace StreetTest;

constexpr EAutomationTestFlags kRoadFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetRoadMarkingsTest, "Streetscape.Road.Markings", kRoadFlags)
bool FStreetRoadMarkingsTest::RunTest(const FString& Parameters)
{
	const FExpected X;
	const TSharedPtr<FJsonObject> DocObj = Fixture(*this, TEXT("straight_100"));
	if (!DocObj.IsValid()) return false;
	const FStreetHeightfield Terrain = TerrainFor(TEXT("straight_100"));
	FBuiltStreet B;
	if (!B.Build(*this, DocObj.ToSharedRef(), &Terrain)) return false;
	const FStreetMeshBuilder& Road = B.RoadBuf();

	// -- ribbon counts -------------------------------------------------------------------------------------------
	const FString MarkPrefix(TEXT("marking:"));
	const TArray<int32> RibbonV = Road.VerticesOfGroups(FString(), nullptr, &MarkPrefix);
	const TArray<bool> MarkTris = Road.GroupMaskTris(MarkPrefix);
	int32 RibbonT = 0;
	for (bool Mk : MarkTris) { if (!Mk) ++RibbonT; }
	TestEqual(TEXT("ribbon verts"), RibbonV.Num(), (int32)X.Num(TEXT("straight_100.ribbon_verts"), 594));
	TestEqual(TEXT("ribbon tris"), RibbonT, (int32)X.Num(TEXT("straight_100.ribbon_tris"), 1060));
	{
		TArray<double> D0;
		for (int32 V : RibbonV) { if (FMath::Abs(Road.VS[V]) < 1e-9) D0.Add(Road.VD[V]); }
		TestEqual(TEXT("ribbon rows at s = 0"), UniqueRounded(D0).Num(), (int32)X.Num(TEXT("straight_100.ribbon_rows"), 11));
	}
	{
		TArray<FString> NonMarking;
		for (FName G : Road.GroupNames) { if (!G.ToString().StartsWith(MarkPrefix)) NonMarking.Add(G.ToString()); }
		NonMarking.Sort();
		TestEqual(TEXT("non-marking groups"), FString::Join(NonMarking, TEXT(",")), FString(TEXT("road,skirt_left,skirt_right")));
	}
	TestEqual(TEXT("road buffer validates clean: ") + FString::Join(Road.Validate(), TEXT(" | ")), Road.Validate().Num(), 0);
	{
		TArray<double> Vs;
		for (int32 V : RibbonV) Vs.Add(Road.VS[V]);
		const TArray<double> Uniq = UniqueRounded(Vs, 12);
		bool bSame = Uniq.Num() == B.Sp.S.Num();
		for (int32 I = 0; bSame && I < Uniq.Num(); ++I) bSame = FMath::Abs(Uniq[I] - B.Sp.S[I]) < 1e-12;
		TestTrue(TEXT("ribbon stations == spline stations"), bSame);
	}

	// -- centre dashes -------------------------------------------------------------------------------------------
	{
		const FName G(TEXT("marking:centre_1004"));
		const TArray<int32> Vi = Road.VerticesOfGroups(FString(), &G);
		TArray<double> Vd;
		for (int32 V : Vi) Vd.Add(Road.VD[V]);
		const TArray<double> UD = UniqueRounded(Vd);
		TestEqual(TEXT("centre dash strip has two lateral rows"), UD.Num(), 2);
		if (UD.Num() == 2)
		{
			TestEqual(TEXT("centre dash vd[0]"), UD[0], -0.05, 1e-9);
			TestEqual(TEXT("centre dash vd[1]"), UD[1], 0.05, 1e-9);
		}
		const TArray<TPair<double, double>> Runs = DashRuns(Road, G);
		const int32 Want = (int32)X.Num(TEXT("straight_100.centre_dashes.count"), 17);
		TestEqual(TEXT("centre dash count"), Runs.Num(), Want);
		for (int32 K = 0; K < Runs.Num(); ++K)
		{
			TestEqual(FString::Printf(TEXT("dash %d start"), K), Runs[K].Key, 6.0 * K, 1e-9);
			TestEqual(FString::Printf(TEXT("dash %d end"), K), Runs[K].Value, 6.0 * K + 4.0, 1e-9);
		}
		if (Runs.Num() == Want && Want > 0)
		{
			TestEqual(TEXT("first dash [0, 4]"), Runs[0].Key, 0.0, 1e-6);
			TestEqual(TEXT("last dash [96, 100]"), Runs.Last().Value, 100.0, 1e-6);
		}
	}
	TestEqual(TEXT("marking strips"), B.Road.MarkingStrips, (int32)X.Num(TEXT("straight_100.marking_strips"), 19));

	// -- double yellow: line centres 0.35 / 0.15 inward of the LEFT kerb line, following the 6 -> 8 ramp ----------
	{
		const FName G(TEXT("marking:dyl_left_1018_1"));
		const TArray<int32> Vi = Road.VerticesOfGroups(FString(), &G);
		const TArray<double> O0 = B.Sp.EdgeOffset(EStreetSide::Left);
		int32 Checked = 0;
		for (int32 I = 0; I < B.Sp.Num(); ++I)
		{
			TArray<double> Vd;
			for (int32 V : Vi) { if (FMath::Abs(Road.VS[V] - B.Sp.S[I]) < 1e-9) Vd.Add(Road.VD[V]); }
			if (Vd.Num() == 0) continue;
			Vd.Sort();
			if (!TestEqual(FString::Printf(TEXT("double yellow at s = %g has 4 lateral values"), B.Sp.S[I]), Vd.Num(), 4)) break;
			const double C0 = (Vd[0] + Vd[1]) / 2.0;
			const double C1 = (Vd[2] + Vd[3]) / 2.0;
			TestEqual(TEXT("dyl inner line centre"), C0, O0[I] - 0.35, 1e-9);
			TestEqual(TEXT("dyl outer line centre"), C1, O0[I] - 0.15, 1e-9);
			TestEqual(TEXT("dyl line width"), Vd[1] - Vd[0], 0.1, 1e-9);
			TestEqual(TEXT("dyl pair centre"), (C0 + C1) / 2.0, O0[I] - 0.25, 1e-9);
			++Checked;
		}
		TestTrue(TEXT("double yellow measured at every painted station"), Checked > 20);
	}

	// -- the lift is measured on the ROAD MESH (SCHEMA.md 3.7 / README parity decision 5) -------------------------
	{
		const TArray<int32> Vi = Road.VerticesOfGroups(MarkPrefix);
		TestTrue(TEXT("marking vertices exist"), Vi.Num() > 100);
		double WorstErr = 0;
		int32 Nan = 0;
		for (int32 V : Vi)
		{
			const double HRoad = FStreetGeometry::SurfaceHeightAt(Road, Road.VS[V], Road.VD[V]);
			if (!FMath::IsFinite(HRoad)) { ++Nan; continue; }
			WorstErr = FMath::Max(WorstErr, FMath::Abs((Road.VH[V] - HRoad) - X.Num(TEXT("straight_100.lift_m"), 0.004)));
		}
		TestEqual(TEXT("every marking vertex sits over the road mesh"), Nan, 0);
		TestTrue(FString::Printf(TEXT("lift = 0.004 everywhere (worst %.3e)"), WorstErr), WorstErr <= X.Num(TEXT("straight_100.lift_tol"), 1e-9));
	}

	// -- camber ---------------------------------------------------------------------------------------------------
	{
		int32 I20 = 0;
		for (int32 I = 0; I < B.Sp.Num(); ++I) { if (FMath::Abs(B.Sp.S[I] - 20.0) < FMath::Abs(B.Sp.S[I20] - 20.0)) I20 = I; }
		TestEqual(TEXT("camber h(0)"), B.Sp.SurfaceHAt(I20, 0.0), X.Num(TEXT("straight_100.camber.h0"), 0.0), 1e-12);
		TestEqual(TEXT("camber h(+3) parabolic"), B.Sp.SurfaceHAt(I20, 3.0), X.Num(TEXT("straight_100.camber.h_pm3_parabolic"), -0.0375), 1e-12);
		TestEqual(TEXT("camber h(-3) parabolic"), B.Sp.SurfaceHAt(I20, -3.0), X.Num(TEXT("straight_100.camber.h_pm3_parabolic"), -0.0375), 1e-12);
	}
	return true;
}

// A dashed marking's phase is global: phase 1 puts dashes at 1, 7, 13 ... (tests/test_road_markings.py).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetRoadDashPhaseTest, "Streetscape.Road.DashPhase", kRoadFlags)
bool FStreetRoadDashPhaseTest::RunTest(const FString& Parameters)
{
	const TSharedPtr<FJsonObject> DocObj = FixtureCopy(*this, TEXT("straight_100"));
	if (!DocObj.IsValid()) return false;
	const TSharedPtr<FJsonObject> Prof = DocObj->GetObjectField(TEXT("profiles"))->GetObjectField(TEXT("road"))->GetObjectField(TEXT("road_test_marked"));
	TArray<TSharedPtr<FJsonValue>> Marks;
	Marks.Add(SegmentFromText(TEXT("{\"id\": \"d\", \"anchor\": \"centre\", \"offset_m\": 0.0, \"width_m\": 0.1, \"pattern\": \"dashed\", \"dash_m\": 4.0, \"gap_m\": 2.0, \"phase_m\": 1.0, \"material\": \"white_paint\"}")));
	Prof->SetArrayField(TEXT("markings"), Marks);
	const FStreetHeightfield Terrain = TerrainFor(TEXT("straight_100"));
	FBuiltStreet B;
	if (!B.Build(*this, DocObj.ToSharedRef(), &Terrain)) return false;
	const TArray<TPair<double, double>> Runs = DashRuns(B.RoadBuf(), FName(TEXT("marking:d")));
	TestTrue(TEXT("at least two dashes"), Runs.Num() >= 2);
	if (Runs.Num() >= 2)
	{
		TestEqual(TEXT("first dash starts at the phase"), Runs[0].Key, 1.0, 1e-9);
		TestEqual(TEXT("second dash starts a period later"), Runs[1].Key, 7.0, 1e-9);
	}
	// one strip per painted run: 17 dashes at 1 + 6 k over 100 m, the last clipped at L
	TestEqual(TEXT("one strip per dash"), B.Road.MarkingStrips, Runs.Num());
	TestEqual(TEXT("17 dashes with phase 1"), Runs.Num(), 17);
	return true;
}

// profile_ids.road = null -> no carriageway at all (SCHEMA.md 4.13).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetRoadNullProfileTest, "Streetscape.Road.NullProfile", kRoadFlags)
bool FStreetRoadNullProfileTest::RunTest(const FString& Parameters)
{
	const TSharedPtr<FJsonObject> DocObj = FixtureCopy(*this, TEXT("straight_100"));
	if (!DocObj.IsValid()) return false;
	FirstSpline(DocObj)->GetObjectField(TEXT("profile_ids"))->SetField(TEXT("road"), MakeShared<FJsonValueNull>());
	const FStreetHeightfield Terrain = TerrainFor(TEXT("straight_100"));
	FBuiltStreet B;
	if (!B.Build(*this, DocObj.ToSharedRef(), &Terrain)) return false;
	TestEqual(TEXT("no road geometry"), B.RoadBuf().V.Num(), 0);
	double WMax = 0, EMax = 0;
	const TArray<double> Eo = B.Sp.EdgeOffset(EStreetSide::Left);
	for (int32 I = 0; I < B.Sp.Num(); ++I) { WMax = FMath::Max(WMax, FMath::Abs(B.Sp.Width[I])); EMax = FMath::Max(EMax, FMath::Abs(Eo[I])); }
	TestEqual(TEXT("width 0 everywhere"), WMax, 0.0, 0.0);
	TestEqual(TEXT("edge offset 0 everywhere"), EMax, 0.0, 0.0);
	return true;
}
