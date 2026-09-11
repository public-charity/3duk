#include "../StreetscapeDocumentEdit.h"
#include "../../../Streetscape/Private/Tests/StreetTestUtil.h"
using namespace StreetTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetInteriorBendPreviewTest,"Streetscape.Editor.InteriorBendPreview",
	EAutomationTestFlags::EditorContext|EAutomationTestFlags::ProductFilter)
bool FStreetInteriorBendPreviewTest::RunTest(const FString&)
{
	FStreetSiteDoc Source;if (!LoadDoc(*this,FixturesDir()/TEXT("straight_100.json"),Source)) return false;
	Source.Junctions.Reset();auto Candidate=Source;
	FStreetJunction J;J.Id=TEXT("bend:test");J.Kind=EStreetJunctionKind::Bend;J.X=50.;J.Y=0.;J.CornerHandleFrac=.65;
	FStreetJunctionEnd Lo,Hi;Lo.SplineId=Hi.SplineId=Source.Splines[0].Id;
	Lo.End=EStreetSplineEnd::End;Lo.StationM=44.;Hi.End=EStreetSplineEnd::Start;Hi.StationM=58.;J.Ends={Lo,Hi};Candidate.Junctions.Add(J);
	FString Error;TestTrue(TEXT("one original-definition interior bend accepted"),StreetDocumentEdit::ValidatePreview(Source,Candidate,Error));
	for (const FString Mode : {TEXT("changed_definition"),TEXT("wrong_control"),TEXT("overlap"),TEXT("trim_radius"),TEXT("endpoint_binding"),TEXT("station_order"),TEXT("missing_station"),TEXT("nonfinite")})
	{
		auto Bad=Candidate;
		if (Mode==TEXT("changed_definition")) Bad.Splines[0].Points[1].WidthM=9.;
		else if (Mode==TEXT("wrong_control")) Bad.Junctions[0].Y=.01;
		else if (Mode==TEXT("overlap")) { auto Other=J;Other.Id=TEXT("bend:other");Bad.Junctions.Add(Other); }
		else if (Mode==TEXT("trim_radius")) Bad.Junctions[0].TrimRadiusM=6.;
		else if (Mode==TEXT("endpoint_binding")) Bad.Splines[0].JunctionStart=J.Id;
		else if (Mode==TEXT("station_order")) Bad.Junctions[0].Ends[0].StationM=60.;
		else if (Mode==TEXT("missing_station")) Bad.Junctions[0].Ends[1].StationM.Reset();
		else Bad.Junctions[0].Ends[0].StationM=NAN;
		TestFalse(Mode+TEXT(" preview rejected"),StreetDocumentEdit::ValidatePreview(Source,Bad,Error));
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetConnectorPreviewBatchTest,"Streetscape.Editor.ConnectorPreviewBatchLimit",
	EAutomationTestFlags::EditorContext|EAutomationTestFlags::ProductFilter)
bool FStreetConnectorPreviewBatchTest::RunTest(const FString&)
{
	FStreetSiteDoc Unit;FJunctionSiteBuild Built;if (!BuildJunctionSite(*this,TEXT("junction_connector_reverse"),Unit,Built)) return false;
	for (int32 Count : {11,16,17})
	{
		auto Candidate=Unit;Candidate.Splines.Reset();Candidate.Junctions.Reset();
		for (int32 I=0;I<Count;++I)
		{
			const FString Suffix=FString::Printf(TEXT("_%d"),I);auto J=Unit.Junctions[0];J.Id+=Suffix;J.X+=30.*I;
			for (auto& E : J.Ends) E.SplineId+=Suffix;
			Candidate.Junctions.Add(J);
			for (auto D : Unit.Splines)
			{
				D.Id+=Suffix;
				for (auto& P : D.Points) P.X+=30.*I;
				for (FString* Id : {&D.JunctionStart,&D.JunctionEnd,&D.ContinuesFrom,&D.ContinuesTo}) if (!Id->IsEmpty()) *Id+=Suffix;
				Candidate.Splines.Add(D);
			}
		}
		auto Source=Candidate;Source.Junctions.Reset();for (auto& D : Source.Splines) { D.JunctionStart.Reset();D.JunctionEnd.Reset(); }
		FString Error;TestEqual(FString::Printf(TEXT("%d unique connectors bounded preview"),Count),StreetDocumentEdit::ValidatePreview(Source,Candidate,Error),Count<=16);
	}
	return true;
}
