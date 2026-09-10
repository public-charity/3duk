#include "StreetscapeEditorLibrary.h"
#include "StreetscapeEditorModule.h"
#include "StreetscapeActor.h"
#include "StreetscapeSiteActor.h"
#include "StreetscapeJson.h"
#include "StreetSpline.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "EngineUtils.h"
#include "FileHelpers.h"
#include "UObject/Package.h"

namespace
{
bool ReadDelta(const FString& Path, FStreetSiteDoc& Doc, UWorld*& World)
{
	World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	TSharedPtr<FJsonObject> Obj;
	FText Error;
	TArray<FString> Problems;
	if (!World || !FStreetscapeJson::LoadFile(Path, Obj, &Error) ||
		!FStreetscapeJson::ReadSite(Obj.ToSharedRef(), Doc, Problems))
	{
		UE_LOG(LogStreetscapeEditor, Error, TEXT("ReadDelta: %s %s"), *Error.ToString(), *FString::Join(Problems, TEXT("; ")));
		return false;
	}
	AStreetscapeSiteActor* Site = AStreetscapeSiteActor::Get(World);
	if (!Site || Doc.Splines.IsEmpty() || !Doc.Junctions.IsEmpty() ||
		!FMath::IsNearlyEqual(Site->OriginEN.X, Doc.Origin.E, 1e-6) ||
		!FMath::IsNearlyEqual(Site->OriginEN.Y, Doc.Origin.N, 1e-6)) return false;
	for (const FStreetSplineDef& Def : Doc.Splines)
		if (!Def.JunctionStart.IsEmpty() || !Def.JunctionEnd.IsEmpty()) return false;
	return true;
}

TArray<AStreetscapeActor*> ActorsById(UWorld* World, const FString& Id)
{
	TArray<AStreetscapeActor*> Result;
	for (TActorIterator<AStreetscapeActor> It(World); It; ++It)
		if (It->StreetId == Id) Result.Add(*It);
	return Result;
}

FString WithoutElevation(const FStreetSplineDef& Def)
{
	TSharedRef<FJsonObject> Obj = FStreetscapeJson::WriteSpline(Def);
	Obj->RemoveField(TEXT("elevation_profile"));
	TArray<FString> Keys;
	for (const auto& Pair : Obj->Values) Keys.Add(FString(*Pair.Key));
	for (const FString& Key : Keys) if (Key.StartsWith(TEXT("_"))) Obj->RemoveField(Key);
	return FStreetscapeJson::Canonical(Obj);
}
}

int32 UStreetscapeEditorLibrary::PreviewElevationJson(const FString& Path)
{
	FStreetSiteDoc Doc;
	UWorld* World = nullptr;
	if (!ReadDelta(Path, Doc, World)) return -1;
	TArray<AStreetscapeActor*> Actors;
	// Preflight ALL IDs and immutable geometry before making any in-memory change.
	for (const FStreetSplineDef& Def : Doc.Splines)
	{
		TArray<AStreetscapeActor*> Found = ActorsById(World, Def.Id);
		if (Found.Num() != 1 || Def.ElevationProfile.IsEmpty()) return -1;
		AStreetscapeActor* A = Found[0];
		if (!A->OwnedJunctions.IsEmpty() || WithoutElevation(A->Spline->Def) != WithoutElevation(Def)) return -1;
		Actors.Add(A);
	}
	TArray<TArray<FStreetElevationKnot>> Original;
	for (AStreetscapeActor* A : Actors) Original.Add(A->Spline->Def.ElevationProfile);
	for (int32 I = 0; I < Actors.Num(); ++I)
	{
		AStreetscapeActor* A = Actors[I];
		UPackage* Package = A->GetExternalPackage() ? A->GetExternalPackage() : A->GetPackage();
		const bool bDirty = Package->IsDirty();
		A->Spline->Def.ElevationProfile = Doc.Splines[I].ElevationProfile;
		A->Spline->MarkDirty();
		FString Error;
		const bool bBuilt = A->RebuildAllChecked(&Error);
		Package->SetDirtyFlag(bDirty);
		if (!bBuilt)
		{
			for (int32 J = 0; J <= I; ++J)
			{
				Actors[J]->Spline->Def.ElevationProfile = Original[J];
				Actors[J]->Spline->MarkDirty();
				Actors[J]->RebuildAllChecked(nullptr);
			}
			UE_LOG(LogStreetscapeEditor, Error, TEXT("PreviewElevationJson: %s"), *Error);
			return -1;
		}
	}
	return Actors.Num();
}

int32 UStreetscapeEditorLibrary::RestoreMissingBaselineJson(const FString& Path)
{
	FStreetSiteDoc Doc;
	UWorld* World = nullptr;
	if (!ReadDelta(Path, Doc, World)) return -1;
	FBox Bounds(ForceInit);
	for (const FStreetSplineDef& Def : Doc.Splines)
	{
		if (!Def.ElevationProfile.IsEmpty()) return -1; // never persist a candidate as recovery
		for (const FStreetPoint& Point : Def.Points)
			Bounds += FStreetscapeJson::ToUE(FVector3d(Point.X, Point.Y, 0));
	}
	if (!LoadRegion(Bounds.GetCenter(), (float)Bounds.GetExtent().GetMax()+10000.f)) return -1;
	TArray<const FStreetSplineDef*> Missing;
	for (const FStreetSplineDef& Def : Doc.Splines)
	{
		TArray<AStreetscapeActor*> Found = ActorsById(World, Def.Id);
		if (Found.Num() > 1) return -1;
		if (Found.IsEmpty()) Missing.Add(&Def);
		else if (WithoutElevation(Found[0]->Spline->Def) != WithoutElevation(Def)) return -1;
	}
	TArray<UPackage*> Packages;
	for (const FStreetSplineDef* Def : Missing)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		AStreetscapeActor* A = World->SpawnActor<AStreetscapeActor>(AStreetscapeActor::StaticClass(), FTransform::Identity, Params);
		if (!A) return -1;
		// Actor.h:1154; FileHelpers.h:86. Save ONLY the new actor package.
		A->SetPackageExternal(true);
		A->ApplyDefinition(*Def, Doc.Profiles, FVector2D(Doc.Origin.E, Doc.Origin.N));
		A->SetJunctionData(FVector2D::ZeroVector, {});
		FString Error;
		if (!A->RebuildAllChecked(&Error))
		{
			UE_LOG(LogStreetscapeEditor, Error, TEXT("RestoreMissingBaselineJson: %s"), *Error);
			return -1;
		}
		UPackage* Package = A->GetExternalPackage();
		if (!Package) return -1;
		Package->MarkPackageDirty();
		Packages.Add(Package);
	}
	if (!Packages.IsEmpty() && !UEditorLoadingAndSavingUtils::SavePackages(Packages, false)) return -1;
	return Packages.Num();
}
