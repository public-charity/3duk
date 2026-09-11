#include "StreetTestUtil.h"
using namespace StreetTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetArmTrimParityTest, "Streetscape.Junction.ArmTrimParity",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetArmTrimParityTest::RunTest(const FString&)
{
	FStreetSiteDoc Doc;
	FJunctionSiteBuild Built;
	if (!BuildJunctionSite(*this,TEXT("junction_arm_trims"),Doc,Built)) return false;
	const auto Original = JunctionFixture(*this,TEXT("junction_arm_trims"));
	TestEqual(TEXT("per-arm values and explicit null round trip"),FStreetscapeJson::Canonical(FStreetscapeJson::WriteSite(Doc)),
		FStreetscapeJson::Canonical(Original.ToSharedRef()));
	for (double Invalid : { -1.,0.,33. })
	{
		const auto Bad = FStreetscapeJson::WriteSite(Doc);
		Bad->GetArrayField(TEXT("junctions"))[0]->AsObject()->GetArrayField(TEXT("ends"))[0]->AsObject()->SetNumberField(TEXT("trim_radius_m"),Invalid);
		FStreetSiteDoc Rejected;TArray<FString> Errors;
		TestFalse(TEXT("invalid per-arm radius rejected"),FStreetscapeJson::ReadSite(Bad,Rejected,Errors));
	}
	const FString Path = FPlatformMisc::GetEnvironmentVariable(TEXT("STREETSCAPE_PARITY_JSON"));
	TSharedPtr<FJsonObject> Reference;
	if (Path.IsEmpty() || !LoadJson(*this,Path,Reference)) { AddError(TEXT("arm trim parity reference missing")); return false; }
	const TSharedPtr<FJsonObject>* Cases = nullptr;
	if (!Reference->TryGetObjectField(TEXT("junction_arm_trims"),Cases)) { AddError(TEXT("arm trim reference case missing")); return false; }
	for (const auto& Def : Doc.Splines)
	{
		const TSharedPtr<FJsonObject>* Row = nullptr;
		if (!(*Cases)->TryGetObjectField(Def.Id,Row)) { AddError(TEXT("arm reference missing: ")+Def.Id); continue; }
		auto Compare = [&](const TSharedPtr<FJsonObject>& Obj,const FString& Label,const FString& Field,const TArray<double>& Mine,double Tolerance)
		{
			const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
			if (!Obj->TryGetArrayField(Field,Values)) { AddError(TEXT("missing array ")+Label); return; }
			if (!TestEqual(Label+TEXT(" count"),Mine.Num(),Values->Num())) return;
			double MaxDiff=0.;
			for (int32 I=0; I<Mine.Num(); ++I)
			{
				if ((*Values)[I]->Type!=EJson::Number || !FMath::IsFinite((*Values)[I]->AsNumber())) { AddError(TEXT("invalid array value ")+Label); return; }
				MaxDiff=FMath::Max(MaxDiff,FMath::Abs(Mine[I]-(*Values)[I]->AsNumber()));
			}
			AddInfo(FString::Printf(TEXT("%s: %d values, max difference %.12g"),*Label,Mine.Num(),MaxDiff));
			TestTrue(Label+TEXT(" parity"),MaxDiff<=Tolerance);
		};
		const auto& Samples=Built.Samples.FindChecked(Def.Id);
		Compare(*Row,Def.Id+TEXT(".s"),TEXT("s"),Samples.S,1e-9);
		Compare(*Row,Def.Id+TEXT(".trim"),TEXT("trim"),{Samples.STrim[0],Samples.STrim[1]},1e-9);
		const auto& Meshes=Built.Builds.FindChecked(Def.Id);
		const TArray<TPair<FString,const FStreetMeshBuilder*>> Parts={
			{TEXT("road"),&Meshes.Road.Buffer},{TEXT("left"),&Meshes.EdgeL.Buffer},{TEXT("right"),&Meshes.EdgeR.Buffer}};
		for (const auto& Part : Parts)
		{
			const TSharedPtr<FJsonObject>* Expected=nullptr;
			if (!(*Row)->TryGetObjectField(Part.Key,Expected)) { AddError(TEXT("missing arm surface ")+Part.Key); continue; }
			const auto& Mesh=*Part.Value;TArray<double> Vertices,Faces;
			for (const auto& P:Mesh.V) { Vertices.Add(P.X);Vertices.Add(P.Y);Vertices.Add(P.Z); }
			for (const auto& F:Mesh.F) { Faces.Add(F[0]);Faces.Add(F[1]);Faces.Add(F[2]); }
			const FString Label=Def.Id+TEXT(".")+Part.Key;
			Compare(*Expected,Label+TEXT(".v"),TEXT("v"),Vertices,1e-9);
			Compare(*Expected,Label+TEXT(".f"),TEXT("f"),Faces,0.);
			Compare(*Expected,Label+TEXT(".vs"),TEXT("vs"),Mesh.VS,1e-9);
			Compare(*Expected,Label+TEXT(".vd"),TEXT("vd"),Mesh.VD,1e-9);
			Compare(*Expected,Label+TEXT(".vh"),TEXT("vh"),Mesh.VH,1e-9);
		}
	}
	return true;
}
