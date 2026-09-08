// Streetscape.Seam.Rules (UE_PLAN.md 2.13; DESIGN.md 5, the "critical" rule of BRIEF 1.1) - the six seam rules on
// the three synthetic roads and on the half-grass profile switch, exactly what Tools/blender/tests/test_seam.py
// asserts: 0.040 lateral overlap at every station, identical station sets, the skirt inside the kerb block, two
// coincident positions per station, height coherence and an invisible seam across the 6 -> 8 m width ramp.

#include "StreetRenderTestUtil.h"

using namespace StreetTest;

constexpr EAutomationTestFlags kSeamFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

namespace
{
struct FSeamCase { FString Label; TSharedPtr<FJsonObject> Doc; FString Fixture; };
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetSeamRulesTest, "Streetscape.Seam.Rules", kSeamFlags)
bool FStreetSeamRulesTest::RunTest(const FString& Parameters)
{
	const FExpected X;
	const double Ov = X.Num(TEXT("straight_100.overlap_m"), 0.04);
	const double Sd = X.Num(TEXT("straight_100.skirt_drop_m"), 0.02);
	const double Td = X.Num(TEXT("straight_100.tuck_depth_m"), 0.03);
	const double Ti = X.Num(TEXT("straight_100.tuck_in_m"), 0.02);
	const int32 CoincPerStation = (int32)X.Num(TEXT("straight_100.coincident_per_station"), 2);
	const int32 CoincStrict = (int32)X.Num(TEXT("straight_100.coincident_strict_band"), 0);

	TArray<FSeamCase> Cases;
	for (const TCHAR* Name : { TEXT("straight_100"), TEXT("sine_5_50"), TEXT("curve_R20_200") })
	{
		FSeamCase C;
		C.Label = FString(Name) + TEXT(" (as is)");
		C.Fixture = Name;
		C.Doc = Fixture(*this, Name);
		if (!C.Doc.IsValid()) return false;
		Cases.Add(C);
	}
	{
		FSeamCase C;
		C.Label = TEXT("straight_100 (half-grass switch 20-60)");
		C.Fixture = TEXT("straight_100");
		C.Doc = FixtureCopy(*this, TEXT("straight_100"));
		if (!C.Doc.IsValid()) return false;
		AddLibraryEdgeProfile(*this, C.Doc, TEXT("edge_uk_half_grass"));
		SetSegments(C.Doc, { TEXT("{\"id\": \"hg\", \"s0_m\": 20.0, \"s1_m\": 60.0, \"side\": \"both\", \"edge\": {\"profile_id\": \"edge_uk_half_grass\"}}") });
		Cases.Add(C);
	}
	{
		FSeamCase C;
		C.Label = TEXT("straight_100 (no drop kerb)");
		C.Fixture = TEXT("straight_100");
		C.Doc = FixtureCopy(*this, TEXT("straight_100"));
		if (!C.Doc.IsValid()) return false;
		FirstSpline(C.Doc)->SetArrayField(TEXT("drop_kerbs"), {});
		Cases.Add(C);
	}

	for (const FSeamCase& C : Cases)
	{
		const FStreetHeightfield Terrain = TerrainFor(C.Fixture);
		FBuiltStreet B;
		if (!B.Build(*this, C.Doc.ToSharedRef(), &Terrain)) return false;
		const FStreetMeshBuilder& Road = B.RoadBuf();

		// rule 2: identical stations
		{
			const TArray<double> St = FStreetGeometry::StationValues(Road);
			bool bSame = St.Num() == B.Sp.S.Num();
			for (int32 I = 0; bSame && I < St.Num(); ++I) bSame = St[I] == B.Sp.S[I];
			TestTrue(C.Label + TEXT(": road stations == spline stations"), bSame);
			const TArray<double> SL = FStreetGeometry::StationValues(B.EdgeBuf(EStreetSide::Left));
			const TArray<double> SR = FStreetGeometry::StationValues(B.EdgeBuf(EStreetSide::Right));
			TestEqual(C.Label + TEXT(": both edges carry the same stations"), SL.Num(), SR.Num());
			bool bEq = SL.Num() == SR.Num();
			for (int32 I = 0; bEq && I < SL.Num(); ++I) bEq = SL[I] == SR[I];
			TestTrue(C.Label + TEXT(": edge station sets identical"), bEq);
			bool bEqSp = SL.Num() == B.Sp.S.Num();
			for (int32 I = 0; bEqSp && I < SL.Num(); ++I) bEqSp = SL[I] == B.Sp.S[I];
			TestTrue(C.Label + TEXT(": edge stations == spline stations"), bEqSp);
		}

		for (int32 K = 0; K < 2; ++K)
		{
			const EStreetSide Side = K == 0 ? EStreetSide::Left : EStreetSide::Right;
			const int32 Sigma = StreetSideSigma(Side);
			const FString L = C.Label + (K == 0 ? TEXT(" left") : TEXT(" right"));
			const FStreetMeshBuilder& E = B.EdgeBuf(Side);
			const TArray<double> O0 = B.Sp.EdgeOffset(Side);
			const TArray<double> H0 = B.Sp.EdgeHeight(Side);
			const FStreetSideSpec& Spec = B.Sp.SideSpec[K];

			// rule 1: lateral overlap exactly 0.040 at every station
			const FStreetGeometry::FOverlap M = FStreetGeometry::MeasureLateralOverlap(Road, E, Sigma, Td);
			TestEqual(L + TEXT(": overlap measured at every station"), M.PerStation.Num(), B.Sp.Num());
			double WorstOv = 0;
			bool bAllFinite = true;
			for (double V : M.PerStation) { if (!FMath::IsFinite(V)) bAllFinite = false; else WorstOv = FMath::Max(WorstOv, FMath::Abs(V - Ov)); }
			TestTrue(L + TEXT(": overlap finite at every station"), bAllFinite);
			TestTrue(L + FString::Printf(TEXT(": |overlap - 0.040| max %.3e"), WorstOv), WorstOv < 1e-9);

			// rule 3: the skirt row sits strictly inside the kerb block; kerb row A reaches -tuck_in
			double HkMin = Spec.Hk.Num() ? Spec.Hk[0] : 0;
			for (double V : Spec.Hk) HkMin = FMath::Min(HkMin, V);
			TestTrue(L + TEXT(": 0 < ov < kw and -td < -sd < hk_min"), 0 < Ov && Ov < 0.125 && -Td < -Sd && -Sd < HkMin);
			{
				const FName KerbG(TEXT("kerb"));
				const TArray<int32> Kv = E.VerticesOfGroups(FString(), &KerbG);
				double OMin = 1e9;
				for (int32 V : Kv) OMin = FMath::Min(OMin, Sigma * E.VD[V] - FStreetSplineMath::Interp(E.VS[V], B.Sp.S, O0));
				TestTrue(L + TEXT(": kerb underside reaches -tuck_in"), FMath::Abs(OMin + Ti) < 1e-9);
			}

			// rule 4: exactly 2 coincident distinct positions per station in [o0, o0 + ov], 0 strictly inside
			{
				int32 Total = 0, Strict = 0;
				for (int32 I = 0; I < B.Sp.Num(); ++I)
				{
					FStreetMeshBuilder A, Bb;
					for (int32 V = 0; V < Road.V.Num(); ++V)
					{
						if (FMath::Abs(Road.VS[V] - B.Sp.S[I]) < 1e-9) { A.V.Add(Road.V[V]); A.VD.Add(Road.VD[V]); }
					}
					for (int32 V = 0; V < E.V.Num(); ++V)
					{
						if (FMath::Abs(E.VS[V] - B.Sp.S[I]) < 1e-9) { Bb.V.Add(E.V[V]); Bb.VD.Add(E.VD[V]); }
					}
					Total += FStreetGeometry::CoincidentXYPositions(A, Bb, O0[I], O0[I] + Ov, Sigma);
					Strict += FStreetGeometry::CoincidentXYPositions(A, Bb, O0[I] + 1e-6, O0[I] + Ov, Sigma);
				}
				TestEqual(L + TEXT(": 2 coincident positions per station"), Total, CoincPerStation * B.Sp.Num());
				TestEqual(L + TEXT(": none strictly inside the overlap band"), Strict, CoincStrict);
			}

			// rules 5 and 6: height coherence and (x, y) coincidence of the road-edge row with kerb row B
			{
				const FString MarkPrefix(TEXT("marking:"));
				const TArray<int32> Rv = Road.VerticesOfGroups(FString(), nullptr, &MarkPrefix);
				TArray<int32> EdgeRow;
				for (int32 V : Rv)
				{
					if (FMath::Abs(Sigma * Road.VD[V] - FStreetSplineMath::Interp(Road.VS[V], B.Sp.S, O0)) < 1e-9) EdgeRow.Add(V);
				}
				TestEqual(L + TEXT(": one road-edge vertex per station"), EdgeRow.Num(), B.Sp.Num());
				double WorstZ = 0;
				for (int32 V : EdgeRow)
				{
					const double Zr = FStreetSplineMath::Interp(Road.VS[V], B.Sp.S, B.Sp.ZRef) + FStreetSplineMath::Interp(Road.VS[V], B.Sp.S, H0);
					WorstZ = FMath::Max(WorstZ, FMath::Abs(Road.V[V].Z - Zr));
				}
				TestTrue(L + FString::Printf(TEXT(": road-edge height coherent (%.3e)"), WorstZ), WorstZ < 1e-9);

				const FName KerbG(TEXT("kerb"));
				const TArray<int32> Kv = E.VerticesOfGroups(FString(), &KerbG);
				TArray<int32> RowB;
				for (int32 V : Kv)
				{
					const double O = Sigma * E.VD[V] - FStreetSplineMath::Interp(E.VS[V], B.Sp.S, O0);
					const double H = E.VH[V] - (FStreetSplineMath::Interp(E.VS[V], B.Sp.S, H0) - Td);
					if (FMath::Abs(O) < 1e-9 && FMath::Abs(H) < 1e-9) RowB.Add(V);
				}
				TestTrue(L + TEXT(": kerb row B present at every station"), RowB.Num() >= B.Sp.Num());
				double WorstXY = 0, WorstZB = 0;
				for (int32 I = 0; I < B.Sp.Num(); ++I)
				{
					int32 Rr = INDEX_NONE, Bb = INDEX_NONE;
					for (int32 V : EdgeRow) { if (FMath::Abs(Road.VS[V] - B.Sp.S[I]) < 1e-9) { Rr = V; break; } }
					for (int32 V : RowB) { if (FMath::Abs(E.VS[V] - B.Sp.S[I]) < 1e-9) { Bb = V; break; } }
					if (Rr == INDEX_NONE || Bb == INDEX_NONE) { WorstXY = 1e9; continue; }
					WorstXY = FMath::Max(WorstXY, std::hypot(Road.V[Rr].X - E.V[Bb].X, Road.V[Rr].Y - E.V[Bb].Y));
					const double Zb = FStreetSplineMath::Interp(E.VS[Bb], B.Sp.S, B.Sp.ZRef) + FStreetSplineMath::Interp(E.VS[Bb], B.Sp.S, H0) - Td;
					WorstZB = FMath::Max(WorstZB, FMath::Abs(E.V[Bb].Z - Zb));
				}
				TestTrue(L + FString::Printf(TEXT(": kerb face (x, y) == road edge (%.3e)"), WorstXY), WorstXY < 1e-9);
				TestTrue(L + FString::Printf(TEXT(": kerb row B is td below (%.3e)"), WorstZB), WorstZB < 1e-9);
			}
		}
		TestEqual(C.Label + TEXT(": road validates clean: ") + FString::Join(Road.Validate(), TEXT(" | ")), Road.Validate().Num(), 0);
	}
	return true;
}
