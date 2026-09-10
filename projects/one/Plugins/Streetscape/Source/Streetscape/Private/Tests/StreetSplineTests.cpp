// Streetscape.Spline.* (UE_PLAN.md 2.13; STAGES.md stage 3). Numbers: Tools/blender/tests/fixtures/expected.json
// (the geometry track's frozen set, SCHEMA.md 9.3 / DESIGN.md 3.7-3.8) with the SCHEMA.md values as fallbacks when a
// key is absent (see StreetTestUtil.h FExpected).

#include "StreetTestUtil.h"
#include "HAL/PlatformMisc.h"

using namespace StreetTest;

namespace
{
constexpr EAutomationTestFlags kFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

double InterpS(const FStreetSamples& Sp, const TArray<double>& F, double S) { return FStreetSplineMath::Interp(S, Sp.S, F); }

bool CheckInvariants(FAutomationTestBase& T, const FString& Name, const FStreetSamples& Sp)
{
	bool bOk = true;
	const int32 N = Sp.Num();
	bOk &= T.TestEqual(Name + TEXT(": s[0]"), Sp.S[0], 0.0, 0.0);
	bOk &= T.TestEqual(Name + TEXT(": s[-1] == L"), Sp.S.Last(), Sp.LengthM, 0.0);
	for (int32 I = 0; I + 1 < N; ++I)
	{
		if (!(Sp.S[I + 1] > Sp.S[I])) { T.AddError(FString::Printf(TEXT("%s: s not strictly increasing at %d"), *Name, I)); bOk = false; break; }
	}
	for (double M : Sp.MandatorySet)
	{
		if (!Sp.S.Contains(M)) { T.AddError(FString::Printf(TEXT("%s: mandatory station %.17g missing"), *Name, M)); bOk = false; }
	}
	// adaptive-adaptive gaps within [min_step, step_m]; the final gap in [min_step, step_m + min_step)
	const double StepM = Sp.Sampling.StepM, MinStep = Sp.Sampling.MinStepM;
	for (int32 I = 0; I + 1 < N; ++I)
	{
		const double G = Sp.S[I + 1] - Sp.S[I];
		if (!Sp.Mandatory[I] && !Sp.Mandatory[I + 1])
		{
			const bool bLast = I + 2 == N;
			const double Hi = bLast ? StepM + MinStep : StepM + 1e-9;
			if (G < MinStep - 1e-9 || G > Hi) { T.AddError(FString::Printf(TEXT("%s: adaptive gap %.9f at s=%.6f outside [%g, %g]"), *Name, G, Sp.S[I], MinStep, Hi)); bOk = false; }
		}
	}
	return bOk;
}

/** Mean of the adaptive-to-adaptive gaps whose midpoint passes Pred (the expected.json "_measure" rule). */
double AdaptiveGapMean(const FStreetSamples& Sp, TFunctionRef<bool(double SMid, double XMid)> Pred, int32* OutCount = nullptr)
{
	double Sum = 0; int32 Nn = 0;
	for (int32 I = 0; I + 1 < Sp.Num(); ++I)
	{
		if (Sp.Mandatory[I] || Sp.Mandatory[I + 1]) continue;
		const double SMid = 0.5 * (Sp.S[I] + Sp.S[I + 1]);
		const double XMid = 0.5 * (Sp.XY[I].X + Sp.XY[I + 1].X);
		if (Pred(SMid, XMid)) { Sum += Sp.S[I + 1] - Sp.S[I]; ++Nn; }
	}
	if (OutCount) *OutCount = Nn;
	return Nn ? Sum / Nn : 0.0;
}
}

// ---------------------------------------------------------------------------------------------------------------
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetSplineStationsTest, "Streetscape.Spline.Stations", kFlags)
bool FStreetSplineStationsTest::RunTest(const FString& Parameters)
{
	const FExpected X;
	AddInfo(FString::Printf(TEXT("expected.json %s at %s"), X.bPresent ? TEXT("present") : TEXT("absent (SCHEMA.md 9.3 / DESIGN.md 3.7 numbers used)"), *ExpectedPath()));

	// -- straight_100 (SCHEMA.md 9.3, verbatim)
	{
		FStreetSiteDoc Doc; FStreetSamples Sp;
		const FStreetHeightfield Terrain = TerrainFor(TEXT("straight_100"));
		if (!BuildFixture(*this, TEXT("straight_100"), &Terrain, Doc, Sp)) return false;
		CheckInvariants(*this, TEXT("straight_100"), Sp);
		TestEqual(TEXT("straight_100: L"), Sp.LengthM, X.Num(TEXT("straight_100.L"), 100.0), 1e-9);
		TestEqual(TEXT("straight_100: N = 54 (51 adaptive + 3 drop-kerb stations)"), Sp.Num(), (int32)X.Num(TEXT("straight_100.N"), 54));
		double GMin = 1e9, GMax = 0; int32 AA = 0, OnGrid = 0; double AAOff = 0;
		const double AdaptiveGap = X.Num(TEXT("straight_100.adaptive_gap"), 2.0);
		for (int32 I = 0; I < Sp.Num(); ++I)
		{
			if (FMath::Abs(Sp.S[I] - FMath::RoundToDouble(Sp.S[I] / 2.0) * 2.0) < 1e-9) ++OnGrid;
			if (I + 1 == Sp.Num()) break;
			const double G = Sp.S[I + 1] - Sp.S[I];
			GMin = FMath::Min(GMin, G); GMax = FMath::Max(GMax, G);
			if (!Sp.Mandatory[I] && !Sp.Mandatory[I + 1]) { ++AA; AAOff = FMath::Max(AAOff, FMath::Abs(G - AdaptiveGap)); }
		}
		TestEqual(TEXT("straight_100: 51 stations on the 2 m grid (n_adaptive)"), OnGrid, (int32)X.Num(TEXT("straight_100.n_adaptive"), 51));
		TestEqual(TEXT("straight_100: gap min 0.17 (71.83 -> 72.0)"), GMin, X.Num(TEXT("straight_100.gap_min"), 0.17), 1e-9);
		TestEqual(TEXT("straight_100: gap max 2.0"), GMax, X.Num(TEXT("straight_100.gap_max"), 2.0), 1e-9);
		TestTrue(FString::Printf(TEXT("straight_100: every adaptive-adaptive gap is %g (%d gaps, max |gap-%g| = %.3g)"), AdaptiveGap, AA, AdaptiveGap, AAOff), AA > 0 && AAOff < 1e-9);
		// the three off-grid drop-kerb stations: s_m - ramp, s_m + length, s_m + length + ramp (70 itself is on the grid)
		const double DkS = 70.0, DkLen = 1.83, DkRamp = 0.915;
		for (double M : { DkS - DkRamp, DkS + DkLen, DkS + DkLen + DkRamp, DkS })
		{
			TestTrue(FString::Printf(TEXT("straight_100: station %.17g present bitwise"), M), Sp.S.Contains(M));
		}
		if (const TSharedPtr<FJsonValue> Off = X.Find(TEXT("straight_100.off_grid_stations")))
		{
			for (const TSharedPtr<FJsonValue>& V : Off->AsArray())
			{
				bool bFound = false;
				for (double S : Sp.S) { if (FMath::Abs(S - V->AsNumber()) < 1e-9) bFound = true; }
				TestTrue(FString::Printf(TEXT("straight_100: off-grid station %g present"), V->AsNumber()), bFound);
			}
		}
		TestEqual(TEXT("straight_100: mandatory set = 2 knots + 4 drop-kerb stations"), Sp.MandatorySet.Num(), 6);
		const double WTol = X.Num(TEXT("straight_100.w_tol"), 1e-9);
		TestEqual(TEXT("straight_100: w(40) = 6"), InterpS(Sp, Sp.Width, 40.0), X.Num(TEXT("straight_100.w.40"), 6.0), WTol);
		TestEqual(TEXT("straight_100: w(45) = 7"), InterpS(Sp, Sp.Width, 45.0), X.Num(TEXT("straight_100.w.45"), 7.0), WTol);
		TestEqual(TEXT("straight_100: w(50) = 8"), InterpS(Sp, Sp.Width, 50.0), X.Num(TEXT("straight_100.w.50"), 8.0), WTol);
		const TArray<double> Eo = Sp.EdgeOffset(EStreetSide::Left), Er = Sp.EdgeOffset(EStreetSide::Right);
		double WMax = 0; for (int32 I = 0; I < Sp.Num(); ++I) WMax = FMath::Max(WMax, Eo[I] + Er[I]);
		TestEqual(TEXT("straight_100: w_max = 8"), WMax, X.Num(TEXT("straight_100.w_max"), 8.0), WTol);
		TestEqual(TEXT("straight_100: z_raw nan count 0"), Sp.ZRawNanCount, 0);
		for (int32 I = 0; I < Sp.Num(); ++I) { if (FMath::Abs(Sp.ZRef[I] - 10.0) > 1e-9) { AddError(TEXT("straight_100: z_ref != 10 on flat terrain")); break; } }
		AddInfo(FString::Printf(TEXT("straight_100 stats: %s"), *FStreetscapeJson::ToText(Sp.StatsJson(), false, -1, -1)));
	}
	// -- straight_100 without the drop kerb: exactly the 51 adaptive stations
	{
		TSharedPtr<FJsonObject> O = Fixture(*this, TEXT("straight_100"));
		if (O.IsValid())
		{
			O->GetArrayField(TEXT("splines"))[0]->AsObject()->SetArrayField(TEXT("drop_kerbs"), {});
			FStreetSiteDoc Doc; FStreetSamples Sp;
			const FStreetHeightfield Terrain = TerrainFor(TEXT("straight_100"));
			if (BuildDoc(*this, O.ToSharedRef(), &Terrain, Doc, Sp))
			{
				TestEqual(TEXT("straight_100 without drop kerb: N = 51"), Sp.Num(), (int32)X.Num(TEXT("straight_100.N_without_drop_kerb"), 51));
			}
		}
	}
	// -- straight_100 with a ramped width override (expected.json width_override): 8 -> 5 over [55, 60], 5 on [60, 80], back over [80, 85]
	{
		TSharedPtr<FJsonObject> O = Fixture(*this, TEXT("straight_100"));
		if (O.IsValid())
		{
			const double S0 = X.Num(TEXT("straight_100.width_override.segment.s0_m"), 60.0), S1 = X.Num(TEXT("straight_100.width_override.segment.s1_m"), 80.0);
			const double Wv = X.Num(TEXT("straight_100.width_override.segment.width_m"), 5.0), Ramp = X.Num(TEXT("straight_100.width_override.segment.ramp_m"), 5.0);
			TSharedRef<FJsonObject> Seg = MakeShared<FJsonObject>();
			Seg->SetStringField(TEXT("id"), TEXT("narrow"));
			Seg->SetNumberField(TEXT("s0_m"), S0); Seg->SetNumberField(TEXT("s1_m"), S1); Seg->SetStringField(TEXT("side"), TEXT("centre")); Seg->SetNumberField(TEXT("ramp_m"), Ramp);
			TSharedRef<FJsonObject> Road = MakeShared<FJsonObject>();
			Road->SetNumberField(TEXT("width_m"), Wv);
			Seg->SetObjectField(TEXT("road"), Road);
			O->GetArrayField(TEXT("splines"))[0]->AsObject()->SetArrayField(TEXT("segments"), { MakeShared<FJsonValueObject>(Seg) });
			FStreetSiteDoc Doc; FStreetSamples Sp;
			const FStreetHeightfield Terrain = TerrainFor(TEXT("straight_100"));
			if (BuildDoc(*this, O.ToSharedRef(), &Terrain, Doc, Sp))
			{
				const TPair<double, double> Checks[] = { { 55.0, 8.0 }, { 57.5, 6.5 }, { 60.0, 5.0 }, { 70.0, 5.0 }, { 80.0, 5.0 }, { 85.0, 8.0 } };
				for (const TPair<double, double>& C : Checks)
				{
					const FString Key = FString::Printf(TEXT("straight_100.width_override.w.%s"), *FStreetscapeJson::FormatNumber(C.Key));
					TestEqual(FString::Printf(TEXT("width override: w(%g)"), C.Key), InterpS(Sp, Sp.Width, C.Key), X.Num(Key, C.Value), 1e-9);
				}
				for (double M : { S0 - Ramp, S0, S1, S1 + Ramp }) TestTrue(FString::Printf(TEXT("width override: station %g mandatory"), M), Sp.S.Contains(M));
			}
		}
	}

	// -- sine_5_50 / curve_R20_200 / rail_R300_600 (expected.json "_measure": adaptive-to-adaptive gaps)
	{
		FStreetSiteDoc Doc; FStreetSamples Sp;
		const FStreetHeightfield Terrain = TerrainFor(TEXT("sine_5_50"));
		if (BuildFixture(*this, TEXT("sine_5_50"), &Terrain, Doc, Sp))
		{
			CheckInvariants(*this, TEXT("sine_5_50"), Sp);
			TestEqual(TEXT("sine_5_50: L = 109.2 +- 0.1"), Sp.LengthM, X.Num(TEXT("sine_5_50.L"), 109.2), X.Num(TEXT("sine_5_50.L_tol"), 0.1));
			const int32 WantN = (int32)X.Num(TEXT("sine_5_50.N"), 119), TolN = (int32)X.Num(TEXT("sine_5_50.N_tol"), 3);
			TestTrue(FString::Printf(TEXT("sine_5_50: N = %d (expected %d +- %d)"), Sp.Num(), WantN, TolN), FMath::Abs(Sp.Num() - WantN) <= TolN);
			int32 Nc = 0, Ni = 0;
			const double Crest = AdaptiveGapMean(Sp, [](double, double Xm) { const double M = FMath::Fmod(Xm, 25.0); return FMath::Abs(M - 12.5) < 3.0; }, &Nc);
			const double Infl = AdaptiveGapMean(Sp, [](double, double Xm) { const double M = FMath::Fmod(Xm, 25.0); return FMath::Min(M, 25.0 - M) < 3.0; }, &Ni);
			AddInfo(FString::Printf(TEXT("sine_5_50: N = %d, L = %.6f, crest spacing %.4f (%d gaps), inflection spacing %.4f (%d gaps), ratio %.3f"), Sp.Num(), Sp.LengthM, Crest, Nc, Infl, Ni, Crest > 0 ? Infl / Crest : 0));
			TestTrue(FString::Printf(TEXT("sine_5_50: crest spacing %.4f <= 0.85"), Crest), Nc > 0 && Crest <= X.Num(TEXT("sine_5_50.crest_spacing_max"), 0.85));
			TestTrue(FString::Printf(TEXT("sine_5_50: inflection spacing %.4f >= 1.5"), Infl), Ni > 0 && Infl >= X.Num(TEXT("sine_5_50.inflection_spacing_min"), 1.5));
			TestTrue(FString::Printf(TEXT("sine_5_50: ratio %.3f >= 1.8"), Infl / Crest), Crest > 0 && Infl / Crest >= X.Num(TEXT("sine_5_50.ratio_min"), 1.8));
		}
	}
	{
		FStreetSiteDoc Doc; FStreetSamples Sp;
		const FStreetHeightfield Terrain = TerrainFor(TEXT("curve_R20_200"));
		if (BuildFixture(*this, TEXT("curve_R20_200"), &Terrain, Doc, Sp))
		{
			CheckInvariants(*this, TEXT("curve_R20_200"), Sp);
			TestEqual(TEXT("curve_R20_200: L = 200 +- 0.05"), Sp.LengthM, X.Num(TEXT("curve_R20_200.L"), 200.0), X.Num(TEXT("curve_R20_200.L_tol"), 0.05));
			const int32 WantN = (int32)X.Num(TEXT("curve_R20_200.N"), 125), TolN = (int32)X.Num(TEXT("curve_R20_200.N_tol"), 2);
			TestTrue(FString::Printf(TEXT("curve_R20_200: N = %d (expected %d +- %d)"), Sp.Num(), WantN, TolN), FMath::Abs(Sp.Num() - WantN) <= TolN);
			int32 Na = 0, Ns = 0;
			const double Arc = AdaptiveGapMean(Sp, [](double Sm, double) { return Sm > 62.0 && Sm < 89.0; }, &Na);
			const double St = AdaptiveGapMean(Sp, [](double Sm, double) { return Sm < 58.0 || Sm > 94.0; }, &Ns);
			AddInfo(FString::Printf(TEXT("curve_R20_200: N = %d, arc spacing %.4f (%d gaps), straights %.4f (%d gaps), ratio %.3f"), Sp.Num(), Arc, Na, St, Ns, Arc > 0 ? St / Arc : 0));
			TestEqual(TEXT("curve_R20_200: arc spacing 1.00 +- 0.03 (R 20, gain 20)"), Arc, X.Num(TEXT("curve_R20_200.arc_spacing"), 1.0), X.Num(TEXT("curve_R20_200.arc_tol"), 0.03));
			TestEqual(TEXT("curve_R20_200: straights 1.99 +- 0.02"), St, X.Num(TEXT("curve_R20_200.straight_spacing"), 1.99), X.Num(TEXT("curve_R20_200.straight_tol"), 0.02));
			TestEqual(TEXT("curve_R20_200: ratio 2.0 +- 0.1"), Arc > 0 ? St / Arc : 0, X.Num(TEXT("curve_R20_200.ratio"), 2.0), X.Num(TEXT("curve_R20_200.ratio_tol"), 0.1));
		}
	}
	{
		FStreetSiteDoc Doc; FStreetSamples Sp;
		const FStreetHeightfield Terrain = TerrainFor(TEXT("rail_R300_600"));
		if (BuildFixture(*this, TEXT("rail_R300_600"), &Terrain, Doc, Sp))
		{
			CheckInvariants(*this, TEXT("rail_R300_600"), Sp);
			TestTrue(TEXT("rail_R300_600: kind rail"), Sp.bHasKind && Sp.Kind == EStreetRoadKind::Rail);
			TestEqual(TEXT("rail_R300_600: L = 600 +- 0.05"), Sp.LengthM, X.Num(TEXT("rail_R300_600.L"), 600.0), X.Num(TEXT("rail_R300_600.L_tol"), 0.05));
			const int32 WantN = (int32)X.Num(TEXT("rail_R300_600.N"), 653), TolN = (int32)X.Num(TEXT("rail_R300_600.N_tol"), 3);
			TestTrue(FString::Printf(TEXT("rail_R300_600: N = %d (expected %d +- %d)"), Sp.Num(), WantN, TolN), FMath::Abs(Sp.Num() - WantN) <= TolN);
			TestEqual(TEXT("rail_R300_600: sampling step 1.0"), Sp.Sampling.StepM, X.Num(TEXT("rail_R300_600.sampling.step_m"), 1.0), 0.0);
			TestEqual(TEXT("rail_R300_600: sampling min step 0.25"), Sp.Sampling.MinStepM, X.Num(TEXT("rail_R300_600.sampling.min_step_m"), 0.25), 0.0);
			TestEqual(TEXT("rail_R300_600: sampling gain 60"), Sp.Sampling.CurvatureGain, X.Num(TEXT("rail_R300_600.sampling.curvature_gain"), 60.0), 0.0);
			TestEqual(TEXT("rail_R300_600: sampling window 40"), Sp.Sampling.SmoothingWindowM, X.Num(TEXT("rail_R300_600.sampling.smoothing_window_m"), 40.0), 0.0);
			TestEqual(TEXT("rail_R300_600: sampling passes 2"), Sp.Sampling.SmoothingPasses, (int32)X.Num(TEXT("rail_R300_600.sampling.smoothing_passes"), 2));
			TestEqual(TEXT("rail_R300_600: sampling bank max 6"), Sp.Sampling.BankMaxDeg, X.Num(TEXT("rail_R300_600.sampling.bank_max_deg"), 6.0), 0.0);
			TestEqual(TEXT("rail_R300_600: z_raw nan count 0"), Sp.ZRawNanCount, (int32)X.Num(TEXT("rail_R300_600.z_raw_nan_count"), 0));
			int32 Ns = 0, Nb = 0;
			const double St = AdaptiveGapMean(Sp, [](double Sm, double) { return Sm < 190.0; }, &Ns);
			const double Bend = AdaptiveGapMean(Sp, [](double Sm, double) { return Sm > 215.0 && Sm < 385.0; }, &Nb);
			AddInfo(FString::Printf(TEXT("rail_R300_600: N = %d, L = %.4f, straight spacing %.4f (%d gaps), bend %.4f (%d gaps)"), Sp.Num(), Sp.LengthM, St, Ns, Bend, Nb));
			TestEqual(TEXT("rail_R300_600: straight 1.00 +- 0.02"), St, X.Num(TEXT("rail_R300_600.straight_spacing"), 1.0), X.Num(TEXT("rail_R300_600.straight_tol"), 0.02));
			TestEqual(TEXT("rail_R300_600: bend 0.83 +- 0.03 (R 300, gain 60)"), Bend, X.Num(TEXT("rail_R300_600.bend_spacing"), 0.83), X.Num(TEXT("rail_R300_600.bend_tol"), 0.03));
		}
	}
	return true;
}

// ---------------------------------------------------------------------------------------------------------------
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetSplineSmoothingTest, "Streetscape.Spline.Smoothing", kFlags)
bool FStreetSplineSmoothingTest::RunTest(const FString& Parameters)
{
	const FExpected X;
	// 2 % grade + 0.1 sqrt(3) unit_noise(i, 7) on 51 stations at 2 m (SCHEMA.md 9.3; the sequence is portable bit for bit)
	TArray<double> S, Z, Noise;
	for (int32 I = 0; I <= 50; ++I)
	{
		S.Add(2.0 * I);
		Noise.Add(0.1 * std::sqrt(3.0) * FStreetNoise::UnitNoise((uint32)I, 7));
		Z.Add(0.02 * S.Last() + Noise.Last());
	}
	struct FRes { double Factor, MaxErr, End0, EndN, Grade; };
	auto Measure = [&](double W, int32 Passes)
	{
		const TArray<double> Zs = FStreetSplineMath::MovingAverageArcLength(S, Z, W, Passes);
		double SumRaw = 0, SumErr = 0, MaxErr = 0; int32 N = 0;
		double Sx = 0, Sy = 0, Sxx = 0, Sxy = 0;
		for (int32 I = 0; I < S.Num(); ++I)
		{
			if (S[I] < 10.0 || S[I] > 90.0) continue;
			const double Err = Zs[I] - 0.02 * S[I];
			SumRaw += Noise[I] * Noise[I]; SumErr += Err * Err; MaxErr = FMath::Max(MaxErr, FMath::Abs(Err)); ++N;
			Sx += S[I]; Sy += Zs[I]; Sxx += S[I] * S[I]; Sxy += S[I] * Zs[I];
		}
		const double RmsRaw = std::sqrt(SumRaw / N), RmsErr = std::sqrt(SumErr / N);
		const double Grade = (N * Sxy - Sx * Sy) / (N * Sxx - Sx * Sx);   // closed-form least squares, no LAPACK
		return FRes{ RmsRaw / RmsErr, MaxErr, Zs[0] - Z[0], Zs.Last() - Z.Last(), Grade };
	};
	const FRes W20 = Measure(20.0, 1), W10 = Measure(10.0, 1), W20p2 = Measure(20.0, 2);
	AddInfo(FString::Printf(TEXT("W=20: factor %.4f max|err| %.4f grade %.5f; W=10: factor %.4f; two passes: factor %.4f (expected.json measured: %.3f / %.3f / %.3f)"),
		W20.Factor, W20.MaxErr, W20.Grade, W10.Factor, W20p2.Factor, X.Num(TEXT("smoothing.W20.factor_measured"), 0), X.Num(TEXT("smoothing.W10.factor_measured"), 0), X.Num(TEXT("smoothing.W20_2pass.factor_measured"), 0)));
	TestTrue(FString::Printf(TEXT("W=20 interior RMS factor >= 2.5 (got %.3f)"), W20.Factor), W20.Factor >= X.Num(TEXT("smoothing.W20.factor_min"), 2.5));
	TestTrue(FString::Printf(TEXT("W=20 interior max|err| <= 0.08 (got %.4f)"), W20.MaxErr), W20.MaxErr <= X.Num(TEXT("smoothing.W20.max_err_max"), 0.08));
	TestEqual(TEXT("W=20 start pinned"), W20.End0, 0.0, 1e-12);
	TestEqual(TEXT("W=20 end pinned"), W20.EndN, 0.0, 1e-12);
	TestEqual(TEXT("W=20 grade 0.0196 +- 0.002"), W20.Grade, X.Num(TEXT("smoothing.W20.grade"), 0.0196), X.Num(TEXT("smoothing.W20.grade_tol"), 0.002));
	TestTrue(FString::Printf(TEXT("W=10 factor >= 1.7 (got %.3f)"), W10.Factor), W10.Factor >= X.Num(TEXT("smoothing.W10.factor_min"), 1.7));
	TestTrue(FString::Printf(TEXT("W=20 two passes factor >= 3.0 (got %.3f)"), W20p2.Factor), W20p2.Factor >= X.Num(TEXT("smoothing.W20_2pass.factor_min"), 3.0));
	// the numpy prototype's measured factors, to 1e-3 (same sequence, same arithmetic)
	if (X.Has(TEXT("smoothing.W20.factor_measured")))
	{
		TestEqual(TEXT("W=20 factor equals the numpy measurement"), W20.Factor, X.Num(TEXT("smoothing.W20.factor_measured"), 0), 1e-3);
		TestEqual(TEXT("W=10 factor equals the numpy measurement"), W10.Factor, X.Num(TEXT("smoothing.W10.factor_measured"), 0), 1e-3);
		TestEqual(TEXT("two-pass factor equals the numpy measurement"), W20p2.Factor, X.Num(TEXT("smoothing.W20_2pass.factor_measured"), 0), 1e-3);
		TestEqual(TEXT("W=20 max err equals the numpy measurement"), W20.MaxErr, X.Num(TEXT("smoothing.W20.max_err_measured"), 0), 1e-4);
	}
	// 8 m ripple 0.1 sin(2 pi s / 8): RMS 0.07 over the 51 stations -> <= 0.010 after W = 20
	{
		TArray<double> Zr;
		for (double Sv : S) Zr.Add(0.02 * Sv + 0.1 * std::sin(2.0 * UE_DOUBLE_PI * Sv / 8.0));
		const TArray<double> Zs = FStreetSplineMath::MovingAverageArcLength(S, Zr, 20.0, 1);
		double BeforeAll = 0, AfterAll = 0, AfterInner = 0; int32 Ninner = 0;
		for (int32 I = 0; I < S.Num(); ++I)
		{
			const double R = Zr[I] - 0.02 * S[I], E = Zs[I] - 0.02 * S[I];
			BeforeAll += R * R; AfterAll += E * E;
			if (S[I] >= 10.0 && S[I] <= 90.0) { AfterInner += E * E; ++Ninner; }
		}
		BeforeAll = std::sqrt(BeforeAll / S.Num()); AfterAll = std::sqrt(AfterAll / S.Num()); AfterInner = std::sqrt(AfterInner / Ninner);
		AddInfo(FString::Printf(TEXT("8 m ripple RMS %.4f -> %.4f (all stations), %.4f (interior)"), BeforeAll, AfterAll, AfterInner));
		TestEqual(TEXT("8 m ripple RMS before = 0.07"), BeforeAll, X.Num(TEXT("smoothing.ripple_8m.rms_raw"), 0.07), X.Num(TEXT("smoothing.ripple_8m.rms_raw_tol"), 0.0005));
		// the window shrinks to zero at the ends (SCHEMA.md 3.5), so the end stations keep their ripple: the frozen 0.0072 is the interior measure
		TestTrue(FString::Printf(TEXT("8 m ripple interior RMS <= 0.010 after W=20 (got %.4f)"), AfterInner), AfterInner <= X.Num(TEXT("smoothing.ripple_8m.rms_max"), 0.010));
		if (X.Has(TEXT("smoothing.ripple_8m.rms_measured"))) TestEqual(TEXT("8 m ripple interior RMS equals the numpy measurement"), AfterInner, X.Num(TEXT("smoothing.ripple_8m.rms_measured"), 0.0072), 1e-4);
	}
	// the same smoothing through the whole build on the grade-noise terrain (heights sampled, filled, averaged)
	{
		FStreetSiteDoc Doc; FStreetSamples Sp;
		const FStreetHeightfield Terrain = GradeNoiseTerrain();
		if (BuildFixture(*this, TEXT("straight_100"), &Terrain, Doc, Sp))
		{
			double SumRaw = 0, SumErr = 0; int32 N = 0;
			for (int32 I = 0; I < Sp.Num(); ++I)
			{
				if (Sp.S[I] < 10.0 || Sp.S[I] > 90.0) continue;
				const double Raw = Sp.ZRaw[I] - 0.02 * Sp.S[I], Err = Sp.ZRef[I] - 0.02 * Sp.S[I];
				SumRaw += Raw * Raw; SumErr += Err * Err; ++N;
			}
			const double F = std::sqrt(SumRaw / N) / std::sqrt(SumErr / N);
			AddInfo(FString::Printf(TEXT("grade-noise terrain through Build: %d stations, interior factor %.3f, ends pinned to raw: %.3g / %.3g"), Sp.Num(), F, Sp.ZRef[0] - Sp.ZRaw[0], Sp.ZRef.Last() - Sp.ZRaw.Last()));
			TestTrue(TEXT("terrain build: ends pinned to the raw terrain"), FMath::Abs(Sp.ZRef[0] - Sp.ZRaw[0]) < 1e-12 && FMath::Abs(Sp.ZRef.Last() - Sp.ZRaw.Last()) < 1e-12);
			TestTrue(TEXT("terrain build: smoothing reduces the noise (factor > 1.5)"), F > 1.5);
			TestEqual(TEXT("terrain build: no nan"), Sp.ZRawNanCount, 0);
		}
	}
	return true;
}

// ---------------------------------------------------------------------------------------------------------------
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetSplineBankTest, "Streetscape.Spline.Bank", kFlags)
bool FStreetSplineBankTest::RunTest(const FString& Parameters)
{
	const FExpected X;
	// cross slope 0.1 (5.71 deg) -> clamped to 4.00 deg
	{
		FStreetSiteDoc Doc; FStreetSamples Sp;
		const FStreetHeightfield Terrain = CrossSlopeTerrain(0.1);
		if (!BuildFixture(*this, TEXT("straight_100"), &Terrain, Doc, Sp)) return false;
		const int32 Mid = Sp.Num() / 2;
		TestEqual(TEXT("bank raw = atan(0.1) = 5.71 deg"), Sp.BankRaw[Mid], X.Num(TEXT("bank.raw_deg"), 5.71), X.Num(TEXT("bank.raw_tol"), 0.02));
		TestEqual(TEXT("bank raw full precision (atan2 in degrees)"), Sp.BankRaw[Mid], std::atan(0.1) * 180.0 / UE_DOUBLE_PI, 1e-6);
		double BMin = 1e9, BMax = -1e9;
		for (double B : Sp.BankDeg) { BMin = FMath::Min(BMin, B); BMax = FMath::Max(BMax, B); }
		const double Clamp = X.Num(TEXT("bank.clamped_deg"), 4.0);
		TestEqual(TEXT("bank clamped to +4.00 (min)"), BMin, Clamp, 1e-9);
		TestEqual(TEXT("bank clamped to +4.00 (max)"), BMax, Clamp, 1e-9);
		TestEqual(TEXT("bank_terrain clamp"), Sp.BankTerrain[Mid], Clamp, 1e-9);
	}
	// roll_deg 2 on every waypoint: mask 1 everywhere, bank = 2 everywhere (the terrain's 5.71 deg is ignored)
	{
		TSharedPtr<FJsonObject> O = Fixture(*this, TEXT("straight_100"));
		if (!O.IsValid()) return false;
		TArray<TSharedPtr<FJsonValue>> Pts = O->GetArrayField(TEXT("splines"))[0]->AsObject()->GetArrayField(TEXT("points"));
		for (const TSharedPtr<FJsonValue>& P : Pts) P->AsObject()->SetNumberField(TEXT("roll_deg"), X.Num(TEXT("bank.roll_all_deg"), 2.0));
		O->GetArrayField(TEXT("splines"))[0]->AsObject()->SetArrayField(TEXT("points"), Pts);
		FStreetSiteDoc Doc; FStreetSamples Sp;
		const FStreetHeightfield Terrain = CrossSlopeTerrain(0.1);
		if (BuildDoc(*this, O.ToSharedRef(), &Terrain, Doc, Sp))
		{
			double Off = 0, MaskOff = 0;
			for (int32 I = 0; I < Sp.Num(); ++I) { Off = FMath::Max(Off, FMath::Abs(Sp.BankDeg[I] - X.Num(TEXT("bank.roll_all_deg"), 2.0))); MaskOff = FMath::Max(MaskOff, FMath::Abs(Sp.RollMask[I] - 1.0)); }
			TestTrue(FString::Printf(TEXT("roll on all points: bank = 2 everywhere (max |diff| %.3g)"), Off), Off < 1e-9);
			TestTrue(TEXT("roll on all points: mask = 1 everywhere"), MaskOff < 1e-12);
		}
	}
	// roll_deg 2 at the third waypoint only (s = 50): mask 1 there, linear to 0 at the neighbours
	{
		TSharedPtr<FJsonObject> O = Fixture(*this, TEXT("straight_100"));
		if (!O.IsValid()) return false;
		TArray<TSharedPtr<FJsonValue>> Pts = O->GetArrayField(TEXT("splines"))[0]->AsObject()->GetArrayField(TEXT("points"));
		Pts[2]->AsObject()->SetNumberField(TEXT("roll_deg"), 2.0);
		O->GetArrayField(TEXT("splines"))[0]->AsObject()->SetArrayField(TEXT("points"), Pts);
		FStreetSiteDoc Doc; FStreetSamples Sp;
		const FStreetHeightfield Terrain = CrossSlopeTerrain(0.1);
		if (!BuildDoc(*this, O.ToSharedRef(), &Terrain, Doc, Sp)) return false;
		auto At = [&](double S) { return FStreetSplineMath::Interp(S, Sp.S, Sp.BankDeg); };
		auto MaskAt = [&](double S) { return FStreetSplineMath::Interp(S, Sp.S, Sp.RollMask); };
		TestEqual(TEXT("roll mask 1 at the knot"), MaskAt(50.0), 1.0, 1e-12);
		TestEqual(TEXT("roll mask 0.5 halfway to the previous knot (40 -> 50)"), MaskAt(45.0), 0.5, 1e-12);
		TestEqual(TEXT("roll mask 0.5 halfway to the next knot (50 -> 100)"), MaskAt(75.0), 0.5, 1e-12);
		TestEqual(TEXT("bank = roll 2.0 at the knot"), At(50.0), 2.0, 1e-9);
		TestEqual(TEXT("bank = blend 0.5*4 + 0.5*2 = 3.0 at s=45 (rate limit inactive: 0.2 deg/m)"), At(45.0), 3.0, 1e-9);
		TestEqual(TEXT("bank = 4.0 where the mask is 0 (s = 20)"), At(20.0), 4.0, 1e-9);
		double MaxRate = 0;
		for (int32 I = 0; I + 1 < Sp.Num(); ++I) MaxRate = FMath::Max(MaxRate, FMath::Abs(Sp.BankDeg[I + 1] - Sp.BankDeg[I]) / (Sp.S[I + 1] - Sp.S[I]));
		const double Rate = X.Num(TEXT("bank.rate_limit_deg_per_m"), 0.25);
		TestTrue(FString::Printf(TEXT("bank rate <= %g deg/m everywhere (got %.4f)"), Rate, MaxRate), MaxRate <= Rate + 1e-9);
	}
	// the rate limit itself on a step: 0 -> 10 deg at s = 20 with 2 m stations: forward pass 0.5 deg per station from
	// s = 20 (0.5, 1.0, ...), backward pass leaves the ramp; 4 deg develop over 16 m
	{
		TArray<double> S, Beta;
		for (int32 I = 0; I <= 20; ++I) { S.Add(2.0 * I); Beta.Add(S.Last() >= 20.0 ? 10.0 : 0.0); }
		const TArray<double> B = FStreetSplineMath::RateLimitBank(Beta, S, 0.25);
		double MaxRate = 0;
		for (int32 I = 0; I + 1 < S.Num(); ++I) MaxRate = FMath::Max(MaxRate, FMath::Abs(B[I + 1] - B[I]) / (S[I + 1] - S[I]));
		TestTrue(FString::Printf(TEXT("RateLimitBank: |d beta/ds| <= 0.25 (got %.4f)"), MaxRate), MaxRate <= 0.25 + 1e-12);
		TestEqual(TEXT("RateLimitBank: s=18 stays 0 (backward pass)"), B[9], 0.0, 1e-12);
		TestEqual(TEXT("RateLimitBank: s=20 rises 0.5"), B[10], 0.5, 1e-12);
		TestEqual(TEXT("RateLimitBank: s=22 rises 1.0"), B[11], 1.0, 1e-12);
		TestEqual(TEXT("RateLimitBank: 4 deg develop over 16 m (s=36 - s=20)"), B[18] - B[10], 4.0, 1e-12);
		TestEqual(TEXT("RateLimitBank: the plateau is reached at s=40 (10 deg)"), B[20], 5.5, 1e-12);
	}
	return true;
}

// ---------------------------------------------------------------------------------------------------------------
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetSplineFramesTest, "Streetscape.Spline.Frames", kFlags)
bool FStreetSplineFramesTest::RunTest(const FString& Parameters)
{
	const FExpected X;
	const double Tol = X.Num(TEXT("bank.frames_tol"), 1e-12);
	FStreetSiteDoc Doc; FStreetSamples Sp;
	const FStreetHeightfield Terrain = CrossSlopeTerrain(0.1);
	if (!BuildFixture(*this, TEXT("straight_100"), &Terrain, Doc, Sp)) return false;
	const FStreetFrames& F = Sp.Frames;
	double MaxTN = 0, MaxBZ = 0, MaxNZ = 0, MaxUnit = 0;
	for (int32 I = 0; I < F.Num(); ++I)
	{
		const double Beta = Sp.BankDeg[I] * (UE_DOUBLE_PI / 180.0);
		MaxTN = FMath::Max(MaxTN, FMath::Abs(F.Th[I].X * F.N[I].X + F.Th[I].Y * F.N[I].Y + F.Th[I].Z * F.N[I].Z));
		MaxBZ = FMath::Max(MaxBZ, FMath::Abs(F.B[I].Z - std::cos(Beta)));
		MaxNZ = FMath::Max(MaxNZ, FMath::Abs(F.N[I].Z - std::sin(Beta)));
		MaxUnit = FMath::Max(MaxUnit, FMath::Abs(F.N[I].Length() - 1.0));
		MaxUnit = FMath::Max(MaxUnit, FMath::Abs(F.B[I].Length() - 1.0));
	}
	TestTrue(FString::Printf(TEXT("t_h . n = 0 (max %.3g)"), MaxTN), MaxTN < Tol);
	TestTrue(FString::Printf(TEXT("b . Z = cos(beta) (max err %.3g)"), MaxBZ), MaxBZ < Tol);
	TestTrue(FString::Printf(TEXT("n . Z = sin(beta) (max err %.3g)"), MaxNZ), MaxNZ < Tol);
	TestTrue(FString::Printf(TEXT("n, b unit (max err %.3g)"), MaxUnit), MaxUnit < Tol);
	TestEqual(TEXT("bank is 4 deg on this terrain"), Sp.BankDeg[Sp.Num() / 2], 4.0, 1e-9);
	// left kerb line of synthetic_straight: JSON y > 0, UE Y < 0
	const TArray<double> Eo = Sp.EdgeOffset(EStreetSide::Left);
	const TArray<double> Eh = Sp.EdgeHeight(EStreetSide::Left);
	bool bAllPos = true, bAllNeg = true;
	for (int32 I = 0; I < F.Num(); ++I)
	{
		const FVector3d Kerb = F.P[I] + Eo[I] * F.N[I] + Eh[I] * F.B[I];
		const FVector UE = FStreetscapeJson::ToUE(Kerb);
		bAllPos &= Kerb.Y > 0.0;
		bAllNeg &= UE.Y < 0.0;
	}
	TestTrue(TEXT("left kerb has JSON y > 0 at every station"), bAllPos);
	TestTrue(TEXT("left kerb has UE Y < 0 at every station"), bAllNeg);
	TestEqual(TEXT("edge_offset(left) at s=45 = 3.5"), FStreetSplineMath::Interp(45.0, Sp.S, Eo), 3.5, 1e-9);
	// Frames.At / Insert: interpolated frames keep t_h . n = 0 and existing stations exact
	{
		TArray<double> Extra = { 1.0, 3.0, 40.0 };   // 40 is an existing station
		const FStreetFrames G = F.Insert(Extra);
		TestEqual(TEXT("Insert adds only the new stations"), G.Num(), F.Num() + 2);
		double MaxTN2 = 0;
		for (int32 I = 0; I < G.Num(); ++I) MaxTN2 = FMath::Max(MaxTN2, FMath::Abs(G.Th[I].X * G.N[I].X + G.Th[I].Y * G.N[I].Y + G.Th[I].Z * G.N[I].Z));
		TestTrue(TEXT("Insert keeps t_h . n = 0"), MaxTN2 < Tol);
		const FStreetFrames H = F.At({ 3.0 });
		TestEqual(TEXT("At(3).p.x = 3"), H.P[0].X, 3.0, 1e-9);
	}
	// the frame conversion for points
	{
		const FVector UE = FStreetscapeJson::ToUE(FVector3d(1.0, 2.0, 3.0));
		TestEqual(TEXT("ToUE x"), UE.X, 100.0, 1e-9); TestEqual(TEXT("ToUE y"), UE.Y, -200.0, 1e-9); TestEqual(TEXT("ToUE z"), UE.Z, 300.0, 1e-9);
		const FVector3d Back = FStreetscapeJson::ToJson(UE);
		TestEqual(TEXT("ToJson round trip"), Back.Y, 2.0, 1e-12);
		TestEqual(TEXT("yaw = bearing - 90"), FStreetscapeJson::YawFromBearingDeg(131.0), 41.0, 1e-12);
	}
	return true;
}

// ---------------------------------------------------------------------------------------------------------------
// The real stretch (schema/examples/test_stretch.json) on the adapter heightfield (data/thanet/out/unreal/landscape),
// expected.json "test_stretch": L 171.4, n_samples 116, z_ref(10/100/160), no nan, steps, bank, w_max. Skipped with an
// info line when the adapter output is not on this machine.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetSplineTestStretchTest, "Streetscape.Spline.TestStretch", kFlags)
bool FStreetSplineTestStretchTest::RunTest(const FString& Parameters)
{
	const FExpected X;
	const FString Dir = FPaths::ConvertRelativePathToFull(ProjectDir() / TEXT("../../data/thanet/out/unreal/landscape"));
	if (!FPaths::FileExists(Dir / TEXT("landscape_manifest.json")))
	{
		AddInfo(TEXT("no adapter landscape output at ") + Dir + TEXT(" - test stretch skipped"));
		return true;
	}
	FStreetHeightfield H;
	FText Err;
	if (!H.LoadLandscapeDir(Dir, &Err)) { AddError(Err.ToString()); return false; }
	FStreetSiteDoc Doc;
	if (!LoadDoc(*this, ExamplesDir() / TEXT("test_stretch.json"), Doc)) return false;
	FStreetHeightfieldSource Src(H);
	Src.SetDocumentOrigin(Doc.Origin.E, Doc.Origin.N);
	FStreetSamples Sp;
	FString BuildErr;
	if (!FStreetSplineMath::Build(Doc.Splines[0], Doc.Profiles, &Src, Sp, &BuildErr)) { AddError(BuildErr); return false; }
	AddInfo(FString::Printf(TEXT("test_stretch on %s: %s"), *H.Describe(), *FStreetscapeJson::ToText(Sp.StatsJson(), false, -1, -1)));
	TestEqual(TEXT("test_stretch: L = 171.4 +- 0.05"), Sp.LengthM, X.Num(TEXT("test_stretch.L"), 171.4), X.Num(TEXT("test_stretch.L_tol"), 0.05));
	TestEqual(TEXT("test_stretch: n_samples = 116"), Sp.Num(), (int32)X.Num(TEXT("test_stretch.n_samples"), 116));
	TestEqual(TEXT("test_stretch: z_raw nan count 0"), Sp.ZRawNanCount, (int32)X.Num(TEXT("test_stretch.z_raw_nan_count"), 0));
	const double ZTol = X.Num(TEXT("test_stretch.z_ref_tol"), 0.02);
	for (const TPair<double, double>& C : { TPair<double, double>(10.0, 20.47), TPair<double, double>(100.0, 19.35), TPair<double, double>(160.0, 18.24) })
	{
		const double Z = FStreetSplineMath::Interp(C.Key, Sp.S, Sp.ZRef);
		TestEqual(FString::Printf(TEXT("test_stretch: z_ref(%g) = %.2f +- %.2f (got %.4f)"), C.Key, C.Value, ZTol, Z), Z, X.Num(FString::Printf(TEXT("test_stretch.z_ref.%d"), (int32)C.Key), C.Value), ZTol);
	}
	double StepMin = 1e9, StepMax = 0, BankAbs = 0, WMax = 0;
	const TArray<double> Eo = Sp.EdgeOffset(EStreetSide::Left), Er = Sp.EdgeOffset(EStreetSide::Right);
	for (int32 I = 0; I < Sp.Num(); ++I)
	{
		if (I + 1 < Sp.Num()) { const double G = Sp.S[I + 1] - Sp.S[I]; StepMin = FMath::Min(StepMin, G); StepMax = FMath::Max(StepMax, G); }
		BankAbs = FMath::Max(BankAbs, FMath::Abs(Sp.BankDeg[I]));
		WMax = FMath::Max(WMax, Eo[I] + Er[I]);
	}
	TestTrue(FString::Printf(TEXT("test_stretch: step_min %.4f >= 0.125"), StepMin), StepMin >= X.Num(TEXT("test_stretch.step_min_floor"), 0.125) - 1e-9);
	TestTrue(FString::Printf(TEXT("test_stretch: step_max %.4f <= 2.0"), StepMax), StepMax <= X.Num(TEXT("test_stretch.step_max"), 2.0) + 1e-9);
	TestTrue(FString::Printf(TEXT("test_stretch: |bank| %.4f <= 4.0"), BankAbs), BankAbs <= X.Num(TEXT("test_stretch.bank_abs_max"), 4.0) + 1e-9);
	TestEqual(TEXT("test_stretch: w_max = 7.0"), WMax, X.Num(TEXT("test_stretch.w_max"), 7.0), 1e-9);
	TestEqual(TEXT("test_stretch: hedge segment painted on the right for [55, 90]"), Sp.SideSpec[1].HedgeTimeline.Num() > 0 ? 1 : 0, 1);
	{
		const int32 K = FStreetTimelineMath::IntervalAt(Sp.SideSpec[1].HedgeTimeline, 70.0);
		TestTrue(TEXT("test_stretch: hedge in force at s = 70 on the right"), K >= 0 && Sp.SideSpec[1].HedgeTimeline[K].bHas);
		const int32 K2 = FStreetTimelineMath::IntervalAt(Sp.SideSpec[1].HedgeTimeline, 30.0);
		TestTrue(TEXT("test_stretch: no hedge at s = 30"), K2 < 0 || !Sp.SideSpec[1].HedgeTimeline[K2].bHas);
		const FStreetBarrier* B70 = Sp.SideSpec[1].BarrierAt(70.0);
		TestTrue(TEXT("test_stretch: chain-link barrier in force at s = 70 on the right"), B70 && B70->Type == EStreetBarrierType::ChainLink);
		const FStreetBarrier* B30 = Sp.SideSpec[1].BarrierAt(30.0);
		TestTrue(TEXT("test_stretch: brick wall in force at s = 30 on the right"), B30 && B30->Type == EStreetBarrierType::BrickWall);
		TestTrue(TEXT("test_stretch: half-grass split on the left at s = 50"), Sp.SideSpec[0].Split[FStreetSplineMath::SearchSortedLeft(Sp.S, 50.0)]);
		const int32 I95 = FStreetSplineMath::SearchSortedLeft(Sp.S, 100.0);
		TestFalse(TEXT("test_stretch: standard kerb (no split) on the left at s = 100"), Sp.SideSpec[0].Split[I95]);
		// pavement_1p5 (side both, whole spline) sets 1.5 m; the later half_grass_left profile switch re-applies that profile's 1.8 m
		// on the LEFT over [0, 95.9] (SCHEMA.md 5 rule 3: a profile switch acts as a ramped scalar override, later segments win)
		const int32 IMid = Sp.Num() / 2;
		TestEqual(TEXT("test_stretch: pavement 1.5 m on the right (segment override)"), Sp.SideSpec[1].PavementWidth[IMid], 1.5, 1e-12);
		TestEqual(TEXT("test_stretch: pavement 1.8 m on the left inside the half-grass switch (s = 50)"), Sp.SideSpec[0].PavementWidth[FStreetSplineMath::SearchSortedLeft(Sp.S, 50.0)], 1.8, 1e-12);
		TestEqual(TEXT("test_stretch: pavement 1.5 m on the left beyond the switch ramp (s = 150)"), Sp.SideSpec[0].PavementWidth[FStreetSplineMath::SearchSortedLeft(Sp.S, 150.0)], 1.5, 1e-12);
	}
	return true;
}

// ---------------------------------------------------------------------------------------------------------------
// Required parity against a fresh numpy dump (generated by run_ue_tests.ps1; path in the
// STREETSCAPE_PARITY_JSON environment variable: {"straight_100": {"s": [...], "width": [...], "z_ref": [...], "bank": [...]}, ...}).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetSplineNumpyParityTest, "Streetscape.Spline.NumpyParity", kFlags)
bool FStreetSplineNumpyParityTest::RunTest(const FString& Parameters)
{
	const FString Path = FPlatformMisc::GetEnvironmentVariable(TEXT("STREETSCAPE_PARITY_JSON"));
	if (Path.IsEmpty() || !FPaths::FileExists(Path))
	{
		AddError(TEXT("STREETSCAPE_PARITY_JSON missing: no reference means no parity check"));
		return false;
	}
	TSharedPtr<FJsonObject> Ref;
	if (!LoadJson(*this, Path, Ref)) return false;
	struct FCase { const TCHAR* Name; const TCHAR* Key; FStreetHeightfield Terrain; };
	TArray<FCase> Cases;
	Cases.Add({ TEXT("straight_100"), TEXT("straight_100"), TerrainFor(TEXT("straight_100")) });
	Cases.Add({ TEXT("sine_5_50"), TEXT("sine_5_50"), TerrainFor(TEXT("sine_5_50")) });
	Cases.Add({ TEXT("curve_R20_200"), TEXT("curve_R20_200"), TerrainFor(TEXT("curve_R20_200")) });
	Cases.Add({ TEXT("rail_R300_600"), TEXT("rail_R300_600"), TerrainFor(TEXT("rail_R300_600")) });
	Cases.Add({ TEXT("straight_100"), TEXT("bank_cross"), CrossSlopeTerrain(0.1) });
	FStreetHeightfield Twist = FStreetHeightfield::FromFunction([](double X, double Y) { return 10.0 + X * Y / 32.0; },
		FVector2d(512.0, 512.0), 1.0, 512.0, FVector2d::ZeroVector, FVector2d(0.0, -256.0));
	Cases.Add({ TEXT("sine_5_50"), TEXT("twist_bilinear"), Twist });
	Twist.Sampling = EStreetHeightSampling::LandscapeTriangulated;
	Cases.Add({ TEXT("sine_5_50"), TEXT("twist_landscape_triangulated"), Twist });
	for (const FCase& C : Cases)
	{
		const TSharedPtr<FJsonObject>* R = nullptr;
		if (!Ref->TryGetObjectField(C.Key, R)) { AddError(FString::Printf(TEXT("missing parity case: %s"), C.Key)); continue; }
		FStreetSiteDoc Doc; FStreetSamples Sp;
		if (!BuildFixture(*this, C.Name, &C.Terrain, Doc, Sp)) continue;
		auto Compare = [&](const TCHAR* Field, const TArray<double>& Mine)
		{
			const TArray<TSharedPtr<FJsonValue>>* A = nullptr;
			if (!(*R)->TryGetArrayField(Field, A)) { AddError(FString::Printf(TEXT("missing parity array: %s.%s"), C.Key, Field)); return; }
			if (A->Num() != Mine.Num()) { AddError(FString::Printf(TEXT("%s.%s: %d values vs numpy %d"), C.Key, Field, Mine.Num(), A->Num())); return; }
			double MaxDiff = 0; int32 Exact = 0;
			for (int32 I = 0; I < Mine.Num(); ++I)
			{
				if (!(*A)[I].IsValid() || (*A)[I]->Type != EJson::Number || !FMath::IsFinite((*A)[I]->AsNumber()))
				{ AddError(FString::Printf(TEXT("invalid parity value: %s.%s[%d]"), C.Key, Field, I)); continue; }
				const double D = FMath::Abs(Mine[I] - (*A)[I]->AsNumber());
				MaxDiff = FMath::Max(MaxDiff, D);
				if (D == 0.0) ++Exact;
			}
			AddInfo(FString::Printf(TEXT("%s.%s: %d/%d bit-identical, max |diff| %.3g"), C.Key, Field, Exact, Mine.Num(), MaxDiff));
			TestTrue(FString::Printf(TEXT("%s.%s parity within 1e-9"), C.Key, Field), MaxDiff < 1e-9);
		};
		Compare(TEXT("s"), Sp.S);
		Compare(TEXT("width"), Sp.Width);
		Compare(TEXT("z_ref"), Sp.ZRef);
		Compare(TEXT("bank"), Sp.BankDeg);
		Compare(TEXT("edge_left"), Sp.EdgeOffset(EStreetSide::Left));
	}
	return true;
}
