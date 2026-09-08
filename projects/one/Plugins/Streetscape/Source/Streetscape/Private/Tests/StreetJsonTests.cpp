// Streetscape.Json.SchemaFixtures / RoundTrip (UE_PLAN.md 2.11, 2.13; SCHEMA.md 8): the two example documents and the
// 20 library profiles load unchanged through the strict reader; a document written back by the C++ writer is
// byte-equal to the input after canonical ordering (sorted keys) and 1e-6 rounding.

#include "StreetTestUtil.h"
#include "HAL/FileManager.h"

using namespace StreetTest;

namespace
{
constexpr EAutomationTestFlags kFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

void ReportDiff(FAutomationTestBase& T, const FString& What, const FString& A, const FString& B)
{
	int32 I = 0;
	while (I < A.Len() && I < B.Len() && A[I] == B[I]) ++I;
	const int32 From = FMath::Max(0, I - 80);
	T.AddError(FString::Printf(TEXT("%s: first difference at %d of %d/%d\n  original: ...%s\n  written : ...%s"), *What, I, A.Len(), B.Len(),
		*A.Mid(From, 200).Replace(TEXT("\n"), TEXT("\\n")), *B.Mid(From, 200).Replace(TEXT("\n"), TEXT("\\n"))));
}

bool RoundTripFile(FAutomationTestBase& T, const FString& Path)
{
	TSharedPtr<FJsonObject> Original;
	if (!LoadJson(T, Path, Original)) return false;
	FStreetSiteDoc Doc;
	TArray<FString> Problems;
	if (!FStreetscapeJson::ReadSite(Original.ToSharedRef(), Doc, Problems))
	{
		T.AddError(FString::Printf(TEXT("%s: %s"), *Path, *FString::Join(Problems, TEXT(" | "))));
		return false;
	}
	const TSharedRef<FJsonObject> Written = FStreetscapeJson::WriteSite(Doc);
	const FString A = FStreetscapeJson::Canonical(Original.ToSharedRef());
	const FString B = FStreetscapeJson::Canonical(Written);
	const FString Name = FPaths::GetCleanFilename(Path);
	if (A != B) { ReportDiff(T, Name + TEXT(" canonical round trip"), A, B); return false; }
	T.AddInfo(FString::Printf(TEXT("%s: canonical round trip byte-equal (%d chars)"), *Name, A.Len()));
	// stability: the pretty text re-parses and re-canonicalises to the same bytes
	const FString Pretty = FStreetscapeJson::ToText(Written, false, 1, -1);
	TSharedPtr<FJsonObject> Again;
	FText Err;
	if (!FStreetscapeJson::ParseString(Pretty, Again, &Err)) { T.AddError(Name + TEXT(": pretty output does not parse: ") + Err.ToString()); return false; }
	FStreetSiteDoc Doc2;
	Problems.Reset();
	if (!FStreetscapeJson::ReadSite(Again.ToSharedRef(), Doc2, Problems)) { T.AddError(Name + TEXT(": pretty output invalid: ") + FString::Join(Problems, TEXT(" | "))); return false; }
	const FString C = FStreetscapeJson::Canonical(FStreetscapeJson::WriteSite(Doc2));
	if (A != C) { ReportDiff(T, Name + TEXT(" second pass"), A, C); return false; }
	T.TestTrue(Name + TEXT(": pretty text has LF only"), !Pretty.Contains(TEXT("\r")));
	return true;
}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetJsonSchemaFixturesTest, "Streetscape.Json.SchemaFixtures", kFlags)
bool FStreetJsonSchemaFixturesTest::RunTest(const FString& Parameters)
{
	// the two examples load unchanged
	for (const TCHAR* Name : { TEXT("test_stretch.json"), TEXT("synthetic_straight.json") })
	{
		const FString Path = ExamplesDir() / Name;
		TSharedPtr<FJsonObject> Obj;
		if (!LoadJson(*this, Path, Obj)) continue;
		TArray<FString> Problems;
		const bool bOk = FStreetscapeJson::ValidateStructure(Obj.ToSharedRef(), Problems);
		TestTrue(FString::Printf(TEXT("%s validates (%s)"), Name, *FString::Join(Problems, TEXT(" | "))), bOk);
		FStreetSiteDoc Doc;
		Problems.Reset();
		if (FStreetscapeJson::ReadSite(Obj.ToSharedRef(), Doc, Problems))
		{
			const TArray<FString> Warn = FStreetscapeJson::ValidateWarnings(Doc);
			TestEqual(FString::Printf(TEXT("%s: no warnings (%s)"), Name, *FString::Join(Warn, TEXT(" | "))), Warn.Num(), 0);
			TestEqual(FString::Printf(TEXT("%s: one spline"), Name), Doc.Splines.Num(), 1);
		}
	}
	{
		FStreetSiteDoc Doc;
		if (LoadDoc(*this, ExamplesDir() / TEXT("test_stretch.json"), Doc))
		{
			const FStreetSplineDef& Sp = Doc.Splines[0];
			TestEqual(TEXT("test_stretch: 15 points"), Sp.Points.Num(), 15);
			TestEqual(TEXT("test_stretch: 6 segments"), Sp.Segments.Num(), 6);
			TestEqual(TEXT("test_stretch: 2 drop kerbs"), Sp.DropKerbs.Num(), 2);
			TestEqual(TEXT("test_stretch: origin E"), Doc.Origin.E, 627680.0, 0.0);
			TestEqual(TEXT("test_stretch: hedge_right"), Sp.ProfileIds.HedgeRight, FString(TEXT("hedge_privet")));
			TestTrue(TEXT("test_stretch: hedge_left null"), Sp.ProfileIds.HedgeLeft.IsEmpty() && Sp.ProfileIds.IsNull(TEXT("hedge_left")));
			TestEqual(TEXT("test_stretch: sampling window 15"), Sp.Sampling.SmoothingWindowM.Get(0.0), 15.0, 0.0);
			TestTrue(TEXT("test_stretch: root _comment kept as a note"), Doc.Notes.Contains(TEXT("_comment")));
			TestTrue(TEXT("test_stretch: point _z_06 kept as a note"), Sp.Points[0].Notes.Contains(TEXT("_z_06")));
			TestTrue(TEXT("test_stretch: source _pav_m kept as a note"), Sp.Source.Notes.Contains(TEXT("_pav_m")));
			TestEqual(TEXT("test_stretch: wall_right barrier type"), (int32)Sp.Segments[2].Edge.Barrier.Type, (int32)EStreetBarrierType::BrickWall);
			TestEqual(TEXT("test_stretch: railing rails 3"), Sp.Segments[5].Edge.Barrier.RailsM.Num(), 3);
			TestEqual(TEXT("test_stretch: dyl marking s1 60"), Doc.Profiles.Road[TEXT("road_trinity")].Markings[1].S1M.Get(0.0), 60.0, 0.0);
			TestEqual(TEXT("test_stretch: junction radius"), Doc.Junctions[0].RadiusM.Get(0.0), 3.4, 0.0);
			TestEqual(TEXT("test_stretch: overlay 11 points, z carried"), Sp.Overlay.Pts.Num(), 11);
			TestTrue(TEXT("test_stretch: overlay pts have z"), Sp.Overlay.PtsHaveZ.Num() == 11 && Sp.Overlay.PtsHaveZ[0]);
			TestTrue(TEXT("test_stretch: continuation_kind from/to null"), Sp.bHasContinuationKind && Sp.ContinuationKind.From == EStreetContinuation::None);
		}
	}
	// the 20 library profiles: 13 road (incl. rail_standard), 6 edge, 1 hedge
	{
		FStreetSiteProfiles Lib;
		TArray<FString> Problems;
		const bool bOk = FStreetscapeJson::LoadProfileLibrary(ProfilesDir(), Lib, Problems);
		TestTrue(TEXT("profile library loads: ") + FString::Join(Problems, TEXT(" | ")), bOk);
		TestEqual(TEXT("library road profiles"), Lib.Road.Num(), 13);
		TestEqual(TEXT("library edge profiles"), Lib.Edge.Num(), 6);
		TestEqual(TEXT("library hedge profiles"), Lib.Hedge.Num(), 1);
		TestEqual(TEXT("library total 20"), Lib.Road.Num() + Lib.Edge.Num() + Lib.Hedge.Num(), 20);
		if (const FRoadProfileData* Rail = Lib.Road.Find(TEXT("rail_standard")))
		{
			TestTrue(TEXT("rail_standard kind rail with rail spec"), Rail->Kind == EStreetRoadKind::Rail && Rail->bHasRail);
			TestEqual(TEXT("rail_standard gauge"), Rail->Rail.GaugeM, 1.435, 0.0);
			TestEqual(TEXT("rail_standard sampling_defaults step"), Rail->SamplingDefaults.StepM.Get(0.0), 1.0, 0.0);
			const FStreetSamplingResolved R = FStreetSamplingResolved::Resolve(Rail->Kind, &Rail->SamplingDefaults, nullptr);
			TestEqual(TEXT("rail resolved passes"), R.SmoothingPasses, 2);
			TestEqual(TEXT("rail resolved gain"), R.CurvatureGain, 60.0, 0.0);
			TestEqual(TEXT("rail resolved min step (built-in)"), R.MinStepM, 0.25, 0.0);
		}
		if (const FEdgeProfileData* Wall = Lib.Edge.Find(TEXT("edge_wall_brick")))
		{
			TestEqual(TEXT("edge_wall_brick barrier list"), Wall->Barriers.Num(), 1);
			TestTrue(TEXT("edge_wall_brick s1_m null -> unset and NullKeys"), !Wall->Barriers[0].S1M.IsSet() && Wall->Barriers[0].IsNull(TEXT("s1_m")));
		}
	}
	// the strict reader refuses what SCHEMA.md 8 says it must
	{
		auto Refuses = [&](const TCHAR* What, TFunctionRef<void(TSharedRef<FJsonObject>)> Mutate, const TCHAR* Needle)
		{
			TSharedPtr<FJsonObject> Obj;
			if (!LoadJson(*this, ExamplesDir() / TEXT("synthetic_straight.json"), Obj)) return;
			Mutate(Obj.ToSharedRef());
			TArray<FString> Problems;
			const bool bOk = FStreetscapeJson::ValidateStructure(Obj.ToSharedRef(), Problems);
			const FString Joined = FString::Join(Problems, TEXT(" | "));
			TestTrue(FString::Printf(TEXT("refuses %s: %s"), What, *Joined), !bOk && Joined.Contains(Needle));
		};
		Refuses(TEXT("an unknown key"), [](TSharedRef<FJsonObject> O) { O->SetNumberField(TEXT("bogus"), 1); }, TEXT("unknown key 'bogus'"));
		Refuses(TEXT("a wrong frame"), [](TSharedRef<FJsonObject> O) { O->SetStringField(TEXT("frame"), TEXT("unreal cm")); }, TEXT("expected const"));
		Refuses(TEXT("a missing profile"), [](TSharedRef<FJsonObject> O) { O->GetArrayField(TEXT("splines"))[0]->AsObject()->GetObjectField(TEXT("profile_ids"))->SetStringField(TEXT("road"), TEXT("nope")); }, TEXT("not in profiles.road"));
		Refuses(TEXT("a non-integer lanes"), [](TSharedRef<FJsonObject> O) { O->GetObjectField(TEXT("profiles"))->GetObjectField(TEXT("road"))->GetObjectField(TEXT("road_test_marked"))->SetNumberField(TEXT("lanes"), 2.5); }, TEXT("expected integer"));
		Refuses(TEXT("a dashed marking without dash_m"), [](TSharedRef<FJsonObject> O) { O->GetObjectField(TEXT("profiles"))->GetObjectField(TEXT("road"))->GetObjectField(TEXT("road_test_marked"))->GetArrayField(TEXT("markings"))[0]->AsObject()->RemoveField(TEXT("dash_m")); }, TEXT("dashed marking needs"));
		Refuses(TEXT("overlap_m below the 0.03 floor"), [](TSharedRef<FJsonObject> O) { O->GetObjectField(TEXT("profiles"))->GetObjectField(TEXT("road"))->GetObjectField(TEXT("road_test_marked"))->SetNumberField(TEXT("overlap_m"), 0.01); }, TEXT("minimum"));
		Refuses(TEXT("a schema_version 2.x"), [](TSharedRef<FJsonObject> O) { O->SetStringField(TEXT("schema_version"), TEXT("2.0.0")); }, TEXT("not 1.x.y"));
		Refuses(TEXT("s1_m <= s0_m"), [](TSharedRef<FJsonObject> O)
		{
			TSharedRef<FJsonObject> Seg = MakeShared<FJsonObject>();
			Seg->SetNumberField(TEXT("s0_m"), 10); Seg->SetNumberField(TEXT("s1_m"), 5); Seg->SetStringField(TEXT("side"), TEXT("both"));
			O->GetArrayField(TEXT("splines"))[0]->AsObject()->SetArrayField(TEXT("segments"), { MakeShared<FJsonValueObject>(Seg) });
		}, TEXT("must be > s0_m"));
	}
	// number formatting used by the canonical form
	TestEqual(TEXT("FormatNumber(0.1)"), FStreetscapeJson::FormatNumber(0.1), FString(TEXT("0.1")));
	TestEqual(TEXT("FormatNumber(627680.0)"), FStreetscapeJson::FormatNumber(627680.0), FString(TEXT("627680")));
	TestEqual(TEXT("FormatNumber(1e-05)"), FStreetscapeJson::FormatNumber(1e-05), FString(TEXT("1e-05")));
	TestEqual(TEXT("FormatNumber(0.1 + 0.2, 6 decimals)"), FStreetscapeJson::FormatNumber(0.1 + 0.2, 6), FString(TEXT("0.3")));
	TestEqual(TEXT("FormatNumber(-0.0)"), FStreetscapeJson::FormatNumber(-0.0), FString(TEXT("0")));
	TestEqual(TEXT("FormatNumber(8099.98)"), FStreetscapeJson::FormatNumber(8099.98), FString(TEXT("8099.98")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetJsonRoundTripTest, "Streetscape.Json.RoundTrip", kFlags)
bool FStreetJsonRoundTripTest::RunTest(const FString& Parameters)
{
	RoundTripFile(*this, ExamplesDir() / TEXT("test_stretch.json"));
	RoundTripFile(*this, ExamplesDir() / TEXT("synthetic_straight.json"));
	// every library profile file: {kind, id, profile} -> structs -> JSON, canonical byte-equal
	TArray<FString> Files;
	IFileManager::Get().FindFiles(Files, *(ProfilesDir() / TEXT("*.json")), true, false);
	Files.Sort();
	int32 Ok = 0;
	for (const FString& Name : Files)
	{
		TSharedPtr<FJsonObject> Original;
		if (!LoadJson(*this, ProfilesDir() / Name, Original)) continue;
		FStreetProfileFile F;
		TArray<FString> Problems;
		if (!FStreetscapeJson::ReadProfileFile(Original.ToSharedRef(), F, Problems)) { AddError(Name + TEXT(": ") + FString::Join(Problems, TEXT(" | "))); continue; }
		const FString A = FStreetscapeJson::Canonical(Original.ToSharedRef());
		const FString B = FStreetscapeJson::Canonical(FStreetscapeJson::WriteProfileFile(F));
		if (A != B) { ReportDiff(*this, Name, A, B); continue; }
		++Ok;
	}
	TestEqual(TEXT("profile files round-tripped byte-equal"), Ok, 20);
	// SaveFile writes LF, no BOM, indent 1, and reads back identical
	{
		FStreetSiteDoc Doc;
		if (LoadDoc(*this, ExamplesDir() / TEXT("synthetic_straight.json"), Doc))
		{
			const FString Out = FPaths::ProjectSavedDir() / TEXT("Tests/roundtrip_synthetic_straight.json");
			IFileManager::Get().MakeDirectory(*FPaths::GetPath(Out), true);
			TestTrue(TEXT("SaveFile"), FStreetscapeJson::SaveFile(Out, FStreetscapeJson::WriteSite(Doc)));
			TArray<uint8> Bytes;
			FFileHelper::LoadFileToArray(Bytes, *Out);
			TestTrue(TEXT("no BOM"), Bytes.Num() > 3 && !(Bytes[0] == 0xEF && Bytes[1] == 0xBB && Bytes[2] == 0xBF));
			TestTrue(TEXT("no CR"), !Bytes.Contains((uint8)'\r'));
			TestTrue(TEXT("indent 1"), Bytes.Num() > 3 && Bytes[0] == '{' && Bytes[1] == '\n' && Bytes[2] == ' ' && Bytes[3] == '"');
			FStreetSiteDoc Back;
			if (LoadDoc(*this, Out, Back))
			{
				TestEqual(TEXT("saved file reads back with the same canonical form"), FStreetscapeJson::Canonical(FStreetscapeJson::WriteSite(Back)), FStreetscapeJson::Canonical(FStreetscapeJson::WriteSite(Doc)));
			}
		}
	}
	return true;
}
