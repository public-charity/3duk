// Streetscape.Hedge.Volume (UE_PLAN.md 2.13; DESIGN.md 4.3) - Renderer C: a closed manifold before and after the
// fbm3 displacement, the base row undisplaced, the inner face stepping out by the barrier thickness, and the leaf
// card count against 12 cards per m2 of the surface above 0.05 m (Tools/blender/tests/test_hedge.py).

#include "StreetRenderTestUtil.h"

using namespace StreetTest;

constexpr EAutomationTestFlags kHedgeFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

namespace
{
/** tests/test_hedge.py hedge_doc: privet on the right for [30, 90] behind a wall (0-45) and a fence (45-70). */
TSharedPtr<FJsonObject> HedgeDoc(FAutomationTestBase& T, double NoiseAmp, const FString& Top, bool bWithWall)
{
	TSharedPtr<FJsonObject> D = FixtureCopy(T, TEXT("straight_100"));
	if (!D.IsValid()) return nullptr;
	AddLibraryHedgeProfile(T, D, TEXT("hedge_privet"));
	const TSharedPtr<FJsonObject> H = D->GetObjectField(TEXT("profiles"))->GetObjectField(TEXT("hedge"))->GetObjectField(TEXT("hedge_privet"));
	H->SetStringField(TEXT("top_profile"), Top);
	if (NoiseAmp >= 0) H->SetNumberField(TEXT("noise_amplitude_m"), NoiseAmp);
	FirstSpline(D)->GetObjectField(TEXT("profile_ids"))->SetStringField(TEXT("hedge_right"), TEXT("hedge_privet"));
	TArray<FString> Segs;
	if (bWithWall)
	{
		Segs.Add(TEXT("{\"id\": \"wall\", \"s0_m\": 0.0, \"s1_m\": 45.0, \"side\": \"right\", \"edge\": {\"barrier\": {\"type\": \"brick_wall\", \"height_m\": 1.2, \"thickness_m\": 0.215, \"material\": \"brick_red\"}}}"));
		Segs.Add(TEXT("{\"id\": \"fence\", \"s0_m\": 45.0, \"s1_m\": 70.0, \"side\": \"right\", \"edge\": {\"barrier\": {\"type\": \"chain_link\", \"height_m\": 1.2, \"thickness_m\": 0.05, \"material\": \"chain_link\", \"post_pitch_m\": 3.0}}}"));
	}
	Segs.Add(TEXT("{\"id\": \"hedge\", \"s0_m\": 30.0, \"s1_m\": 90.0, \"side\": \"right\", \"hedge\": {\"present\": true, \"offset_m\": 0.1}}"));
	SetSegments(D, Segs);
	return D;
}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetHedgeVolumeTest, "Streetscape.Hedge.Volume", kHedgeFlags)
bool FStreetHedgeVolumeTest::RunTest(const FString& Parameters)
{
	const FExpected X;
	const FStreetHeightfield Terrain = TerrainFor(TEXT("straight_100"));
	const TSharedPtr<FJsonObject> D1 = HedgeDoc(*this, -1.0, TEXT("flat"), true);
	const TSharedPtr<FJsonObject> D0 = HedgeDoc(*this, 0.0, TEXT("flat"), true);
	if (!D1.IsValid() || !D0.IsValid()) return false;
	FBuiltStreet B, B0;
	if (!B.Build(*this, D1.ToSharedRef(), &Terrain)) return false;
	if (!B0.Build(*this, D0.ToSharedRef(), &Terrain)) return false;
	const FStreetMeshBuilder& H = B.HedgeBuf(EStreetSide::Right);
	const FStreetMeshBuilder& H0 = B0.HedgeBuf(EStreetSide::Right);

	TestTrue(TEXT("hedge geometry exists"), H.V.Num() > 0);
	TestTrue(TEXT("undisplaced hedge is a closed manifold"), H0.IsClosedManifold());
	TestTrue(TEXT("displaced hedge is a closed manifold"), H.IsClosedManifold());
	TestEqual(TEXT("hedge validates clean: ") + FString::Join(H.Validate(), TEXT(" | ")), H.Validate().Num(), 0);
	TestEqual(TEXT("displacement does not change the vertex count"), H.V.Num(), H0.V.Num());

	const FStreetSideSpec& Spec = B.Sp.SideSpec[1];
	const TArray<double> Eh = B.Sp.EdgeHeight(EStreetSide::Right);
	TArray<double> Base, BackH;
	Base.SetNum(B.Sp.Num()); BackH.SetNum(B.Sp.Num());
	for (int32 I = 0; I < B.Sp.Num(); ++I) { BackH[I] = Eh[I] + Spec.HkBack[I]; Base[I] = BackH[I] - 0.1; }

	double DMax = 0;
	double BottomMax = 0;
	int32 BottomCount = 0;
	for (int32 V = 0; V < H.V.Num(); ++V)
	{
		const double D = (H.V[V] - H0.V[V]).Length();
		DMax = FMath::Max(DMax, D);
		if (FMath::Abs(H.VH[V] - FStreetSplineMath::Interp(H.VS[V], B.Sp.S, Base)) < 1e-9)
		{
			++BottomCount;
			BottomMax = FMath::Max(BottomMax, D);
		}
	}
	TestTrue(FString::Printf(TEXT("displacement <= noise_amplitude (%.5f)"), DMax), DMax <= X.Num(TEXT("hedge.noise_amplitude_m"), 0.06) + X.Num(TEXT("hedge.noise_tol"), 1e-9));
	TestTrue(TEXT("displacement is actually applied"), DMax > 0.01);
	TestTrue(TEXT("base row exists"), BottomCount > 0);
	TestEqual(TEXT("base row undisplaced"), BottomMax, 0.0, 0.0);

	// spans [30, 90] on stations shared with the edge buffer
	{
		double SMin = 1e9, SMax = -1e9;
		bool bAllStations = true;
		for (int32 V = 0; V < H.V.Num(); ++V)
		{
			SMin = FMath::Min(SMin, H.VS[V]);
			SMax = FMath::Max(SMax, H.VS[V]);
			bool bFound = false;
			for (double S : B.Sp.S) { if (S == H.VS[V]) { bFound = true; break; } }
			if (!bFound) bAllStations = false;
		}
		TestEqual(TEXT("hedge starts at s = 30"), SMin, 30.0, 0.0);
		TestEqual(TEXT("hedge ends at s = 90"), SMax, 90.0, 0.0);
		TestTrue(TEXT("hedge stations are spline stations"), bAllStations);
	}

	// stacking beside the wall (0.215), the fence (0.05) and nothing (0.0)
	{
		const FStreetMeshBuilder& Hn = B0.HedgeBuf(EStreetSide::Right);
		const TArray<double> O0 = B0.Sp.EdgeOffset(EStreetSide::Right);
		const FStreetSideSpec& Sp2 = B0.Sp.SideSpec[1];
		TArray<double> Back;
		Back.SetNum(B0.Sp.Num());
		for (int32 I = 0; I < B0.Sp.Num(); ++I) Back[I] = O0[I] + Sp2.BackOffset[I];
		const double Cases[6][2] = { { 32.0, 0.215 }, { 44.0, 0.215 }, { 46.0, 0.05 }, { 68.0, 0.05 }, { 72.0, 0.0 }, { 88.0, 0.0 } };
		for (int32 K = 0; K < 6; ++K)
		{
			double Inner = 1e9, Outer = -1e9;
			for (int32 V = 0; V < Hn.V.Num(); ++V)
			{
				if (FMath::Abs(Hn.VS[V] - Cases[K][0]) >= 1e-9) continue;
				const double O = -Hn.VD[V] - FStreetSplineMath::Interp(Hn.VS[V], B0.Sp.S, Back);
				Inner = FMath::Min(Inner, O);
				Outer = FMath::Max(Outer, O);
			}
			TestEqual(FString::Printf(TEXT("hedge inner face at s = %g"), Cases[K][0]), Inner, Cases[K][1] + 0.1, 1e-9);
			TestEqual(FString::Printf(TEXT("hedge outer face at s = %g"), Cases[K][0]), Outer, Cases[K][1] + 0.1 + 0.8, 1e-9);
		}
		double HbMax = -1e9, HbMin = 1e9;
		for (int32 V = 0; V < Hn.V.Num(); ++V)
		{
			const double Hb = Hn.VH[V] - FStreetSplineMath::Interp(Hn.VS[V], B0.Sp.S, BackH);
			HbMax = FMath::Max(HbMax, Hb);
			HbMin = FMath::Min(HbMin, Hb);
		}
		TestEqual(TEXT("hedge top 1.5 above the pavement back edge"), HbMax, 1.5, 1e-9);
		TestEqual(TEXT("hedge base sunk 0.1"), HbMin, -0.1, 1e-9);
	}

	// leaf cards: floor(area * 12 + frac) over the surface above 0.05 m
	{
		const TArray<FStreetInstance> Cards = B.InstancesOf(FName(TEXT("leaf_card")));
		TestTrue(TEXT("leaf cards generated"), Cards.Num() > 0);
		double Area = 0;
		for (int32 T = 0; T < H.F.Num(); ++T)
		{
			const UE::Geometry::FIndex3i& F = H.F[T];
			const double H0r = H.VH[F.A] - FStreetSplineMath::Interp(H.VS[F.A], B.Sp.S, Base);
			const double H1r = H.VH[F.B] - FStreetSplineMath::Interp(H.VS[F.B], B.Sp.S, Base);
			const double H2r = H.VH[F.C] - FStreetSplineMath::Interp(H.VS[F.C], B.Sp.S, Base);
			if ((H0r + H1r + H2r) / 3.0 > 0.05) Area += H.FaceArea(T);
		}
		const double Ratio = (double)Cards.Num() / (X.Num(TEXT("hedge.card_density_per_m2"), 12.0) * Area);
		TestEqual(FString::Printf(TEXT("card count %d over %.3f m2 -> ratio %.4f"), Cards.Num(), Area, Ratio), Ratio, 1.0, X.Num(TEXT("hedge.card_tol_frac"), 0.05));
		for (int32 K = 0; K < FMath::Min(50, Cards.Num()); ++K)
		{
			TestEqual(TEXT("card size"), Cards[K].Size.X, 0.25, 1e-12);
			TestEqual(TEXT("card material"), Cards[K].Material, FName(TEXT("privet_leaf")));
			TestEqual(TEXT("card normal is unit"), Cards[K].B.Length(), 1.0, 1e-9);
		}
	}

	// every top profile stays a closed manifold
	for (const TCHAR* Top : { TEXT("flat"), TEXT("rounded"), TEXT("domed") })
	{
		const TSharedPtr<FJsonObject> D = HedgeDoc(*this, 0.0, Top, true);
		FBuiltStreet Bt;
		if (!Bt.Build(*this, D.ToSharedRef(), &Terrain)) return false;
		TestTrue(FString::Printf(TEXT("top_profile %s is a closed manifold"), Top), Bt.HedgeBuf(EStreetSide::Right).IsClosedManifold());
		TestEqual(FString::Printf(TEXT("top_profile %s validates clean"), Top), Bt.HedgeBuf(EStreetSide::Right).Validate().Num(), 0);
	}
	return true;
}
