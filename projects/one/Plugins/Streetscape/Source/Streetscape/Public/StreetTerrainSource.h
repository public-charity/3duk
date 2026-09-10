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

/**
 * How a sample between four grid posts is interpolated.
 *
 * Bilinear is the numpy prototype's rule (Tools/blender/streetscape/terrain.py) and the frozen contract every
 * parity number in fixtures/expected.json was computed with.
 *
 * LandscapeTriangulated is what the ALandscape the explorer collides with actually is. UE stores a landscape as
 * a triangle mesh, and Chaos splits every cell along its (0,0)-(1,1) diagonal:
 *   Chaos::FHeightField::GetHeightAt -> GetHeightNormalAt
 *   (Engine/Source/Runtime/Experimental/Chaos/Private/Chaos/HeightField.cpp:921-968), reached from
 *   ULandscapeHeightfieldCollisionComponent::GetHeight (LandscapeCollision.cpp:2548) and
 *   ALandscapeProxy::GetHeightAtLocation (LandscapeCollision.cpp:2703).
 * With Fx, Fy the fractions inside the cell and P00 north-west, P10 north-east, P01 south-west, P11 south-east
 * (grid +Y is landscape +Y = south):
 *   Fx <  Fy:  P00*(1 - Fy) + P11*Fx        + P01*(Fy - Fx)
 *   Fx >= Fy:  P00*(1 - Fx) + P10*(Fx - Fy) + P11*Fy
 *
 * THE DIAGONAL, DETERMINED RATHER THAN ASSUMED. Both branches share P00 and P11, so the quad is split on the
 * NW-SE diagonal: Fx < Fy is the south-west triangle and Fx >= Fy the north-east one. A quad can be split either
 * way and the two choices differ by the full |twist|/4 at the quad centre - up to 6.12 m at the Thanet maximum -
 * so getting it backwards would be worse than using bilinear. It was settled by MEASUREMENT against the running
 * engine, not by reading a header: predicting z_heightfield - z_landscape at 6,958 probe points with nothing but
 * this expression minus the bilinear one leaves a residual of 0.000587 m maximum and 0.0000983 m rms over the
 * 6,866 points further than 1 m from a tile boundary (docs/TERRAIN_ROADS.md 3.4,
 * Saved/Diag/d2_interp_vs_engine.json). Flipping the comparison to Fx > 1 - Fy would have to leave a residual the
 * size of the term itself, and does not. Tools/blender/streetscape/terrain.py:_interp is the same expression.
 *
 * The two rules differ by up to 0.52 m on Thanet's steepest ground (measured over 1200 gradient-rich points),
 * which is four times the 0.125 m kerb Renderer B exists to model, so a street draped with one sits above or
 * below the ground the pawn walks on.
 *
 * WHICH IS THE DEFAULT, AND WHY THERE ARE TWO ANSWERS. FStreetHeightfield - the pure struct the numpy-parity
 * fixtures drive - keeps Bilinear, because that is the default of the numpy Heightfield dataclass
 * (Tools/blender/streetscape/terrain.py:77) and every frozen number in fixtures/expected.json was computed with
 * it. UStreetHeightfieldTerrain - the terrain source that decides where a REAL road sits in the level - defaults
 * to LandscapeTriangulated, because a consumer that must sit ON the landscape has to use the landscape's own
 * rule (landscape_manifest.json:sampling_note), and the numpy tools that decide the same thing already do:
 * Tools/road_fusion_audit.py --sampling defaults to landscape_triangulated and the corridor conform is measured
 * with it. On the synthetic fixtures the choice is invisible - they are planar, and a triangulation of a plane is
 * that plane - which is why Streetscape.Terrain.SamplerAgreement measures that as an equality rather than
 * assuming it.
 */
UENUM(BlueprintType)
enum class EStreetHeightSampling : uint8
{
	Bilinear             UMETA(DisplayName = "Bilinear (numpy parity)"),
	LandscapeTriangulated UMETA(DisplayName = "Landscape triangulated (what the pawn walks on)"),
};

/** Pure C++ heightfield (no UObject), so the tests and the numpy-parity checks can use it directly. */
struct STREETSCAPE_API FStreetHeightfield
{
	/** Bilinear: the numpy Heightfield dataclass's default (terrain.py:77) and the contract every frozen parity
	    number was computed with. UStreetHeightfieldTerrain::Load overwrites it with that source's own setting. */
	EStreetHeightSampling Sampling = EStreetHeightSampling::Bilinear;
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
	/** Python-facing name for the virtual Describe() (a plain virtual is invisible to unreal.py). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape") FString DescribeSource() const { return Describe(); }

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
	/**
	 * Interpolation between grid posts, defaulting to LandscapeTriangulated: this is the source a real street is
	 * draped from, and what ALandscape::GetHeightAtLocation returns between the posts is what the pawn collides
	 * with and the camera sees. See EStreetHeightSampling for the diagonal, the measurement that settled it, and
	 * why the pure FStreetHeightfield keeps the numpy contract's Bilinear instead.
	 */
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetHeightSampling Sampling = EStreetHeightSampling::LandscapeTriangulated;

	/** Python-facing setter (the UPROPERTY alone is enough for Blueprint, not for a running commandlet's cache). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape") void SetSampling(EStreetHeightSampling In) { Sampling = In; Field.Sampling = In; }

	/**
	 * VERIFICATION ONLY: replace the field with the synthetic plane the frozen fixtures were computed on -
	 * z = Z0 + GX * (x - 200) + GY * (y - 100), sampled the way tests/synthetic.py samples it (one 512 m tile of
	 * 1 m posts with its south-west corner at (0, -256), float32, bilinear).
	 *
	 * It exists because the ONLY honest way to prove the junction wiring is to drive the real
	 * ImportStreetscapeJson over the six frozen documents, and that path takes its heights from the site actor's
	 * terrain source - which otherwise can only be a landscape directory on disk. This makes the terrain the
	 * fixtures were frozen against reachable from a headless run, and it changes nothing about a site import: the
	 * flag it sets is the same bLoaded a real Load() sets, and LandscapeDir is left alone.
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetscape") void SetSyntheticPlane(double Z0, double GX, double GY);

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
