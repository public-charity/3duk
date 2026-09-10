// StreetJunctions - the SHARED junction layer (SCHEMA.md 4.18; DESIGN.md 3.9; BRIEF 1.1).
//
// A verbatim port of the junction half of Tools/blender/streetscape/spline.py: JunctionArm, JunctionPlan, ArmFrame,
// resolve_arm_frames, corner_curve and corner_frames, one static per numpy function, in the JSON frame (local metres,
// X east, Y north, Z up) and in doubles.
//
// WHY IT SITS HERE AND NOT IN A RENDERER. A junction is road SURFACE, so filling it is Renderer A
// (FStreetRenderBuild::BuildJunctionPatch) and turning the kerb round it is Renderer B (BuildJunctionCorners) - there
// is no fourth renderer. But the TRIMMING of a spline end back to the junction belongs one level lower, in the shared
// spline layer, because Renderer A and Renderer B must both see the same trimmed extent: if the carriageway stopped at
// the junction and the kerb did not, they would disagree the moment a width or a profile changed. FStreetJunctionPlan
// resolves the trim ONCE per document, in plan geometry only (no terrain), before any FStreetSamples is built; both
// trim stations then join the mandatory station set, so they exist EXACTLY in every renderer's station list.
//
// Junctions are DATA: the 1,642 records the adapter already writes into every site document as junctions[]. Nothing
// here invents a parallel mechanism.

#pragma once

#include "CoreMinimal.h"
#include "StreetProfiles.h"
#include "StreetSplineMath.h"
#include "StreetTimelines.h"
#include "StreetTypes.h"
#include "StreetJunctions.generated.h"

/** schema.JUNCTION_DEFAULTS. */
struct STREETSCAPE_API FStreetJunctionDefaults
{
	double SnapM = 0.3;
	/** angular clearance subtracted from each adjacent arm gap before the trim radius is solved */
	double ClearanceDeg = 2.0;
	/** beyond this an arm's requirement is UNSEPARABLE and is dropped from the maximum instead of driving it */
	double MaxTrimRadiusM = 20.0;
	double MinRemainingM = 1.0;
	double MaxTrimFracOfLength = 0.5;
	double CornerStepDeg = 10.0;
	double CornerHandleFrac = 0.45;
};

/**
 * spline.JunctionArm: one spline end standing in a junction, resolved in PLAN only (no terrain needed).
 *
 * A USTRUCT because the OWNING actor carries its junctions' solved arms through a save (FStreetOwnedJunction): the
 * plan is solved once, over the WHOLE document, and an owner streamed in on its own could never re-solve it - the
 * degeneracy scale of a spline trimmed at both ends couples two different junctions. Every member is the value the
 * numpy JunctionArm dataclass carries and nothing else.
 */
USTRUCT()
struct STREETSCAPE_API FStreetJunctionArm
{
	GENERATED_BODY()
	UPROPERTY() FString JunctionId;
	UPROPERTY() FString SplineId;
	UPROPERTY() EStreetSplineEnd End = EStreetSplineEnd::Start;
	UPROPERTY() double STrim = 0;            // arc length of the trim station on that spline
	UPROPERTY() double TrimM = 0;            // arc length removed from that end
	UPROPERTY() FVector2D U = FVector2D(1, 0);   // outward unit tangent at the trim station, pointing AWAY from the node
	UPROPERTY() FVector2D P = FVector2D::ZeroVector;   // plan position of the trim station
	UPROPERTY() double ELeft = 0;
	UPROPERTY() double ERight = 0;           // edge_offset(LEFT/RIGHT) at the trim station
	UPROPERTY() double OverlapM = 0.04;      // road skirt overhang at the trim station
	UPROPERTY() double Phi = 0;              // bearing of the TRIM POINT about the node - the angular order key
	UPROPERTY() double HalfAng = 0;          // angular half-width the arm's end edge subtends at the node, measured
	UPROPERTY() double RadiusM = 0;          // the trim radius THIS arm was solved at

	/** The arm's true plan half-extent at the trim: the outer edge of its skirt row. */
	double HalfExtentM() const { return FMath::Max(ELeft, ERight) + OverlapM; }
};

/**
 * One junction, solved: everything the two renderers need and nothing they do not.
 *
 * It is a VALUE, deliberately, so the same builders serve the plan (a whole document in one pass, as the numpy
 * build_all does) and an actor that carries only the junctions it owns - the geometry of a junction depends on its own
 * arms and on nothing else in the document.
 */
struct STREETSCAPE_API FStreetJunctionSpec
{
	FStreetJunction Junction;
	TArray<FStreetJunctionArm> Arms;     // canonical (bearing, spline id, end) order
	double TrimRadiusM = 0;
	FStreetJunctionDefaults Cfg;

	bool IsValid() const { return Arms.Num() >= 3; }
};

// ---------------------------------------------------------------------------------------------------------------
// What an ACTOR carries, so a junction is right whatever World Partition has loaded
// ---------------------------------------------------------------------------------------------------------------
//
// A junction's arms are different AStreetscapeActors - one actor per spline - and the patch goes into the OWNING
// spline's own road buffer (build.build_all). Neither the plan nor the arms can be re-derived by an actor on its
// own: the plan is a per-DOCUMENT solve, and a spline trimmed at both ends couples two junctions through one
// degeneracy scale factor. So the whole-document solve happens ONCE, at import, and its result is SERIALISED onto
// the actors:
//
//   * every arm actor keeps its own {t_start, t_end}, so an arm loaded without its junction's owner is still
//     trimmed - the kerb and the carriageway stop where they should even with nothing else resident;
//   * the owner keeps the solved arms AND the FStreetSplineDef of every arm it does not own, so it rebuilds each
//     arm's FStreetSamples itself and can draw the complete patch and every kerb corner with no other actor
//     loaded at all.
//
// Nothing here consults the world for another actor, which is the point: the geometry does not depend on load
// order, on streaming radius, or on which cell the camera is in. The price is that ~3.5k arm definitions are
// duplicated onto their owners (about 5 MB of the 23 MB the documents themselves occupy) and that an owner builds
// its arms' samples a second time. Both were preferred to a junction that is only right when everything is in.
//
// THE LIMITATION, STATED. The owner's copy of an arm is a COPY, taken at import. Drag an arm spline's points in
// the editor and that arm rebuilds, but its junction does not: the owner still holds the definition the document
// had, so the patch would meet where the ribbon used to be. Junctions are import-time data - re-import the
// DOCUMENT (03_import_streetscape.py --files <that file>) after editing a spline that stands in one, which
// re-solves the whole document's plan and rewrites every affected actor. This is a real constraint and not a
// latent bug: the import path is the only writer, and it always rewrites a whole document at once.

/** One arm as its OWNER carries it: the solved arm, plus what the owner needs to rebuild that arm's samples. */
USTRUCT()
struct STREETSCAPE_API FStreetJunctionArmRecord
{
	GENERATED_BODY()
	UPROPERTY() FStreetJunctionArm Arm;
	/** The arm spline's definition - EMPTY for the owner's own arm, which uses the owner's already-built samples. */
	UPROPERTY() FStreetSplineDef Def;
	/** That arm spline's whole-document trim {t_start, t_end}: the owner must build it exactly as its own actor does. */
	UPROPERTY() FVector2D TrimM = FVector2D::ZeroVector;
	UPROPERTY() bool bIsOwner = false;
};

/** One junction as its OWNER carries it. Cfg is not stored: every solve uses FStreetJunctionDefaults. */
USTRUCT()
struct STREETSCAPE_API FStreetOwnedJunction
{
	GENERATED_BODY()
	UPROPERTY() FStreetJunction Junction;
	UPROPERTY() double TrimRadiusM = 0.0;
	UPROPERTY() TArray<FStreetJunctionArmRecord> Arms;   // canonical (bearing, spline id, end) order

	FStreetJunctionSpec ToSpec() const
	{
		FStreetJunctionSpec Spec;
		Spec.Junction = Junction;
		Spec.TrimRadiusM = TrimRadiusM;
		Spec.Arms.Reserve(Arms.Num());
		for (const FStreetJunctionArmRecord& R : Arms) Spec.Arms.Add(R.Arm);
		return Spec;
	}
};

/** The per-actor junction counters the census and the import gate add up (road.build_junction_patch's dict). */
USTRUCT()
struct STREETSCAPE_API FStreetActorJunctionStats
{
	GENERATED_BODY()
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 Owned = 0;        // junctions this actor owns
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 Built = 0;        // ... of which a patch was built
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 Skipped = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 NonMonotone = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 PatchVerts = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 PatchTris = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 Corners = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 CornersSkippedNoKerb = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 CornersSkippedIncompatible = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 CornerVerts = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") int32 CornerTris = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") double PatchAreaM2 = 0;
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") double PatchOverlapAreaM2 = 0;

	void Add(const FStreetActorJunctionStats& O)
	{
		Owned += O.Owned; Built += O.Built; Skipped += O.Skipped; NonMonotone += O.NonMonotone;
		PatchVerts += O.PatchVerts; PatchTris += O.PatchTris; Corners += O.Corners;
		CornersSkippedNoKerb += O.CornersSkippedNoKerb; CornersSkippedIncompatible += O.CornersSkippedIncompatible;
		CornerVerts += O.CornerVerts; CornerTris += O.CornerTris;
		PatchAreaM2 += O.PatchAreaM2; PatchOverlapAreaM2 += O.PatchOverlapAreaM2;
	}
};

/**
 * spline.JunctionPlan - the junction geometry of one document, solved once, in plan, before any spline is built.
 *
 * THE TRIM RADIUS, derived (never stored). Order the arms by Phi, the bearing of the arm's TRIM POINT about the node,
 * and give arm i the half-extent e_i = max(e_left, e_right) + overlap - the outer edge of its skirt row, which is
 * where the ribbon actually ends in plan. At trim radius d that arm subtends about atan(e_i / d) there (HalfAng,
 * measured exactly from its own two skirt corners). The patch that fills the junction is a fan from the node, and that
 * fan is free of self-overlap exactly when its boundary is angularly monotone about the node - i.e. when no two
 * neighbouring arms overlap in bearing. Requiring EACH arm to take at most half of EACH of its two adjacent gaps is
 * sufficient and gives a closed form, with D_i the smaller of arm i's two adjacent gaps:
 *
 *     atan(e_i / d) <= (D_i - eps) / 2   =>   requirement_i = e_i / tan((D_i - eps) / 2)
 *     d = clamp(max over arms of requirement_i, radius_m, MaxTrimRadiusM)
 *
 * Phi is the bearing of the trim POINT and not of the outward TANGENT because on a spline that curves near its end the
 * tangent swings far faster than the node direction does, and a fixed point solved on the tangent oscillates instead
 * of converging (measured on Thanet junction 16_10:0: 17.09 m and 128.6 m2 of double cover on the tangent against
 * 16.90 m and 8.6 m2 on the node bearing).
 *
 * Because e and Phi are read at the trim station and the trim station depends on d, the solve is a fixed-point
 * iteration from d = radius_m, run to convergence within Iters passes.
 *
 * DEGENERACY. A spline trimmed at both ends keeps at least MinRemainingM; when the two trims would leave less, BOTH
 * are scaled by one common factor k in [0, 1] so the spline shortens symmetrically instead of vanishing or inverting,
 * and the arms are then re-derived at the scaled trims so the patch still meets the ribbon exactly.
 */
class STREETSCAPE_API FStreetJunctionPlan
{
public:
	static constexpr int32 Iters = 8;

	FStreetJunctionPlan() = default;
	explicit FStreetJunctionPlan(const FStreetSiteDoc& Doc, const FStreetJunctionDefaults& InCfg = FStreetJunctionDefaults())
	{
		Build(Doc, InCfg);
	}
	void Build(const FStreetSiteDoc& Doc, const FStreetJunctionDefaults& InCfg = FStreetJunctionDefaults());

	/** {t_start, t_end} in metres for one spline; {0, 0} when it stands in no junction. */
	void TrimFor(const FString& SplineId, double OutTrim[2]) const;
	bool IsTrimmed(const FString& SplineId) const;
	/** The spline whose road buffer carries this junction's patch: the first arm in the canonical order. */
	FString Owner(const FString& JunctionId) const;
	TArray<FString> JunctionsOwnedBy(const FString& SplineId) const;
	/** Junction ids that have arms, in sorted order (the order build_all walks them in). */
	TArray<FString> BuiltJunctionIds() const;
	const TArray<FStreetJunctionArm>* Arms(const FString& JunctionId) const { return ArmsByJunction.Find(JunctionId); }
	const FStreetJunction* Junction(const FString& JunctionId) const;
	/** The solved junction as a self-contained value; Arms empty when the id has no arms. */
	FStreetJunctionSpec SpecFor(const FString& JunctionId) const;
	double TrimRadius(const FString& JunctionId) const { const double* R = TrimRadiusById.Find(JunctionId); return R ? *R : 0.0; }
	const FStreetJunctionDefaults& Cfg() const { return Config; }

	/** JunctionPlan.stats, keyed exactly as the numpy dict. */
	TMap<FString, int32> Stats;
	TArray<FString> Notes;

private:
	struct FCurve
	{
		TArray<FStreetPoint> Points;
		TArray<double> SD;
		TArray<FVector2d> XYD;
		TArray<double> SKnots;
		TArray<FVector2d> TD;
		TArray<double> Xd, Yd, Tx, Ty;   // XYD / TD split into the arrays Interp wants, cached: the fixed-point
		                                 // iteration reads them Iters times per arm
		const FRoadProfileData* RoadProf = nullptr;
		FStreetRoadTimeline RoadTl;
		double L = 0;
	};
	const FCurve* Curve(const FString& SplineId) const;
	bool ArmAt(const FString& Jid, const FString& SplineId, EStreetSplineEnd End, double Cx, double Cy, double D, FStreetJunctionArm& Out) const;
	bool ArmFromStation(const FString& Jid, const FString& SplineId, EStreetSplineEnd End, double St, double Cx, double Cy, FStreetJunctionArm& Out) const;
	void SolveRadii(const TArray<FStreetJunctionArm>& InArms, double RFloor, TArray<double>& OutD, TArray<bool>& OutUnsep) const;

	const FStreetSiteDoc* Doc = nullptr;
	FStreetJunctionDefaults Config;
	mutable TMap<FString, FCurve> Curves;
	TMap<FString, TArray<FStreetJunctionArm>> ArmsByJunction;
	TMap<FString, double> TrimRadiusById;
	TMap<FString, TArray<double>> Trims;   // spline id -> {t_start, t_end}
};

/**
 * spline.ArmFrame: one arm of a junction resolved against its BUILT spline - the station index of the trim, the
 * outward direction, and the two kerb-line origins (position, INWARD normal, up) the corner fillets start and end on.
 * Lo is the side at the lower bearing about the node and Hi the side at the higher, so walking the arms
 * anticlockwise walks lo -> hi.
 */
struct STREETSCAPE_API FStreetArmFrame
{
	const FStreetJunctionArm* Arm = nullptr;
	const FStreetSamples* Spline = nullptr;
	int32 I = 0;
	FVector3d U = FVector3d(1, 0, 0);
	EStreetSide SideLo = EStreetSide::Right;
	EStreetSide SideHi = EStreetSide::Left;
	FVector3d PLo = FVector3d::ZeroVector, NLo = FVector3d::ZeroVector, BLo = FVector3d::ZeroVector;
	FVector3d PHi = FVector3d::ZeroVector, NHi = FVector3d::ZeroVector, BHi = FVector3d::ZeroVector;
};

struct STREETSCAPE_API FStreetJunctionMath
{
	/** [ArmFrame] in anticlockwise order; false when an arm's spline is missing from Splines or carries no kind. */
	static bool ResolveArmFrames(const FStreetJunctionSpec& Spec, const TMap<FString, const FStreetSamples*>& Splines, TArray<FStreetArmFrame>& Out);

	/**
	 * spline.corner_curve - the kerb corner between two arms: a cubic fillet from A leaving along Dir0 and arriving at
	 * B along Dir1, sampled at StepDeg of turn.
	 *
	 * Why a cubic and not a circle: a single circular arc can be tangent to BOTH kerb lines at BOTH trim ends only
	 * when the two ends happen to be equidistant from the intersection of their normals - true for a symmetric
	 * right-angle crossroads, false for a skew crossing or two arms of different width. The handle length
	 * m = (4/3) tan(|tau|/4) r is the standard circular-arc handle, so where a circle does exist this curve IS that
	 * circle to 2e-4 of its radius, and where it does not the curve is still G1 at both ends. HandleFrac caps the
	 * handle at a fraction of the endpoint's distance to the node so the fillet can never fold back through it.
	 *
	 * OutP[0] == A and OutP.Last() == B exactly.
	 */
	static void CornerCurve(const FVector3d& A, const FVector3d& B, const FVector2d& Dir0, const FVector2d& Dir1,
		const FVector2d& NodeXY, double StepDeg, double HandleFrac, TArray<FVector3d>& OutP, TArray<FVector3d>& OutT);

	/**
	 * spline.corner_frames - frames along a corner: positions P, tangents T, and the INWARD normal lerped from N0 to
	 * N1, orthogonalised against the tangent and renormalised (the rule FStreetFrames::At already uses), so a corner
	 * is banked the way the two straights it joins are. B = T x N then points up, and a sweep with Side = -1 puts the
	 * section's outward o away from the junction. The endpoints are forced to N0 / N1 exactly so the corner's first
	 * and last rings coincide with the arms' own rings. S carries the cumulative plan length along the corner.
	 */
	static FStreetFrames CornerFrames(const TArray<FVector3d>& P, const TArray<FVector3d>& T, const FVector3d& N0, const FVector3d& N1);
};
