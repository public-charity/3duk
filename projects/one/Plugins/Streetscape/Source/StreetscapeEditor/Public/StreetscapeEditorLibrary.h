// StreetscapeEditorLibrary - editor UFUNCTIONs callable from Python (UE_PLAN.md 2.12): unreal.StreetscapeEditorLibrary.*
// Phase 2 provides the profile/material bootstrap and the validators; ImportStreetscapeJson / ImportMassing /
// LoadRegion / ExportSiteJson / ActorStatsJson arrive with the actors (phase 3).

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "StreetscapeEditorLibrary.generated.h"

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
};
