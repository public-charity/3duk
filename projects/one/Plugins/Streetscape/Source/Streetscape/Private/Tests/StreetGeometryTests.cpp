// Streetscape.Geometry.ToDynamicMesh (UE_PLAN.md 2.7, 2.13): the winding flip of the Y mirror; vertex count == input;
// the left kerb of synthetic_straight lands at UE Y < 0 with its face normal toward the carriageway. Plus the
// mesh helpers (ear clipping, manifold check, welding).

#include "StreetTestUtil.h"
#include "DynamicMesh/DynamicMesh3.h"
#include "DynamicMesh/DynamicMeshAttributeSet.h"

using namespace StreetTest;
using namespace UE::Geometry;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetGeometryToDynamicMeshTest, "Streetscape.Geometry.ToDynamicMesh", EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetGeometryToDynamicMeshTest::RunTest(const FString& Parameters)
{
	FStreetSiteDoc Doc; FStreetSamples Sp;
	const FStreetHeightfield Terrain = TerrainFor(TEXT("straight_100"));
	if (!BuildFixture(*this, TEXT("straight_100"), &Terrain, Doc, Sp)) return false;
	// the left kerb face (rows B -> C of DESIGN.md 4.2) swept at edge_offset(left)
	const FName Kerb(TEXT("concrete_kerb"));
	const FStreetSection Face = FStreetSection::Make(false, { MakeTuple(0.0, -0.03, Kerb), MakeTuple(0.0, 0.125, Kerb) });
	FStreetMeshBuilder Buf;
	FStreetSweepParams Pr;
	Pr.Side = +1;
	Pr.Lateral = Sp.EdgeOffset(EStreetSide::Left);
	Pr.Height = Sp.EdgeHeight(EStreetSide::Left);
	Pr.Group = TEXT("kerb");
	Pr.bCapStart = false; Pr.bCapEnd = false;
	FStreetSweep::Sweep(Buf, Face, Sp.Frames, Pr);
	TestEqual(TEXT("kerb face: 2 (N-1) triangles"), Buf.F.Num(), 2 * (Sp.Num() - 1));
	bool bJsonLeft = true;
	for (const FVector3d& V : Buf.V) bJsonLeft &= V.Y > 0.0;
	TestTrue(TEXT("JSON: left kerb has y > 0"), bJsonLeft);

	FDynamicMesh3 Mesh;
	const int32 Skipped = FStreetGeometry::ToDynamicMesh(Buf, Mesh);
	TestEqual(TEXT("no triangles refused"), Skipped, 0);
	TestEqual(TEXT("vertex count == input"), Mesh.VertexCount(), Buf.V.Num());
	TestEqual(TEXT("triangle count == input"), Mesh.TriangleCount(), Buf.F.Num());
	bool bUeY = true, bUeX = true, bUeZ = true;
	for (int32 Vid : Mesh.VertexIndicesItr())
	{
		const FVector3d P = Mesh.GetVertex(Vid);
		bUeY &= P.Y < 0.0;
		bUeX &= P.X >= -1e-9 && P.X <= 10000.0 + 1e-9;
		bUeZ &= FMath::Abs(P.Z - 1000.0) < 20.0;   // 10 m ODN -> 1000 cm (kerb -3 .. +12.5 cm)
	}
	TestTrue(TEXT("UE: left kerb has Y < 0 (mirror)"), bUeY);
	TestTrue(TEXT("UE: x in centimetres 0..10000"), bUeX);
	TestTrue(TEXT("UE: z in centimetres around 1000"), bUeZ);
	// winding flip: the face normal after conversion points toward the carriageway (+Y in UE, since the kerb is at Y < 0)
	int32 Wrong = 0;
	double MinNy = 1.0;
	for (int32 Tid : Mesh.TriangleIndicesItr())
	{
		const FVector3d Nn = Mesh.GetTriNormal(Tid);
		MinNy = FMath::Min(MinNy, Nn.Y);
		if (Nn.Y < 0.9) ++Wrong;
	}
	TestEqual(FString::Printf(TEXT("UE face normals point at the carriageway (+Y), min n.y = %.4f"), MinNy), Wrong, 0);
	// and in the JSON frame the same faces point at -y: the mirror + reversed winding preserve the outward sense
	int32 WrongJson = 0;
	for (int32 T = 0; T < Buf.F.Num(); ++T) { if (Buf.FaceNormal(T).Y >= 0) ++WrongJson; }
	TestEqual(TEXT("JSON face normals point at -y"), WrongJson, 0);
	// attributes carried
	TestTrue(TEXT("material id attribute enabled"), Mesh.HasAttributes() && Mesh.Attributes()->HasMaterialID());
	TestTrue(TEXT("triangle groups enabled"), Mesh.HasTriangleGroups());
	TestTrue(TEXT("primary UV overlay has elements"), Mesh.Attributes()->PrimaryUV() && Mesh.Attributes()->PrimaryUV()->ElementCount() == 3 * Buf.F.Num());
	TestTrue(TEXT("normals overlay initialised"), Mesh.Attributes()->PrimaryNormals() && Mesh.Attributes()->PrimaryNormals()->ElementCount() > 0);
	if (Mesh.Attributes()->HasMaterialID())
	{
		int32 Mid = -1;
		Mesh.Attributes()->GetMaterialID()->GetValue(0, &Mid);
		TestEqual(TEXT("material id of triangle 0 = concrete_kerb slot"), Mid, Buf.FindMaterialId(Kerb));
	}
	// a closed box converts to a closed mesh with vertex count preserved
	{
		const FName Brick(TEXT("brick_red"));
		const FStreetSection Square = FStreetSection::Make(true, { MakeTuple(-0.5, -0.5, Brick), MakeTuple(-0.5, 0.5, Brick), MakeTuple(0.5, 0.5, Brick), MakeTuple(0.5, -0.5, Brick) });
		FStreetMeshBuilder Box;
		FStreetSweepParams P2;
		FStreetSweep::Sweep(Box, Square, Sp.Frames, P2);
		FDynamicMesh3 M2;
		const int32 Sk = FStreetGeometry::ToDynamicMesh(Box, M2);
		TestEqual(TEXT("box: no triangles refused"), Sk, 0);
		TestEqual(TEXT("box: vertex count == input"), M2.VertexCount(), Box.V.Num());
		TestTrue(TEXT("box: JSON manifold"), Box.IsClosedManifold());
	}
	// mesh helpers
	{
		TArray<FVector2d> Sq = { FVector2d(0, 0), FVector2d(1, 0), FVector2d(1, 1), FVector2d(0, 1) };
		TestEqual(TEXT("ear clip square -> 2 tris"), FStreetGeometry::TriangulatePolygon2D(Sq).Num(), 2);
		TestEqual(TEXT("polygon area 1"), FStreetGeometry::PolygonArea2D(Sq), 1.0, 1e-12);
		Algo::Reverse(Sq);
		TestEqual(TEXT("ear clip clockwise square -> 2 tris"), FStreetGeometry::TriangulatePolygon2D(Sq).Num(), 2);
		TArray<FVector2d> L = { FVector2d(0, 0), FVector2d(2, 0), FVector2d(2, 1), FVector2d(1, 1), FVector2d(1, 2), FVector2d(0, 2) };
		TestEqual(TEXT("ear clip L-shape -> 4 tris"), FStreetGeometry::TriangulatePolygon2D(L).Num(), 4);
		TArray<FVector3d> Ring = { FVector3d(0, 0, 0), FVector3d(1, 0, 0), FVector3d(1, 1, 0), FVector3d(0, 1, 0) };
		const FVector3d Nn = FStreetGeometry::NewellNormal(Ring);
		TestTrue(TEXT("Newell normal of a ccw square is +z"), Nn.Z > 0 && FMath::Abs(Nn.X) < 1e-12 && FMath::Abs(Nn.Y) < 1e-12);
		FStreetMeshBuilder Tet;
		TArray<FVector3d> Vs = { FVector3d(0, 0, 0), FVector3d(1, 0, 0), FVector3d(0, 1, 0), FVector3d(0, 0, 1) };
		TArray<FVector2d> Uv; Uv.Init(FVector2d::ZeroVector, 4);
		TArray<double> Zero; Zero.Init(0.0, 4);
		Tet.AppendVertices(Vs, Uv, Zero, Zero, Zero);
		const int32 M = Tet.MaterialId(TEXT("x")), G = Tet.GroupId(TEXT("g"));
		TArray<FIndex3i> Tris = { FIndex3i(0, 2, 1), FIndex3i(0, 1, 3), FIndex3i(1, 2, 3), FIndex3i(0, 3, 2) };
		Tet.AppendTriangles(Tris, M, G);
		TestTrue(TEXT("tetrahedron is a closed manifold"), Tet.IsClosedManifold());
		TArray<FIndex3i> Open = { FIndex3i(0, 2, 1) };
		FStreetMeshBuilder Tri;
		Tri.AppendVertices(Vs, Uv, Zero, Zero, Zero);
		Tri.AppendTriangles(Open, Tri.MaterialId(TEXT("x")), Tri.GroupId(TEXT("g")));
		TestFalse(TEXT("single triangle is not closed"), Tri.IsClosedManifold());
		TArray<FVector3d> Dup = { FVector3d(0, 0, 0), FVector3d(1e-12, 0, 0), FVector3d(1, 0, 0) };
		const TArray<int32> W = FStreetGeometry::WeldIndices(Dup, 1e-9);
		TestTrue(TEXT("weld maps coincident vertices to the first"), W[0] == 0 && W[1] == 0 && W[2] == 2);
		TestEqual(TEXT("distinct positions"), FStreetGeometry::DistinctPositions(Dup, 1e-9).Num(), 2);
	}
	return true;
}
