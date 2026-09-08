// Streetscape.Rail.Gauge (UE_PLAN.md 2.13; DESIGN.md 6) - rail is a PROFILE KIND of Renderer A, not a fourth
// renderer: the same UStreetRoadRenderer builds the ballast ribbon, the sleeper instances and the two BS113A rails.
// Numbers from Tools/blender/tests/fixtures/expected.json (rail_R300_600).

#include "StreetRenderTestUtil.h"

using namespace StreetTest;

constexpr EAutomationTestFlags kRailFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetRailGaugeTest, "Streetscape.Rail.Gauge", kRailFlags)
bool FStreetRailGaugeTest::RunTest(const FString& Parameters)
{
	const FExpected X;
	const TSharedPtr<FJsonObject> DocObj = Fixture(*this, TEXT("rail_R300_600"));
	if (!DocObj.IsValid()) return false;
	const FStreetHeightfield Terrain = TerrainFor(TEXT("rail_R300_600"));
	FBuiltStreet B;
	if (!B.Build(*this, DocObj.ToSharedRef(), &Terrain)) return false;
	const FStreetMeshBuilder& Rb = B.RoadBuf();

	TestTrue(TEXT("kind is rail"), B.Sp.bHasKind && B.Sp.Kind == EStreetRoadKind::Rail);
	TestEqual(TEXT("rail buffer validates clean: ") + FString::Join(Rb.Validate(), TEXT(" | ")), Rb.Validate().Num(), 0);

	const FName LeftG(TEXT("rail:left")), RightG(TEXT("rail:right")), Ballast(TEXT("ballast"));
	const TArray<int32> Lv = Rb.VerticesOfGroups(FString(), &LeftG);
	const TArray<int32> Rv = Rb.VerticesOfGroups(FString(), &RightG);
	TestTrue(TEXT("both rails exist"), Lv.Num() > 0 && Rv.Num() > 0);

	const double Top = 0.055 + 0.15875;
	TestEqual(TEXT("rail top above the ballast"), Top, X.Num(TEXT("rail_R300_600.rail_top_above_ballast"), 0.21375), 1e-9);
	{
		double VhMax = -1e9;
		for (int32 V : Lv) VhMax = FMath::Max(VhMax, Rb.VH[V]);
		TestEqual(TEXT("measured rail top"), VhMax, X.Num(TEXT("rail_R300_600.rail_top_above_ballast"), 0.21375), X.Num(TEXT("rail_R300_600.rail_top_tol"), 1e-6));
	}
	{
		double LMin = 1e9, RMax = -1e9, LSum = 0, RSum = 0;
		int32 LN = 0, RN = 0;
		for (int32 V : Lv) { if (FMath::Abs(Rb.VH[V] - Top) < 1e-9) LMin = FMath::Min(LMin, Rb.VD[V]); LSum += Rb.VD[V]; ++LN; }
		for (int32 V : Rv) { if (FMath::Abs(Rb.VH[V] - Top) < 1e-9) RMax = FMath::Max(RMax, Rb.VD[V]); RSum += Rb.VD[V]; ++RN; }
		TestEqual(TEXT("inner faces 1.435 apart"), LMin - RMax, X.Num(TEXT("rail_R300_600.gauge_inner_faces"), 1.435), X.Num(TEXT("rail_R300_600.gauge_tol"), 0.001));
		TestEqual(TEXT("rail centres 1.50485 apart"), LSum / LN - RSum / RN, X.Num(TEXT("rail_R300_600.rail_centres"), 1.50485), X.Num(TEXT("rail_R300_600.rail_centres_tol"), 0.001));
	}
	{
		TSet<FName> L; L.Add(LeftG);
		TSet<FName> R; R.Add(RightG);
		TestTrue(TEXT("left rail is a closed manifold"), Rb.IsClosedManifold(nullptr, &L));
		TestTrue(TEXT("right rail is a closed manifold"), Rb.IsClosedManifold(nullptr, &R));
	}

	// -- ballast
	{
		const TArray<int32> Bv = Rb.VerticesOfGroups(FString(), &Ballast);
		double TopMin = 1e9, TopMax = -1e9, ToeMin = 1e9, ToeMax = -1e9;
		for (int32 V : Bv)
		{
			if (FMath::Abs(Rb.VH[V]) < 1e-9) { TopMin = FMath::Min(TopMin, Rb.VD[V]); TopMax = FMath::Max(TopMax, Rb.VD[V]); }
			if (FMath::Abs(Rb.VH[V] + 0.45) < 1e-9) { ToeMin = FMath::Min(ToeMin, Rb.VD[V]); ToeMax = FMath::Max(ToeMax, Rb.VD[V]); }
		}
		TestEqual(TEXT("ballast top width"), TopMax - TopMin, X.Num(TEXT("rail_R300_600.ballast_top_width"), 3.4), 1e-9);
		TestEqual(TEXT("ballast toe width"), ToeMax - ToeMin, X.Num(TEXT("rail_R300_600.ballast_toe_width"), 4.75), 1e-9);
		const TArray<bool> Mask = Rb.GroupMaskTris(FString(), &Ballast);
		TSet<FName> Mats;
		for (int32 T = 0; T < Rb.F.Num(); ++T) { if (Mask[T]) Mats.Add(Rb.MaterialNames[Rb.Mat[T]]); }
		TestEqual(TEXT("ballast is one material"), Mats.Num(), 1);
		TestTrue(TEXT("ballast material"), Mats.Contains(FName(TEXT("ballast"))));
	}

	// -- sleepers
	{
		const TArray<FStreetInstance> Sl = B.InstancesOf(FName(TEXT("sleeper")));
		const int32 Want = (int32)FMath::FloorToDouble(B.Sp.LengthM / 0.65) + 1;
		TestEqual(TEXT("sleeper count = floor(L / 0.65) + 1"), Sl.Num(), Want);
		TestEqual(TEXT("sleeper count matches the frozen number"), Sl.Num(), (int32)X.Num(TEXT("rail_R300_600.sleepers"), 924));
		TArray<double> Sj;
		for (int32 J = 0; J < Sl.Num(); ++J) Sj.Add(0.65 * J);
		const FStreetFrames Fr = B.Sp.Frames.At(Sj);
		double Worst = 0;
		for (int32 J = 0; J < Sl.Num(); ++J)
		{
			const FVector3d Want2 = Fr.P[J] - 0.10 * Fr.B[J];
			Worst = FMath::Max(Worst, (Sl[J].P - Want2).Length());
		}
		TestTrue(FString::Printf(TEXT("sleepers sit on frames.at(0.65 j) (%.3e)"), Worst), Worst < 1e-9);
		for (int32 J = 0; J < FMath::Min(5, Sl.Num()); ++J)
		{
			TestEqual(TEXT("sleeper size x"), Sl[J].Size.X, 0.25, 1e-12);
			TestEqual(TEXT("sleeper size y"), Sl[J].Size.Y, 2.5, 1e-12);
			TestEqual(TEXT("sleeper size z"), Sl[J].Size.Z, 0.15, 1e-12);
			TestEqual(TEXT("sleeper material"), Sl[J].Material, FName(TEXT("sleeper_concrete")));
		}
	}

	// -- tessellation: 1 m on the straights, 0.83 m in the R = 300 bend
	{
		double SumStraight = 0, SumBend = 0;
		int32 NStraight = 0, NBend = 0;
		for (int32 I = 0; I + 1 < B.Sp.Num(); ++I)
		{
			if (B.Sp.Mandatory[I] || B.Sp.Mandatory[I + 1]) continue;
			const double G = B.Sp.S[I + 1] - B.Sp.S[I];
			const double Mid = (B.Sp.S[I] + B.Sp.S[I + 1]) / 2.0;
			if (Mid > 20 && Mid < 180) { SumStraight += G; ++NStraight; }
			if (Mid > 220 && Mid < 380) { SumBend += G; ++NBend; }
		}
		TestTrue(TEXT("straight and bend gaps measured"), NStraight > 0 && NBend > 0);
		TestEqual(TEXT("straight spacing"), SumStraight / NStraight, X.Num(TEXT("rail_R300_600.straight_spacing"), 1.0), X.Num(TEXT("rail_R300_600.straight_tol"), 0.02));
		TestEqual(TEXT("bend spacing"), SumBend / NBend, X.Num(TEXT("rail_R300_600.bend_spacing"), 0.83), X.Num(TEXT("rail_R300_600.bend_tol"), 0.03));
	}
	TestEqual(TEXT("rail carries no marking strips"), B.Road.MarkingStrips, 0);
	return true;
}
