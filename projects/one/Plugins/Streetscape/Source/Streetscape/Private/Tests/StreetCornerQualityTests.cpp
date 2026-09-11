#include "StreetRenderTestUtil.h"
#include "StreetJunctions.h"
#include "StreetJunctionBuild.h"
#include "StreetscapeActor.h"
#include "StreetscapeSiteActor.h"
#include "StreetSpline.h"
#include "Engine/World.h"
#include <cmath>
using namespace StreetTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetCornerQualityParityTest, "Streetscape.Junction.CornerQualityParity",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetCornerQualityParityTest::RunTest(const FString& Parameters)
{
	const FString Path=FPlatformMisc::GetEnvironmentVariable(TEXT("STREETSCAPE_PARITY_JSON"));
	TSharedPtr<FJsonObject> Reference;
	if (Path.IsEmpty() || !LoadJson(*this,Path,Reference)) { AddError(TEXT("corner parity reference missing")); return false; }
	const TSharedPtr<FJsonObject>* Cases=nullptr;
	if (!Reference->TryGetObjectField(TEXT("corner_curves"),Cases)) { AddError(TEXT("corner parity cases missing")); return false; }
	for (int32 Case=0;Case<3;++Case)
	{
		const FString Name=Case==0 ? TEXT("long_shallow") : Case==1 ? TEXT("parallel_s") : TEXT("translated_s");
		const FVector3d A=Case==0 ? FVector3d(0,0,51.7) : Case==1 ? FVector3d(0,0,10) : FVector3d(8370,4480,10);
		const FVector3d B=Case==0 ? FVector3d(.13,25.22,51.3) : Case==1 ? FVector3d(30,10,11) : FVector3d(8400,4490,11);
		const FVector2d D0=Case==0 ? FVector2d(-.063,.998) : FVector2d(1,0);
		const FVector2d D1=Case==0 ? FVector2d(-.311,.950) : FVector2d(1,0);
		const FVector2d Node=Case==0 ? FVector2d(-3.9,16.5) : Case==1 ? FVector2d(15,5) : FVector2d(8385,4485);
		TArray<FVector3d> P,T;
		if (!TestTrue(Name+TEXT(" builds"),FStreetJunctionMath::CornerCurve(A,B,D0,D1,Node,10.,.75,P,T))) continue;
		TestTrue(Name+TEXT(" endpoints exact"),P[0]==A && P.Last()==B);
		TestTrue(Name+TEXT(" long curve has more than three rings"),P.Num()>25);
		for (int32 I=1;I<P.Num();++I)
		{
			TestTrue(Name+TEXT(" segment <=1 m"),(P[I]-P[I-1]).Size()<=1.0+1e-9);
			const double Dot=T[I].X*T[I-1].X+T[I].Y*T[I-1].Y;
			TestTrue(Name+TEXT(" actual turn <=10 degrees"),Dot>=std::cos(10.0*3.14159265358979323846/180.0)-1e-12);
		}
		const TSharedPtr<FJsonObject>* Row=nullptr;
		if (!(*Cases)->TryGetObjectField(Name,Row)) { AddError(TEXT("missing corner case ")+Name); continue; }
		const FVector3d N0(-T[0].Y*std::cos(.05),T[0].X*std::cos(.05),std::sin(.05));
		const FVector3d N1(-T.Last().Y*std::cos(-.08),T.Last().X*std::cos(-.08),std::sin(-.08));
		const auto Frames=FStreetJunctionMath::CornerFrames(P,T,N0,N1);
		for (int32 K=0;K<4;++K)
		{
			const FString Field=K==0 ? TEXT("points") : K==1 ? TEXT("tangents") : K==2 ? TEXT("normals") : TEXT("up");
			const auto& Mine=K==0 ? P : K==1 ? T : K==2 ? Frames.N : Frames.B;
			const TArray<TSharedPtr<FJsonValue>>* Values=nullptr;
			if (!(*Row)->TryGetArrayField(Field,Values)) { AddError(TEXT("missing corner array ")+Field); continue; }
			if (!TestEqual(Name+TEXT(".")+Field+TEXT(" count"),Mine.Num()*3,Values->Num())) continue;
			double MaxDiff=0.;int32 Identical=0;
			for (int32 I=0;I<Mine.Num();++I) for (int32 Axis=0;Axis<3;++Axis)
			{
				const auto& V=(*Values)[I*3+Axis];
				if (V->Type!=EJson::Number || !FMath::IsFinite(V->AsNumber())) { AddError(TEXT("nonfinite corner reference")); return false; }
				const double Expected=V->AsNumber(),Got=Mine[I][Axis];
				MaxDiff=FMath::Max(MaxDiff,FMath::Abs(Got-Expected));if (Got==Expected) ++Identical;
			}
			AddInfo(FString::Printf(TEXT("%s.%s: %d/%d identical, max difference %.12g"),*Name,*Field,Identical,Values->Num(),MaxDiff));
			TestTrue(Name+TEXT(".")+Field+TEXT(" parity"),MaxDiff<=1e-9);
		}
	}
	TArray<FVector3d> P,T;
	TestFalse(TEXT("cusp fails within bounded work"),FStreetJunctionMath::CornerCurve(FVector3d(0,0,0),FVector3d(10,0,0),
		FVector2d(-1,0),FVector2d(-1,0),FVector2d(5,1),10.,.75,P,T));
	TestEqual(TEXT("failed curve publishes no points"),P.Num(),0);
	TestEqual(TEXT("failed curve publishes no tangents"),T.Num(),0);
	for (double Degrees : {0.,60.,120.,170.,120.,60.,0.})
	{
		const double Angle=Degrees*3.14159265358979323846/180.;
		P.Add(FVector3d(P.Num(),0,0));T.Add(FVector3d(std::cos(Angle),std::sin(Angle),0));
	}
	const auto Frames=FStreetJunctionMath::CornerFrames(P,T,FVector3d(0,std::cos(.05),std::sin(.05)),
		FVector3d(0,std::cos(-.08),std::sin(-.08)));
	for (const auto& Up:Frames.B) TestTrue(TEXT("bank transport keeps internal frame upright"),Up.Z>=std::cos(.08)-1e-12);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetPartialJunctionTest,"Streetscape.Junction.PartialRebuildRejected",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetPartialJunctionTest::RunTest(const FString& Parameters)
{
	FStreetSiteDoc Doc;FJunctionSiteBuild Reference;
	if (!BuildJunctionSite(*this,TEXT("junction_crossroads"),Doc,Reference)) return false;
	TMap<FString,FVector2D> Trims;TMap<FString,TArray<FStreetOwnedJunction>> Owned;
	FStreetJunctionBuild::Distribute(Doc,Reference.Plan,Trims,Owned);
	const FString Id=Reference.Owner[TEXT("j0")];
	UWorld* World=UWorld::CreateWorld(EWorldType::Game,false);
	if (!TestNotNull(TEXT("transient junction world"),World)) return false;
	AStreetscapeSiteActor* Site=AStreetscapeSiteActor::Get(World,true);
	UStreetHeightfieldTerrain* Terrain=NewObject<UStreetHeightfieldTerrain>(Site);
	Terrain->SetSyntheticPlane(10,0,0);Site->TerrainSource=Terrain;
	AStreetscapeActor* Actor=World->SpawnActor<AStreetscapeActor>();
	Actor->ApplyDefinition(*Doc.FindSpline(Id),Doc.Profiles,FVector2D(Doc.Origin.E,Doc.Origin.N));
	Actor->SetJunctionData(Trims.FindChecked(Id),MoveTemp(Owned.FindChecked(Id)));
	FString Error;
	if (!TestTrue(TEXT("complete junction build"),Actor->RebuildAllChecked(&Error)))
	{ AddError(Error);World->DestroyWorld(false);return false; }
	const auto BeforeRoad=Actor->Road->GetLastBuffer().V;
	const auto BeforeEdge=Actor->EdgeLeft->GetLastBuffer().V;
	FStreetOwnedJunction Broken=Actor->OwnedJunctions[0];
	Broken.Junction.Id=TEXT("j_missing_arms");Broken.Arms.Reset();
	Actor->OwnedJunctions.Add(MoveTemp(Broken));
	TestFalse(TEXT("one successful junction cannot hide a second failed junction"),Actor->RebuildAllChecked(&Error));
	TestTrue(TEXT("failure reports partial coverage"),Error.Contains(TEXT("built only 1")));
	TestTrue(TEXT("failed junction rebuild keeps complete road buffer"),Actor->Road->GetLastBuffer().V==BeforeRoad);
	TestTrue(TEXT("failed junction rebuild keeps complete edge buffer"),Actor->EdgeLeft->GetLastBuffer().V==BeforeEdge);
	World->DestroyWorld(false);return true;
}
