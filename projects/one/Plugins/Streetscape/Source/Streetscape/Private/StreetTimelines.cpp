#include "StreetTimelines.h"

// ---------------------------------------------------------------------------------------------------------------
// FStreetTimelineMath
// ---------------------------------------------------------------------------------------------------------------

void FStreetTimelineMath::ApplyRampedOverride(TConstArrayView<double> S, TArray<double>& Out, double S0, double S1, double Ramp, double Value)
{
	if (S1 < S0) return;
	const TArray<double> Base = Out;   // numpy reads the untouched base for the ramps
	for (int32 I = 0; I < S.Num(); ++I)
	{
		const double X = S[I];
		if (X >= S0 && X <= S1)
		{
			Out[I] = Value;
		}
		else if (Ramp > 0)
		{
			if (X >= S0 - Ramp && X < S0)
			{
				const double T = (X - (S0 - Ramp)) / Ramp;
				Out[I] = Base[I] + (Value - Base[I]) * T;
			}
			else if (X > S1 && X <= S1 + Ramp)
			{
				const double T = (X - S1) / Ramp;
				Out[I] = Value + (Base[I] - Value) * T;
			}
		}
	}
}

TArray<double> FStreetTimelineMath::Ramped(TConstArrayView<double> S, double BaseValue, const TArray<FStreetScalarOverride>& Overrides)
{
	TArray<double> Out;
	Out.Init(BaseValue, S.Num());
	for (const FStreetScalarOverride& O : Overrides)
	{
		ApplyRampedOverride(S, Out, O.S0, O.S1, O.Ramp, O.Value);
	}
	return Out;
}

double FStreetTimelineMath::Smoothstep(double T)
{
	T = FMath::Clamp(T, 0.0, 1.0);
	return T * T * (3.0 - 2.0 * T);
}

double FStreetTimelineMath::DropFactor(double S, double SD, double Length, double Ramp)
{
	if (S >= SD - Ramp && S < SD) return Smoothstep((S - (SD - Ramp)) / Ramp);
	if (S >= SD && S <= SD + Length) return 1.0;
	if (S > SD + Length && S <= SD + Length + Ramp) return 1.0 - Smoothstep((S - (SD + Length)) / Ramp);
	return 0.0;
}

int64 FStreetTimelineMath::NewIdentity()
{
	static int64 Counter = 1;
	return ++Counter;
}

namespace
{
TArray<double> ClampOpen(const TArray<double>& Vals, double L)
{
	TArray<double> Out;
	for (double V : Vals) { if (0.0 < V && V < L) Out.Add(V); }
	return Out;
}

TArray<double> SortedUnique(const TArray<double>& Vals)
{
	TArray<double> S = Vals;
	S.Sort();
	TArray<double> Out;
	for (double V : S) { if (Out.Num() == 0 || Out.Last() != V) Out.Add(V); }
	return Out;
}

double SegEnd(const FStreetSegment& Seg, double L) { return Seg.S1M.IsSet() ? Seg.S1M.GetValue() : L; }
}

// ---------------------------------------------------------------------------------------------------------------
// FStreetRoadTimeline (schema.resolve_road)
// ---------------------------------------------------------------------------------------------------------------

TArray<double> FStreetRoadTimeline::MandatoryStations() const { return SortedUnique(Mandatory); }

TArray<const FRoadProfileData*> FStreetRoadTimeline::ProfileAt(TConstArrayView<double> S) const
{
	TArray<const FRoadProfileData*> Out;
	Out.Init(Base, S.Num());
	if (ProfileIntervals.Num() == 0) return Out;
	for (int32 I = 0; I < S.Num(); ++I)
	{
		const int32 K = FStreetTimelineMath::IntervalAt(ProfileIntervals, S[I]);
		if (K >= 0) Out[I] = ProfileIntervals[K].bHas ? ProfileIntervals[K].Value : Base;
	}
	return Out;
}

TArray<const TArray<FStreetMarking>*> FStreetRoadTimeline::MarkingsAt(TConstArrayView<double> S) const
{
	TArray<const TArray<FStreetMarking>*> Out;
	Out.Init(nullptr, S.Num());
	for (int32 I = 0; I < S.Num(); ++I)
	{
		const int32 K = FStreetTimelineMath::IntervalAt(MarkingIntervals, S[I]);
		if (K >= 0) Out[I] = &MarkingIntervals[K].Value;
	}
	return Out;
}

FStreetRoadTimeline FStreetRoadTimeline::Resolve(const FStreetSplineDef& Spline, const FStreetSiteProfiles& Profiles, double L, double RampDefault)
{
	FStreetRoadTimeline T;
	T.L = L;
	T.Base = Spline.ProfileIds.Road.IsEmpty() ? nullptr : Profiles.Road.Find(Spline.ProfileIds.Road);
	T.bHasKind = T.Base != nullptr;
	if (T.Base) T.Kind = T.Base->Kind;
	const double RampD = RampDefault;
	TArray<double>& Mand = T.Mandatory;

	TArray<TStreetLayer<const FRoadProfileData*>> ProfLayers;
	{
		TStreetLayer<const FRoadProfileData*>& Lay = ProfLayers.AddDefaulted_GetRef();
		Lay.S0 = 0.0; Lay.bHas = T.Base != nullptr; Lay.Value = T.Base; Lay.Identity = FStreetTimelineMath::PointerIdentity(T.Base);
	}
	struct FMarkLayer { double A; TOptional<double> B; TArray<FStreetMarking> List; bool bReplace; };
	TArray<FMarkLayer> MarkLayers;
	{
		FMarkLayer& M = MarkLayers.AddDefaulted_GetRef();
		M.A = 0.0; M.bReplace = true;
		if (T.Base) M.List = T.Base->Markings;
	}
	for (const FStreetSegment& Seg : Spline.Segments)
	{
		if (!Seg.bHasRoad) continue;
		const FStreetSegmentRoad& R = Seg.Road;
		const double S0 = Seg.S0M;
		const double S1 = SegEnd(Seg, L);
		const double Ramp = Seg.RampM.IsSet() ? Seg.RampM.GetValue() : RampD;
		if (R.WidthM.IsSet())
		{
			T.WidthOverrides.Add({ S0, S1, Ramp, R.WidthM.GetValue() });
			Mand.Append({ S0, S1, S0 - Ramp, S1 + Ramp });
		}
		if (R.EdgeExtraLeftM.IsSet())
		{
			T.ExtraOverrides[0].Add({ S0, S1, Ramp, R.EdgeExtraLeftM.GetValue() });
			Mand.Append({ S0, S1, S0 - Ramp, S1 + Ramp });
		}
		if (R.EdgeExtraRightM.IsSet())
		{
			T.ExtraOverrides[1].Add({ S0, S1, Ramp, R.EdgeExtraRightM.GetValue() });
			Mand.Append({ S0, S1, S0 - Ramp, S1 + Ramp });
		}
		if (!R.ProfileId.IsEmpty())
		{
			const FRoadProfileData* P = Profiles.Road.Find(R.ProfileId);
			check(P);
			TStreetLayer<const FRoadProfileData*>& Lay = ProfLayers.AddDefaulted_GetRef();
			Lay.S0 = S0; Lay.S1 = S1; Lay.bHas = true; Lay.Value = P; Lay.Identity = FStreetTimelineMath::PointerIdentity(P);
			FMarkLayer& M = MarkLayers.AddDefaulted_GetRef();
			M.A = S0; M.B = S1; M.List = P->Markings; M.bReplace = true;
			Mand.Append({ S0, S1, S0 - Ramp, S1 + Ramp });
			if (P->Camber.CrossfallPct.IsSet()) T.CrossfallOverrides.Add({ S0, S1, Ramp, P->Camber.CrossfallPct.GetValue() });
			if (P->Camber.CamberM.IsSet()) T.CamberMOverrides.Add({ S0, S1, Ramp, P->Camber.CamberM.GetValue() });
		}
		if (R.bHasMarkings)
		{
			FMarkLayer& M = MarkLayers.AddDefaulted_GetRef();
			M.A = S0; M.B = S1; M.List = R.Markings; M.bReplace = true;
			Mand.Append({ S0, S1 });
		}
		if (R.bHasMarkingsAdd)
		{
			FMarkLayer& M = MarkLayers.AddDefaulted_GetRef();
			M.A = S0; M.B = S1; M.List = R.MarkingsAdd; M.bReplace = false;
			Mand.Append({ S0, S1 });
		}
	}
	T.ProfileIntervals = FStreetTimelineMath::PaintIntervals(L, ProfLayers);
	// markings: painted with replace/add semantics
	TArray<double> Bps = { 0.0, L };
	for (const FMarkLayer& M : MarkLayers)
	{
		Bps.Add(FMath::Max(0.0, M.A));
		Bps.Add(M.B.IsSet() ? FMath::Min(L, M.B.GetValue()) : L);
	}
	for (const FMarkLayer& M : MarkLayers)
	{
		for (const FStreetMarking& Mk : M.List)
		{
			if (Mk.S0M.IsSet()) Mand.Add(Mk.S0M.GetValue());
			if (Mk.S1M.IsSet()) Mand.Add(Mk.S1M.GetValue());
		}
	}
	Bps = SortedUnique(Bps);
	for (int32 I = 0; I + 1 < Bps.Num(); ++I)
	{
		const double A = Bps[I], B = Bps[I + 1];
		if (B - A <= 1e-9) continue;
		TArray<FStreetMarking> Cur;
		for (const FMarkLayer& M : MarkLayers)
		{
			const double B0 = M.B.IsSet() ? M.B.GetValue() : L;
			if (M.A <= A + 1e-9 && B <= B0 + 1e-9)
			{
				if (M.bReplace) Cur = M.List; else Cur.Append(M.List);
			}
		}
		TStreetInterval<TArray<FStreetMarking>>& Iv = T.MarkingIntervals.AddDefaulted_GetRef();
		Iv.A = A; Iv.B = B; Iv.bHas = true; Iv.Value = Cur; Iv.Identity = FStreetTimelineMath::NewIdentity();
	}
	for (const auto& Iv : T.ProfileIntervals) Mand.Append({ Iv.A, Iv.B });
	for (const FStreetPoint& P : Spline.Points) T.WidthKnots.Add(P.WidthM);
	T.Mandatory = ClampOpen(Mand, L);
	return T;
}

// ---------------------------------------------------------------------------------------------------------------
// FStreetSideTimeline (schema.resolve_side / SideTimeline.evaluate)
// ---------------------------------------------------------------------------------------------------------------

TArray<double> FStreetSideTimeline::MandatoryStations() const { return SortedUnique(Mandatory); }

const FStreetBarrier* FStreetSideSpec::BarrierAt(double S) const
{
	const int32 K = FStreetTimelineMath::IntervalAt(BarrierTimeline, S);
	return (K >= 0 && BarrierTimeline[K].bHas) ? &BarrierTimeline[K].Value : nullptr;
}

namespace
{
FStreetBarrier InlineBarrier(const FStreetBarrier& B)
{
	FStreetBarrier Out = B;
	Out.S0M.Reset();
	Out.S1M.Reset();
	Out.NullKeys.Remove(TEXT("s1_m"));
	Out.JsonKeys.Remove(TEXT("s0_m"));
	Out.JsonKeys.Remove(TEXT("s1_m"));
	return Out;
}
FStreetEmbankment InlineEmbankment(const FStreetEmbankment& E)
{
	FStreetEmbankment Out = E;
	Out.S0M.Reset();
	Out.S1M.Reset();
	Out.NullKeys.Remove(TEXT("s1_m"));
	Out.JsonKeys.Remove(TEXT("s0_m"));
	Out.JsonKeys.Remove(TEXT("s1_m"));
	return Out;
}
template <typename T>
void AddLayer(TArray<TStreetLayer<T>>& Layers, double S0, TOptional<double> S1, bool bHas, const T& Value, int64 Identity)
{
	TStreetLayer<T>& Lay = Layers.AddDefaulted_GetRef();
	Lay.S0 = S0; Lay.S1 = S1; Lay.bHas = bHas; if (bHas) Lay.Value = Value; Lay.Identity = bHas ? Identity : 0;
}
}

FStreetSideTimeline FStreetSideTimeline::Resolve(const FStreetSplineDef& Spline, EStreetSide Side, const FStreetSiteProfiles& Profiles, double L, double RampDefault)
{
	FStreetSideTimeline T;
	T.Side = Side;
	T.L = L;
	const FString& Eid = Spline.ProfileIds.Edge(Side);
	T.Base = Eid.IsEmpty() ? nullptr : Profiles.Edge.Find(Eid);
	const FString& Hid = Spline.ProfileIds.Hedge(Side);
	T.HedgeBase = Hid.IsEmpty() ? nullptr : Profiles.Hedge.Find(Hid);
	const double RampD = RampDefault;
	TArray<double>& Mand = T.Mandatory;

	TArray<TStreetLayer<const FEdgeProfileData*>> ProfLayers;
	AddLayer<const FEdgeProfileData*>(ProfLayers, 0.0, TOptional<double>(), T.Base != nullptr, T.Base, FStreetTimelineMath::PointerIdentity(T.Base));
	TArray<TStreetLayer<FStreetSplitMaterial>> SplitLayers;
	AddLayer<FStreetSplitMaterial>(SplitLayers, 0.0, TOptional<double>(), false, FStreetSplitMaterial(), 0);
	TArray<TStreetLayer<FStreetBarrier>> BarLayers;
	TArray<TStreetLayer<FStreetEmbankment>> EmbLayers;
	TArray<TStreetLayer<FStreetHedgeSpec>> HedgeLayers;
	TArray<FStreetDropKerb>& Drops = T.DropKerbs;

	if (T.Base)
	{
		for (const FStreetBarrier& B : T.Base->Barriers)
		{
			const bool bHas = B.Type != EStreetBarrierType::None;
			AddLayer<FStreetBarrier>(BarLayers, B.S0M.Get(0.0), B.S1M, bHas, bHas ? InlineBarrier(B) : FStreetBarrier(), FStreetTimelineMath::NewIdentity());
		}
		for (const FStreetEmbankment& E : T.Base->Embankments)
		{
			AddLayer<FStreetEmbankment>(EmbLayers, E.S0M.Get(0.0), E.S1M, true, InlineEmbankment(E), FStreetTimelineMath::NewIdentity());
		}
		Drops.Append(T.Base->DropKerbs);
	}
	if (T.HedgeBase)
	{
		for (const FStreetHedgeSegment& HS : T.HedgeBase->Segments)
		{
			FStreetHedgeSpec H;
			H.Profile = T.HedgeBase;
			H.OffsetM = HS.OffsetM;
			H.HeightM = HS.HeightOverrideM.IsSet() ? HS.HeightOverrideM.GetValue() : T.HedgeBase->HeightM;
			H.WidthM = HS.WidthOverrideM.IsSet() ? HS.WidthOverrideM.GetValue() : T.HedgeBase->WidthM;
			AddLayer<FStreetHedgeSpec>(HedgeLayers, HS.S0M, HS.S1M, true, H, FStreetTimelineMath::NewIdentity());
		}
	}
	for (const FStreetSegment& Seg : Spline.Segments)
	{
		if (!Seg.AppliesTo(Side)) continue;
		const double S0 = Seg.S0M;
		const double S1 = SegEnd(Seg, L);
		const double Ramp = Seg.RampM.IsSet() ? Seg.RampM.GetValue() : RampD;
		if (Seg.bHasEdge && T.Base)
		{
			const FStreetSegmentEdge& E = Seg.Edge;
			if (!E.ProfileId.IsEmpty())
			{
				const FEdgeProfileData* P = Profiles.Edge.Find(E.ProfileId);
				check(P);
				AddLayer<const FEdgeProfileData*>(ProfLayers, S0, S1, true, P, FStreetTimelineMath::PointerIdentity(P));
				Mand.Append({ S0, S1, S0 - Ramp, S1 + Ramp });
				T.ScalarOverrides[0].Add({ S0, S1, Ramp, P->KerbWidthM });
				T.ScalarOverrides[1].Add({ S0, S1, Ramp, P->KerbHeightM });
				T.ScalarOverrides[2].Add({ S0, S1, Ramp, P->PavementWidthM });
				T.ScalarOverrides[3].Add({ S0, S1, Ramp, P->PavementCrossfallPct });
				// the switched profile's lists replace the baseline lists inside [s0, s1]
				AddLayer<FStreetBarrier>(BarLayers, S0, S1, false, FStreetBarrier(), 0);
				AddLayer<FStreetEmbankment>(EmbLayers, S0, S1, false, FStreetEmbankment(), 0);
				for (const FStreetBarrier& B : P->Barriers)
				{
					const double A0 = FMath::Max(S0, B.S0M.Get(0.0));
					const double B1 = B.S1M.IsSet() ? FMath::Min(S1, B.S1M.GetValue()) : S1;
					const bool bHas = B.Type != EStreetBarrierType::None;
					AddLayer<FStreetBarrier>(BarLayers, A0, B1, bHas, bHas ? InlineBarrier(B) : FStreetBarrier(), FStreetTimelineMath::NewIdentity());
				}
				for (const FStreetEmbankment& Em : P->Embankments)
				{
					const double A0 = FMath::Max(S0, Em.S0M.Get(0.0));
					const double B1 = Em.S1M.IsSet() ? FMath::Min(S1, Em.S1M.GetValue()) : S1;
					AddLayer<FStreetEmbankment>(EmbLayers, A0, B1, true, InlineEmbankment(Em), FStreetTimelineMath::NewIdentity());
				}
				Drops.Append(P->DropKerbs);
			}
			const TOptional<double>* Scalars[4] = { &E.KerbWidthM, &E.KerbHeightM, &E.PavementWidthM, &E.PavementCrossfallPct };
			for (int32 K = 0; K < 4; ++K)
			{
				if (Scalars[K]->IsSet())
				{
					T.ScalarOverrides[K].Add({ S0, S1, Ramp, Scalars[K]->GetValue() });
					Mand.Append({ S0, S1, S0 - Ramp, S1 + Ramp });
				}
			}
			if (E.bHasSplitMaterial)
			{
				AddLayer<FStreetSplitMaterial>(SplitLayers, S0, S1, true, E.SplitMaterial, FStreetTimelineMath::PointerIdentity(&E.SplitMaterial));
				Mand.Append({ S0, S1 });
			}
			if (E.bBarrierSet)
			{
				const bool bHas = E.bHasBarrier && E.Barrier.Type != EStreetBarrierType::None;
				AddLayer<FStreetBarrier>(BarLayers, S0, S1, bHas, bHas ? E.Barrier : FStreetBarrier(), FStreetTimelineMath::PointerIdentity(&E.Barrier));
				Mand.Append({ S0, S1 });
			}
			if (E.bEmbankmentSet)
			{
				AddLayer<FStreetEmbankment>(EmbLayers, S0, S1, E.bHasEmbankment, E.bHasEmbankment ? E.Embankment : FStreetEmbankment(), FStreetTimelineMath::PointerIdentity(&E.Embankment));
				Mand.Append({ S0, S1 });
			}
		}
		if (Seg.bHasHedge)
		{
			const FStreetSegmentHedge& H = Seg.Hedge;
			const FHedgeProfileData* HP = H.ProfileId.IsEmpty() ? T.HedgeBase : Profiles.Hedge.Find(H.ProfileId);
			if (H.bPresent && HP)
			{
				FStreetHedgeSpec Spec;
				Spec.Profile = HP;
				Spec.OffsetM = H.OffsetM.IsSet() ? H.OffsetM.GetValue() : 0.1;
				Spec.HeightM = H.HeightM.IsSet() ? H.HeightM.GetValue() : HP->HeightM;
				Spec.WidthM = H.WidthM.IsSet() ? H.WidthM.GetValue() : HP->WidthM;
				AddLayer<FStreetHedgeSpec>(HedgeLayers, S0, S1, true, Spec, FStreetTimelineMath::NewIdentity());
			}
			else
			{
				AddLayer<FStreetHedgeSpec>(HedgeLayers, S0, S1, false, FStreetHedgeSpec(), 0);
			}
			Mand.Append({ S0, S1 });
		}
	}
	for (const FStreetSplineDropKerb& DK : Spline.DropKerbs)
	{
		if (DK.Side == EStreetSideOrBoth::Both || (DK.Side == EStreetSideOrBoth::Left && Side == EStreetSide::Left) || (DK.Side == EStreetSideOrBoth::Right && Side == EStreetSide::Right))
		{
			Drops.Add(DK.AsDropKerb());
		}
	}
	for (const FStreetDropKerb& DK : Drops)
	{
		Mand.Append({ DK.SM - DK.RampM, DK.SM, DK.SM + DK.LengthM, DK.SM + DK.LengthM + DK.RampM });
	}
	auto AddBounds = [&Mand](auto& Layers)
	{
		for (const auto& Lay : Layers)
		{
			Mand.Add(Lay.S0);
			if (Lay.S1.IsSet()) Mand.Add(Lay.S1.GetValue());
		}
	};
	AddBounds(BarLayers);
	AddBounds(EmbLayers);
	AddBounds(HedgeLayers);
	T.ProfileIntervals = FStreetTimelineMath::PaintIntervals(L, ProfLayers);
	for (const auto& Iv : T.ProfileIntervals) Mand.Append({ Iv.A, Iv.B });
	T.SplitIntervals = FStreetTimelineMath::PaintIntervals(L, SplitLayers);
	T.BarrierIntervals = FStreetTimelineMath::PaintIntervals(L, BarLayers);
	T.EmbankmentIntervals = FStreetTimelineMath::PaintIntervals(L, EmbLayers);
	T.HedgeIntervals = FStreetTimelineMath::PaintIntervals(L, HedgeLayers);
	T.Mandatory = ClampOpen(Mand, L);
	return T;
}

FStreetSideSpec FStreetSideTimeline::Evaluate(TConstArrayView<double> S) const
{
	FStreetSideSpec Spec;
	Spec.Side = Side;
	const int32 N = S.Num();
	Spec.Present.Init(Base != nullptr, N);
	Spec.HedgeTimeline = HedgeIntervals;
	if (!Base)
	{
		TArray<double> Z; Z.Init(0.0, N);
		Spec.KerbWidth = Z; Spec.KerbHeight = Z; Spec.PavementWidth = Z; Spec.Crossfall = Z; Spec.MaxCrossfall = Z; Spec.LipSize = Z;
		Spec.LipKind.Init(EStreetLipKind::None, N);
		Spec.ArcPoints = 1;
		Spec.TuckDepth = Z; Spec.TuckIn = Z; Spec.Skirt = Z;
		Spec.MatKerb.Init(NAME_None, N); Spec.MatPavement.Init(NAME_None, N); Spec.MatInner.Init(NAME_None, N); Spec.MatOuter.Init(NAME_None, N);
		Spec.Split.Init(false, N);
		Spec.SplitFrac = Z; Spec.DropFactor = Z; Spec.DropTarget = Z; Spec.Hk = Z; Spec.LipR = Z; Spec.HkBack = Z; Spec.BackOffset = Z;
		Spec.bHasKerbOrPavement = false;
		return Spec;
	}
	const TArray<double> Kw = FStreetTimelineMath::Ramped(S, Base->KerbWidthM, ScalarOverrides[0]);
	const TArray<double> Kh = FStreetTimelineMath::Ramped(S, Base->KerbHeightM, ScalarOverrides[1]);
	const TArray<double> Pw = FStreetTimelineMath::Ramped(S, Base->PavementWidthM, ScalarOverrides[2]);
	const TArray<double> Cfp = FStreetTimelineMath::Ramped(S, Base->PavementCrossfallPct, ScalarOverrides[3]);
	Spec.KerbWidth = Kw; Spec.KerbHeight = Kh; Spec.PavementWidth = Pw;
	Spec.ArcPoints = Base->Lip.ArcPoints;
	Spec.Crossfall.SetNum(N); Spec.MaxCrossfall.SetNum(N); Spec.LipSize.SetNum(N); Spec.LipKind.SetNum(N);
	Spec.TuckDepth.SetNum(N); Spec.TuckIn.SetNum(N); Spec.Skirt.SetNum(N);
	Spec.MatKerb.SetNum(N); Spec.MatPavement.SetNum(N); Spec.MatInner.SetNum(N); Spec.MatOuter.SetNum(N);
	Spec.Split.SetNum(N); Spec.SplitFrac.SetNum(N); Spec.DropFactor.SetNum(N); Spec.DropTarget.SetNum(N);
	Spec.Hk.SetNum(N); Spec.LipR.SetNum(N); Spec.HkBack.SetNum(N); Spec.BackOffset.SetNum(N);
	bool bHasKp = false;
	for (int32 I = 0; I < N; ++I)
	{
		const int32 PK = FStreetTimelineMath::IntervalAt(ProfileIntervals, S[I]);
		const FEdgeProfileData* P = (PK >= 0 && ProfileIntervals[PK].bHas) ? ProfileIntervals[PK].Value : Base;
		const int32 SK = FStreetTimelineMath::IntervalAt(SplitIntervals, S[I]);
		const FStreetSplitMaterial* SO = (SK >= 0 && SplitIntervals[SK].bHas) ? &SplitIntervals[SK].Value : nullptr;
		Spec.LipSize[I] = P->Lip.Kind != EStreetLipKind::None ? P->Lip.SizeM : 0.0;
		Spec.LipKind[I] = P->Lip.Kind;
		Spec.TuckDepth[I] = P->TuckDepthM;
		Spec.TuckIn[I] = P->TuckInM;
		Spec.Skirt[I] = P->SkirtM;
		Spec.MaxCrossfall[I] = P->PavementMaxCrossfallPct / 100.0;
		Spec.MatKerb[I] = P->Materials.Kerb;
		Spec.MatPavement[I] = P->Materials.Pavement;
		Spec.Split[I] = false;
		Spec.SplitFrac[I] = 0.5;
		Spec.MatInner[I] = P->Materials.Kerb;
		Spec.MatOuter[I] = P->Materials.Pavement;
		const FStreetSplitMaterial* SM = SO ? SO : &P->SplitMaterial;
		if (SM && SM->bEnabled)
		{
			Spec.Split[I] = true;
			Spec.SplitFrac[I] = SM->BoundaryFrac;
			Spec.MatInner[I] = SM->Inner;
			Spec.MatOuter[I] = SM->Outer;
		}
		double F = 0.0, Target = 0.0;
		for (const FStreetDropKerb& DK : DropKerbs)
		{
			const double Fk = FStreetTimelineMath::DropFactor(S[I], DK.SM, DK.LengthM, DK.RampM);
			if (Fk > F) Target = DK.TargetHeightM;
			F = FMath::Max(F, Fk);
		}
		Spec.DropFactor[I] = F;
		Spec.DropTarget[I] = Target;
		const double Hk = Kh[I] * (1.0 - F) + Target * F;
		Spec.Hk[I] = Hk;
		Spec.LipR[I] = Kh[I] > 0 ? Spec.LipSize[I] * Hk / Kh[I] : 0.0;
		const double Cf = Cfp[I] / 100.0;
		Spec.Crossfall[I] = Cf;
		double HkBack = FMath::Min(Kh[I] + Pw[I] * Cf, Hk + Pw[I] * Spec.MaxCrossfall[I]);
		Spec.HkBack[I] = Pw[I] > 0 ? HkBack : Hk;
		Spec.BackOffset[I] = Kw[I] + Pw[I];
		if (Kw[I] > 0 || Pw[I] > 0) bHasKp = true;
	}
	Spec.BarrierTimeline = BarrierIntervals;
	Spec.EmbankmentTimeline = EmbankmentIntervals;
	Spec.bHasKerbOrPavement = bHasKp;
	return Spec;
}
