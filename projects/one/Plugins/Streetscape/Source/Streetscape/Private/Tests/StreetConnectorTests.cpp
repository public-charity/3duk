#include "StreetTestUtil.h"
using namespace StreetTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetConnectorValidationTest, "Streetscape.Junction.ConnectorValidation",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetConnectorValidationTest::RunTest(const FString&)
{
	const auto Original = JunctionFixture(*this,TEXT("junction_connector_bend"));
	if (!Original) return false;
	FStreetSiteDoc Doc; TArray<FString> Errors;
	if (!TestTrue(TEXT("connector fixture parses"),FStreetscapeJson::ReadSite(Original.ToSharedRef(),Doc,Errors))) return false;
	TestEqual(TEXT("complete connector round trip"),FStreetscapeJson::Canonical(FStreetscapeJson::WriteSite(Doc)),FStreetscapeJson::Canonical(Original.ToSharedRef()));
	FStreetJunctionPlan Plan; Plan.Build(Doc);
	TestTrue(TEXT("two-arm spec builds"),Plan.SpecFor(TEXT("j0")).IsValid());
	FStreetOwnedJunction Owned; Owned.Junction=Doc.Junctions[0]; Owned.Arms.SetNum(2);
	TestTrue(TEXT("stored two-arm owner remains valid"),Owned.ToSpec().IsValid());
	TestEqual(TEXT("stored owner retains local handle cap"),Owned.ToSpec().CornerHandleFraction(),1.);
	for (double Value : { -1.,0.,1.01 })
	{
		auto Bad=FStreetscapeJson::WriteSite(Doc);Bad->GetArrayField(TEXT("junctions"))[0]->AsObject()->SetNumberField(TEXT("corner_handle_frac"),Value);
		FStreetSiteDoc Rejected;Errors.Reset();TestFalse(TEXT("invalid handle cap rejected"),FStreetscapeJson::ReadSite(Bad,Rejected,Errors));
	}
	for (const FString Case : {TEXT("one"),TEXT("duplicate"),TEXT("missing"),TEXT("unbound"),TEXT("off_node"),TEXT("no_road"),TEXT("rail")})
	{
		auto Bad=FStreetscapeJson::WriteSite(Doc);auto J=Bad->GetArrayField(TEXT("junctions"))[0]->AsObject();auto Ends=J->GetArrayField(TEXT("ends"));
		auto Sp=Bad->GetArrayField(TEXT("splines"))[0]->AsObject();
		if (Case==TEXT("one")) { Ends.SetNum(1);J->SetArrayField(TEXT("ends"),Ends); }
		else if (Case==TEXT("duplicate")) { Ends[1]=Ends[0];J->SetArrayField(TEXT("ends"),Ends); }
		else if (Case==TEXT("missing")) Ends[1]->AsObject()->SetStringField(TEXT("spline_id"),TEXT("authored:missing"));
		else if (Case==TEXT("unbound")) Sp->SetField(TEXT("junction_start"),MakeShared<FJsonValueNull>());
		else if (Case==TEXT("off_node")) J->SetNumberField(TEXT("x"),J->GetNumberField(TEXT("x"))+1.);
		else if (Case==TEXT("no_road")) Sp->GetObjectField(TEXT("profile_ids"))->SetField(TEXT("road"),MakeShared<FJsonValueNull>());
		else Bad->GetObjectField(TEXT("profiles"))->GetObjectField(TEXT("road"))->GetObjectField(TEXT("road_test_marked"))->SetStringField(TEXT("kind"),TEXT("rail"));
		FStreetSiteDoc Rejected;Errors.Reset();TestFalse(Case+TEXT(" connector rejected"),FStreetscapeJson::ReadSite(Bad,Rejected,Errors));
	}
	for (bool Null : { false,true })
	{
		auto Raw=FStreetscapeJson::WriteSite(Doc);auto J=Raw->GetArrayField(TEXT("junctions"))[0]->AsObject();
		if (Null) J->SetField(TEXT("corner_handle_frac"),MakeShared<FJsonValueNull>());else J->RemoveField(TEXT("corner_handle_frac"));
		FStreetSiteDoc Parsed;Errors.Reset();TestTrue(TEXT("optional handle parses"),FStreetscapeJson::ReadSite(Raw,Parsed,Errors));
		TestEqual(TEXT("null or absent handle round trip"),FStreetscapeJson::Canonical(FStreetscapeJson::WriteSite(Parsed)),FStreetscapeJson::Canonical(Raw));
		FStreetJunctionPlan Defaults;Defaults.Build(Parsed);TestEqual(TEXT("default handle cap"),Defaults.SpecFor(TEXT("j0")).CornerHandleFraction(),.45);
	}
	Doc.Junctions[0].Kind=EStreetJunctionKind::Disc;Plan.Build(Doc);
	TestFalse(TEXT("legacy two-arm disc remains unbuilt"),Plan.SpecFor(TEXT("j0")).IsValid());
	return true;
}
