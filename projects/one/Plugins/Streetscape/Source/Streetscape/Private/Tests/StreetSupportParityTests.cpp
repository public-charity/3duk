#include "StreetRenderTestUtil.h"
using namespace StreetTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetSupportParityTest, "Streetscape.Edge.SupportNumpyParity",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetSupportParityTest::RunTest(const FString& Parameters)
{
	const FString Path = FPlatformMisc::GetEnvironmentVariable(TEXT("STREETSCAPE_PARITY_JSON"));
	TSharedPtr<FJsonObject> Reference;
	if (Path.IsEmpty() || !LoadJson(*this, Path, Reference)) { AddError(TEXT("support parity reference missing")); return false; }
	for (const FString Kind : { FString(TEXT("batter")), FString(TEXT("retaining_wall")) })
	{
		const auto Doc = FixtureCopy(*this,TEXT("straight_100"));
		if (!Doc.IsValid()) return false;
		FirstSpline(Doc)->SetArrayField(TEXT("elevation_profile"), {
			SegmentFromText(TEXT("{\"s_m\":0,\"z_m\":11.5,\"bank_deg\":12}")),
			SegmentFromText(TEXT("{\"s_m\":100,\"z_m\":11.5,\"bank_deg\":12}")) });
		SetSegments(Doc,{FString::Printf(TEXT("{\"id\":\"support\",\"s0_m\":0,\"s1_m\":null,\"side\":\"both\",\"edge\":{\"embankment\":{\"kind\":\"%s\",\"side\":\"both\",\"material\":\"grass\",\"threshold_m\":0.01}}}"),*Kind)});
		const auto Terrain = FStreetHeightfield::FromFunction([&](double, double Y) { return Kind==TEXT("batter") ? 10.0-0.2*Y : 10.0; },
			FVector2d(512,512),1.0,512.0,FVector2d::ZeroVector,FVector2d(0,-256));
		FBuiltStreet Built;
		if (!Built.Build(*this,Doc.ToSharedRef(),&Terrain)) return false;
		const TSharedPtr<FJsonObject>* Case = nullptr;
		if (!Reference->TryGetObjectField(TEXT("support_")+Kind,Case)) { AddError(TEXT("missing support parity case: ")+Kind); continue; }
		for (int32 K=0; K<2; ++K)
		{
			const FString Side = K==0 ? TEXT("left") : TEXT("right");
			const TSharedPtr<FJsonObject>* Row = nullptr;
			if (!(*Case)->TryGetObjectField(Side,Row)) { AddError(TEXT("missing support side: ")+Side); continue; }
			TestEqual(TEXT("support built without problems"),Built.Edge[K].Problems.Num(),0);
			const auto& Mesh = Built.Edge[K].Buffer;
			auto Compare = [&](const FString& Field,const TArray<double>& Mine,double Tolerance)
			{
				const FString Label = Kind+TEXT(".")+Side+TEXT(".")+Field;
				const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
				if (!(*Row)->TryGetArrayField(Field,Values)) { AddError(TEXT("missing array ")+Label); return; }
				if (!TestEqual(Label+TEXT(" count"),Mine.Num(),Values->Num())) return;
				double MaxDiff=0;
				for (int32 I=0; I<Mine.Num(); ++I)
				{
					if ((*Values)[I]->Type!=EJson::Number || !FMath::IsFinite((*Values)[I]->AsNumber())) { AddError(TEXT("invalid reference ")+Label); return; }
					MaxDiff=FMath::Max(MaxDiff,FMath::Abs(Mine[I]-(*Values)[I]->AsNumber()));
				}
				AddInfo(FString::Printf(TEXT("%s: %d values, max difference %.12g"),*Label,Mine.Num(),MaxDiff));
				TestTrue(Label+TEXT(" parity"),MaxDiff<=Tolerance);
			};
			TArray<double> Vertices,Faces;
			for (const auto& P : Mesh.V) { Vertices.Add(P.X); Vertices.Add(P.Y); Vertices.Add(P.Z); }
			for (const auto& F : Mesh.F) { Faces.Add(F[0]); Faces.Add(F[1]); Faces.Add(F[2]); }
			Compare(TEXT("v"),Vertices,1e-9);
			Compare(TEXT("f"),Faces,0.0);
			Compare(TEXT("vs"),Mesh.VS,1e-9);
			Compare(TEXT("vd"),Mesh.VD,1e-9);
			Compare(TEXT("vh"),Mesh.VH,1e-9);
		}
	}
	return true;
}
