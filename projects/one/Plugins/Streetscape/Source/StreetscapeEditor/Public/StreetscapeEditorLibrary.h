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
	 * bPreloadWorld streams the whole world in before the import so "replace the actor with this id" can see the
	 * actors already there (a World Partition commandlet has nothing loaded, and an invisible actor is not
	 * replaced, it is doubled). Pass false ONLY when the caller knows the level holds no streetscape actor for
	 * these ids - a slice of a fresh site import - because at site scale (15,422 splines) preloading every slice
	 * would hold the whole isle in memory at once.
	 * MaxNoTerrainActors is how many splines may come out with NO terrain under any station - built flat at
	 * z = 0, which is geometry that looks right and is wrong. 0 (the default) means any such spline fails the
	 * import and its id is logged as an Error; a positive value accepts up to that many and logs them as
	 * Warnings, so accepting a known-bad document is a deliberate, counted, recorded act.
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static int32 ImportStreetscapeJson(const FString& FileOrDir, bool bPlacePlayerStart, bool bPreloadWorld = true, int32 MaxNoTerrainActors = 0);

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
	 * One AStreetscapeMassingActor per <Dir>/buildings_x{i}_y{j}.jsonl (grey extruded footprints). An actor that
	 * already covers a tile is rebuilt in place and any surplus one is deleted, so re-importing keeps the level at
	 * exactly one actor per tile. Returns the actor count (-1 on error) and fills OutReportJson with the totals.
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static int32 ImportMassing(const FString& Dir, const FString& MaterialPath, FString& OutReportJson);

	// -- phase 5: what the renderer actually got -------------------------------------------------------------------

	/**
	 * Block until every queued shader has compiled AND its results have been applied
	 * (FShaderCompilingManager::FinishAllCompilation, Runtime/Engine/Public/ShaderCompiler.h:1327; the manager is
	 * GShaderCompilingManager, :1371). A material whose shader map is not ready renders as
	 * UMaterial::GetDefaultMaterial - the engine's WorldGridMaterial checkerboard - and a Python script that only
	 * *sleeps* between captures never gets there, because the compiler's results are applied from the game thread
	 * the script is blocking. Returns the number of jobs that were still outstanding when it was called.
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static int32 FinishShaderCompilation();

	/**
	 * What material every streetscape / massing component would actually draw with: per component, the slot count
	 * and each slot's material path, plus a count of slots resolving to the engine default material. Separates
	 * "the table did not resolve" from "the shader map was not ready" when a capture comes back grey.
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static FString MaterialAuditJson();

	/**
	 * Destroy actors AND delete the World Partition external-actor packages that hold them
	 * (ObjectTools::CleanupAfterSuccessfulDelete, ObjectTools.h:313). UWorld::EditorDestroyActor on its own leaves
	 * the .uasset on disk, so the "deleted" actor is back the next time the map is opened - which is how a repeated
	 * import silently doubles the level. Not a UFUNCTION: C++ callers only. Returns the number of packages deleted.
	 */
	static int32 DeleteActorsAndPackages(const TArray<AActor*>& Actors);
};
