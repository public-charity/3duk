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

	// replace any massing actors of a previous run so the import is idempotent
	int32 Removed = 0;
	for (TActorIterator<AStreetscapeMassingActor> It(World); It; ++It)
	{
		AStreetscapeMassingActor* A = *It;
		World->EditorDestroyActor(A, false);
		++Removed;
	}
	Report->SetNumberField(TEXT("actors_removed"), Removed);

	int32 Actors = 0, Buildings = 0, Rings = 0, HoleRings = 0, Verts = 0, Tris = 0, Clamped = 0, Skipped = 0, Failed = 0;
	double MinZ = TNumericLimits<double>::Max(), MaxZ = -TNumericLimits<double>::Max();
	for (const FString& Name : Files)
	{
		const FString Path = Dir / Name;
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		AStreetscapeMassingActor* A = World->SpawnActor<AStreetscapeMassingActor>(AStreetscapeMassingActor::StaticClass(), FTransform::Identity, Params);
		if (!A) { ++Failed; continue; }
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
