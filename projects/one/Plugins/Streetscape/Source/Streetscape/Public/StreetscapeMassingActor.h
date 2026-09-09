// AStreetscapeMassingActor - the grey building placeholder of DESIGN.md 15 / BRIEF stage 8. One actor per
// massing/buildings_x{i}_y{j}.jsonl tile, one UDynamicMeshComponent holding every footprint of that tile extruded
// from `skirt` to `base_z + h` (ODN metres, absolute - the adapter already draped them), ear-clipped caps.
//
// This is deliberately NOT a Streetscape renderer: it reads no spline, no profile and no terrain. It exists so the
// explorer has buildings to walk between; the real building work is explicitly last (BRIEF 1).

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "StreetscapeMassingActor.generated.h"

class UDynamicMeshComponent;
class UMaterialInterface;

/** What one tile's import produced - reported by ImportMassing and readable in the details panel. */
USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetMassingStats
{
	GENERATED_BODY()

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") int32 Buildings = 0;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") int32 Rings = 0;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") int32 HoleRings = 0;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") int32 Verts = 0;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") int32 Tris = 0;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") int32 ClampedHeights = 0;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") int32 SkippedRings = 0;
	/** JSONL lines that did not parse. Non-zero means the file was only partly readable - never a silent pass. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") int32 SkippedLines = 0;
	/** Buildings with no "skirt" field, extruded from base_z - 1 m instead. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") int32 SkirtDefaulted = 0;
	/** Buildings with no usable "rings" array. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") int32 SkippedBuildings = 0;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") double MinZM = 0;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") double MaxZM = 0;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") double BuildMs = 0;
};

UCLASS(BlueprintType)
class STREETSCAPE_API AStreetscapeMassingActor : public AActor
{
	GENERATED_BODY()
public:
	AStreetscapeMassingActor();

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") TObjectPtr<UDynamicMeshComponent> Mesh;
	/** Absolute path of the buildings_x{i}_y{j}.jsonl this actor was built from. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streetscape") FString SourceFile;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") int32 TileX = -1;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") int32 TileY = -1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streetscape") TObjectPtr<UMaterialInterface> MassingMaterial;
	/** Minimum extrusion height in metres: 337 of Thanet's 20,121 footprints have h <= 0 (flat roofs of sheds). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Streetscape") double MinHeightM = 0.5;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Streetscape") FStreetMassingStats Stats;

	/** Parse the JSONL, build the mesh, set the material and complex-as-simple collision. False on a read error. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	bool BuildFromFile(const FString& Path);

	/**
	 * Vertical ray-cast straight down against THIS tile's mesh at document metres (x east, y north): the ODN
	 * metres of the highest surface, or NaN when the ray misses. Geometry, not physics - it answers "is the
	 * extrusion there and how tall is it" without depending on whether the complex collision has been cooked.
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	double SampleTopZM(double XM, double YM) const;

	/** Re-cook the complex collision of an already-loaded mesh (UDynamicMeshComponent::UpdateCollision). Returns the triangle count. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	int32 RefreshCollision();
};
