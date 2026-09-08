// Streetscape.Perf.Tile (UE_PLAN.md 2.13, DESIGN.md 10) - informational: how long one streetscape actor takes to
// go from a document to three renderer buffers, which is what rebuild-on-load pays per actor. The test only fails
// if a build errors; the milliseconds are logged so the 24k-actor estimate has a measured basis.

#include "StreetRenderTestUtil.h"

using namespace StreetTest;

constexpr EAutomationTestFlags kPerfFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetPerfTileTest, "Streetscape.Perf.Tile", kPerfFlags)
bool FStreetPerfTileTest::RunTest(const FString& Parameters)
{
	struct FCase { const TCHAR* Name; const TCHAR* Fixture; };
	const FCase Cases[] = { { TEXT("straight_100"), TEXT("straight_100") }, { TEXT("curve_R20_200"), TEXT("curve_R20_200") }, { TEXT("rail_R300_600"), TEXT("rail_R300_600") } };
	const int32 Repeats = 5;
	for (const FCase& C : Cases)
	{
		const TSharedPtr<FJsonObject> DocObj = Fixture(*this, C.Fixture);
		if (!DocObj.IsValid()) return false;
		const FStreetHeightfield Terrain = TerrainFor(C.Fixture);
		double SplineMs = 0, RenderMs = 0;
		int32 Verts = 0, Tris = 0;
		for (int32 R = 0; R < Repeats; ++R)
		{
			FStreetSiteDoc Doc;
			TArray<FString> Problems;
			if (!FStreetscapeJson::ReadSite(DocObj.ToSharedRef(), Doc, Problems)) { AddError(FString::Join(Problems, TEXT(" | "))); return false; }
			FStreetHeightfieldSource Src(Terrain);
			Src.SetDocumentOrigin(Doc.Origin.E, Doc.Origin.N);
			FStreetSamples Sp;
			FString Err;
			const double T0 = FPlatformTime::Seconds();
			if (!FStreetSplineMath::Build(Doc.Splines[0], Doc.Profiles, &Src, Sp, &Err)) { AddError(Err); return false; }
			const double T1 = FPlatformTime::Seconds();
			FStreetRenderResult Road, EdgeL, EdgeR, HedgeL, HedgeR;
			FStreetRenderBuild::BuildRoad(Sp, Road);
			FStreetRenderBuild::BuildEdge(Sp, EStreetSide::Left, &Src, EdgeL);
			FStreetRenderBuild::BuildEdge(Sp, EStreetSide::Right, &Src, EdgeR);
			FStreetRenderBuild::BuildHedge(Sp, EStreetSide::Left, HedgeL);
			FStreetRenderBuild::BuildHedge(Sp, EStreetSide::Right, HedgeR);
			const double T2 = FPlatformTime::Seconds();
			SplineMs += (T1 - T0) * 1000.0;
			RenderMs += (T2 - T1) * 1000.0;
			Verts = Road.Buffer.V.Num() + EdgeL.Buffer.V.Num() + EdgeR.Buffer.V.Num() + HedgeL.Buffer.V.Num() + HedgeR.Buffer.V.Num();
			Tris = Road.Buffer.F.Num() + EdgeL.Buffer.F.Num() + EdgeR.Buffer.F.Num() + HedgeL.Buffer.F.Num() + HedgeR.Buffer.F.Num();
		}
		AddInfo(FString::Printf(TEXT("Perf.Tile %s: spline %.2f ms + renderers %.2f ms = %.2f ms per actor, %d verts / %d tris (mean of %d)"),
			C.Name, SplineMs / Repeats, RenderMs / Repeats, (SplineMs + RenderMs) / Repeats, Verts, Tris, Repeats));
		TestTrue(FString::Printf(TEXT("%s produced geometry"), C.Name), Tris > 0);
	}
	return true;
}
