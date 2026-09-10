// Renderer B world-space support invariants; mirrors tests/test_support.py.
#include "StreetRenderTestUtil.h"
using namespace StreetTest;
constexpr EAutomationTestFlags kSupportFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

namespace
{
TSharedPtr<FJsonObject> SupportDoc(FAutomationTestBase& Test, const FString& Kind)
{
	TSharedPtr<FJsonObject> Doc = FixtureCopy(Test, TEXT("straight_100"));
	if (!Doc.IsValid()) return nullptr;
	FirstSpline(Doc)->SetArrayField(TEXT("elevation_profile"), {
		SegmentFromText(TEXT("{\"s_m\":0,\"z_m\":11.5,\"bank_deg\":12}")),
		SegmentFromText(TEXT("{\"s_m\":100,\"z_m\":11.5,\"bank_deg\":12}")) });
	SetSegments(Doc, { FString::Printf(TEXT("{\"id\":\"support\",\"s0_m\":0,\"s1_m\":null,\"side\":\"both\",\"edge\":{\"embankment\":{\"kind\":\"%s\",\"side\":\"both\",\"material\":\"grass\",\"threshold_m\":0.01}}}"), *Kind) });
	return Doc;
}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetSupportWallTest, "Streetscape.Edge.SupportVerticalWalls", kSupportFlags)
bool FStreetSupportWallTest::RunTest(const FString& Parameters)
{
	const auto Doc = SupportDoc(*this, TEXT("retaining_wall"));
	if (!Doc.IsValid()) return false;
	const FStreetHeightfield Terrain = FlatTerrain(10.0);
	FBuiltStreet Built;
	if (!Built.Build(*this, Doc.ToSharedRef(), &Terrain)) return false;
	const FName Group(TEXT("embankment:retaining_wall:0"));
	for (int32 K = 0; K < 2; ++K)
	{
		const auto& Mesh = Built.Edge[K].Buffer;
		TestEqual(TEXT("no support problem"), Built.Edge[K].Problems.Num(), 0);
		const auto Vertices = Mesh.VerticesOfGroups(FString(), &Group);
		TestTrue(TEXT("explicit wall emitted on raised road"), Vertices.Num() > 0);
		TSet<FName> Groups; Groups.Add(Group);
		TestTrue(TEXT("wall is closed"), Mesh.IsClosedManifold(nullptr, &Groups));
		TArray<FVector3d> Row;
		for (int32 V : Vertices) if (FMath::Abs(Mesh.VS[V] - 20.0) < 1e-8) Row.Add(Mesh.V[V]);
		TestTrue(TEXT("20 m row exists"), Row.Num() > 0);
		if (Row.Num() == 0) continue;
		double MinZ = Row[0].Z, MinY = Row[0].Y, MaxY = Row[0].Y;
		for (const FVector3d& P : Row) { MinZ = FMath::Min(MinZ, P.Z); MinY = FMath::Min(MinY, P.Y); MaxY = FMath::Max(MaxY, P.Y); }
		TestEqual(TEXT("footing reaches ground - 0.3 m"), MinZ, 9.7, 1e-8);
		TestEqual(TEXT("horizontal world thickness"), MaxY - MinY, 0.3, 1e-8);
		for (const FVector3d& P : Row) TestTrue(TEXT("top and bottom stay vertically aligned"),
			FMath::Abs(P.Y - MinY) < 1e-8 || FMath::Abs(P.Y - MaxY) < 1e-8);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetSupportBatterTest, "Streetscape.Edge.SupportBatterContact", kSupportFlags)
bool FStreetSupportBatterTest::RunTest(const FString& Parameters)
{
	const auto Doc = SupportDoc(*this, TEXT("batter"));
	if (!Doc.IsValid()) return false;
	const auto Terrain = FStreetHeightfield::FromFunction([](double, double Y) { return 10.0 - 0.2 * Y; },
		FVector2d(512,512), 1.0, 512.0, FVector2d::ZeroVector, FVector2d(0,-256));
	FBuiltStreet Built;
	if (!Built.Build(*this, Doc.ToSharedRef(), &Terrain)) return false;
	TestEqual(TEXT("no support problem"), Built.Edge[0].Problems.Num(), 0);
	const auto& Mesh = Built.Edge[0].Buffer;
	const FName Group(TEXT("embankment:batter:0"));
	const auto Vertices = Mesh.VerticesOfGroups(FString(), &Group);
	TestTrue(TEXT("batter emitted"), Vertices.Num() > 0);
	for (double S : Built.Sp.S)
	{
		TArray<FVector3d> Row;
		for (int32 V : Vertices) if (FMath::Abs(Mesh.VS[V]-S) < 1e-8) Row.Add(Mesh.V[V]);
		if (Row.Num() == 0) continue;
		FVector3d Top = Row[0], Toe = Row[0];
		for (const auto& P : Row) { if (P.Z > Top.Z) Top = P; if (P.Z < Toe.Z) Toe = P; }
		double Ground = 0.0;
		TestTrue(TEXT("toe terrain exists"), Terrain.Sample(Toe.X,Toe.Y,Ground));
		TestEqual(TEXT("toe reaches terrain at actual XY"), Toe.Z, Ground-0.3, 1e-7);
		const double Run = std::hypot(Top.X-Toe.X, Top.Y-Toe.Y);
		TestEqual(TEXT("world batter slope before below-ground tuck"), Run/(Top.Z-Toe.Z-0.3), 1.5, 1e-7);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetSupportMissingTest, "Streetscape.Edge.SupportMissingToe", kSupportFlags)
bool FStreetSupportMissingTest::RunTest(const FString& Parameters)
{
	const auto Doc = SupportDoc(*this, TEXT("batter"));
	if (!Doc.IsValid()) return false;
	const auto Terrain = FlatTerrain(10.0);
	FBuiltStreet Built;
	if (!Built.Build(*this, Doc.ToSharedRef(), &Terrain)) return false;
	struct FMissingToe : IStreetTerrainSource
	{
		bool SampleHeight(double X, double Y, double& Z) const override { Z = 10.0; return FMath::Abs(Y) < 6.0; }
		FString Describe() const override { return TEXT("missing beyond road edge"); }
	} Missing;
	FStreetRenderResult Out;
	FStreetRenderBuild::BuildEdge(Built.Sp, EStreetSide::Left, &Missing, Out);
	TestTrue(TEXT("missing toe cannot masquerade as a complete support"), Out.Problems.Num() > 0);
	return true;
}
