// Streetscape.Conform.* (docs/TERRAIN_ROADS.md 5.1, D3): the ground under the built street IS the street.
//
// Alex's report from the editor was "the real road geometry is still fusing with the landscape".  Measured over the
// whole isle before the fix: 89.06 % of 666,314 road stations had terrain standing above the carriageway somewhere
// across its width, 866.06 km of 968.84 km, worst 13.698 m.  The corridor conform
// (Tools/conform_landscape.py -> data/thanet/out/unreal/landscape_conformed) burns the road surface into a COPY of
// the landscape heightmap; the whole-isle gate is Tools/road_fusion_audit.py.
//
// These two tests are the engine's own copy of that measurement, so a C++ change that moves the road surface (or a
// landscape re-import from the wrong directory) fails here and not only in numpy:
//
//   Streetscape.Conform.Manifest   the shipped product says in words that it is not the survey, and carries the
//                                  corridor parameters and the delta rasters that make it reversible.
//   Streetscape.Conform.NoFusion   the spline built by FStreetSplineMath on the SURVEY heightfield (BRIEF 1.1: the
//                                  road drapes on the survey) is measured against the CONFORMED heightfield with
//                                  ALandscape's own triangulated rule - what the pawn walks on and the camera sees.
//
// Both skip with an info line when data/thanet/out/unreal is not on this machine.

#include "StreetTestUtil.h"

using namespace StreetTest;

static constexpr EAutomationTestFlags kConformFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

/** Same tolerance as the numpy gate: r16 half-quantum 0.0039 m plus the sampling residue, well inside the 0.03 m sink. */
static constexpr double kGateM = 0.005;
/** A kerb is 0.125 m tall: daylight under the built block deeper than that would be visible from eye level. */
static constexpr double kFloatGateM = 0.125;

static FString SurveyDir() { return FPaths::ConvertRelativePathToFull(ProjectDir() / TEXT("../../data/thanet/out/unreal/landscape")); }
static FString ConformedDir() { return FPaths::ConvertRelativePathToFull(ProjectDir() / TEXT("../../data/thanet/out/unreal/landscape_conformed")); }

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetConformManifestTest, "Streetscape.Conform.Manifest", kConformFlags)
bool FStreetConformManifestTest::RunTest(const FString& Parameters)
{
	const FString Path = ConformedDir() / TEXT("landscape_manifest.json");
	if (!FPaths::FileExists(Path))
	{
		AddInfo(TEXT("no conformed landscape at ") + ConformedDir() + TEXT(" - skipped (run Tools/conform_landscape.py)"));
		return true;
	}
	TSharedPtr<FJsonObject> Man;
	if (!LoadJson(*this, Path, Man)) return false;
	const TSharedPtr<FJsonObject>* Conform = nullptr;
	if (!Man->TryGetObjectField(TEXT("conform"), Conform) || !Conform)
	{
		AddError(TEXT("landscape_conformed/landscape_manifest.json has no `conform` block: a consumer cannot tell it from the survey"));
		return false;
	}
	FString Semantics;
	(*Man->GetObjectField(TEXT("heightmap"))).TryGetStringField(TEXT("semantics"), Semantics);
	TestTrue(TEXT("heightmap.semantics says the heights are NOT the raw survey"), Semantics.ToUpper().Contains(TEXT("NOT THE RAW SURVEY")));
	int32 Changed = 0;
	(*Conform)->TryGetNumberField(TEXT("cells_changed"), Changed);
	TestTrue(FString::Printf(TEXT("the burn changed cells (%d)"), Changed), Changed > 0);
	const TSharedPtr<FJsonObject>* Corridor = nullptr;
	TestTrue(TEXT("the corridor parameters are recorded"), (*Conform)->TryGetObjectField(TEXT("corridor"), Corridor) && Corridor);
	if (Corridor)
	{
		double Sink = -1, Verge = -1;
		(*Corridor)->TryGetNumberField(TEXT("sink_m"), Sink);
		(*Corridor)->TryGetNumberField(TEXT("verge_m"), Verge);
		AddInfo(FString::Printf(TEXT("conform: %d cells changed, sink %.3f m, verge %.3f m"), Changed, Sink, Verge));
		TestTrue(TEXT("the sink is inside the kerb tuck (0.03 m)"), Sink > 0.0 && Sink <= 0.03 + 1e-9);
	}
	FString Src;
	TestTrue(TEXT("the source product is named"), (*Conform)->TryGetStringField(TEXT("source"), Src) && !Src.IsEmpty());
	// the survey product itself must still be there, unconformed
	TSharedPtr<FJsonObject> Survey;
	if (LoadJson(*this, SurveyDir() / TEXT("landscape_manifest.json"), Survey))
	{
		TestFalse(TEXT("the adapter's landscape product was NOT overwritten (it has no conform block)"),
			Survey->HasField(TEXT("conform")));
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetConformNoFusionTest, "Streetscape.Conform.NoFusion", kConformFlags)
bool FStreetConformNoFusionTest::RunTest(const FString& Parameters)
{
	if (!FPaths::FileExists(ConformedDir() / TEXT("landscape_manifest.json")) ||
		!FPaths::FileExists(SurveyDir() / TEXT("landscape_manifest.json")))
	{
		AddInfo(TEXT("no adapter output on this machine - skipped"));
		return true;
	}
	FText Err;
	FStreetHeightfield Survey, Conformed;
	if (!Survey.LoadLandscapeDir(SurveyDir(), &Err)) { AddError(Err.ToString()); return false; }
	if (!Conformed.LoadLandscapeDir(ConformedDir(), &Err)) { AddError(Err.ToString()); return false; }
	// what the pawn walks on and the camera sees: the landscape's two triangles per quad, not the bilinear contract
	Conformed.Sampling = EStreetHeightSampling::LandscapeTriangulated;

	TArray<FString> Docs;
	Docs.Add(ExamplesDir() / TEXT("test_stretch.json"));
	const FString SiteDoc = FPaths::ConvertRelativePathToFull(ProjectDir() / TEXT("../../data/thanet/out/unreal/streetscape/site_x16_y2.json"));
	if (FPaths::FileExists(SiteDoc)) Docs.Add(SiteDoc);

	int32 Splines = 0, Stations = 0, Penetrated = 0, Floating = 0, Fused = 0;
	double WorstPen = 0.0, WorstFloat = 0.0, WorstBefore = 0.0;
	FString WorstId;
	for (const FString& DocPath : Docs)
	{
		FStreetSiteDoc Doc;
		if (!LoadDoc(*this, DocPath, Doc)) return false;
		FStreetHeightfieldSource SurveySrc(Survey);
		SurveySrc.SetDocumentOrigin(Doc.Origin.E, Doc.Origin.N);
		const int32 Limit = FMath::Min(Doc.Splines.Num(), 40);
		for (int32 SI = 0; SI < Limit; ++SI)
		{
			const FStreetSplineDef& Def = Doc.Splines[SI];
			if (Def.ProfileIds.Road.IsEmpty()) continue;
			FStreetSamples Sp;
			FString BuildErr;
			// BRIEF 1.1: the road samples the SURVEY and sits on the smoothed curve.  The conformed product is
			// derived from the road, never the other way round -- building on it would be a feedback loop.
			if (!FStreetSplineMath::Build(Def, Doc.Profiles, &SurveySrc, Sp, &BuildErr)) { AddError(BuildErr); return false; }
			bool bNoTerrain = false;
			for (const FString& W : Sp.Warnings) if (W.Contains(TEXT("no terrain"))) bNoTerrain = true;
			if (bNoTerrain) continue;
			++Splines;
			const TArray<double> OL = Sp.EdgeOffset(EStreetSide::Left), OR = Sp.EdgeOffset(EStreetSide::Right);
			for (int32 I = 0; I < Sp.Num(); ++I)
			{
				double MinClear = TNumericLimits<double>::Max(), MaxClear = -TNumericLimits<double>::Max(), MinBefore = TNumericLimits<double>::Max();
				int32 Got = 0;
				const int32 K = 9;
				for (int32 J = 0; J < K; ++J)
				{
					const double F = (double)J / (double)(K - 1);
					const double D = -OR[I] + F * (OL[I] + OR[I]);
					const FVector3d P = Sp.Frames.P[I] + D * Sp.Frames.N[I] + Sp.SurfaceHAt(I, D) * Sp.Frames.B[I];
					double ZT = 0.0, ZS = 0.0;
					if (!Conformed.Sample(P.X, P.Y, ZT)) continue;
					MinClear = FMath::Min(MinClear, P.Z - ZT);
					MaxClear = FMath::Max(MaxClear, P.Z - ZT);
					if (Survey.Sample(P.X, P.Y, ZS)) MinBefore = FMath::Min(MinBefore, P.Z - ZS);
					++Got;
				}
				if (Got == 0) continue;
				++Stations;
				const double Pen = FMath::Max(0.0, -MinClear);
				// the visible gap: the road's own skirt hides SkirtDropM, a kerb block another 0.125 m
				const double Hide = FMath::Max(Sp.SkirtDropM[I], Sp.SideSpec[0].bHasKerbOrPavement || Sp.SideSpec[1].bHasKerbOrPavement ? 0.3 : Sp.SkirtDropM[I]);
				const double Flt = FMath::Max(0.0, MaxClear - Hide);
				if (Pen > kGateM) ++Penetrated;
				if (Flt > kFloatGateM) ++Floating;
				if (MinBefore < -kGateM) ++Fused;
				if (MinBefore < TNumericLimits<double>::Max()) WorstBefore = FMath::Max(WorstBefore, -MinBefore);
				if (Pen > WorstPen) { WorstPen = Pen; WorstId = Def.Id; }
				WorstFloat = FMath::Max(WorstFloat, Flt);
			}
		}
	}
	AddInfo(FString::Printf(TEXT("%d splines, %d stations: worst penetration %.6f m (was %.6f m on the survey), worst float %.6f m, %d stations penetrated (%d fused before)"),
		Splines, Stations, WorstPen, WorstBefore, WorstFloat, Penetrated, Fused));
	TestTrue(TEXT("the sample is not empty"), Splines > 2 && Stations > 200);
	TestTrue(FString::Printf(TEXT("the unconformed survey really does fuse (worst %.3f m) - otherwise this test proves nothing"), WorstBefore), WorstBefore > 0.05);
	TestTrue(FString::Printf(TEXT("no terrain above the carriageway: worst %.6f m at %s <= %.3f"), WorstPen, *WorstId, kGateM), WorstPen <= kGateM);
	TestEqual(TEXT("no station penetrated"), Penetrated, 0);
	return true;
}
