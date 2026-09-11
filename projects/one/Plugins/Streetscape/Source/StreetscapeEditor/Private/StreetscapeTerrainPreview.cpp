// Bounded commandlet-only terrain previews. Never use the production importer here.
#include "StreetscapeEditorLibrary.h"
#include "StreetscapeJson.h"
#include "StreetscapeSiteActor.h"
#include "StreetTerrainSource.h"
#include "AssetCompilingManager.h"
#include "Editor.h"
#include "EngineUtils.h"
#include "Landscape.h"
#include "LandscapeComponent.h"
#include "LandscapeEdit.h"
#include "LandscapeEditLayer.h"
#include "LandscapeInfo.h"
#include "RenderingThread.h"
#include "UObject/Package.h"
#include "UObject/UObjectIterator.h"

namespace
{
struct FPreviewHeights
{
	TWeakObjectPtr<ALandscape> Landscape;
	FGuid Layer;
	int32 X1=0,Y1=0,X2=0,Y2=0;
	TArray<uint16> Original;
	TArray<TPair<TWeakObjectPtr<UPackage>,bool>> Dirty;
};
TUniquePtr<FPreviewHeights> CurrentPreview;

FString Reply(const TSharedRef<FJsonObject>& Report, const FString& Error=FString())
{
	Report->SetBoolField(TEXT("saved"),false);
	Report->SetBoolField(TEXT("ok"),Error.IsEmpty());
	if (!Error.IsEmpty()) Report->SetStringField(TEXT("error"),Error);
	return FStreetscapeJson::ToText(Report,false,1,-1);
}

void RestoreDirty(const FPreviewHeights& Snapshot)
{
	for (const auto& Pair : Snapshot.Dirty) if (UPackage* Package=Pair.Key.Get()) Package->SetDirtyFlag(Pair.Value);
}

bool ReadHeights(const FPreviewHeights& Snapshot,TArray<uint16>& Out)
{
	ALandscape* Landscape=Snapshot.Landscape.Get();
	ULandscapeInfo* Info=Landscape ? Landscape->GetLandscapeInfo() : nullptr;
	if (!Info) return false;
	FHeightmapAccessor<false> Accessor(Info);
	Accessor.SetEditLayer(Snapshot.Layer);
	TMap<FIntPoint,uint16> Values;
	Accessor.GetDataFast(Snapshot.X1,Snapshot.Y1,Snapshot.X2,Snapshot.Y2,Values);
	Out.Reset();
	for (int32 Y=Snapshot.Y1;Y<=Snapshot.Y2;++Y)
	{
		for (int32 X=Snapshot.X1;X<=Snapshot.X2;++X)
		{
			const uint16* Value=Values.Find(FIntPoint(X,Y));
			if (!Value) return false; // An unloaded component is not a zero-height sample.
			Out.Add(*Value);
		}
	}
	return Out.Num()>0;
}

void WriteHeights(const FPreviewHeights& Snapshot,const TArray<uint16>& Values)
{
	ALandscape* Landscape=Snapshot.Landscape.Get();
	ULandscapeInfo* Info=Landscape->GetLandscapeInfo();
	{
		FScopedSetLandscapeEditingLayer Scope(Landscape,Snapshot.Layer,[Landscape]
			{ Landscape->RequestLayersContentUpdate(ELandscapeLayerUpdateMode::Update_Heightmap_All); });
		FHeightmapAccessor<false> Accessor(Info);
		Accessor.SetEditLayer(Snapshot.Layer);
		Accessor.SetData(Snapshot.X1,Snapshot.Y1,Snapshot.X2,Snapshot.Y2,Values.GetData());
	}
	Info->ForceLayersFullUpdate();
	FAssetCompilingManager::Get().FinishAllCompilation();
	FlushRenderingCommands();
	RestoreDirty(Snapshot);
}
}

FString UStreetscapeEditorLibrary::RestoreLandscapePreviewJson()
{
	TSharedRef<FJsonObject> Report=MakeShared<FJsonObject>();
	if (!IsRunningCommandlet()) return Reply(Report,TEXT("terrain previews are restricted to commandlets"));
	if (!CurrentPreview)
	{
		Report->SetBoolField(TEXT("restored"),true);
		Report->SetBoolField(TEXT("nothing_to_restore"),true);
		return Reply(Report);
	}
	ALandscape* Landscape=CurrentPreview->Landscape.Get();
	if (!Landscape || !Landscape->GetLandscapeInfo()) return Reply(Report,TEXT("preview landscape no longer loaded"));
	WriteHeights(*CurrentPreview,CurrentPreview->Original);
	TArray<uint16> Readback;
	const bool bSame=ReadHeights(*CurrentPreview,Readback) && Readback==CurrentPreview->Original;
	RestoreDirty(*CurrentPreview);
	Report->SetBoolField(TEXT("restored"),bSame);
	Report->SetNumberField(TEXT("samples"),CurrentPreview->Original.Num());
	if (!bSame) return Reply(Report,TEXT("terrain preview restoration did not read back identically"));
	CurrentPreview.Reset();
	return Reply(Report);
}

FString UStreetscapeEditorLibrary::PreviewLandscapeHeightsJson(const FString& LandscapeDir,
	double MinXM,double MinYM,double MaxXM,double MaxYM)
{
	TSharedRef<FJsonObject> Report=MakeShared<FJsonObject>();
	if (!IsRunningCommandlet()) return Reply(Report,TEXT("terrain previews are restricted to commandlets"));
	if (CurrentPreview) return Reply(Report,TEXT("restore the current terrain preview before starting another"));
	if (!FMath::IsFinite(MinXM) || !FMath::IsFinite(MinYM) || !FMath::IsFinite(MaxXM) || !FMath::IsFinite(MaxYM) ||
		MaxXM<=MinXM || MaxYM<=MinYM || MaxXM-MinXM>512 || MaxYM-MinYM>512 ||
		FMath::Max(FMath::Abs(MinXM),FMath::Abs(MaxXM))>1000000 || FMath::Max(FMath::Abs(MinYM),FMath::Abs(MaxYM))>1000000)
		return Reply(Report,TEXT("invalid terrain rectangle; each dimension must be within 512 m"));
	UWorld* World=GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	AStreetscapeSiteActor* Site=World ? AStreetscapeSiteActor::Get(World) : nullptr;
	if (!Site) return Reply(Report,TEXT("no loaded site actor"));
	ALandscape* Landscape=nullptr;
	for (TActorIterator<ALandscape> It(World);It;++It)
	{
		if (Landscape) return Reply(Report,TEXT("multiple landscapes: preview target is ambiguous"));
		Landscape=*It;
	}
	if (!Landscape || !Landscape->GetLandscapeInfo()) return Reply(Report,TEXT("no loaded landscape"));
	const FTransform Transform=Landscape->GetActorTransform();
	if (!Transform.GetRotation().Equals(FQuat::Identity,1e-8) || !Transform.GetScale3D().Equals(FVector(100,100,100),1e-8) ||
		FMath::Abs(Transform.GetLocation().Z)>1e-8)
		return Reply(Report,TEXT("landscape transform does not match the 1 m / ODN height encoding"));
	TSharedPtr<FJsonObject> Manifest;
	FText LoadError;
	if (!FStreetscapeJson::LoadFile(LandscapeDir/TEXT("landscape_manifest.json"),Manifest,&LoadError)) return Reply(Report,LoadError.ToString());
	FString Crs,Datum;
	if (!Manifest->TryGetStringField(TEXT("crs"),Crs) || Crs!=Site->Crs ||
		!Manifest->TryGetStringField(TEXT("vertical_datum"),Datum) || Datum!=Site->VerticalDatum)
		return Reply(Report,TEXT("candidate terrain CRS/datum differs from the loaded site"));
	FStreetHeightfield Candidate;
	if (!Candidate.LoadLandscapeDir(LandscapeDir,&LoadError)) return Reply(Report,LoadError.ToString());
	Candidate.Sampling=EStreetHeightSampling::LandscapeTriangulated;
	if (FMath::Abs(Candidate.OriginE-Site->OriginEN.X)>1e-8 || FMath::Abs(Candidate.OriginN-Site->OriginEN.Y)>1e-8 ||
		FMath::Abs(Candidate.PxM-1.0)>1e-8)
		return Reply(Report,TEXT("candidate grid/origin differs from the loaded site"));
	auto Snapshot=MakeUnique<FPreviewHeights>();
	Snapshot->Landscape=Landscape;
	const auto Layers=Landscape->GetEditLayersConst();
	if (Layers.Num()>1) return Reply(Report,TEXT("terrain preview requires at most one base edit layer"));
	if (Layers.Num()==1) Snapshot->Layer=Layers[0]->GetGuid();
	const FVector A=Transform.InverseTransformPosition(FVector(MinXM*100,-MaxYM*100,0));
	const FVector B=Transform.InverseTransformPosition(FVector(MaxXM*100,-MinYM*100,0));
	Snapshot->X1=FMath::FloorToInt(A.X); Snapshot->Y1=FMath::FloorToInt(A.Y);
	Snapshot->X2=FMath::CeilToInt(B.X); Snapshot->Y2=FMath::CeilToInt(B.Y);
	if (!ReadHeights(*Snapshot,Snapshot->Original)) return Reply(Report,TEXT("preview rectangle is not fully loaded"));
	TArray<uint16> Desired;
	int32 Changed=0;
	double MaxDelta=0;
	for (int32 Y=Snapshot->Y1;Y<=Snapshot->Y2;++Y)
	{
		for (int32 X=Snapshot->X1;X<=Snapshot->X2;++X)
		{
			const FVector P=Transform.TransformPosition(FVector(X,Y,0));
			double Z=0;
			if (!Candidate.Sample(P.X/100,-P.Y/100,Z) || !FMath::IsFinite(Z)) return Reply(Report,TEXT("candidate has missing ground inside preview rectangle"));
			const double Encoded=FMath::RoundToDouble(Z*128.0+32768.0);
			if (Encoded<0 || Encoded>65535) return Reply(Report,TEXT("candidate height exceeds landscape encoding"));
			const uint16 H=static_cast<uint16>(Encoded);
			const int32 Delta=FMath::Abs(static_cast<int32>(H)-static_cast<int32>(Snapshot->Original[Desired.Num()]));
			if (Delta) ++Changed;
			MaxDelta=FMath::Max(MaxDelta,Delta/128.0);
			Desired.Add(H);
		}
	}
	for (TObjectIterator<UPackage> It;It;++It) Snapshot->Dirty.Add({*It,It->IsDirty()});
	CurrentPreview=MoveTemp(Snapshot); // Installed before mutation so restoration is always available.
	WriteHeights(*CurrentPreview,Desired);
	TArray<uint16> Readback;
	if (!ReadHeights(*CurrentPreview,Readback) || Readback!=Desired)
	{
		Report->SetStringField(TEXT("rollback"),RestoreLandscapePreviewJson());
		return Reply(Report,TEXT("preview height data did not read back identically"));
	}
	RestoreDirty(*CurrentPreview);
	Report->SetStringField(TEXT("landscape"),Landscape->GetPathName());
	Report->SetStringField(TEXT("candidate"),LandscapeDir);
	Report->SetNumberField(TEXT("samples"),Desired.Num());
	Report->SetNumberField(TEXT("changed_samples"),Changed);
	Report->SetNumberField(TEXT("max_change_m"),MaxDelta);
	Report->SetBoolField(TEXT("readback_identical"),true);
	return Reply(Report);
}
