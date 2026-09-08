// StreetscapeEditorLibrary - editor UFUNCTIONs callable from Python (UE_PLAN.md 2.12): unreal.StreetscapeEditorLibrary.*
// Phase 2 provided the profile/material bootstrap and the validators; phase 3 adds the actors:
// ImportStreetscapeJson, LoadRegion, ExportSiteJson, ActorStatsJson (the stats.json of DESIGN.md 14) and the three
// fixed cameras of Tools/blender/streetscape/render.py so the Unreal screenshots frame what Blender framed.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "StreetscapeEditorLibrary.generated.h"

class AStreetscapeActor;
class AStreetscapeSiteActor;
class UMaterialInterface;
class UStreetMaterialTable;

UCLASS()
class STREETSCAPEEDITOR_API UStreetscapeEditorLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()
public:
	/** For each <JsonDir>/*.json ({kind, id, profile}): create or update the DataAsset <PackagePath>/<id> of the class by kind, save it. Returns the count (20 for the library). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static int32 ImportProfiles(const FString& JsonDir, const FString& PackagePath);

	/** Ids of the profile assets under PackagePath (asset registry), sorted. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static TArray<FString> ProfileAssetIds(const FString& PackagePath);

	/** Create or update the UStreetMaterialTable asset <PackagePath>/<AssetName> from name -> material, save it. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static UStreetMaterialTable* CreateMaterialTable(const FString& PackagePath, const FString& AssetName, const TMap<FName, UMaterialInterface*>& Materials, UMaterialInterface* Fallback);

	/** UEditorLoadingAndSavingUtils::SaveDirtyPackages(true, true) (UED/Public/FileHelpers.h:108). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static bool SaveAll();

	/** Structural problems of a Streetscape document file (SCHEMA.md 8); empty = valid. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static TArray<FString> ValidateStreetscapeJson(const FString& Path);

	/** Non-fatal warnings of a Streetscape document file (unhinted materials, missing overlays, lane widths). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static TArray<FString> StreetscapeJsonWarnings(const FString& Path);

	/** Load a document, write it back through the canonical serialiser; returns the output path or empty on error. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static FString RewriteStreetscapeJson(const FString& InPath, const FString& OutPath);

	/** Height of the adapter heightfield (UStreetscapeSettings::DataDir/landscape) at document metres; NaN if no ground. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static double ProbeHeightfieldM(double XM, double YM);

	// -- phase 3: the actors ---------------------------------------------------------------------------------------

	/** The level's site actor (created and populated from the asset registry when missing). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static AStreetscapeSiteActor* EnsureSiteActor(const FString& SiteName, double OriginE, double OriginN);

	/**
	 * Load a Streetscape document (a file, or a directory of site_x*_y*.json), spawn one AStreetscapeActor per
	 * spline, label it with the spline id and RebuildAll it. Returns the number of actors spawned (-1 on error).
	 * bPlacePlayerStart drops an APlayerStart at the first spline's first point, yaw = bearing - 90.
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static int32 ImportStreetscapeJson(const FString& FileOrDir, bool bPlacePlayerStart);

	/** Street ids of every AStreetscapeActor in the editor world, sorted. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static TArray<FString> StreetscapeActorIds();

	/** Rebuild every AStreetscapeActor in the editor world; returns the count. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static int32 RebuildAllStreetscapeActors();

	/** The stats.json of DESIGN.md 14 for one actor (by spline id), as pretty JSON text; empty when not found. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static FString ActorStatsJson(const FString& StreetId);

	/** Write ActorStatsJson to a file; returns the path or empty. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static FString WriteActorStatsJson(const FString& StreetId, const FString& OutPath);

	/** {cam1, cam2, cam3} of Tools/blender/streetscape/render.py, in UE centimetres: eye, target, fov_deg. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static FString ActorCameraJson(const FString& StreetId);

	/** FLoaderAdapterShape + Load(): commandlets skip LoadLastLoadedRegions (WorldPartition.cpp:880-886). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static bool LoadRegion(FVector CenterUE, float RadiusCm);

	/** Every actor's spline written back as one Streetscape document. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static FString ExportSiteJson(const FString& Path);

	// -- phase 4: massing (DESIGN.md 15) --------------------------------------------------------------------------

	/**
	 * One AStreetscapeMassingActor per <Dir>/buildings_x{i}_y{j}.jsonl (grey extruded footprints). Existing massing
	 * actors are destroyed first, so the import is idempotent. Returns the actor count (-1 on error) and fills
	 * OutReportJson with the per-run totals.
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static int32 ImportMassing(const FString& Dir, const FString& MaterialPath, FString& OutReportJson);
};
