// StreetTerrainSource - what the shared spline samples heights from (UE_PLAN.md 2.5.5; DESIGN.md 8).
//
// FStreetHeightfield is a literal transcription of Tools/blender/streetscape/terrain.py (itself a transcription of
// sources/derive/06_build_networks.py:54-69): tiled north-up float32 heights, pixel centres on integer metres, row 0
// north, adjacent tiles sharing their edge row/column (513 samples per 512 m), bilinear between pixel centres with the
// inward clamp at the last row/column, NaN (false) off coverage or where any of the four samples is NaN.
//
// Frames: a heightfield carries the survey origin (E, N) of its tile (0, 0) corner. A document authored in another
// origin is sampled after SetDocumentOrigin(E_doc, N_doc): x_hf = x_doc + (E_doc - E_hf) (terrain.Heightfield.rebased).
// The IStreetTerrainSource interface takes JSON-frame metres of the DOCUMENT and returns ODN metres.

#pragma once

#include "CoreMinimal.h"
#include "UObject/Interface.h"
#include "UObject/Object.h"
#include "StreetTerrainSource.generated.h"

class ALandscapeProxy;

/** Pure C++ heightfield (no UObject), so the tests and the numpy-parity checks can use it directly. */
struct STREETSCAPE_API FStreetHeightfield
{
	double TileM = 512.0;
	int32 Res = 513;
	double PxM = 1.0;
	TMap<FIntPoint, TArray<float>> Tiles;   // (i, j) -> Res*Res floats, row 0 = north; NaN = no ground
	double OriginE = 0.0;                    // survey E of the local x = 0 line of THIS heightfield
	double OriginN = 0.0;
	FVector2d ShiftXY = FVector2d::ZeroVector;   // added to query (x, y) before lookup (document -> heightfield frame)
	FVector2d XY0 = FVector2d::ZeroVector;       // heightfield-frame coordinates of tile (0, 0)'s SW corner
	FString Source;
	TArray<FIntPoint> TilesMissing, TilesClipped;

	/** Synthetic field: Fn(x, y) over local metres; tiles cover [XY0, XY0 + Extent) (terrain.Heightfield.from_function). */
	static FStreetHeightfield FromFunction(TFunctionRef<double(double, double)> Fn, FVector2d ExtentM = FVector2d(512.0, 512.0), double PxM = 1.0, double TileM = 512.0,
		FVector2d Origin = FVector2d::ZeroVector, FVector2d InXY0 = FVector2d::ZeroVector);
	/** Adapter product (PIPELINE_CHANGES.md 13.3): landscape_manifest.json + hm_x{i}_y{j}.r16 + clip_x{i}_y{j}.r8. */
	bool LoadLandscapeDir(const FString& Dir, FText* Err);

	/** terrain.Heightfield.rebased: sample documents whose origin is (DocE, DocN). */
	void SetDocumentOrigin(double DocE, double DocN) { ShiftXY = FVector2d(DocE - OriginE, DocN - OriginN); }

	/** Bilinear sample at document-frame metres; false = NaN (off coverage / nodata). */
	bool Sample(double X, double Y, double& OutZ) const;
	/** Document-frame bounds of the tiled coverage (x0, y0, x1, y1); false when empty. */
	bool Bounds(double& X0, double& Y0, double& X1, double& Y1) const;
	FString Describe() const;
};

UINTERFACE(MinimalAPI)
class UStreetTerrainSource : public UInterface
{
	GENERATED_BODY()
};

class STREETSCAPE_API IStreetTerrainSource
{
	GENERATED_BODY()
public:
	/** JSON frame (document metres) in, ODN metres out; false = no ground. */
	virtual bool SampleHeight(double XM, double YM, double& OutZM) const = 0;
	virtual FString Describe() const = 0;
	/** Document origin (survey E, N) the queries are expressed in. */
	virtual void SetDocumentOrigin(double E, double N) {}
};

/** Plain C++ adapter: an FStreetHeightfield as an IStreetTerrainSource (tests, numpy parity). */
class STREETSCAPE_API FStreetHeightfieldSource : public IStreetTerrainSource
{
public:
	explicit FStreetHeightfieldSource(const FStreetHeightfield& In) : Field(In) {}
	FStreetHeightfield Field;
	virtual bool SampleHeight(double XM, double YM, double& OutZM) const override { return Field.Sample(XM, YM, OutZM); }
	virtual FString Describe() const override { return Field.Describe(); }
	virtual void SetDocumentOrigin(double E, double N) override { Field.SetDocumentOrigin(E, N); }
};

UCLASS(Abstract, EditInlineNew, DefaultToInstanced, BlueprintType)   // COU/UObject/ObjectMacros.h:237 CLASS_EditInlineNew, :260 CLASS_DefaultToInstanced
class STREETSCAPE_API UStreetTerrainSourceBase : public UObject, public IStreetTerrainSource
{
	GENERATED_BODY()
public:
	virtual bool SampleHeight(double XM, double YM, double& OutZM) const override { return false; }
	virtual FString Describe() const override { return GetClass()->GetName(); }
};

/** The adapter's heightfield (hm_*.r16 + clip_*.r8 under LandscapeDir) - the reference terrain of every build. */
UCLASS(EditInlineNew, DefaultToInstanced, BlueprintType)
class STREETSCAPE_API UStreetHeightfieldTerrain : public UStreetTerrainSourceBase
{
	GENERATED_BODY()
public:
	/** Directory holding landscape_manifest.json; empty = UStreetscapeSettings::DataDir / "landscape". */
	UPROPERTY(EditAnywhere, Category = "Streetscape") FString LandscapeDir;
	/** Document origin (survey metres) that queries are expressed in; defaults to the manifest origin. */
	UPROPERTY(EditAnywhere, Category = "Streetscape") FVector2D DocumentOriginEN = FVector2D::ZeroVector;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bDocumentOriginSet = false;

	UFUNCTION(BlueprintCallable, Category = "Streetscape") bool Load();
	UFUNCTION(BlueprintCallable, Category = "Streetscape") bool IsLoaded() const { return bLoaded; }
	UFUNCTION(BlueprintCallable, Category = "Streetscape") int32 NumTiles() const { return Field.Tiles.Num(); }
	/** NaN when no ground (the Python-friendly probe). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape") double ProbeM(double XM, double YM) const;
	FString ResolvedDir() const;

	virtual bool SampleHeight(double XM, double YM, double& OutZM) const override;
	virtual FString Describe() const override;
	virtual void SetDocumentOrigin(double E, double N) override;
	const FStreetHeightfield& GetField() const { return Field; }
	FStreetHeightfield& GetFieldMutable() { return Field; }

private:
	FStreetHeightfield Field;
	bool bLoaded = false;
	FString LastError;
};

/** Samples the imported ALandscape (in-editor verification of the import; 1 cm at vertices vs the heightfield). */
UCLASS(EditInlineNew, DefaultToInstanced, BlueprintType)
class STREETSCAPE_API UStreetLandscapeTerrain : public UStreetTerrainSourceBase
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, Category = "Streetscape") TWeakObjectPtr<ALandscapeProxy> Landscape;
	virtual bool SampleHeight(double XM, double YM, double& OutZM) const override;   // LS/Classes/LandscapeProxy.h GetHeightAtLocation
	virtual FString Describe() const override;
};
