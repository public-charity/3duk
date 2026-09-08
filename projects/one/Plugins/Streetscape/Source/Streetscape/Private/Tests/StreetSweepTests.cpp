// Streetscape.Sweep.Manifold (UE_PLAN.md 2.13; DESIGN.md 4): closed square manifold with outward normals and
// triangle count 2*4*(N-1) + 2*2; open kerb section winding on both sides; caps only at run ends.

#include "StreetTestUtil.h"

using namespace StreetTest;

namespace
{
FStreetFrames StraightFrames(int32 N, double Step, double BankDeg = 0.0)
{
	TArray<double> S, Bank;
	TArray<FVector3d> P, Th;
	for (int32 I = 0; I < N; ++I)
	{
		S.Add(I * Step);
		P.Add(FVector3d(I * Step, 0.0, 10.0));
		Th.Add(FVector3d(1.0, 0.0, 0.0));
		Bank.Add(BankDeg);
	}
	return FStreetFrames::Build(S, P, Th, Bank);
}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetSweepManifoldTest, "Streetscape.Sweep.Manifold", EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetSweepManifoldTest::RunTest(const FString& Parameters)
{
	const int32 N = 10;
	const FStreetFrames Frames = StraightFrames(N, 2.0);
	// closed unit square listed clockwise in the (o, h) plane, all points hard -> 8 rows
	const FName Brick(TEXT("brick_red"));
	const FStreetSection Square = FStreetSection::Make(true, { MakeTuple(-0.5, -0.5, Brick), MakeTuple(-0.5, 0.5, Brick), MakeTuple(0.5, 0.5, Brick), MakeTuple(0.5, -0.5, Brick) });
	{
		FStreetMeshBuilder Buf;
		FStreetSweepParams Pr;
		Pr.Side = +1;
		Pr.Group = TEXT("wall");
		const FStreetSweepResult R = FStreetSweep::Sweep(Buf, Square, Frames, Pr);
		TestEqual(TEXT("closed all-hard section: R = 2P rows"), R.R, 8);
		TestEqual(TEXT("quads = 4 (N-1)"), R.NumQuads, 4 * (N - 1));
		TestEqual(TEXT("triangles = 2*4*(N-1) + 2*2"), Buf.F.Num(), 2 * 4 * (N - 1) + 2 * 2);
		TestEqual(TEXT("vertices = N * R"), Buf.V.Num(), N * 8);
		TestEqual(TEXT("one run"), R.Runs.Num(), 1);
		TestTrue(TEXT("validate clean: ") + FString::Join(Buf.Validate(), TEXT(" | ")), Buf.Validate().Num() == 0);
		TestTrue(TEXT("closed manifold after welding the duplicated hard rows"), Buf.IsClosedManifold());
		// outward normals: every face normal points away from the box axis (the caps are tested against a point
		// half a station inside the box, so their normals along -x / +x count as outward too)
		int32 Inward = 0;
		for (int32 T = 0; T < Buf.F.Num(); ++T)
		{
			const FVector3d C = (Buf.V[Buf.F[T].A] + Buf.V[Buf.F[T].B] + Buf.V[Buf.F[T].C]) / 3.0;
			const FVector3d Centre(FMath::Clamp(C.X, 1.0, (N - 1) * 2.0 - 1.0), 0.0, 10.0);
			if (FVector3d::DotProduct(Buf.FaceNormal(T), C - Centre) <= 0) ++Inward;
		}
		TestEqual(TEXT("all face normals outward"), Inward, 0);
		const FStreetBuildStats St = Buf.Stats();
		TestEqual(TEXT("stats tris"), St.Tris, Buf.F.Num());
		TestTrue(TEXT("stats per group 'wall'"), St.PerGroup.Contains(TEXT("wall")) && St.PerGroup[TEXT("wall")].X == Buf.F.Num());
		// o runs along n (= +y for a spline along +x), h along b (= +z): x spans the stations only
		TestEqual(TEXT("bbox x max = last station"), St.BBoxMax.X, (N - 1) * 2.0, 1e-12);
		TestEqual(TEXT("bbox y max = +o"), St.BBoxMax.Y, 0.5, 1e-12);
		TestEqual(TEXT("bbox z max = z_ref + h"), St.BBoxMax.Z, 10.5, 1e-12);
	}
	// no caps -> 8 (N-1) triangles only; an open square (not closed) is not a closed manifold
	{
		FStreetMeshBuilder Buf;
		FStreetSweepParams Pr;
		Pr.bCapStart = false; Pr.bCapEnd = false;
		FStreetSweep::Sweep(Buf, Square, Frames, Pr);
		TestEqual(TEXT("no caps: triangles = 8 (N-1)"), Buf.F.Num(), 8 * (N - 1));
		TestFalse(TEXT("no caps: not closed"), Buf.IsClosedManifold());
	}
	// masked stations split the sweep into runs, each capped
	{
		FStreetMeshBuilder Buf;
		FStreetSweepParams Pr;
		Pr.Mask.Init(true, N);
		Pr.Mask[4] = false;   // stations 0-3 and 5-9
		const FStreetSweepResult R = FStreetSweep::Sweep(Buf, Square, Frames, Pr);
		TestEqual(TEXT("mask: two runs"), R.Runs.Num(), 2);
		TestEqual(TEXT("mask: quads = 3 + 4 per edge"), R.NumQuads, 4 * 7);
		TestEqual(TEXT("mask: triangles = 8*7 + 2 caps * 2 runs * 2 tris"), Buf.F.Num(), 8 * 7 + 8);
		TestTrue(TEXT("mask: still a closed manifold (two boxes)"), Buf.IsClosedManifold());
		TestEqual(TEXT("mask: isolated station emits no vertices"), R.VertexAt(4, 0), -1);
	}
	// kerb face winding: open section B (0, -0.03) -> C (0, 0.125) on the left side faces the carriageway (-y)
	{
		const FName Kerb(TEXT("concrete_kerb"));
		const FStreetSection Face = FStreetSection::Make(false, { MakeTuple(0.0, -0.03, Kerb), MakeTuple(0.0, 0.125, Kerb) });
		for (int32 Side : { +1, -1 })
		{
			FStreetMeshBuilder Buf;
			FStreetSweepParams Pr;
			Pr.Side = Side;
			Pr.LateralScalar = 3.0;
			Pr.Group = TEXT("kerb");
			Pr.bCapStart = false; Pr.bCapEnd = false;
			FStreetSweep::Sweep(Buf, Face, Frames, Pr);
			TestEqual(FString::Printf(TEXT("side %+d: 2 (N-1) triangles"), Side), Buf.F.Num(), 2 * (N - 1));
			int32 Wrong = 0;
			for (int32 T = 0; T < Buf.F.Num(); ++T)
			{
				const FVector3d Nn = Buf.FaceNormal(T);
				// exposed normal = -o mapped to world: the left side's -o is -y, the right side's -o is +y
				if ((Side > 0 && Nn.Y >= 0) || (Side < 0 && Nn.Y <= 0)) ++Wrong;
			}
			TestEqual(FString::Printf(TEXT("side %+d: kerb face normals point at the carriageway"), Side), Wrong, 0);
			TestEqual(FString::Printf(TEXT("side %+d: vd attribute = side * 3"), Side), Buf.VD[0], Side * 3.0, 0.0);
			TestEqual(FString::Printf(TEXT("side %+d: vertex y = side * 3"), Side), Buf.V[0].Y, Side * 3.0, 1e-12);
		}
	}
	// per-station materials, edge groups, two-sided flag
	{
		const FName A(TEXT("tarmac")), B(TEXT("grass"));
		const FStreetSection Top = FStreetSection::Make(false, { MakeTuple(0.0, 0.0, A), MakeTuple(0.5, 0.0, A), MakeTuple(1.0, 0.0, B) }, { true, true, true });
		FStreetMeshBuilder Buf;
		FStreetSweepParams Pr;
		Pr.Groups = { TEXT("inner"), TEXT("outer") };
		Pr.EdgeMatStation.Init(A, N * 2);
		for (int32 I = 5; I < N; ++I) Pr.EdgeMatStation[I * 2 + 1] = B;   // outer edge turns to grass from station 5
		Pr.bTwoSided = true;
		Pr.bCapStart = false; Pr.bCapEnd = false;
		FStreetSweep::Sweep(Buf, Top, Frames, Pr);
		TestEqual(TEXT("smooth section: R = P rows"), Buf.V.Num(), N * 3);
		const FStreetBuildStats St = Buf.Stats();
		TestTrue(TEXT("groups inner/outer present"), St.PerGroup.Contains(TEXT("inner")) && St.PerGroup.Contains(TEXT("outer")));
		TestEqual(TEXT("grass triangles = 2 * 4 quads"), St.PerMaterial.Contains(B) ? St.PerMaterial[B].X : 0, 8);
		TestTrue(TEXT("two-sided names recorded"), Buf.TwoSided.Contains(A) && Buf.TwoSided.Contains(B));
		TestEqual(TEXT("station values = the frames' s"), FStreetGeometry::StationValues(Buf).Num(), N);
	}
	// RunsToQuadMask
	{
		TArray<double> S = { 0, 1, 2, 3, 4, 5 };
		const TArray<bool> Q = FStreetSweep::RunsToQuadMask(S, { TPair<double, double>(1.0, 3.0) });
		TestTrue(TEXT("quad mask [1,3] -> quads 1-2 and 2-3"), Q.Num() == 5 && !Q[0] && Q[1] && Q[2] && !Q[3] && !Q[4]);
	}
	return true;
}
