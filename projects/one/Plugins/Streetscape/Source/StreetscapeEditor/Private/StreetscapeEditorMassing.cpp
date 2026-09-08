// UStreetscapeEditorLibrary::ImportMassing (DESIGN.md 15, UE_PLAN.md 2.12): one AStreetscapeMassingActor per
// massing/buildings_x{i}_y{j}.jsonl. Grey placeholder boxes; nothing here reads a spline or a profile.

#include "StreetscapeEditorLibrary.h"

#include "Editor.h"
#include "EngineUtils.h"
#include "HAL/FileManager.h"
#include "Materials/MaterialInterface.h"
#include "Misc/Paths.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "StreetscapeEditorModule.h"
#include "StreetscapeMassingActor.h"

int32 UStreetscapeEditorLibrary::ImportMassing(const FString& Dir, const FString& MaterialPath, FString& OutReportJson)
{
	const double T0 = FPlatformTime::Seconds();
	TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
	auto Emit = [&Report, &OutReportJson](int32 Result) -> int32
	{
		FString Out;
		TSharedRef<TJsonWriter<>> W = TJsonWriterFactory<>::Create(&Out);
		FJsonSerializer::Serialize(Report, W);
		OutReportJson = Out;
		return Result;
	};

	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		Report->SetStringField(TEXT("error"), TEXT("no editor world"));
		return Emit(-1);
	}

	TArray<FString> Files;
	IFileManager::Get().FindFiles(Files, *(Dir / TEXT("buildings_x*_y*.jsonl")), true, false);
	Files.Sort();
	Report->SetStringField(TEXT("dir"), Dir);
	Report->SetNumberField(TEXT("files"), Files.Num());
	if (Files.Num() == 0)
	{
		Report->SetStringField(TEXT("error"), FString::Printf(TEXT("no buildings_x*_y*.jsonl under %s"), *Dir));
		return Emit(-1);
	}

	UMaterialInterface* Mat = MaterialPath.IsEmpty() ? nullptr : LoadObject<UMaterialInterface>(nullptr, *MaterialPath);
	if (!MaterialPath.IsEmpty() && !Mat)
	{
		UE_LOG(LogStreetscapeEditor, Warning, TEXT("ImportMassing: material %s not found; the boxes get the engine default"), *MaterialPath);
	}
	Report->SetStringField(TEXT("material"), Mat ? Mat->GetPathName() : TEXT(""));

	// World Partition: nothing is loaded after load_level in a commandlet, so an actor from a previous run is
	// invisible here unless the region is pulled in first - and an invisible actor is not replaced, it is doubled.
	UStreetscapeEditorLibrary::LoadRegion(FVector::ZeroVector, 2000000.f);

	// Re-use one actor per tile (keeps its external package, so the level does not grow) and delete every surplus.
	TMap<FIntPoint, AStreetscapeMassingActor*> ByTile;
	TArray<AActor*> Surplus;
	for (TActorIterator<AStreetscapeMassingActor> It(World); It; ++It)
	{
		AStreetscapeMassingActor* A = *It;
		const FIntPoint Key(A->TileX, A->TileY);
		if (ByTile.Contains(Key)) { Surplus.Add(A); continue; }
		ByTile.Add(Key, A);
	}
	const int32 Removed = UStreetscapeEditorLibrary::DeleteActorsAndPackages(Surplus);
	Report->SetNumberField(TEXT("actors_reused"), ByTile.Num());
	Report->SetNumberField(TEXT("actors_removed"), Removed);

	int32 Actors = 0, Buildings = 0, Rings = 0, HoleRings = 0, Verts = 0, Tris = 0, Clamped = 0, Skipped = 0, Failed = 0;
	double MinZ = TNumericLimits<double>::Max(), MaxZ = -TNumericLimits<double>::Max();
	int32 Reused = 0;
	TSet<FIntPoint> Covered;
	for (const FString& Name : Files)
	{
		const FString Path = Dir / Name;
		// buildings_x{i}_y{j}.jsonl -> the tile this file is for, so an existing actor can be re-used in place
		FIntPoint Key(-1, -1);
		{
			FString Base = FPaths::GetBaseFilename(Path);
			FString Rest, Xs, Ys;
			if (Base.Split(TEXT("_x"), nullptr, &Rest) && Rest.Split(TEXT("_y"), &Xs, &Ys))
			{
				Key = FIntPoint(FCString::Atoi(*Xs), FCString::Atoi(*Ys));
			}
		}
		AStreetscapeMassingActor* A = ByTile.FindRef(Key);
		if (A)
		{
			++Reused;
			A->Modify();
		}
		else
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			A = World->SpawnActor<AStreetscapeMassingActor>(AStreetscapeMassingActor::StaticClass(), FTransform::Identity, Params);
		}
		if (!A) { ++Failed; continue; }
		Covered.Add(Key);
		A->MassingMaterial = Mat;
		if (!A->BuildFromFile(Path))
		{
			World->EditorDestroyActor(A, false);
			++Failed;
			continue;
		}
		A->SetActorLabel(FString::Printf(TEXT("Massing_x%d_y%d"), A->TileX, A->TileY));
		A->Modify();
		A->MarkPackageDirty();
		++Actors;
		Buildings += A->Stats.Buildings;
		Rings += A->Stats.Rings;
		HoleRings += A->Stats.HoleRings;
		Verts += A->Stats.Verts;
		Tris += A->Stats.Tris;
		Clamped += A->Stats.ClampedHeights;
		Skipped += A->Stats.SkippedRings;
		if (A->Stats.Buildings > 0)
		{
			MinZ = FMath::Min(MinZ, A->Stats.MinZM);
			MaxZ = FMath::Max(MaxZ, A->Stats.MaxZM);
		}
	}

	// a tile that used to have buildings and no longer does leaves an actor behind: delete those too
	TArray<AActor*> Orphans;
	for (const TPair<FIntPoint, AStreetscapeMassingActor*>& Kv : ByTile)
	{
		if (!Covered.Contains(Kv.Key) && Kv.Value) Orphans.Add(Kv.Value);
	}
	Report->SetNumberField(TEXT("actors_orphaned_removed"), UStreetscapeEditorLibrary::DeleteActorsAndPackages(Orphans));
	Report->SetNumberField(TEXT("actors_reused_in_place"), Reused);
	Report->SetNumberField(TEXT("actors"), Actors);
	Report->SetNumberField(TEXT("failed"), Failed);
	Report->SetNumberField(TEXT("buildings"), Buildings);
	Report->SetNumberField(TEXT("rings"), Rings);
	Report->SetNumberField(TEXT("hole_rings"), HoleRings);
	Report->SetNumberField(TEXT("verts"), Verts);
	Report->SetNumberField(TEXT("tris"), Tris);
	Report->SetNumberField(TEXT("clamped_heights"), Clamped);
	Report->SetNumberField(TEXT("skipped_rings"), Skipped);
	Report->SetNumberField(TEXT("z_min_m"), Actors ? MinZ : 0.0);
	Report->SetNumberField(TEXT("z_max_m"), Actors ? MaxZ : 0.0);
	Report->SetNumberField(TEXT("seconds"), FPlatformTime::Seconds() - T0);
	UE_LOG(LogStreetscapeEditor, Log, TEXT("ImportMassing: %d actors, %d buildings, %d verts / %d tris in %.1f s"),
		Actors, Buildings, Verts, Tris, FPlatformTime::Seconds() - T0);
	return Emit(Actors);
}
