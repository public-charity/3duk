// AStreetscapeSiteActor - the one per-level actor that owns the site header, the terrain source, the profile
// library and the material table (UE_PLAN.md 2.10; DESIGN.md 10). Not spatially loaded, so every streetscape
// actor can reach it whatever the World Partition cell.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "StreetProfiles.h"
#include "StreetTypes.h"
#include "StreetscapeSiteActor.generated.h"

class UStreetMaterialTable;
class UStreetProfileBase;
class UStreetTerrainSourceBase;
class IStreetTerrainSource;

UCLASS(BlueprintType)
class STREETSCAPE_API AStreetscapeSiteActor : public AActor
{
	GENERATED_BODY()
public:
	AStreetscapeSiteActor();

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streetscape") FString SiteName;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streetscape") FString Crs = TEXT("EPSG:27700");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streetscape") FString VerticalDatum = TEXT("ODN");
	/** Survey origin (E, N) every document must match. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streetscape") FVector2D OriginEN = FVector2D::ZeroVector;
	UPROPERTY(EditAnywhere, Instanced, BlueprintReadWrite, Category = "Streetscape") TObjectPtr<UStreetTerrainSourceBase> TerrainSource;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streetscape") TArray<TObjectPtr<UStreetProfileBase>> Profiles;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streetscape") TObjectPtr<UStreetMaterialTable> Materials;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streetscape") bool bShowOverlay = true;

	/** The first site actor of the world (spawning one when bCreate and none exists). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static AStreetscapeSiteActor* Get(UWorld* World, bool bCreate = false);

	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	UStreetProfileBase* FindProfile(FName Id) const;

	/** DataDir/landscape heightfield, created on demand from UStreetscapeSettings when TerrainSource is unset. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	UStreetTerrainSourceBase* ResolveTerrainSource();

	/** Terrain source ready to sample documents authored at OriginEN (SetDocumentOrigin applied). */
	const IStreetTerrainSource* TerrainForOrigin(double E, double N);

	/** The site's assets as an FStreetSiteProfiles (the fallback the loader uses when a document lacks a profile). */
	FStreetSiteProfiles AssetProfiles() const;

	virtual void PostLoad() override;
};
