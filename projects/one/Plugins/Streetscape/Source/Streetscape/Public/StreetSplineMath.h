// StreetSplineMath - the shared spline, pure C++ (UE_PLAN.md 2.5.4; SCHEMA.md 3; DESIGN.md 3).
//
// A verbatim port of Tools/blender/streetscape/spline.py, one static per numpy function with the same name, in the
// JSON frame (local metres, X east, Y north, Z up) and in doubles. numpy semantics that matter for bit parity are
// reproduced on purpose: np.interp's slope*(x - xp[j]) + fp[j], np.gradient's central differences, np.linspace's
// start + k*step with the exact end point, np.sum's pairwise summation, np.linalg.norm's sequential sum of squares,
// float32 heightfield tiles. **No USplineComponent curve is ever used for geometry.**

#pragma once

#include "CoreMinimal.h"
#include "StreetTypes.h"
#include "StreetProfiles.h"
#include "StreetTimelines.h"

class IStreetTerrainSource;
class FJsonObject;

/** spline.Frames: stations with position, horizontal tangent, flat normal, banked normal and up vector. */
struct STREETSCAPE_API FStreetFrames
{
	TArray<double> S;
	TArray<FVector3d> P;       // position incl. z_ref
	TArray<FVector3d> Th;      // unit horizontal tangent
	TArray<FVector3d> NFlat;   // Z x t_h
	TArray<FVector3d> N;       // banked left normal
	TArray<FVector3d> B;       // t_h x n

	int32 Num() const { return S.Num(); }
	static FStreetFrames Build(const TArray<double>& InS, const TArray<FVector3d>& InP, const TArray<FVector3d>& InTh, const TArray<double>& BankDeg);
	/** Frames at arbitrary s: p linear, t_h / n interpolated and renormalised, b = t_h x n. */
	FStreetFrames At(TConstArrayView<double> SQuery) const;
	/** Union of the stations with SExtra (duplicates within 1e-9 dropped, existing frames kept exact). */
	FStreetFrames Insert(TConstArrayView<double> SExtra) const;
	FStreetFrames Subset(const TArray<bool>& Mask) const;
};

/** == the numpy Spline object after construction: everything the renderers read. */
struct STREETSCAPE_API FStreetSamples
{
	FString Id;
	double LengthM = 0;
	int32 PointsMerged = 0;
	TArray<FStreetPoint> Points;          // after the duplicate merge
	TArray<double> SDense;
	TArray<FVector2d> XYDense;
	TArray<double> SKnots;
	FStreetSamplingResolved Sampling;
	bool bHasKind = false;
	EStreetRoadKind Kind = EStreetRoadKind::Road;
	const FRoadProfileData* RoadProfile = nullptr;
	FStreetRoadTimeline Road;
	FStreetSideTimeline Sides[2];         // left, right
	TArray<double> MandatorySet;
	TArray<double> S;
	TArray<bool> Mandatory;
	TArray<FVector2d> XY;
	TArray<double> Kappa;
	TArray<FVector2d> ThXY;
	TArray<double> Width;
	TArray<double> Extra[2];
	TArray<double> RollPl, RollMask;
	TArray<const FRoadProfileData*> ProfileAt;
	TArray<EStreetCamberKind> CamberKind;
	TArray<double> CrossfallPct, CamberM; // CamberM NaN = unset
	TArray<FName> SurfaceMaterial;
	TArray<double> OverlapM, SkirtDropM;
	double LateralStationSpacingM = 1.0;
	TArray<double> ZRaw, ZFill, ZRef;
	int32 ZRawNanCount = 0;
	TArray<TPair<double, double>> Pins;
	TArray<double> BankRaw, BankTerrain, BankUnlimited, BankDeg;
	FStreetFrames Frames;
	FStreetSideSpec SideSpec[2];
	TArray<FString> Warnings;

	/**
	 * The junction trim (SCHEMA.md 4.18; spline.Spline.__init__'s trim argument), resolved once per document by
	 * FStreetJunctionPlan and handed to Build, so Renderer A and Renderer B read ONE trimmed extent and cannot drift.
	 *
	 * It is a MASK on s, never a re-basing: LengthM stays the document's arc length, S still spans [0, L], every
	 * Segment.S0M / marking interval / drop kerb / barrier run keeps its meaning, and the two trim stations are added
	 * to MandatorySet so they exist EXACTLY in every renderer's station list (S[first active] == STrim[0]).
	 */
	double TrimM[2] = { 0.0, 0.0 };    // metres cut off the start / the end
	double STrim[2] = { 0.0, 0.0 };    // the two trim stations: (TrimM[0], L - TrimM[1])
	bool bTrimmed = false;
	TArray<bool> Active;               // (N) stations inside [STrim[0], STrim[1]]; all true when untrimmed

	int32 Num() const { return S.Num(); }
	/** Index in S of the trim station of that end: the first / last active station (spline.arm_station_index). */
	int32 ArmStationIndex(EStreetSplineEnd End) const;
	const TArray<double>& ExtraOf(EStreetSide Side) const { return Extra[StreetSideIndex(Side)]; }
	/** THE edge contract: outward distance of the kerb line from the centreline on that side: w/2 + extra(side). */
	TArray<double> EdgeOffset(EStreetSide Side) const;
	/** Road-surface height at the kerb line relative to z_ref (<= 0): surface_h(sigma * edge_offset). */
	TArray<double> EdgeHeight(EStreetSide Side) const;
	/** Camber height at signed lateral d per station (D.Num() == N). */
	TArray<double> SurfaceH(TConstArrayView<double> D) const;
	double SurfaceHAt(int32 Station, double D) const;
	/** stats.json keys (DESIGN.md 14): length_m, n_samples, points_merged, step_min/max/mean, z_raw_nan_count, bank_min/max, w_max, kind, warnings. */
	TSharedRef<FJsonObject> StatsJson() const;
};

struct STREETSCAPE_API FStreetSplineMath
{
	// -- numpy-compatible primitives --------------------------------------------------------------------------
	static double Hypot(double X, double Y);
	/** np.add.reduce on a contiguous float64 array: pairwise summation with 8-way unrolled blocks of 128. */
	static double NumpySum(TConstArrayView<double> A);
	/** np.interp (linear, clamped at the ends, slope*(x - xp[j]) + fp[j]). */
	static double Interp(double X, TConstArrayView<double> XP, TConstArrayView<double> FP);
	static FVector3d Unit3(const FVector3d& V);
	static FVector2d Unit2(const FVector2d& V);
	/** np.gradient of a 1-D array (unit spacing). */
	static TArray<double> Gradient(TConstArrayView<double> F);
	/** np.searchsorted(a, v, side='right') */
	static int32 SearchSortedRight(TConstArrayView<double> A, double V);
	static int32 SearchSortedLeft(TConstArrayView<double> A, double V);

	// -- spline.py ----------------------------------------------------------------------------------------------
	/** Merge consecutive points closer than Tol (later point's z/roll/width win, tags unioned). Returns the count merged. */
	static int32 MergePoints(const TArray<FStreetPoint>& In, TArray<FStreetPoint>& Out, double Tol = 1e-6);
	/** Centripetal Catmull-Rom through P (K >= 2). False when K < 2. */
	static bool CatmullRomDense(const TArray<FVector2d>& P, TArray<double>& OutSD, TArray<FVector2d>& OutXYD, TArray<double>& OutSKnots, double Alpha = 0.5, double MaxChordM = 0.1);
	static TArray<FVector2d> DenseTangents(const TArray<FVector2d>& XY);
	static void DenseCurvature(const TArray<double>& SD, const TArray<FVector2d>& XYD, TArray<double>& OutKappaAbs, TArray<double>& OutKappaSigned);
	static double StepFor(double Kappa, const FStreetSamplingResolved& Sampling);
	static TArray<double> AdaptiveStations(const TArray<double>& SD, const TArray<double>& KappaD, const FStreetSamplingResolved& Sampling, const TArray<double>& Mandatory);
	static TArray<double> FillNanAlong(const TArray<double>& Z, bool& bOutAllNan);
	static TArray<double> MovingAverageArcLength(const TArray<double>& S, const TArray<double>& Z, double W, int32 Passes);
	static TArray<double> ApplyPins(const TArray<double>& Z, const TArray<double>& S, const TArray<TPair<double, double>>& Pins, double Blend);
	static TArray<double> RateLimitBank(const TArray<double>& Beta, const TArray<double>& S, double R);

	/**
	 * spline.resolve_widths - the ONE definition of half-width, extracted so FStreetJunctionPlan can ask for it at a
	 * candidate trim station without building the whole FStreetSamples (which needs terrain).
	 * Points are the MERGED points; OutW / OutExtra[2] come back with one entry per query station.
	 */
	static void ResolveWidths(const TArray<FStreetPoint>& Points, const TArray<double>& SKnots, const FRoadProfileData* RoadProf,
		const FStreetRoadTimeline& RoadTl, TConstArrayView<double> S, TArray<double>& OutW, TArray<double> OutExtra[2]);

	/** The whole build (spline.Spline.__init__). Terrain may be null (heights 0 + warning). False on a structural error.
	    Trim, when given, is {t_start, t_end} in metres from FStreetJunctionPlan::TrimFor. */
	static bool Build(const FStreetSplineDef& Def, const FStreetSiteProfiles& Profiles, const IStreetTerrainSource* Terrain, FStreetSamples& Out, FString* Error,
		const double* Trim = nullptr);
};
