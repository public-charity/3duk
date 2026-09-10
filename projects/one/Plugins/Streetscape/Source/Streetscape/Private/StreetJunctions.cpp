#include "StreetJunctions.h"

#include "StreetscapeModule.h"
#include <cmath>

namespace
{
constexpr double kPiJ = 3.14159265358979323846;

double WrapTwoPi(double A)
{
	// numpy's a % (2 pi): the result carries the sign of the divisor, so it is always in [0, 2 pi)
	const double T = 2.0 * kPiJ;
	double R = std::fmod(A, T);
	if (R < 0.0) R += T;
	return R;
}
double WrapPi(double A) { return WrapTwoPi(A + kPiJ) - kPiJ; }

/** np.linspace(0, 1, Num)[K]: start + k*step with the exact end point (numpy sets y[-1] = stop). */
double LinspaceUnit(int32 K, int32 Num)
{
	if (Num <= 1) return 0.0;
	if (K == Num - 1) return 1.0;
	return (double)K * (1.0 / (double)(Num - 1));
}

FVector2d Unit2Safe(const FVector2d& V)
{
	const double N = std::hypot(V.X, V.Y);
	return N > 0.0 ? FVector2d(V.X / N, V.Y / N) : FVector2d(1.0, 0.0);
}

/** spline._first_crossing: arc length where the dense centreline first reaches plan distance D from (Cx, Cy),
    scanning inward from End. False when the whole curve stays inside the disc. */
bool FirstCrossing(const TArray<double>& SD, const TArray<FVector2d>& XYD, EStreetSplineEnd End, double Cx, double Cy, double D, double& Out)
{
	const int32 M = XYD.Num();
	int32 First = -1, Last = -1;
	for (int32 I = 0; I < M; ++I)
	{
		if (std::hypot(XYD[I].X - Cx, XYD[I].Y - Cy) >= D)
		{
			if (First < 0) First = I;
			Last = I;
		}
	}
	if (First < 0) return false;
	auto R = [&](int32 I) { return std::hypot(XYD[I].X - Cx, XYD[I].Y - Cy); };
	if (End == EStreetSplineEnd::Start)
	{
		const int32 K = First;
		if (K == 0) { Out = 0.0; return true; }
		const double R0 = R(K - 1), R1 = R(K);
		const double T = (R1 == R0) ? 0.0 : (D - R0) / (R1 - R0);
		Out = SD[K - 1] + T * (SD[K] - SD[K - 1]);
		return true;
	}
	const int32 K = Last;
	if (K == M - 1) { Out = SD.Last(); return true; }
	const double R0 = R(K), R1 = R(K + 1);
	const double T = (R1 == R0) ? 0.0 : (R0 - D) / (R0 - R1);
	Out = SD[K] + T * (SD[K + 1] - SD[K]);
	return true;
}
}   // namespace

// ---------------------------------------------------------------------------------------------------------------
// FStreetJunctionPlan
// ---------------------------------------------------------------------------------------------------------------

const FStreetJunctionPlan::FCurve* FStreetJunctionPlan::Curve(const FString& SplineId) const
{
	if (const FCurve* Found = Curves.Find(SplineId)) return Found;
	if (!Doc) return nullptr;
	const FStreetSplineDef* Def = Doc->FindSpline(SplineId);
	if (!Def) return nullptr;
	FCurve C;
	FStreetSplineMath::MergePoints(Def->Points, C.Points);
	TArray<FVector2d> P;
	for (const FStreetPoint& Pt : C.Points) P.Add(FVector2d(Pt.X, Pt.Y));
	if (!FStreetSplineMath::CatmullRomDense(P, C.SD, C.XYD, C.SKnots)) return nullptr;
	C.L = C.SD.Last();
	C.RoadProf = Def->ProfileIds.Road.IsEmpty() ? nullptr : Doc->Profiles.Road.Find(Def->ProfileIds.Road);
	const FStreetSamplingResolved Sampling = FStreetSamplingResolved::Resolve(
		C.RoadProf ? C.RoadProf->Kind : EStreetRoadKind::Road,
		(C.RoadProf && C.RoadProf->bHasSamplingDefaults) ? &C.RoadProf->SamplingDefaults : nullptr,
		Def->bHasSampling ? &Def->Sampling : nullptr);
	C.RoadTl = FStreetRoadTimeline::Resolve(*Def, Doc->Profiles, C.L, Sampling.WidthRampM);
	C.TD = FStreetSplineMath::DenseTangents(C.XYD);
	C.Xd.SetNumUninitialized(C.XYD.Num()); C.Yd.SetNumUninitialized(C.XYD.Num());
	for (int32 I = 0; I < C.XYD.Num(); ++I) { C.Xd[I] = C.XYD[I].X; C.Yd[I] = C.XYD[I].Y; }
	C.Tx.SetNumUninitialized(C.TD.Num()); C.Ty.SetNumUninitialized(C.TD.Num());
	for (int32 I = 0; I < C.TD.Num(); ++I) { C.Tx[I] = C.TD[I].X; C.Ty[I] = C.TD[I].Y; }
	return &Curves.Add(SplineId, MoveTemp(C));
}

bool FStreetJunctionPlan::ArmFromStation(const FString& Jid, const FString& SplineId, EStreetSplineEnd End, double St, double Cx, double Cy, FStreetJunctionArm& Out) const
{
	const FCurve* C = Curve(SplineId);
	if (!C) return false;
	const double L = C->L;
	St = FMath::Clamp(St, 0.0, L);
	const double Px = FStreetSplineMath::Interp(St, C->SD, C->Xd);
	const double Py = FStreetSplineMath::Interp(St, C->SD, C->Yd);
	FVector2d U = Unit2Safe(FVector2d(FStreetSplineMath::Interp(St, C->SD, C->Tx), FStreetSplineMath::Interp(St, C->SD, C->Ty)));
	if (U.X * (Px - Cx) + U.Y * (Py - Cy) < 0.0) U = FVector2d(-U.X, -U.Y);   // orient AWAY from the junction node

	TArray<double> W, Extra[2];
	const TArray<double> Sq = { St };
	FStreetSplineMath::ResolveWidths(C->Points, C->SKnots, C->RoadProf, C->RoadTl, Sq, W, Extra);
	const TArray<const FRoadProfileData*> Pa = C->RoadTl.ProfileAt(Sq);
	const FRoadProfileData* Prof = Pa.Num() ? Pa[0] : nullptr;

	Out = FStreetJunctionArm();
	Out.JunctionId = Jid;
	Out.SplineId = SplineId;
	Out.End = End;
	Out.STrim = St;
	Out.TrimM = (End == EStreetSplineEnd::Start) ? St : (L - St);
	Out.U = U;
	Out.P = FVector2d(Px, Py);
	Out.ELeft = W[0] / 2.0 + Extra[0][0];
	Out.ERight = W[0] / 2.0 + Extra[1][0];
	Out.OverlapM = Prof ? Prof->OverlapM : 0.04;
	// The angular order key is the bearing of the TRIM POINT about the node, not of the tangent (see the class doc).
	Out.Phi = std::atan2(Py - Cy, Px - Cx);
	const FVector2d NPlan(-U.Y, U.X);      // left of travel-outward
	const double E = Out.HalfExtentM();
	double Half = 0.0;
	for (int32 K = 0; K < 2; ++K)
	{
		const double Sg = K == 0 ? 1.0 : -1.0;
		const double Qx = Px + Sg * E * NPlan.X, Qy = Py + Sg * E * NPlan.Y;
		Half = FMath::Max(Half, FMath::Abs(WrapPi(std::atan2(Qy - Cy, Qx - Cx) - Out.Phi)));
	}
	Out.HalfAng = Half;
	return true;
}

bool FStreetJunctionPlan::ArmAt(const FString& Jid, const FString& SplineId, EStreetSplineEnd End, double Cx, double Cy, double D, FStreetJunctionArm& Out) const
{
	const FCurve* C = Curve(SplineId);
	if (!C) return false;
	double St = 0.0;
	if (!FirstCrossing(C->SD, C->XYD, End, Cx, Cy, D, St))
	{
		St = (End == EStreetSplineEnd::Start) ? C->L : 0.0;   // the whole spline is inside the disc
	}
	return ArmFromStation(Jid, SplineId, End, St, Cx, Cy, Out);
}

void FStreetJunctionPlan::SolveRadii(const TArray<FStreetJunctionArm>& InArms, double RFloor, TArray<double>& OutD, TArray<bool>& OutUnsep) const
{
	const double Eps = Config.ClearanceDeg * (kPiJ / 180.0);
	const double Cap = Config.MaxTrimRadiusM;
	const int32 N = InArms.Num();
	TArray<int32> Order;
	for (int32 I = 0; I < N; ++I) Order.Add(I);
	// python's sorted() is stable: ties keep the arms' own order
	Order.StableSort([&InArms](int32 A, int32 B) { return WrapTwoPi(InArms[A].Phi) < WrapTwoPi(InArms[B].Phi); });
	TArray<double> GapNext;
	GapNext.Init(0.0, N);
	for (int32 K = 0; K < N; ++K)
	{
		const int32 I = Order[K], J = Order[(K + 1) % N];
		GapNext[I] = (N > 1) ? WrapTwoPi(InArms[J].Phi - InArms[I].Phi) : 2.0 * kPiJ;
	}
	TArray<double> Req;
	Req.Init(0.0, N);
	OutUnsep.Init(false, N);
	for (int32 K = 0; K < N; ++K)
	{
		const int32 I = Order[K], Pv = Order[(K - 1 + N) % N];
		const double Delta = (N > 1) ? FMath::Min(GapNext[I], GapNext[Pv]) : 2.0 * kPiJ;
		const double Target = 0.5 * (Delta - Eps);
		double Q;
		if (Target >= 0.5 * kPiJ - 1e-9 || (Target > 1e-9 && InArms[I].HalfAng <= Target))
		{
			Q = InArms[I].RadiusM;                 // already inside its share of both gaps
		}
		else if (Target <= 1e-9)
		{
			Q = TNumericLimits<double>::Max();
		}
		else
		{
			Q = InArms[I].HalfExtentM() / std::tan(Target);
		}
		Req[I] = Q;
		OutUnsep[I] = Q > Cap;
	}
	double Common = RFloor;
	for (int32 I = 0; I < N; ++I) { if (!OutUnsep[I]) Common = FMath::Max(Common, Req[I]); }
	Common = FMath::Min(Common, Cap);
	const double Frac = Config.MaxTrimFracOfLength;
	OutD.Reset();
	for (int32 I = 0; I < N; ++I)
	{
		// never give up more than MaxTrimFracOfLength of the arm's own spline to one junction
		const FCurve* C = Curve(InArms[I].SplineId);
		const double L = C ? C->L : 0.0;
		OutD.Add(FMath::Min(Common, FMath::Max(RFloor, Frac * L)));
	}
}

void FStreetJunctionPlan::Build(const FStreetSiteDoc& InDoc, const FStreetJunctionDefaults& InCfg)
{
	Doc = &InDoc;
	Config = InCfg;
	Curves.Reset();
	ArmsByJunction.Reset();
	TrimRadiusById.Reset();
	Trims.Reset();
	Notes.Reset();
	Stats.Reset();
	for (const TCHAR* K : { TEXT("junctions"), TEXT("junctions_built"), TEXT("junctions_skipped_kind"), TEXT("junctions_skipped_arms"),
		TEXT("arms"), TEXT("arms_dropped"), TEXT("splines_trimmed"), TEXT("splines_degenerate"), TEXT("splines_untrimmable"),
		TEXT("arms_unseparable") })
	{
		Stats.Add(FString(K), 0);
	}

	TArray<FString> PendingIds;
	TMap<FString, TArray<FStreetJunctionArm>> Pending;
	for (const FStreetJunction& J : InDoc.Junctions)
	{
		Stats[TEXT("junctions")] += 1;
		if (J.Kind != EStreetJunctionKind::Disc)
		{
			Stats[TEXT("junctions_skipped_kind")] += 1;
			continue;
		}
		TArray<TPair<FString, EStreetSplineEnd>> Keys;
		TSet<FString> Seen;
		for (const FStreetJunctionEnd& En : J.Ends)
		{
			const FString Key = En.SplineId + TEXT("|") + FString(FStreetEnums::ToString(En.End));
			if (Seen.Contains(Key)) continue;
			Seen.Add(Key);
			const FStreetSplineDef* Def = InDoc.FindSpline(En.SplineId);
			if (!Def)
			{
				Stats[TEXT("arms_dropped")] += 1;
				Notes.Add(FString::Printf(TEXT("%s: end %s %s is not in this document"), *J.Id, *En.SplineId, FStreetEnums::ToString(En.End)));
				continue;
			}
			const FRoadProfileData* Rp = Def->ProfileIds.Road.IsEmpty() ? nullptr : InDoc.Profiles.Road.Find(Def->ProfileIds.Road);
			if (!Rp || Rp->Kind == EStreetRoadKind::Rail)
			{
				Stats[TEXT("arms_dropped")] += 1;   // a level crossing is not a tarmac junction
				continue;
			}
			Keys.Add(TPair<FString, EStreetSplineEnd>(En.SplineId, En.End));
		}
		if (Keys.Num() < 3)
		{
			Stats[TEXT("junctions_skipped_arms")] += 1;
			continue;
		}
		const double RFloor = J.RadiusM.IsSet() ? J.RadiusM.GetValue() : 0.0;
		TArray<double> D;
		D.Init(FMath::Max(RFloor, 1e-6), Keys.Num());
		TArray<FStreetJunctionArm> LocalArms;
		TArray<bool> Unsep;
		Unsep.Init(false, Keys.Num());
		bool bOk = true;
		for (int32 Pass = 0; Pass < Iters; ++Pass)
		{
			LocalArms.Reset();
			for (int32 Q = 0; Q < Keys.Num(); ++Q)
			{
				FStreetJunctionArm A;
				if (!ArmAt(J.Id, Keys[Q].Key, Keys[Q].Value, J.X, J.Y, D[Q], A)) { bOk = false; break; }
				A.RadiusM = D[Q];
				LocalArms.Add(A);
			}
			if (!bOk) break;
			TArray<double> DNew;
			if (J.TrimRadiusM.IsSet())
			{
				DNew.Init(J.TrimRadiusM.GetValue(), Keys.Num());
				Unsep.Init(false, Keys.Num());
			}
			else
			{
				SolveRadii(LocalArms, RFloor, DNew, Unsep);
			}
			double MaxDelta = 0.0;
			for (int32 Q = 0; Q < Keys.Num(); ++Q) MaxDelta = FMath::Max(MaxDelta, FMath::Abs(DNew[Q] - D[Q]));
			D = DNew;
			if (MaxDelta < 1e-9) break;
		}
		if (!bOk)
		{
			Stats[TEXT("junctions_skipped_arms")] += 1;
			continue;
		}
		LocalArms.Reset();
		for (int32 Q = 0; Q < Keys.Num(); ++Q)
		{
			FStreetJunctionArm A;
			if (!ArmAt(J.Id, Keys[Q].Key, Keys[Q].Value, J.X, J.Y, D[Q], A)) { bOk = false; break; }
			A.RadiusM = D[Q];
			LocalArms.Add(A);
		}
		if (!bOk)
		{
			Stats[TEXT("junctions_skipped_arms")] += 1;
			continue;
		}
		for (bool Un : Unsep) { if (Un) Stats[TEXT("arms_unseparable")] += 1; }
		double MaxD = 0.0;
		for (double X : D) MaxD = FMath::Max(MaxD, X);
		TrimRadiusById.Add(J.Id, MaxD);
		PendingIds.Add(J.Id);
		Pending.Add(J.Id, LocalArms);
		for (const FStreetJunctionArm& A : LocalArms)
		{
			TArray<double>& T = Trims.FindOrAdd(A.SplineId);
			if (T.Num() != 2) { T.Reset(); T.Add(0.0); T.Add(0.0); }
			const int32 Slot = (A.End == EStreetSplineEnd::Start) ? 0 : 1;
			T[Slot] = FMath::Max(T[Slot], A.TrimM);
		}
	}

	// -- degeneracy: one common scale factor per spline, then re-derive the arms ---------------------------------
	const double Keep = Config.MinRemainingM;
	TMap<FString, double> Scale;
	TArray<FString> TrimIds;
	Trims.GetKeys(TrimIds);
	TrimIds.Sort();
	for (const FString& Sid : TrimIds)
	{
		TArray<double>& T = Trims[Sid];
		const FCurve* C = Curve(Sid);
		const double L = C ? C->L : 0.0;
		if (T[0] + T[1] <= L - Keep) continue;
		if (L <= Keep || (T[0] + T[1]) <= 0.0)
		{
			T[0] = 0.0; T[1] = 0.0;
			Scale.Add(Sid, 0.0);
			Stats[TEXT("splines_untrimmable")] += 1;
			Notes.Add(FString::Printf(TEXT("%s: L=%.3f m cannot be trimmed (min_remaining_m %.3f)"), *Sid, L, Keep));
			continue;
		}
		const double K = FMath::Max(0.0, (L - Keep) / (T[0] + T[1]));
		T[0] *= K; T[1] *= K;
		Scale.Add(Sid, K);
		Stats[TEXT("splines_degenerate")] += 1;
		Notes.Add(FString::Printf(TEXT("%s: trims scaled by %.6f to keep %.3f m of L=%.3f m"), *Sid, K, Keep, L));
	}
	for (const FString& Jid : PendingIds)
	{
		const FStreetJunction* J = Junction(Jid);
		TArray<FStreetJunctionArm> Outs;
		for (const FStreetJunctionArm& A0 : Pending[Jid])
		{
			FStreetJunctionArm A = A0;
			if (Scale.Contains(A.SplineId) && J)
			{
				const FCurve* C = Curve(A.SplineId);
				const double L = C ? C->L : 0.0;
				const TArray<double>& T = Trims[A.SplineId];
				const double St = (A.End == EStreetSplineEnd::Start) ? T[0] : (L - T[1]);
				FStreetJunctionArm B;
				if (ArmFromStation(Jid, A.SplineId, A.End, St, J->X, J->Y, B)) A = B;
			}
			Outs.Add(A);
		}
		Outs.Sort([](const FStreetJunctionArm& A, const FStreetJunctionArm& B)
		{
			const double Pa = WrapTwoPi(A.Phi), Pb = WrapTwoPi(B.Phi);
			if (Pa != Pb) return Pa < Pb;
			if (A.SplineId != B.SplineId) return A.SplineId < B.SplineId;
			return (int32)A.End < (int32)B.End;
		});
		Stats[TEXT("arms")] += Outs.Num();
		Stats[TEXT("junctions_built")] += 1;
		ArmsByJunction.Add(Jid, MoveTemp(Outs));
	}
	int32 NTrimmed = 0;
	for (const TPair<FString, TArray<double>>& KV : Trims) { if (KV.Value[0] > 0.0 || KV.Value[1] > 0.0) ++NTrimmed; }
	Stats[TEXT("splines_trimmed")] = NTrimmed;
}

void FStreetJunctionPlan::TrimFor(const FString& SplineId, double OutTrim[2]) const
{
	const TArray<double>* T = Trims.Find(SplineId);
	OutTrim[0] = T ? (*T)[0] : 0.0;
	OutTrim[1] = T ? (*T)[1] : 0.0;
}

bool FStreetJunctionPlan::IsTrimmed(const FString& SplineId) const
{
	const TArray<double>* T = Trims.Find(SplineId);
	return T && ((*T)[0] > 0.0 || (*T)[1] > 0.0);
}

FString FStreetJunctionPlan::Owner(const FString& JunctionId) const
{
	const TArray<FStreetJunctionArm>* A = ArmsByJunction.Find(JunctionId);
	return (A && A->Num()) ? (*A)[0].SplineId : FString();
}

TArray<FString> FStreetJunctionPlan::JunctionsOwnedBy(const FString& SplineId) const
{
	TArray<FString> Out;
	for (const TPair<FString, TArray<FStreetJunctionArm>>& KV : ArmsByJunction)
	{
		if (Owner(KV.Key) == SplineId) Out.Add(KV.Key);
	}
	Out.Sort();
	return Out;
}

TArray<FString> FStreetJunctionPlan::BuiltJunctionIds() const
{
	TArray<FString> Out;
	ArmsByJunction.GetKeys(Out);
	Out.Sort();
	return Out;
}

const FStreetJunction* FStreetJunctionPlan::Junction(const FString& JunctionId) const
{
	if (!Doc) return nullptr;
	for (const FStreetJunction& J : Doc->Junctions) { if (J.Id == JunctionId) return &J; }
	return nullptr;
}

// ---------------------------------------------------------------------------------------------------------------
// FStreetJunctionMath
// ---------------------------------------------------------------------------------------------------------------

FStreetJunctionSpec FStreetJunctionPlan::SpecFor(const FString& JunctionId) const
{
	FStreetJunctionSpec Spec;
	Spec.Cfg = Config;
	if (const FStreetJunction* J = Junction(JunctionId)) Spec.Junction = *J;
	if (const TArray<FStreetJunctionArm>* A = ArmsByJunction.Find(JunctionId)) Spec.Arms = *A;
	Spec.TrimRadiusM = TrimRadius(JunctionId);
	return Spec;
}

bool FStreetJunctionMath::ResolveArmFrames(const FStreetJunctionSpec& Spec, const TMap<FString, const FStreetSamples*>& Splines, TArray<FStreetArmFrame>& Out)
{
	Out.Reset();
	if (Spec.Arms.Num() == 0) return false;
	for (const FStreetJunctionArm& A : Spec.Arms)
	{
		const FStreetSamples* const* Found = Splines.Find(A.SplineId);
		const FStreetSamples* Sp = Found ? *Found : nullptr;
		if (!Sp || !Sp->bHasKind) return false;
		FStreetArmFrame F;
		F.Arm = &A;
		F.Spline = Sp;
		F.I = Sp->ArmStationIndex(A.End);
		const FVector3d Th = Sp->Frames.Th[F.I];
		F.U = (A.End == EStreetSplineEnd::Start) ? Th : FVector3d(-Th.X, -Th.Y, -Th.Z);
		F.SideLo = (A.End == EStreetSplineEnd::Start) ? EStreetSide::Right : EStreetSide::Left;
		F.SideHi = (A.End == EStreetSplineEnd::Start) ? EStreetSide::Left : EStreetSide::Right;
		for (int32 Tag = 0; Tag < 2; ++Tag)
		{
			const EStreetSide Side = Tag == 0 ? F.SideLo : F.SideHi;
			const int32 Sg = StreetSideSigma(Side);
			const double O0 = Sp->EdgeOffset(Side)[F.I];
			const double H0 = Sp->EdgeHeight(Side)[F.I];
			const FVector3d& Pp = Sp->Frames.P[F.I];
			const FVector3d& Nn = Sp->Frames.N[F.I];
			const FVector3d& Bb = Sp->Frames.B[F.I];
			const FVector3d Pt(Pp.X + Sg * O0 * Nn.X + H0 * Bb.X, Pp.Y + Sg * O0 * Nn.Y + H0 * Bb.Y, Pp.Z + Sg * O0 * Nn.Z + H0 * Bb.Z);
			const FVector3d Nin(-Sg * Nn.X, -Sg * Nn.Y, -Sg * Nn.Z);
			if (Tag == 0) { F.PLo = Pt; F.NLo = Nin; F.BLo = Bb; }
			else { F.PHi = Pt; F.NHi = Nin; F.BHi = Bb; }
		}
		Out.Add(F);
	}
	return Out.Num() > 0;
}

void FStreetJunctionMath::CornerCurve(const FVector3d& A, const FVector3d& B, const FVector2d& Dir0, const FVector2d& Dir1,
	const FVector2d& NodeXY, double StepDeg, double HandleFrac, TArray<FVector3d>& OutP, TArray<FVector3d>& OutT)
{
	OutP.Reset();
	OutT.Reset();
	const FVector2d U0 = Unit2Safe(Dir0), U1 = Unit2Safe(Dir1);
	const FVector3d D0(U0.X, U0.Y, 0.0), D1(U1.X, U1.Y, 0.0);
	const double Chord = std::hypot(B.X - A.X, B.Y - A.Y);
	const double Tau = std::atan2(D0.X * D1.Y - D0.Y * D1.X, D0.X * D1.X + D0.Y * D1.Y);
	if (Chord < 1e-9)
	{
		OutP.Add(A); OutP.Add(B);
		OutT.Add(D0); OutT.Add(D1);
		return;
	}
	double Mh = 0.0;
	int32 M = 1;
	if (FMath::Abs(Tau) >= 1e-6)
	{
		const double R = Chord / (2.0 * std::sin(FMath::Abs(Tau) / 2.0));
		Mh = (4.0 / 3.0) * std::tan(FMath::Abs(Tau) / 4.0) * R;
		const double Cap = HandleFrac * FMath::Min(std::hypot(A.X - NodeXY.X, A.Y - NodeXY.Y), std::hypot(B.X - NodeXY.X, B.Y - NodeXY.Y));
		Mh = FMath::Min(Mh, Cap);
		M = FMath::Max(2, (int32)FMath::CeilToDouble(FMath::Abs(Tau) * (180.0 / kPiJ) / StepDeg));
	}
	const FVector3d P0 = A, P3 = B;
	const FVector3d P1(A.X + Mh * D0.X, A.Y + Mh * D0.Y, A.Z + Mh * D0.Z);
	const FVector3d P2(B.X - Mh * D1.X, B.Y - Mh * D1.Y, B.Z - Mh * D1.Z);
	OutP.SetNum(M + 1);
	OutT.SetNum(M + 1);
	for (int32 K = 0; K <= M; ++K)
	{
		const double T = LinspaceUnit(K, M + 1);
		const double Om = 1.0 - T;
		const double C0 = Om * Om * Om, C1 = 3.0 * Om * Om * T, C2 = 3.0 * Om * T * T, C3 = T * T * T;
		OutP[K] = FVector3d(C0 * P0.X + C1 * P1.X + C2 * P2.X + C3 * P3.X,
			C0 * P0.Y + C1 * P1.Y + C2 * P2.Y + C3 * P3.Y,
			C0 * P0.Z + C1 * P1.Z + C2 * P2.Z + C3 * P3.Z);
		const double G0 = 3.0 * Om * Om, G1 = 6.0 * Om * T, G2 = 3.0 * T * T;
		double Dx = G0 * (P1.X - P0.X) + G1 * (P2.X - P1.X) + G2 * (P3.X - P2.X);
		double Dy = G0 * (P1.Y - P0.Y) + G1 * (P2.Y - P1.Y) + G2 * (P3.Y - P2.Y);
		double Nrm = std::hypot(Dx, Dy);
		if (Nrm < 1e-12)
		{
			Dx = B.X - A.X; Dy = B.Y - A.Y;
			Nrm = std::hypot(Dx, Dy);
		}
		OutT[K] = FVector3d(Dx / Nrm, Dy / Nrm, 0.0);
	}
	if (Mh > 0.0)
	{
		OutT[0] = D0;
		OutT[M] = D1;
	}
	OutP[0] = A;
	OutP[M] = B;
}

FStreetFrames FStreetJunctionMath::CornerFrames(const TArray<FVector3d>& P, const TArray<FVector3d>& T, const FVector3d& N0, const FVector3d& N1)
{
	const int32 M = T.Num();
	FStreetFrames F;
	F.P = P;
	F.Th = T;
	F.N.SetNum(M);
	F.NFlat.SetNum(M);
	F.B.SetNum(M);
	F.S.SetNum(M);
	for (int32 K = 0; K < M; ++K)
	{
		const double Tt = LinspaceUnit(K, M);
		FVector3d Nn((1.0 - Tt) * N0.X + Tt * N1.X, (1.0 - Tt) * N0.Y + Tt * N1.Y, (1.0 - Tt) * N0.Z + Tt * N1.Z);
		const double Dp = Nn.X * T[K].X + Nn.Y * T[K].Y + Nn.Z * T[K].Z;
		Nn = FVector3d(Nn.X - Dp * T[K].X, Nn.Y - Dp * T[K].Y, Nn.Z - Dp * T[K].Z);
		F.N[K] = FStreetSplineMath::Unit3(Nn);
	}
	{
		const FVector3d& T0 = T[0];
		const double D0 = N0.X * T0.X + N0.Y * T0.Y + N0.Z * T0.Z;
		F.N[0] = FStreetSplineMath::Unit3(FVector3d(N0.X - D0 * T0.X, N0.Y - D0 * T0.Y, N0.Z - D0 * T0.Z));
		const FVector3d& Tl = T[M - 1];
		const double Dl = N1.X * Tl.X + N1.Y * Tl.Y + N1.Z * Tl.Z;
		F.N[M - 1] = FStreetSplineMath::Unit3(FVector3d(N1.X - Dl * Tl.X, N1.Y - Dl * Tl.Y, N1.Z - Dl * Tl.Z));
	}
	for (int32 K = 0; K < M; ++K)
	{
		F.B[K] = FVector3d(T[K].Y * F.N[K].Z - T[K].Z * F.N[K].Y,
			T[K].Z * F.N[K].X - T[K].X * F.N[K].Z,
			T[K].X * F.N[K].Y - T[K].Y * F.N[K].X);
		const FVector3d Zc(0.0 * T[K].Z - 1.0 * T[K].Y, 1.0 * T[K].X - 0.0 * T[K].Z, 0.0);
		F.NFlat[K] = FStreetSplineMath::Unit3(Zc);
	}
	F.S[0] = 0.0;
	for (int32 K = 1; K < M; ++K) F.S[K] = F.S[K - 1] + std::hypot(P[K].X - P[K - 1].X, P[K].Y - P[K - 1].Y);
	return F;
}
