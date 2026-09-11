#include "StreetTestUtil.h"
#include "StreetJunctionBuild.h"
#include "StreetSpline.h"
#include "Serialization/MemoryReader.h"
#include "Serialization/MemoryWriter.h"
#include "Serialization/ObjectAndNameAsStringProxyArchive.h"

using namespace StreetTest;
namespace
{
bool BendFixture(FAutomationTestBase& Test,FStreetSiteDoc& Doc)
{
	if (!LoadDoc(Test,FixturesDir()/TEXT("straight_100.json"),Doc)) return false;
	Doc.Junctions.Reset();
	FStreetJunction J; J.Id=TEXT("bend:test"); J.Kind=EStreetJunctionKind::Bend;
	J.X=50.;J.Y=0.;J.CornerHandleFrac=.65;
	FStreetJunctionEnd Lo,Hi;
	Lo.SplineId=Hi.SplineId=Doc.Splines[0].Id;
	Lo.End=EStreetSplineEnd::End;Lo.StationM=44.;
	Hi.End=EStreetSplineEnd::Start;Hi.StationM=58.;
	J.Ends={Lo,Hi};Doc.Junctions.Add(J);return true;
}
bool BuildSamples(FAutomationTestBase& Test,const FStreetSiteDoc& Doc,FStreetSamples& Sp)
{
	FStreetJunctionPlan Plan;
	if (!Test.TestTrue(TEXT("valid bend plan"),Plan.Build(Doc))) { Test.AddError(Plan.Error); return false; }
	FString Error;double Trim[2];Plan.TrimFor(Doc.Splines[0].Id,Trim);
	const FStreetHeightfield Field=FlatTerrain();FStreetHeightfieldSource Terrain(Field);
	return Test.TestTrue(TEXT("samples build with interior mask"),FStreetSplineMath::Build(Doc.Splines[0],Doc.Profiles,&Terrain,Sp,&Error,Trim,Plan.InteriorBendsFor(Doc.Splines[0].Id)));
}
bool NoFacesAcrossCut(const FStreetMeshBuilder& Mesh,double Lo,double Hi)
{
	for (const auto& Face : Mesh.F)
	{
		const double A=Mesh.VS[Face.A],B=Mesh.VS[Face.B],C=Mesh.VS[Face.C];
		if (!(FMath::Max3(A,B,C)<=Lo+1e-9 || FMath::Min3(A,B,C)>=Hi-1e-9)) return false;
	}
	return true;
}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetInteriorBendValidationTest,"Streetscape.Junction.InteriorBendValidation",
	EAutomationTestFlags::EditorContext|EAutomationTestFlags::ProductFilter)
bool FStreetInteriorBendValidationTest::RunTest(const FString&)
{
	FStreetSiteDoc Doc;if (!BendFixture(*this,Doc)) return false;
	const auto Raw=FStreetscapeJson::WriteSite(Doc);FStreetSiteDoc Parsed;TArray<FString> Errors;
	TestTrue(TEXT("bend schema parses"),FStreetscapeJson::ReadSite(Raw,Parsed,Errors));
	TestEqual(TEXT("complete bend round trip"),FStreetscapeJson::Canonical(Raw),FStreetscapeJson::Canonical(FStreetscapeJson::WriteSite(Parsed)));
	for (const FString Mode : {TEXT("two_ids"),TEXT("duplicate_ends"),TEXT("missing_station"),TEXT("legacy_station"),TEXT("trim"),TEXT("node"),TEXT("binding"),TEXT("steps_flag")})
	{
		auto Bad=Doc;auto& J=Bad.Junctions[0];
		if (Mode==TEXT("two_ids")) J.Ends[1].SplineId=TEXT("missing");
		else if (Mode==TEXT("duplicate_ends")) J.Ends[1].End=J.Ends[0].End;
		else if (Mode==TEXT("missing_station")) J.Ends[1].StationM.Reset();
		else if (Mode==TEXT("legacy_station")) J.Kind=EStreetJunctionKind::Disc;
		else if (Mode==TEXT("trim")) J.TrimRadiusM=6.;
		else if (Mode==TEXT("node")) J.Y=.01;
		else if (Mode==TEXT("binding")) Bad.Splines[0].JunctionStart=J.Id;
		else { Bad.Splines[0].bHasFlags=true;Bad.Splines[0].Flags.bSteps=true; }
		Errors.Reset();TestFalse(Mode+TEXT(" schema rejects"),FStreetscapeJson::ReadSite(FStreetscapeJson::WriteSite(Bad),Parsed,Errors));
	}
	for (const FString Mode : {TEXT("overlap"),TEXT("outside"),TEXT("wrong_control"),TEXT("short_head"),TEXT("short_tail")})
	{
		auto Bad=Doc;auto& J=Bad.Junctions[0];
		if (Mode==TEXT("overlap")) { auto Other=J;Other.Id=TEXT("bend:other");Bad.Junctions.Add(Other); }
		else if (Mode==TEXT("outside")) J.Ends[1].StationM=101.;
		else if (Mode==TEXT("wrong_control")) { J.Ends[0].StationM=25.;J.Ends[1].StationM=35.; }
		else if (Mode==TEXT("short_head")) J.Ends[0].StationM=.5;
		else { J.Ends[0].StationM=40.;J.Ends[1].StationM=99.5; }
		FStreetJunctionPlan Plan;TestFalse(Mode+TEXT(" plan rejects before actors change"),Plan.Build(Bad));
		TestFalse(TEXT("invalid plan status"),Plan.IsValid());TestTrue(TEXT("invalid plan exposes no patches"),Plan.BuiltJunctionIds().IsEmpty());
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetInteriorBendMasksTest,"Streetscape.Junction.InteriorBendMasks",
	EAutomationTestFlags::EditorContext|EAutomationTestFlags::ProductFilter)
bool FStreetInteriorBendMasksTest::RunTest(const FString&)
{
	FStreetSiteDoc Doc;if (!BendFixture(*this,Doc)) return false;
	FStreetSamples Masked,Original;auto Source=Doc;Source.Junctions.Reset();
	if (!BuildSamples(*this,Doc,Masked) || !BuildSamples(*this,Source,Original)) return false;
	TestEqual(TEXT("source length unchanged"),Masked.LengthM,Original.LengthM);
	TestTrue(TEXT("all original stations retained exactly"),Masked.S==Original.S);
	TestEqual(TEXT("one cut"),Masked.InteriorTrims.Num(),1);TestEqual(TEXT("two body runs"),Masked.ActiveRanges.Num(),2);
	for (int32 I=0;I<Masked.Num();++I) TestEqual(TEXT("active mask"),Masked.Active[I],Masked.S[I]<=44.+1e-12 || Masked.S[I]>=58.-1e-12);
	FStreetRenderResult Road;FStreetRenderBuild::BuildRoad(Masked,Road);
	TestTrue(TEXT("road and markings do not cross the cut"),NoFacesAcrossCut(Road.Buffer,44.,58.));
	FStreetJunctionPlan Plan;Plan.Build(Doc);TMap<FString,const FStreetSamples*> Samples;Samples.Add(Masked.Id,&Masked);
	FStreetMeshBuilder Patch,Corner;
	const auto PatchInfo=FStreetRenderBuild::BuildJunctionPatch(Plan.SpecFor(TEXT("bend:test")),Samples,Patch);
	const auto CornerInfo=FStreetRenderBuild::BuildJunctionCorners(Plan.SpecFor(TEXT("bend:test")),Samples,Corner);
	TestTrue(TEXT("bend patch builds"),PatchInfo.bBuilt);TestEqual(TEXT("two kerb corners"),CornerInfo.Corners,2);
	TestTrue(TEXT("bend patch has no excess area"),PatchInfo.OverlapAreaM2<=1e-4);
	const double BadTrim[2]={45.,0.};FStreetSamples Rejected;FString Error;
	TestFalse(TEXT("cut cannot intersect ordinary end trim"),FStreetSplineMath::Build(Doc.Splines[0],Doc.Profiles,nullptr,Rejected,&Error,BadTrim,Doc.Junctions));
	// A cached component must notice adding, changing and removing an interior mask.
	UStreetSplineComponent* Component=NewObject<UStreetSplineComponent>();Component->Def=Doc.Splines[0];
	const FStreetHeightfield Field=FlatTerrain();FStreetHeightfieldSource Terrain(Field);
	const FStreetSamples* Cached=Component->Build(&Terrain,Doc.Profiles,&Error);
	if (!TestNotNull(TEXT("unmasked cache"),Cached)) return false;
	TestTrue(TEXT("cache initially has no cuts"),Cached->InteriorTrims.IsEmpty());
	Cached=Component->Build(&Terrain,Doc.Profiles,&Error,false,nullptr,Doc.Junctions);
	if (!TestNotNull(TEXT("masked cache"),Cached)) return false;
	TestEqual(TEXT("cache sees added cut"),Cached->InteriorTrims.Num(),1);
	auto Changed=Doc.Junctions;Changed[0].Ends[0].StationM=43.;
	Cached=Component->Build(&Terrain,Doc.Profiles,&Error,false,nullptr,Changed);
	if (!TestNotNull(TEXT("changed cache"),Cached)) return false;
	TestEqual(TEXT("cache sees moved cut"),Cached->InteriorTrims[0].X,43.);
	Cached=Component->Build(&Terrain,Doc.Profiles,&Error);
	if (!TestNotNull(TEXT("restored cache"),Cached)) return false;
	TestTrue(TEXT("cache sees removed cut"),Cached->InteriorTrims.IsEmpty());
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetInteriorBendOwnershipTest,"Streetscape.Junction.InteriorBendOwnership",
	EAutomationTestFlags::EditorContext|EAutomationTestFlags::ProductFilter)
bool FStreetInteriorBendOwnershipTest::RunTest(const FString&)
{
	FStreetSiteDoc Doc;if (!BendFixture(*this,Doc)) return false;
	const FString First=Doc.Splines[0].Id,Second=TEXT("authored:next");
	auto Next=Doc.Splines[0];Next.Id=Second;for (auto& P : Next.Points) P.X+=100.;
	Doc.Splines[0].JunctionEnd=TEXT("join");Next.JunctionStart=TEXT("join");Doc.Splines.Add(Next);
	FStreetJunction Join;Join.Id=TEXT("join");Join.Kind=EStreetJunctionKind::Connector;Join.X=100.;Join.Y=0.;Join.TrimRadiusM=4.;
	FStreetJunctionEnd A,B;A.SplineId=First;A.End=EStreetSplineEnd::End;B.SplineId=Second;B.End=EStreetSplineEnd::Start;Join.Ends={A,B};Doc.Junctions.Add(Join);
	FStreetJunctionPlan Plan;if (!TestTrue(TEXT("bend plus endpoint connector plan"),Plan.Build(Doc))) return false;
	TMap<FString,FVector2D> Trims;TMap<FString,TArray<FStreetOwnedJunction>> Owned;TMap<FString,TArray<FStreetJunction>> Bends;
	FStreetJunctionBuild::Distribute(Doc,Plan,Trims,Owned,&Bends);
	TestEqual(TEXT("actor carries one bend"),Bends.FindRef(First).Num(),1);
	const FString Owner=Plan.Owner(Join.Id);TestEqual(TEXT("foreign spline owns endpoint connector"),Owner,Second);
	bool Found=false;for (const auto& J : Owned.FindRef(Owner)) for (const auto& R : J.Arms)
		if (!R.bIsOwner && R.Arm.SplineId==First) { Found=true;TestEqual(TEXT("foreign-arm copy retains bend"),R.InteriorBends.Num(),1); }
	TestTrue(TEXT("foreign arm exists"),Found);
	const FStreetHeightfield Field=FlatTerrain();FStreetHeightfieldSource Terrain(Field);FString Error;
	FStreetSamples OwnerSamples;const auto T=Trims.FindRef(Owner);const double Trim[2]={T.X,T.Y};
	if (!TestTrue(TEXT("owner alone builds"),FStreetSplineMath::Build(*Doc.FindSpline(Owner),Doc.Profiles,&Terrain,OwnerSamples,&Error,Trim,Bends.FindRef(Owner)))) return false;
	FStreetMeshBuilder Road,Edge;FStreetActorJunctionStats Stats;TArray<FString> Skips;
	FStreetJunctionBuild::BuildOwned(Owned.FindRef(Owner),Owner,OwnerSamples,Doc.Profiles,&Terrain,Road,Edge,Stats,Skips);
	TestEqual(TEXT("owner builds complete connector without a foreign actor"),Stats.Built,1);TestTrue(TEXT("nothing skipped"),Skips.IsEmpty());
	for (const FString Id : {First,Second})
	{
		const auto Records=Owned.FindRef(Id);TArray<FStreetOwnedJunction> Restored;
		for (auto Record : Records)
		{
			TArray<uint8> Bytes;
			FMemoryWriter MemoryOut(Bytes,true);FObjectAndNameAsStringProxyArchive Writer(MemoryOut,false);
			FStreetOwnedJunction::StaticStruct()->SerializeItem(Writer,&Record,nullptr);
			TestFalse(TEXT("owner write has no archive error"),Writer.IsError());
			FStreetOwnedJunction Loaded;FMemoryReader MemoryIn(Bytes,true);FObjectAndNameAsStringProxyArchive Reader(MemoryIn,false);
			FStreetOwnedJunction::StaticStruct()->SerializeItem(Reader,&Loaded,nullptr);
			TestFalse(TEXT("owner read has no archive error"),Reader.IsError());
			TestEqual(TEXT("complete saved record consumed"),MemoryIn.Tell(),int64(Bytes.Num()));
			Restored.Add(Loaded);
		}
		FStreetSamples Sp;const auto EndTrim=Trims.FindRef(Id);const double Pair[2]={EndTrim.X,EndTrim.Y};
		if (!TestTrue(TEXT("saved owner samples build"),FStreetSplineMath::Build(*Doc.FindSpline(Id),Doc.Profiles,&Terrain,Sp,&Error,Pair,Bends.FindRef(Id)))) return false;
		FStreetMeshBuilder BeforeA,BeforeB,AfterA,AfterB;FStreetActorJunctionStats BeforeStats,AfterStats;TArray<FString> BeforeSkips,AfterSkips;
		FStreetJunctionBuild::BuildOwned(Records,Id,Sp,Doc.Profiles,&Terrain,BeforeA,BeforeB,BeforeStats,BeforeSkips);
		FStreetJunctionBuild::BuildOwned(Restored,Id,Sp,Doc.Profiles,&Terrain,AfterA,AfterB,AfterStats,AfterSkips);
		TestEqual(TEXT("saved owner preserves all patch counts"),AfterStats.Built,BeforeStats.Built);TestTrue(TEXT("restored owner skips nothing"),AfterSkips.IsEmpty());
		for (const auto& PairOfMeshes : {TPair<const FStreetMeshBuilder*,const FStreetMeshBuilder*>(&BeforeA,&AfterA),{&BeforeB,&AfterB}})
		{
			const auto& X=*PairOfMeshes.Key;const auto& Y=*PairOfMeshes.Value;
			TestTrue(TEXT("serialized owner positions exact"),X.V==Y.V);
			TestTrue(TEXT("serialized owner stations and offsets exact"),X.VS==Y.VS && X.VD==Y.VD && X.VH==Y.VH);
			TestTrue(TEXT("serialized owner materials/groups exact"),X.Mat==Y.Mat && X.Grp==Y.Grp && X.MaterialNames==Y.MaterialNames && X.GroupNames==Y.GroupNames);
			TestEqual(TEXT("serialized owner face count exact"),X.F.Num(),Y.F.Num());
			for (int32 K=0;K<FMath::Min(X.F.Num(),Y.F.Num());++K) for (int32 C=0;C<3;++C) TestEqual(TEXT("serialized face index exact"),X.F[K][C],Y.F[K][C]);
		}
	}
	return true;
}
