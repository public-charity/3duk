// StreetscapeLandscapeImporter - the adapter's landscape products -> one World Partition ALandscape (UE_PLAN.md 3;
// DESIGN.md 9). Everything here is editor-only and callable from Tools/ue/02_import_landscape.py through
// unreal.StreetscapeLandscapeImporter.*.
//
// The importer never guesses: every number it uses (res, nx, ny, tile_m, pad_value_h16, the z encoding, the clip line)
// is read from landscape_manifest.json and the hard-fails of UE_PLAN.md 3.6 step 2 refuse a manifest that does not
// match what this code knows how to read. Padding goes NORTH and EAST only so the site origin stays at UE (0, 0)
// (DESIGN.md 9): data row r -> padded row r + pad_north, columns unchanged, actor at (0, -100*(H-1 + pad_north), 0).

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "StreetscapeLandscapeImporter.generated.h"

class ALandscape;
class ALandscapeProxy;

UCLASS()
class STREETSCAPEEDITOR_API UStreetscapeLandscapeImporter : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()
public:
	/**
	 * Read the manifest and report what an import WOULD do (component size, counts, padding, extent, placement,
	 * the engine helper's own suggestion) without touching the world. Returns the report JSON, or a JSON object
	 * with "error" when the manifest is unusable. Used by --probes-only and by the gate reports.
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static FString PlanSiteJson(const FString& ManifestPath, int32 QuadsPerSection = 127, int32 SectionsPerComponent = 2, int32 WorldPartitionGridSize = 4);

	/**
	 * Import the whole site (UE_PLAN.md 3.6). MaxComponentsPerImport 0 = one Import call for everything; otherwise
	 * a component count above it takes the region path of 3.7 (16x16-component blocks). Returns the landscape
	 * (nullptr on failure) and always writes OutReportJson.
	 *
	 * MaxSharedEdgeH16Delta gates the shared-edge check: neighbouring tiles write the row / column they share
	 * twice and, where the landscape renders ground, the two writes must agree bit for bit - they come from the
	 * same source raster. 0 (the default the scripts pass) = must be identical; a positive value allows that many
	 * h16 units (1 h16 = 1/128 m at Z scale 100); a NEGATIVE value waives the gate for a deliberate import of
	 * known-bad data and records "waived": true in the report.
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static ALandscape* ImportSite(const FString& ManifestPath, int32 QuadsPerSection, int32 SectionsPerComponent, int32 WorldPartitionGridSize,
		const FString& MaterialPath, const FString& LayerInfoPackagePath, int32 MaxComponentsPerImport, int32 MaxSharedEdgeH16Delta, FString& OutReportJson);

	/** The editor world's ALandscape (the parent actor, not a streaming proxy); nullptr when none. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static ALandscape* FindLandscape();

	/** Components registered in the landscape info (all proxies, loaded or not, via XYtoComponentMap). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static int32 CountLandscapeComponents(ALandscapeProxy* Proxy);

	/** ALandscapeStreamingProxy actors of the same landscape info. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static int32 CountStreamingProxies(ALandscapeProxy* Proxy);

	/**
	 * Landscape height at document metres (x east, y north) as ODN metres; NaN where the landscape has no data.
	 * bUseCollision picks EHeightfieldSource::Complex (the collision heightfield, which has the visibility holes
	 * cut out of it) instead of ::Editor (the raw heightmap, which has a value everywhere including inside a hole).
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static double ProbeHeightM(ALandscapeProxy* Proxy, double XM, double YM, bool bUseCollision = false);

	/** Vertical line trace at document metres from TopZM down to BottomZM: the ODN metres of the hit, else NaN. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static double TraceDownZM(double XM, double YM, double TopZM, double BottomZM);

	/** Resident set size of this process in MB (FPlatformMemory::GetStats().UsedPhysical). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static double RssMb();

	/** {"extent": [minX, minY, maxX, maxY], "components": n, "proxies": n, "location_cm": [...], "scale": [...]}. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static FString LandscapeStateJson(ALandscapeProxy* Proxy);

	/**
	 * The target layers actually on the landscape after an import: every name in ALandscapeProxy::GetTargetLayers()
	 * with its ULandscapeLayerInfoObject path, plus the names ULandscapeInfo knows and which one is
	 * ALandscapeProxy::VisibilityLayer. Read-back proof for UE_PLAN.md 3.5 / DESIGN.md 9.
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static FString LandscapeLayersJson(ALandscapeProxy* Proxy);

	/**
	 * Painted weight of a named target layer at document metres (x east, y north), 0..1 by
	 * ULandscapeComponent::GetLayerWeightAtLocation (LandscapeEdit.cpp:2816, bilinear over the weightmap).
	 * -1 when the layer info, the landscape info or the component covering that point is missing (component
	 * not streamed in), so a caller can tell "no data here" from "weight 0 here".
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	static double ProbeLayerWeight(ALandscapeProxy* Proxy, double XM, double YM, FName LayerName);
};
