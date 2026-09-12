#include "StreetscapeLandscapeImporter.h"
#include "StreetscapeJson.h"
#include "StreetscapeSiteActor.h"
#include "StreetscapeMassingActor.h"
#include "Editor.h"
#include "EngineUtils.h"
#include "Landscape.h"
#include "LandscapeComponent.h"
#include "LandscapeEdit.h"
#include "LandscapeEditLayer.h"
#include "LandscapeInfo.h"
#include "LandscapeLayerInfoObject.h"
#include "AssetCompilingManager.h"
#include "RenderingThread.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "WorldPartition/WorldPartition.h"
#include "WorldPartition/WorldPartitionHelpers.h"
#include "WorldPartition/WorldPartitionActorDescInstance.h"

int32 UStreetscapeLandscapeImporter::LoadLandscapeForReview(bool bIncludeMassing)
{
	UWorld* World=GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	UWorldPartition* WP=World ? World->GetWorldPartition() : nullptr;
	if (!WP || !IsRunningCommandlet()) return -1;
	static TArray<FWorldPartitionReference> References;
	int32 Count=0;
	auto Load=[&](const FWorldPartitionActorDescInstance* Desc)
	{
		References.Emplace(WP,Desc->GetGuid()); ++Count; return true;
	};
	FWorldPartitionHelpers::ForEachActorDescInstance<ALandscapeProxy>(WP,Load);
	if (bIncludeMassing) FWorldPartitionHelpers::ForEachActorDescInstance<AStreetscapeMassingActor>(WP,Load);
	return Count;
}

FString UStreetscapeLandscapeImporter::ApplyOffshoreTileJson(const FString& PatchPath,bool bPreflightOnly)
{
	TSharedRef<FJsonObject> R=MakeShared<FJsonObject>();
	auto Reply=[&](FString Error=FString()) {R->SetBoolField(TEXT("ok"),Error.IsEmpty());R->SetBoolField(TEXT("saved"),false);
		if(!Error.IsEmpty())R->SetStringField(TEXT("error"),Error);return FStreetscapeJson::ToText(R,false,1,-1);};
	if(!IsRunningCommandlet())return Reply(TEXT("offshore patches require commandlet isolation"));
	ALandscape* Land=FindLandscape();ULandscapeInfo* Info=Land?Land->GetLandscapeInfo():nullptr;
	if(!Info)return Reply(TEXT("landscape missing"));
	const FTransform Tr=Land->GetActorTransform();
	if(!Tr.GetRotation().Equals(FQuat::Identity,1e-8)||!Tr.GetScale3D().Equals(FVector(100,100,100),1e-8)||FMath::Abs(Tr.GetLocation().Z)>1e-8)
		return Reply(TEXT("unsupported landscape transform"));
	TSharedPtr<FJsonObject> J;FText Error;
	if(!FStreetscapeJson::LoadFile(PatchPath,J,&Error))return Reply(Error.ToString());
	if(J->GetStringField(TEXT("crs"))!=TEXT("EPSG:27700")||J->GetStringField(TEXT("vertical_datum"))!=TEXT("ODN"))return Reply(TEXT("unsupported patch datum"));
	UWorld* World=GEditor->GetEditorWorldContext().World();AStreetscapeSiteActor* Site=AStreetscapeSiteActor::Get(World);
	if(!Site||Site->Crs!=TEXT("EPSG:27700")||Site->OriginEN!=FVector2D(627680,163080))return Reply(TEXT("patch requires the reviewed Thanet site"));
	const int32 Size=J->GetIntegerField(TEXT("size")), N=Size*Size;
	if(Size<2||Size>513)return Reply(TEXT("patch must be at most one 512m tile"));
	const int32 XM=J->GetIntegerField(TEXT("x_m")), NYM=J->GetIntegerField(TEXT("north_y_m"));
	const FVector P=Tr.InverseTransformPosition(FVector(XM*100.,-NYM*100.,0));
	const int32 X1=FMath::RoundToInt(P.X),Y1=FMath::RoundToInt(P.Y),X2=X1+Size-1,Y2=Y1+Size-1;
	TArray<uint8> BeforeBytes,AfterBytes,HM,WM,Weights;
	auto Read=[&](const TCHAR* Key,int32 Bytes,TArray<uint8>& Dest){const FString Name=J->GetStringField(Key);
		return FPaths::GetCleanFilename(Name)==Name&&FFileHelper::LoadFileToArray(Dest,*(FPaths::GetPath(PatchPath)/Name))&&Dest.Num()==Bytes;};
	if(!Read(TEXT("before"),N*2,BeforeBytes)||!Read(TEXT("after"),N*2,AfterBytes)||!Read(TEXT("height_mask"),N,HM)||!Read(TEXT("water_mask"),N,WM)||!Read(TEXT("weights"),N*4,Weights))return Reply(TEXT("invalid patch payload"));
	FGuid Layer;const auto Layers=Land->GetEditLayersConst();
	if(Layers.Num()>1)return Reply(TEXT("multiple landscape edit layers require explicit composition"));
	if(Layers.Num()==1)Layer=Layers[0]->GetGuid();
	FHeightmapAccessor<false> HeightAccess(Info);HeightAccess.SetEditLayer(Layer);
	TMap<FIntPoint,uint16> Sparse;HeightAccess.GetDataFast(X1,Y1,X2,Y2,Sparse);
	TArray<uint16> Original,Desired;Original.Reserve(N);Desired.Reserve(N);
	const uint16* Before=reinterpret_cast<const uint16*>(BeforeBytes.GetData());const uint16* After=reinterpret_cast<const uint16*>(AfterBytes.GetData());
	int32 Mismatch=0,Changed=0,Painted=0;
	for(int32 Y=Y1;Y<=Y2;++Y)for(int32 X=X1;X<=X2;++X)
	{
		const uint16* V=Sparse.Find(FIntPoint(X,Y));if(!V)return Reply(TEXT("patch rectangle not fully loaded"));
		const int32 K=Original.Num();Original.Add(*V);Desired.Add(HM[K]?After[K]:*V);
		if(HM[K]&&*V!=Before[K]&&*V!=After[K])++Mismatch;
		if(Desired[K]!=*V)++Changed;if(WM[K])++Painted;
	}
	R->SetNumberField(TEXT("baseline_mismatches"),Mismatch);R->SetNumberField(TEXT("changed_heights"),Changed);R->SetNumberField(TEXT("water_samples"),Painted);
	if(Mismatch)return Reply(TEXT("touched live heights differ from frozen baseline and candidate"));
	TArray<ULandscapeLayerInfoObject*> Infos;
	for(const TCHAR* Name:{TEXT("grass"),TEXT("sand"),TEXT("rock"),TEXT("water")})
	{
		ULandscapeLayerInfoObject* Found=nullptr;
		for(const auto& L:Info->Layers)if(L.LayerInfoObj&&L.LayerInfoObj->GetLayerName()==FName(Name))Found=L.LayerInfoObj;
		if(!Found)return Reply(TEXT("required landscape material layer missing"));Infos.Add(Found);
	}
	FLandscapeEditDataInterface Edit(Info);Edit.SetEditLayer(Layer);
	TArray<TArray<uint8>> OriginalWeights,DesiredWeights;
	for(int32 B=0;B<4;++B)
	{
		TArray<uint8> Values;Values.Init(0,N);Edit.GetWeightDataFast(Infos[B],X1,Y1,X2,Y2,Values.GetData(),0);
		OriginalWeights.Add(Values);
		for(int32 K=0;K<N;++K)if(WM[K])Values[K]=Weights[K*4+B];
		DesiredWeights.Add(MoveTemp(Values));
	}
	if(bPreflightOnly){R->SetBoolField(TEXT("preflight_only"),true);return Reply();}
	{
		FScopedSetLandscapeEditingLayer Scope(Land,Layer,[Land]{Land->RequestLayersContentUpdate(ELandscapeLayerUpdateMode::Update_All);});
		if(Changed)HeightAccess.SetData(X1,Y1,X2,Y2,Desired.GetData());
		if(Painted)
		{
			TSet<ULandscapeLayerInfoObject*> Dirty;TArray<uint8> Interleaved;Interleaved.Init(0,N*Info->Layers.Num());
			for(int32 B=0;B<4;++B)
			{
				Dirty.Add(Infos[B]);const int32 LI=Info->GetLayerInfoIndex(Infos[B]);
				for(int32 K=0;K<N;++K)Interleaved[K*Info->Layers.Num()+LI]=DesiredWeights[B][K];
			}
			Edit.SetAlphaData(Dirty,X1,Y1,X2,Y2,Interleaved.GetData(),0);
		}
		// Release/upload height textures before evaluating the composed layers.
		HeightAccess.Flush();Edit.Flush();
	}
	// SetData/SetAlphaData already mark the touched components. Evaluate those
	// requests without forcing all 2,067 loaded components through every patch.
	Land->ForceUpdateLayersContent();FAssetCompilingManager::Get().FinishAllCompilation();FlushRenderingCommands();
	// Full-rectangle readback includes protected samples and all four material channels.
	TArray<uint16> Check;Check.Init(0,N);HeightAccess.GetDataFast(X1,Y1,X2,Y2,Check.GetData());
	if(Check!=Desired)return Reply(TEXT("height readback differs from requested masked patch"));
	for(int32 B=0;B<4;++B)
	{
		TArray<uint8> Values;Values.Init(0,N);Edit.GetWeightDataFast(Infos[B],X1,Y1,X2,Y2,Values.GetData(),0);
		if(Values!=DesiredWeights[B])return Reply(TEXT("material readback differs from requested masked patch"));
	}
	R->SetBoolField(TEXT("untouched_samples_preserved"),true);R->SetBoolField(TEXT("readback_exact"),true);
	return Reply();
}
