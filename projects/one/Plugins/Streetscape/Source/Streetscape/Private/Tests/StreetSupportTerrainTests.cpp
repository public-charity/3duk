#include "StreetRenderTestUtil.h"
#include "StreetscapeActor.h"
#include "StreetscapeSiteActor.h"
#include "StreetSpline.h"
#include "Engine/World.h"
using namespace StreetTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetSupportTerrainTest,"Streetscape.Edge.SupportTerrainSeparation",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetSupportTerrainTest::RunTest(const FString& Parameters)
{
	const auto Json=FixtureCopy(*this,TEXT("straight_100"));
	if (!Json.IsValid()) return false;
	SetSegments(Json,{TEXT("{\"id\":\"support\",\"s0_m\":0,\"s1_m\":null,\"side\":\"both\",\"edge\":{\"embankment\":{\"kind\":\"retaining_wall\",\"side\":\"both\",\"material\":\"grass\"}}}")});
	FStreetSiteDoc Doc;
	TArray<FString> Problems;
	if (!FStreetscapeJson::ReadSite(Json.ToSharedRef(),Doc,Problems)) { AddError(FString::Join(Problems,TEXT(" | "))); return false; }
	UWorld* World=UWorld::CreateWorld(EWorldType::Game,false);
	if (!TestNotNull(TEXT("transient world"),World)) return false;
	AStreetscapeSiteActor* Site=AStreetscapeSiteActor::Get(World,true);
	UStreetHeightfieldTerrain* Survey=NewObject<UStreetHeightfieldTerrain>(Site);
	Survey->SetSyntheticPlane(10,0,0);
	Site->TerrainSource=Survey;
	AStreetscapeActor* Actor=World->SpawnActor<AStreetscapeActor>();
	Actor->ApplyDefinition(Doc.Splines[0],Doc.Profiles,FVector2D(Doc.Origin.E,Doc.Origin.N));
	FString Error;
	if (!TestTrue(TEXT("baseline build"),Actor->RebuildAllChecked(&Error))) { AddError(Error); World->DestroyWorld(false); return false; }
	const auto BeforeRoad=Actor->Road->GetLastBuffer().V;
	UStreetHeightfieldTerrain* Ground=NewObject<UStreetHeightfieldTerrain>(Site);
	Ground->SetSyntheticPlane(8,0,0);
	Site->SupportTerrainSource=Ground;
	if (!TestTrue(TEXT("separate support terrain build"),Actor->RebuildAllChecked(&Error))) { AddError(Error); World->DestroyWorld(false); return false; }
	TestTrue(TEXT("road vertices unchanged when support ground moves"),BeforeRoad==Actor->Road->GetLastBuffer().V);
	for (double Z:Actor->GetSamples()->ZRef) TestEqual(TEXT("spline keeps original survey elevation"),Z,10.0,1e-9);
	const FName Group(TEXT("embankment:retaining_wall:0"));
	const auto& Mesh=Actor->EdgeLeft->GetLastBuffer();
	const auto Vertices=Mesh.VerticesOfGroups(FString(),&Group);
	TestTrue(TEXT("support wall emitted against lower terrain"),Vertices.Num()>0);
	double MinZ=DBL_MAX;
	for (int32 V:Vertices) MinZ=FMath::Min(MinZ,Mesh.V[V].Z);
	TestEqual(TEXT("footing reaches separate ground"),MinZ,7.7,1e-8);
	const auto BeforeEdge=Mesh.V;
	Site->SupportTerrainSource=NewObject<UStreetLandscapeTerrain>(Site); // No landscape: samples fail.
	TestFalse(TEXT("missing support terrain rejects rebuild"),Actor->RebuildAllChecked(&Error));
	TestTrue(TEXT("error names missing support ground"),Error.Contains(TEXT("embankment edge")));
	TestTrue(TEXT("failure preserves last complete road"),BeforeRoad==Actor->Road->GetLastBuffer().V);
	TestTrue(TEXT("failure preserves last complete support"),BeforeEdge==Actor->EdgeLeft->GetLastBuffer().V);
	World->DestroyWorld(false);
	return true;
}
