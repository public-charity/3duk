// StreetRenderers - the THREE renderers (UE_PLAN.md 2.6; DESIGN.md 4; BRIEF 1.1 "THREE RENDERERS ONLY").
//
// A: UStreetRoadRenderer  = road.py  (ribbon + camber + skirts + lifted marking strips; rail is a PROFILE KIND
//                           handled inside this renderer, never a fourth one - road.py dispatches to rail.py)
// B: UStreetEdgeRenderer  = edge.py  (kerb + PAVEMENT + drop kerbs + split materials + barriers + embankments)
// C: UStreetHedgeRenderer = hedge.py (volumetric swept hedge + fbm3 displacement + leaf-card instances)
//
// The geometry lives in FStreetRenderBuild: pure C++ statics over FStreetSamples that fill an FStreetMeshBuilder and
// an instance list in the JSON frame (metres, X east, Y north, Z up). The UDynamicMeshComponent subclasses only
// commit those buffers (ToDynamicMesh does the (100, -100, 100) conversion), so every number the Automation tests
// assert is produced without a world, an actor or an RHI - exactly the numbers Tools/blender/streetscape produces.

#pragma once

#include "CoreMinimal.h"
#include "Components/DynamicMeshComponent.h"       // GF/Components/DynamicMeshComponent.h
#include "StreetGeometry.h"
#include "StreetSplineMath.h"
#include "StreetTypes.h"
#include "StreetRenderers.generated.h"

class IStreetTerrainSource;
class UStreetMaterialTable;

/** instance.Instance: a (4x4) transform in document metres whose columns are (t_h, n, b, p), plus the box extents
    along those axes. Boxes span [-Sx/2, Sx/2] x [-Sy/2, Sy/2] x [0, Sz]; cards use Sz = 0. Never merged into a mesh. */
struct STREETSCAPE_API FStreetInstance
{
	FName Kind;
	FVector3d Th = FVector3d(1, 0, 0);
	FVector3d N = FVector3d(0, 1, 0);
	FVector3d B = FVector3d(0, 0, 1);
	FVector3d P = FVector3d::ZeroVector;
	FVector3d Size = FVector3d::ZeroVector;
	FName Material;
	FString SplineId;
	int32 Side = 0;

	/** UE transform of the instance: columns scaled by Size, origin at the box's bottom centre (cm). */
	FTransform ToUETransform() const;
};

/** What one renderer produced: the buffer, its instances and the counters stats.json carries. */
struct STREETSCAPE_API FStreetRenderResult
{
	FStreetMeshBuilder Buffer;
	TArray<FStreetInstance> Instances;
	int32 MarkingStrips = 0;
};

/** The three renderers as pure functions (mirror table UE_PLAN.md 2.14). */
struct STREETSCAPE_API FStreetRenderBuild
{
	// -- Renderer A (road.py) ------------------------------------------------------------------------------------
	/** Row layout of the ribbon: D / H are N x R, Groups is R-1 names, OutNInt the interior row count. */
	static void RibbonRows(const FStreetSamples& Sp, TArray<double>& OutD, TArray<double>& OutH, TArray<FName>& OutGroups, int32& OutNInt, int32& OutR);
	/** Height of the ribbon MESH (bilinear rows, quads split on the V(i,k)-V(i+1,k+1) diagonal) at (s, d). */
	static double MeshSurfaceH(const FStreetSamples& Sp, const TArray<double>& D, const TArray<double>& H, int32 R, double SQ, double DQ);
	/** Painted s-intervals of one marking inside [A, B] (road.marking_intervals). */
	static TArray<TPair<double, double>> MarkingIntervals(const FStreetMarking& M, double A, double B, double L);
	/** road.build_road: dispatches to BuildRail when Kind == Rail and knows nothing else about rails. */
	static void BuildRoad(const FStreetSamples& Sp, FStreetRenderResult& Out);
	/** rail.build_rail: ballast ribbon, sleeper instances, two BS113A rails. Called only from BuildRoad. */
	static void BuildRail(const FStreetSamples& Sp, FStreetRenderResult& Out);

	// -- Renderer B (edge.py) ------------------------------------------------------------------------------------
	/** n = floor(D/p) + 1 + [frac(D/p) > 0.5]; posts at a + j p for j < n - 1, the last at b. */
	static TArray<double> PostStations(double A, double B, double Pitch);
	static void BuildEdge(const FStreetSamples& Sp, EStreetSide Side, const IStreetTerrainSource* Terrain, FStreetRenderResult& Out);

	// -- Renderer C (hedge.py) -----------------------------------------------------------------------------------
	/** Closed clockwise polygon in (o, h): (0,0) up the inner face, over the top, down the outer face. */
	static TArray<FVector2d> HedgeSectionPoints(double W, double H, double R, int32 M, EStreetTopProfile Top);
	static TArray<FVector2d> SectionOutwardNormals(const TArray<FVector2d>& Pts);
	static void BuildHedge(const FStreetSamples& Sp, EStreetSide Side, FStreetRenderResult& Out);
};

/** Common base of the three renderers (UE_PLAN.md 2.6). */
UCLASS(Abstract, ClassGroup = Streetscape)
class STREETSCAPE_API UStreetRendererBase : public UDynamicMeshComponent
{
	GENERATED_BODY()
public:
	UStreetRendererBase();

	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bRebuildOnLoad = true;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bCollision = true;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TArray<FName> MaterialSlotIds;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 LastVertexCount = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 LastTriangleCount = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") double LastBuildMs = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") FStreetBuildStats Stats;

	/** Rebuild from the owning actor's samples (builds them when needed). */
	UFUNCTION(CallInEditor, BlueprintCallable, Category = "Streetscape") void Rebuild();
	UFUNCTION(BlueprintCallable, Category = "Streetscape") void Clear();

	/** Build into Out from already-computed samples; the actor calls this so every component shares one FStreetSamples. */
	virtual void BuildFrom(const FStreetSamples& Samples, const IStreetTerrainSource* Terrain, FStreetRenderResult& Out) const PURE_VIRTUAL(UStreetRendererBase::BuildFrom, );
	/** ToDynamicMesh + SetMesh + ConfigureMaterialSet + collision; keeps the stats. */
	void Commit(const FStreetRenderResult& In, const UStreetMaterialTable* Materials);
	/** Restore the mesh stashed by PreSave (called from AStreetscapeActor::PostSaveRoot). */
	void RestoreAfterSave();

	/**
	 * Turn bCollision into collision the physics scene can actually answer. UDynamicMeshComponent's constructor
	 * sets the NoCollision profile (GeometryFramework/Private/Components/DynamicMeshComponent.cpp:92), so
	 * SetComplexAsSimpleCollisionEnabled on its own cooks a triangle mesh that no trace or capsule will ever
	 * touch - the explorer would walk through the road (BRIEF 4.4 asks for the opposite).
	 */
	void ApplyCollision();

	const TArray<FStreetInstance>& GetInstances() const { return Instances; }
	/** The mesh buffer of the last build (empty before it): what ActorStatsJson and the seam tests measure. */
	const FStreetMeshBuilder& GetLastBuffer() const { return LastBuffer; }
	int32 GetMarkingStrips() const { return MarkingStrips; }

protected:
	virtual void OnRegister() override;
	virtual void PreSave(FObjectPreSaveContext ObjectSaveContext) override;

	TUniquePtr<UE::Geometry::FDynamicMesh3> Stash;
	TArray<FStreetInstance> Instances;
	FStreetMeshBuilder LastBuffer;
	int32 MarkingStrips = 0;
};

/** Renderer A. Kind == Rail builds ballast / sleepers / rails through the same component (DESIGN.md 6). */
UCLASS(ClassGroup = Streetscape, meta = (BlueprintSpawnableComponent))
class STREETSCAPE_API UStreetRoadRenderer : public UStreetRendererBase
{
	GENERATED_BODY()
public:
	virtual void BuildFrom(const FStreetSamples& Samples, const IStreetTerrainSource* Terrain, FStreetRenderResult& Out) const override;
};

/** Renderer B (one per side). */
UCLASS(ClassGroup = Streetscape, meta = (BlueprintSpawnableComponent))
class STREETSCAPE_API UStreetEdgeRenderer : public UStreetRendererBase
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetSide Side = EStreetSide::Left;
	virtual void BuildFrom(const FStreetSamples& Samples, const IStreetTerrainSource* Terrain, FStreetRenderResult& Out) const override;
};

/** Renderer C (one per side). */
UCLASS(ClassGroup = Streetscape, meta = (BlueprintSpawnableComponent))
class STREETSCAPE_API UStreetHedgeRenderer : public UStreetRendererBase
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, Category = "Streetscape") EStreetSide Side = EStreetSide::Right;
	virtual void BuildFrom(const FStreetSamples& Samples, const IStreetTerrainSource* Terrain, FStreetRenderResult& Out) const override;
};
