#include "../StreetscapeDocumentEdit.h"
#include "../../../Streetscape/Private/Tests/StreetTestUtil.h"
#include "StreetJunctionBuild.h"

using namespace StreetTest;
namespace
{
TArray<FStreetDocumentActorState> Snapshot(const FStreetSiteDoc& Doc)
{
	TArray<FStreetDocumentActorState> States;
	for (const FStreetSplineDef& D : Doc.Splines)
		States.Add({D.Id, FVector2D(Doc.Origin.E, Doc.Origin.N), D, Doc.Profiles});
	return States;
}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetDocumentRoundTripTest, "Streetscape.Editor.DocumentRoundTrip",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetDocumentRoundTripTest::RunTest(const FString&)
{
	for (const FString& Name : JunctionFixtureNames())
	{
		FStreetSiteDoc Source, Out;
		FJunctionSiteBuild Built;
		if (!BuildJunctionSite(*this, Name, Source, Built)) continue;
		FString Error;
		auto States = Snapshot(Source);
		TestTrue(Name + TEXT(" assembles"), StreetDocumentEdit::Assemble(Source, States, Out, Error));
		TestEqual(Name + TEXT(" complete canonical roundtrip"), FStreetscapeJson::Canonical(FStreetscapeJson::WriteSite(Out)),
			FStreetscapeJson::Canonical(FStreetscapeJson::WriteSite(Source)));
		// Change a non-owner arm away from its junction endpoint; the next solve must carry the live definition.
		const FString Owner = Built.Plan.Owner(TEXT("j0"));
		int32 Index = 0;
		while (States[Index].Id == Owner) ++Index;
		States[Index].Def.Points.Last().X += 0.5;
		TestTrue(Name + TEXT(" edit assembles"), StreetDocumentEdit::Assemble(Source, States, Out, Error));
		FStreetJunctionPlan Plan;
		Plan.Build(Out);
		TMap<FString, FVector2D> Trims;
		TMap<FString, TArray<FStreetOwnedJunction>> Owned;
		FStreetJunctionBuild::Distribute(Out, Plan, Trims, Owned);
		bool Found = false;
		for (const auto& Pair : Owned)
			for (const auto& J : Pair.Value)
				for (const auto& R : J.Arms)
					if (!R.bIsOwner && R.Arm.SplineId == States[Index].Id)
					{
						Found = true;
						TestEqual(Name + TEXT(" owner carries edited arm"), R.Def.Points.Last().X, States[Index].Def.Points.Last().X);
					}
		TestTrue(Name + TEXT(" changed arm reached owner"), Found);
		// Intentionally disabled junctions are still source data and must survive export too.
		Source.Junctions[0].Kind = EStreetJunctionKind::None;
		TestTrue(Name + TEXT(" disabled junction assembles"), StreetDocumentEdit::Assemble(Source, States, Out, Error));
		TestEqual(Name + TEXT(" disabled junction preserved"), Out.Junctions.Num(), 1);
		TestTrue(Name + TEXT(" disabled kind preserved"), Out.Junctions[0].Kind == EStreetJunctionKind::None);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetDocumentRejectionTest, "Streetscape.Editor.DocumentRejectsIncomplete",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetDocumentRejectionTest::RunTest(const FString&)
{
	FStreetSiteDoc Source, Out;
	FJunctionSiteBuild Built;
	if (!BuildJunctionSite(*this, TEXT("junction_crossroads"), Source, Built)) return false;
	FString Error;
	const auto Original = Snapshot(Source);
	auto States = Original;
	States.Pop();
	TestFalse(TEXT("unloaded arm rejected"), StreetDocumentEdit::Assemble(Source, States, Out, Error));
	TestTrue(TEXT("unloaded arm named"), Error.Contains(Original.Last().Id));
	States = Original;
	const FStreetDocumentActorState Duplicate = States[0];
	States.Add(Duplicate);
	TestFalse(TEXT("duplicate ID rejected"), StreetDocumentEdit::Assemble(Source, States, Out, Error));
	States = Original;
	States[0].OriginEN.X += 1;
	TestFalse(TEXT("wrong origin rejected"), StreetDocumentEdit::Assemble(Source, States, Out, Error));
	States = Original;
	States[0].Def.Id += TEXT("_renamed");
	TestFalse(TEXT("renamed spline rejected"), StreetDocumentEdit::Assemble(Source, States, Out, Error));
	States = Original;
	const FString ProfileId = States[0].Def.ProfileIds.Road;
	States[1].Def.ProfileIds.Road = ProfileId;
	States[1].Profiles.Road[ProfileId].WidthM += 1;
	TestFalse(TEXT("conflicting shared profile rejected"), StreetDocumentEdit::Assemble(Source, States, Out, Error));
	TestTrue(TEXT("conflicting profile named"), Error.Contains(ProfileId));
	States = Original;
	States[0].Profiles.Road.Remove(ProfileId);
	TestFalse(TEXT("missing profile rejected"), StreetDocumentEdit::Assemble(Source, States, Out, Error));
	return true;
}
