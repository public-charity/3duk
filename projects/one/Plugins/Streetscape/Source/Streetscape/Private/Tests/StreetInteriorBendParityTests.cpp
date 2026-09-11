#include "StreetTestUtil.h"
using namespace StreetTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetInteriorBendParityTest,"Streetscape.Junction.InteriorBendParity",
	EAutomationTestFlags::EditorContext|EAutomationTestFlags::ProductFilter)
bool FStreetInteriorBendParityTest::RunTest(const FString&)
{
	const FString Path=FPlatformMisc::GetEnvironmentVariable(TEXT("STREETSCAPE_PARITY_JSON"));
	TSharedPtr<FJsonObject> Reference;
	if (Path.IsEmpty() || !LoadJson(*this,Path,Reference)) { AddError(TEXT("interior bend parity reference missing")); return false; }
	auto Compare=[&](const TSharedPtr<FJsonObject>& Obj,const FString& Label,const FString& Field,const TArray<double>& Mine,double Tolerance)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values=nullptr;
		if (!Obj->TryGetArrayField(Field,Values)) { AddError(TEXT("missing array ")+Label); return; }
		if (!TestEqual(Label+TEXT(" count"),Mine.Num(),Values->Num())) return;
		double MaxDiff=0.;
		for (int32 I=0;I<Mine.Num();++I)
		{
			if (!FMath::IsFinite(Mine[I]) || (*Values)[I]->Type!=EJson::Number || !FMath::IsFinite((*Values)[I]->AsNumber()))
			{ AddError(TEXT("nonfinite or nonnumeric array ")+Label); return; }
			MaxDiff=FMath::Max(MaxDiff,FMath::Abs(Mine[I]-(*Values)[I]->AsNumber()));
		}
		AddInfo(FString::Printf(TEXT("%s: %d values, max difference %.12g"),*Label,Mine.Num(),MaxDiff));
		TestTrue(Label+TEXT(" parity"),MaxDiff<=Tolerance);
	};
	auto Names=[&](const TSharedPtr<FJsonObject>& Obj,const FString& Label,const FString& Field,const TArray<FName>& Mine)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values=nullptr;
		if (!Obj->TryGetArrayField(Field,Values)) { AddError(TEXT("missing names ")+Label); return; }
		if (!TestEqual(Label+TEXT(" count"),Mine.Num(),Values->Num())) return;
		for (int32 I=0;I<Mine.Num();++I) TestEqual(Label,Mine[I].ToString(),(*Values)[I]->AsString());
	};
	for (const FString Fixture : {TEXT("junction_interior_bend"),TEXT("junction_interior_bend_garrard")})
	{
		FStreetSiteDoc Doc;FJunctionSiteBuild Built;if (!BuildJunctionSite(*this,Fixture,Doc,Built)) return false;
		const TSharedPtr<FJsonObject>* Cases=nullptr;
		if (!Reference->TryGetObjectField(Fixture,Cases)) { AddError(TEXT("missing bend case ")+Fixture); continue; }
		for (const auto& Def : Doc.Splines)
		{
			const TSharedPtr<FJsonObject>* Row=nullptr;if (!(*Cases)->TryGetObjectField(Def.Id,Row)) { AddError(TEXT("missing bend spline ")+Def.Id); continue; }
			const FString Prefix=Fixture+TEXT(".")+Def.Id;
			const auto& Samples=Built.Samples.FindChecked(Def.Id);TArray<double> Active;
			for (bool Value : Samples.Active) Active.Add(Value ? 1. : 0.);
			Compare(*Row,Prefix+TEXT(".s"),TEXT("s"),Samples.S,1e-9);
			Compare(*Row,Prefix+TEXT(".active"),TEXT("active"),Active,0.);
			Compare(*Row,Prefix+TEXT(".trim"),TEXT("trim"),{Samples.STrim[0],Samples.STrim[1]},1e-9);
			const auto& Meshes=Built.Builds.FindChecked(Def.Id);
			const TArray<TPair<FString,const FStreetMeshBuilder*>> Parts={{TEXT("road"),&Meshes.Road.Buffer},{TEXT("left"),&Meshes.EdgeL.Buffer},{TEXT("right"),&Meshes.EdgeR.Buffer}};
			for (const auto& Part : Parts)
			{
				const TSharedPtr<FJsonObject>* Expected=nullptr;
				if (!(*Row)->TryGetObjectField(Part.Key,Expected)) { AddError(TEXT("missing bend surface ")+Part.Key); continue; }
				const auto& Mesh=*Part.Value;TArray<double> V,F,Mat,Grp;
				for (const auto& P : Mesh.V) { V.Add(P.X);V.Add(P.Y);V.Add(P.Z); }
				for (const auto& Face : Mesh.F) { F.Add(Face.A);F.Add(Face.B);F.Add(Face.C); }
				for (auto Value : Mesh.Mat) Mat.Add(Value);for (auto Value : Mesh.Grp) Grp.Add(Value);
				const FString Label=Prefix+TEXT(".")+Part.Key;
				Compare(*Expected,Label+TEXT(".v"),TEXT("v"),V,1e-9);
				Compare(*Expected,Label+TEXT(".f"),TEXT("f"),F,0.);
				Compare(*Expected,Label+TEXT(".vs"),TEXT("vs"),Mesh.VS,1e-9);
				Compare(*Expected,Label+TEXT(".vd"),TEXT("vd"),Mesh.VD,1e-9);
				Compare(*Expected,Label+TEXT(".vh"),TEXT("vh"),Mesh.VH,1e-9);
				Compare(*Expected,Label+TEXT(".mat"),TEXT("mat"),Mat,0.);
				Compare(*Expected,Label+TEXT(".grp"),TEXT("grp"),Grp,0.);
				Names(*Expected,Label+TEXT(".materials"),TEXT("material_names"),Mesh.MaterialNames);
				Names(*Expected,Label+TEXT(".groups"),TEXT("group_names"),Mesh.GroupNames);
			}
			TArray<double> Transforms,Sizes,Sides;TArray<FName> Kinds,Materials;
			for (const auto* Part : {&Meshes.Road,&Meshes.EdgeL,&Meshes.HedgeL,&Meshes.EdgeR,&Meshes.HedgeR})
				for (const auto& I : Part->Instances)
				{
					Transforms.Append({I.Th.X,I.N.X,I.B.X,I.P.X,I.Th.Y,I.N.Y,I.B.Y,I.P.Y,I.Th.Z,I.N.Z,I.B.Z,I.P.Z,0.,0.,0.,1.});
					Sizes.Append({I.Size.X,I.Size.Y,I.Size.Z});Sides.Add(I.Side);Kinds.Add(I.Kind);Materials.Add(I.Material);
				}
			Compare(*Row,Prefix+TEXT(".instance_transforms"),TEXT("instance_transforms"),Transforms,1e-9);
			Compare(*Row,Prefix+TEXT(".instance_sizes"),TEXT("instance_sizes"),Sizes,0.);
			Compare(*Row,Prefix+TEXT(".instance_sides"),TEXT("instance_sides"),Sides,0.);
			Names(*Row,Prefix+TEXT(".instance_kinds"),TEXT("instance_kinds"),Kinds);
			Names(*Row,Prefix+TEXT(".instance_materials"),TEXT("instance_materials"),Materials);
		}
	}
	return true;
}
