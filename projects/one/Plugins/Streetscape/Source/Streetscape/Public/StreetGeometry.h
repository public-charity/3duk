// StreetGeometry - the geometry core (UE_PLAN.md 2.7; DESIGN.md 4, 5): mesh buffer, the one cross-section sweep, the
// integer-hash noise, the seam/marking measurement helpers, and ToDynamicMesh (THE frame conversion for meshes).
// Pure C++ ports of Tools/blender/streetscape/{mesh, sweep, noise}.py in the JSON frame and doubles.

#pragma once

#include "CoreMinimal.h"
#include "IndexTypes.h"
#include "StreetSplineMath.h"
#include "StreetGeometry.generated.h"

namespace UE::Geometry { class FDynamicMesh3; }

/** stats.json per-buffer keys (DESIGN.md 14). */
USTRUCT(BlueprintType)
struct STREETSCAPE_API FStreetBuildStats
{
	GENERATED_BODY()
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 Verts = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 Tris = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") FVector3d BBoxMin = FVector3d::ZeroVector;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") FVector3d BBoxMax = FVector3d::ZeroVector;
	/** name -> (tris, verts) */
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TMap<FName, FIntPoint> PerMaterial;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TMap<FName, FIntPoint> PerGroup;
};

/** (o, h, material, v, smooth) in the (o, h) plane of the station frame (sweep.SectionPoint). */
struct STREETSCAPE_API FStreetSectionPoint
{
	double O = 0, H = 0;
	FName Mat;
	double V = 0;
	bool bSmooth = false;
};

/** sweep.Section: orientation rule - walking the points with o to the right and h up, the EXPOSED surface is on the
    LEFT (open sections list the visible surface so; closed sections are listed clockwise). */
struct STREETSCAPE_API FStreetSection
{
	TArray<FStreetSectionPoint> Points;
	bool bClosed = false;

	int32 NumPoints() const { return Points.Num(); }
	int32 NumEdges() const { return bClosed ? Points.Num() : Points.Num() - 1; }
	/** pts = (o, h, mat); v defaults to the cumulative section length; Smooth empty = all hard, one entry = all. */
	static FStreetSection Make(bool bClosed, const TArray<TTuple<double, double, FName>>& Pts, const TArray<bool>& Smooth = {}, const TArray<double>& V = {});
};

/** mesh.MeshBuffer: vertex attributes vs (station s), vd (signed lateral, + left), vh (height above z_ref) make the
    seam and marking tests measurements rather than guesses. */
struct STREETSCAPE_API FStreetMeshBuilder
{
	TArray<FVector3d> V;
	TArray<UE::Geometry::FIndex3i> F;
	TArray<FVector2d> UV;
	TArray<int32> Mat, Grp;
	TArray<double> VS, VD, VH;
	TArray<FName> MaterialNames, GroupNames;
	TSet<FName> TwoSided;

	int32 MaterialId(FName Name);
	int32 GroupId(FName Name);
	int32 FindMaterialId(FName Name) const { return MaterialNames.IndexOfByKey(Name); }
	int32 FindGroupId(FName Name) const { return GroupNames.IndexOfByKey(Name); }
	/** Append vertices; returns the index of the first one. */
	int32 AppendVertices(TConstArrayView<FVector3d> P, TConstArrayView<FVector2d> InUV, TConstArrayView<double> S, TConstArrayView<double> D, TConstArrayView<double> H);
	void AppendTriangles(TConstArrayView<UE::Geometry::FIndex3i> T, TConstArrayView<int32> MatIds, int32 GrpId);
	void AppendTriangles(TConstArrayView<UE::Geometry::FIndex3i> T, int32 MatId, int32 GrpId);
	/** Ear-clip the ring (vertex indices) in its best plane (Newell normal), oriented toward the hint; returns the count. */
	int32 AppendPolygon(TConstArrayView<int32> Ring, int32 MatId, int32 GrpId, const FVector3d& NormalHint);
	void Merge(const FStreetMeshBuilder& Other);

	FVector3d FaceNormal(int32 T) const;   // unnormalised (b - a) x (c - a)
	double FaceArea(int32 T) const;
	TArray<FString> Validate() const;
	/** Every edge in exactly two triangles with opposite orientation, after welding coincident vertices. */
	bool IsClosedManifold(const TSet<FName>* MatFilter = nullptr, const TSet<FName>* GrpFilter = nullptr, double Tol = 1e-9) const;
	FStreetBuildStats Stats() const;

	TArray<bool> GroupMaskTris(const FString& Prefix, const FName* Exact = nullptr) const;
	/** Indices of vertices used by triangles of the named group(s) (sorted unique). */
	TArray<int32> VerticesOfGroups(const FString& Prefix, const FName* Exact = nullptr, const FString* ExcludePrefix = nullptr) const;
};

struct STREETSCAPE_API FStreetSweepParams
{
	int32 Side = +1;
	double LateralScalar = 0.0, HeightScalar = 0.0;
	TArray<double> Lateral, Height;          // (N) or empty -> scalar
	TArray<double> PointO, PointH;           // (N x P) per-station overrides of every point's o / h, or empty
	TArray<bool> Mask;                       // (N) station present, empty = all
	TArray<bool> QuadMask;                   // (N-1) quad emitted, empty = all
	bool bCapStart = true, bCapEnd = true;
	FName CapMat;                            // None = first point's material
	FName Group;                             // one name for every triangle ...
	TArray<FName> Groups;                    // ... or one per section edge (E)
	TArray<FName> EdgeMat;                   // material per section edge (default: the edge's start point mat)
	TArray<FName> EdgeMatStation;            // (N x E) per station and edge (quad (i, i+1) uses row i), or empty
	bool bTwoSided = false;
};

struct STREETSCAPE_API FStreetSweepResult
{
	int32 N = 0, R = 0;
	TArray<int32> VIdx;                      // N x R vertex ids, -1 where not emitted
	TArray<int32> RowPoint;                  // (R) section point index of each row
	TArray<FIntPoint> EdgeRows;              // (E) [start row, end row] of each section edge
	FIntPoint TriRange = FIntPoint(0, 0);
	int32 NumQuads = 0;
	TArray<FIntPoint> Runs;                  // station index ranges [i0, i1] of the emitted runs
	int32 VertexAt(int32 Station, int32 Row) const { return VIdx[Station * R + Row]; }
};

struct STREETSCAPE_API FStreetSweep
{
	/** sweep.sweep: rows/quads/winding/caps = DESIGN.md 4. */
	static FStreetSweepResult Sweep(FStreetMeshBuilder& Buf, const FStreetSection& Section, const FStreetFrames& Frames, const FStreetSweepParams& Params);
	/** Row layout: (row_point (R), edge_rows (E)). */
	static void Rows(const FStreetSection& Section, TArray<int32>& OutRowPoint, TArray<FIntPoint>& OutEdgeRows);
	/** (N-1) quad mask: quad (i, i+1) emitted when it lies inside one of the closed intervals. */
	static TArray<bool> RunsToQuadMask(TConstArrayView<double> S, const TArray<TPair<double, double>>& Intervals);
};

/** noise.py: uint32 arithmetic so it reproduces numpy bit for bit (DESIGN.md 3.8). */
struct STREETSCAPE_API FStreetNoise
{
	static uint32 LowBias32(uint32 X);
	/** in [-1, 1) */
	static double UnitNoise(uint32 I, uint32 Seed);
	static double UnitNoise01(uint32 I, uint32 Seed) { return (UnitNoise(I, Seed) + 1.0) * 0.5; }
	static double Lattice(int64 Ix, int64 Iy, int64 Iz, uint32 Seed);
	static double ValueNoise3(const FVector3d& P, uint32 Seed);
	/** two-octave normalised value noise in [-1, 1] */
	static double Fbm3(const FVector3d& P, uint32 Seed);
};

struct STREETSCAPE_API FStreetGeometry
{
	/** THE frame conversion for meshes: vertices x (100, -100, 100), winding kept (the mirror's handedness flip and UE's
	    left-handed front-face convention cancel), material ids, UVs, per-vertex normals.
	    Returns the number of triangles the mesh refused (non-manifold / duplicate). */
	static int32 ToDynamicMesh(const FStreetMeshBuilder& In, UE::Geometry::FDynamicMesh3& Out);

	// -- mesh.py helpers (no LAPACK anywhere) --
	static FVector3d NewellNormal(TConstArrayView<FVector3d> P);
	static void PlaneBasis(const FVector3d& N, FVector3d& OutU, FVector3d& OutW);
	static double PolygonArea2D(TConstArrayView<FVector2d> Pts);
	/** Ear clipping of a simple polygon of either orientation -> (K-2) index triples. */
	static TArray<UE::Geometry::FIndex3i> TriangulatePolygon2D(TConstArrayView<FVector2d> Pts);
	/** Map every vertex to the index of the first vertex within Tol (coordinate quantisation). */
	static TArray<int32> WeldIndices(TConstArrayView<FVector3d> V, double Tol = 1e-9);
	static TArray<FVector3d> DistinctPositions(TConstArrayView<FVector3d> V, double Tol = 1e-9);

	// -- measurements for the seam tests (DESIGN.md 5) --
	struct FOverlap { double MinM = NAN, MaxM = NAN; TArray<double> PerStation; TArray<double> Stations; };
	static TArray<double> StationValues(const FStreetMeshBuilder& Buf, const FString& ExcludePrefix = TEXT("marking:"));
	static FOverlap MeasureLateralOverlap(const FStreetMeshBuilder& Road, const FStreetMeshBuilder& Edge, int32 Side, double TuckDepth = 0.03);
	static int32 CoincidentXYPositions(const FStreetMeshBuilder& A, const FStreetMeshBuilder& B, double DLo, double DHi, int32 Side, double TolXY = 1e-6, double TolZ = 1e-6, double Dedup = 1e-9);
	/** vh of the (non-marking) mesh at (s, d): barycentric on the triangle whose (vs, vd) footprint contains it; NaN when none. */
	static double SurfaceHeightAt(const FStreetMeshBuilder& Buf, double S, double D, const FString& GroupPrefixExclude = TEXT("marking:"));
};
