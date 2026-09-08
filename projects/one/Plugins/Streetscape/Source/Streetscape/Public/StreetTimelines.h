// StreetTimelines - profiles + segments -> per-side timelines (UE_PLAN.md 2.5.6; SCHEMA.md 5). A function-for-function
// mirror of Tools/blender/streetscape/schema.py: resolve_road / resolve_side / paint_intervals / apply_ramped_override /
// drop_factor / SideTimeline.evaluate. Computed BEFORE sampling (they contribute mandatory stations); the same
// FStreetSideSpec evaluated on the stations is handed to Renderer B AND Renderer C.
//
// Pure C++ (no UObjects), JSON frame, doubles. Timelines keep pointers into the FStreetSiteProfiles they were
// resolved from, which must outlive them (the site document / site actor does).

#pragma once

#include "CoreMinimal.h"
#include "StreetTypes.h"
#include "StreetProfiles.h"

struct STREETSCAPE_API FStreetScalarOverride
{
	double S0 = 0, S1 = 0, Ramp = 0, Value = 0;
};

/** One painted interval [A, B] with an optional value; Identity mirrors python object identity for merging. */
template <typename T>
struct TStreetInterval
{
	double A = 0, B = 0;
	bool bHas = false;
	T Value{};
	int64 Identity = 0;   // 0 = None
};

template <typename T>
struct TStreetLayer
{
	double S0 = 0;
	TOptional<double> S1;   // unset = L
	bool bHas = false;
	T Value{};
	int64 Identity = 0;
};

struct STREETSCAPE_API FStreetHedgeSpec
{
	const FHedgeProfileData* Profile = nullptr;
	double OffsetM = 0.1, HeightM = 1.5, WidthM = 0.8;
};

struct STREETSCAPE_API FStreetTimelineMath
{
	/** [s0-ramp, s0]: lerp base -> value; [s0, s1]: value; [s1, s1+ramp]: lerp value -> base (schema.apply_ramped_override). */
	static void ApplyRampedOverride(TConstArrayView<double> S, TArray<double>& InOutBase, double S0, double S1, double Ramp, double Value);
	static TArray<double> Ramped(TConstArrayView<double> S, double BaseValue, const TArray<FStreetScalarOverride>& Overrides);
	/** f_k(s) of SCHEMA.md 4.9: smoothstep down-ramp, 1 on the flat run, smoothstep up-ramp (schema.drop_factor). */
	static double DropFactor(double S, double SD, double Length, double Ramp);
	static double Smoothstep(double T);
	/** schema.paint_intervals: breakpoints {0, L} + every s0/s1; the value in force is the last layer covering the piece;
	    adjacent pieces merge when they carry the same identity (both None, or the same object). */
	template <typename T>
	static TArray<TStreetInterval<T>> PaintIntervals(double L, const TArray<TStreetLayer<T>>& Layers)
	{
		const double Eps = 1e-9;
		struct FNorm { double A, B; bool bHas; const T* Value; int64 Identity; };
		TArray<FNorm> Norm;
		for (const TStreetLayer<T>& Lay : Layers)
		{
			const double A = FMath::Max(0.0, Lay.S0);
			const double B = Lay.S1.IsSet() ? FMath::Min(L, Lay.S1.GetValue()) : L;
			if (B <= A + Eps) continue;
			Norm.Add({ A, B, Lay.bHas, &Lay.Value, Lay.bHas ? Lay.Identity : 0 });
		}
		TArray<double> Bps = { 0.0, L };
		for (const FNorm& N : Norm) { Bps.Add(N.A); Bps.Add(N.B); }
		Bps.Sort();
		// python set semantics: exact duplicates removed
		TArray<double> U;
		for (double X : Bps) { if (U.Num() == 0 || U.Last() != X) U.Add(X); }
		TArray<TStreetInterval<T>> Out;
		for (int32 I = 0; I + 1 < U.Num(); ++I)
		{
			const double A = U[I], B = U[I + 1];
			if (B - A <= Eps) continue;
			const FNorm* Val = nullptr;
			for (const FNorm& N : Norm)
			{
				if (N.A <= A + Eps && B <= N.B + Eps) Val = &N;
			}
			const int64 Id = Val ? Val->Identity : 0;
			const bool bHas = Val ? Val->bHas : false;
			if (Out.Num() > 0 && Out.Last().Identity == Id && Out.Last().bHas == bHas && FMath::Abs(Out.Last().B - A) <= Eps)
			{
				Out.Last().B = B;
			}
			else
			{
				TStreetInterval<T>& Iv = Out.AddDefaulted_GetRef();
				Iv.A = A; Iv.B = B; Iv.bHas = bHas; Iv.Identity = Id;
				if (Val && Val->bHas) Iv.Value = *Val->Value;
			}
		}
		return Out;
	}
	/** schema._values_at: interval index in force at s (searchsorted(starts, s + 1e-9, 'right') - 1); -1 when none. */
	template <typename T>
	static int32 IntervalAt(const TArray<TStreetInterval<T>>& Intervals, double S)
	{
		int32 K = -1;
		for (int32 I = 0; I < Intervals.Num(); ++I)
		{
			if (Intervals[I].A <= S + 1e-9) K = I; else break;
		}
		return K;
	}
	/** Fresh identity for a layer that is a new python object (b.inline(), a segment's own block). */
	static int64 NewIdentity();
	static int64 PointerIdentity(const void* P) { return (int64)(intptr_t)P; }
};

/** schema.RoadTimeline. */
struct STREETSCAPE_API FStreetRoadTimeline
{
	bool bHasKind = false;                        // false = no carriageway (profile_ids.road null)
	EStreetRoadKind Kind = EStreetRoadKind::Road;
	const FRoadProfileData* Base = nullptr;
	double L = 0;
	TArray<TOptional<double>> WidthKnots;         // per (merged) point: width_m or unset -> base width
	TArray<FStreetScalarOverride> WidthOverrides;
	TArray<FStreetScalarOverride> ExtraOverrides[2];   // [0] left, [1] right
	TArray<TStreetInterval<const FRoadProfileData*>> ProfileIntervals;
	TArray<TStreetInterval<TArray<FStreetMarking>>> MarkingIntervals;
	TArray<FStreetScalarOverride> CrossfallOverrides;
	TArray<FStreetScalarOverride> CamberMOverrides;
	TArray<double> Mandatory;

	TArray<double> MandatoryStations() const;
	/** Road profile in force per station (interval [a, b); the last includes L); Base when none. */
	TArray<const FRoadProfileData*> ProfileAt(TConstArrayView<double> S) const;
	TArray<const TArray<FStreetMarking>*> MarkingsAt(TConstArrayView<double> S) const;

	static FStreetRoadTimeline Resolve(const FStreetSplineDef& Spline, const FStreetSiteProfiles& Profiles, double L, double RampDefault);
};

/** schema.SideSpec: per-station arrays over the N stations for one side (read by Renderer B AND Renderer C). */
struct STREETSCAPE_API FStreetSideSpec
{
	EStreetSide Side = EStreetSide::Left;
	TArray<bool> Present;
	TArray<double> KerbWidth, KerbHeight, PavementWidth, Crossfall, MaxCrossfall, LipSize;
	TArray<EStreetLipKind> LipKind;
	int32 ArcPoints = 1;
	TArray<double> TuckDepth, TuckIn, Skirt;
	TArray<FName> MatKerb, MatPavement, MatInner, MatOuter;
	TArray<bool> Split;
	TArray<double> SplitFrac, DropFactor, DropTarget, Hk, LipR, HkBack, BackOffset;
	TArray<TStreetInterval<FStreetBarrier>> BarrierTimeline;
	TArray<TStreetInterval<FStreetEmbankment>> EmbankmentTimeline;
	TArray<TStreetInterval<FStreetHedgeSpec>> HedgeTimeline;
	bool bHasKerbOrPavement = false;

	/** Barrier in force at s (nullptr when none). */
	const FStreetBarrier* BarrierAt(double S) const;
};

/** schema.SideTimeline. */
struct STREETSCAPE_API FStreetSideTimeline
{
	EStreetSide Side = EStreetSide::Left;
	const FEdgeProfileData* Base = nullptr;
	const FHedgeProfileData* HedgeBase = nullptr;
	double L = 0;
	TArray<FStreetScalarOverride> ScalarOverrides[4];   // kerb_width_m, kerb_height_m, pavement_width_m, pavement_crossfall_pct
	TArray<TStreetInterval<const FEdgeProfileData*>> ProfileIntervals;
	TArray<TStreetInterval<FStreetSplitMaterial>> SplitIntervals;
	TArray<TStreetInterval<FStreetBarrier>> BarrierIntervals;
	TArray<TStreetInterval<FStreetEmbankment>> EmbankmentIntervals;
	TArray<TStreetInterval<FStreetHedgeSpec>> HedgeIntervals;
	TArray<FStreetDropKerb> DropKerbs;
	TArray<double> Mandatory;

	TArray<double> MandatoryStations() const;
	FStreetSideSpec Evaluate(TConstArrayView<double> S) const;

	static FStreetSideTimeline Resolve(const FStreetSplineDef& Spline, EStreetSide Side, const FStreetSiteProfiles& Profiles, double L, double RampDefault);
};
