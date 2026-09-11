#include "StreetRenderers.h"

#include "DynamicMesh/DynamicMesh3.h"
#include "Engine/World.h"
#include "StreetMaterialTable.h"
#include "StreetTerrainSource.h"
#include "StreetscapeActor.h"
#include "StreetscapeModule.h"
#include "Engine/CollisionProfile.h"
#include "UDynamicMesh.h"
#include "UObject/ObjectSaveContext.h"
#include <cmath>

using UE::Geometry::FDynamicMesh3;

namespace
{
constexpr double kPiD = 3.14159265358979323846;

FVector3d Cross3(const FVector3d& A, const FVector3d& B)
{
	return FVector3d(A.Y * B.Z - A.Z * B.Y, A.Z * B.X - A.X * B.Z, A.X * B.Y - A.Y * B.X);
}
double Norm3(const FVector3d& V) { return std::sqrt((V.X * V.X + V.Y * V.Y) + V.Z * V.Z); }
double Dot3(const FVector3d& A, const FVector3d& B) { return (A.X * B.X + A.Y * B.Y) + A.Z * B.Z; }

/** python's "%g" for the group-name suffixes ("barrier:<type>:<s0>", "hedge:<s0>"). */
FString FmtG(double V) { return FString::Printf(TEXT("%g"), V); }

/** np.interp of a per-station array at an arbitrary s. */
double InterpAt(const TArray<double>& S, const TArray<double>& F, double X)
{
	return FStreetSplineMath::Interp(X, S, F);
}

/** (N,) mask of the closed interval [A, B] with the 1e-9 slack the numpy renderers use. */
TArray<bool> RangeMask(const TArray<double>& S, double A, double B)
{
	TArray<bool> M;
	M.SetNum(S.Num());
	for (int32 I = 0; I < S.Num(); ++I) M[I] = (S[I] >= A - 1e-9) && (S[I] <= B + 1e-9);
	return M;
}
bool AnyTrue(const TArray<bool>& M) { for (bool B : M) { if (B) return true; } return false; }
int32 CountTrue(const TArray<bool>& M) { int32 C = 0; for (bool B : M) { if (B) ++C; } return C; }

// support.py: world horizontal-outward run and vertical offset into the banked sweep frame.
FVector2d SupportSection(const FStreetFrames& Frames, int32 I, int32 Side, double Run, double Dz)
{
	const double C = Frames.B[I].Z, S = Frames.N[I].Z;
	return FVector2d(C * Run + Side * S * Dz, -Side * S * Run + C * Dz);
}

bool BatterToe(const IStreetTerrainSource* Terrain, const FVector3d& P, const FVector3d& U,
	double Ratio, double Extra, double& Run, double& Dz)
{
	double Lo = 0.0, Hi = 0.0, Ground = 0.0;
	for (int32 Step = 1; Step <= 256; ++Step)
	{
		const double D = Step * 0.25;
		const FVector3d Q = P + D * U;
		if (!Terrain->SampleHeight(Q.X, Q.Y, Ground) || !std::isfinite(Ground)) return false;
		if (P.Z - D / Ratio <= Ground) { Hi = D; break; }
		Lo = D;
	}
	if (Hi == 0.0) return false;
	for (int32 K = 0; K < 28; ++K)
	{
		const double Mid = (Lo + Hi) * 0.5;
		const FVector3d Q = P + Mid * U;
		if (!Terrain->SampleHeight(Q.X, Q.Y, Ground) || !std::isfinite(Ground)) return false;
		if (P.Z - Mid / Ratio > Ground) Lo = Mid; else Hi = Mid;
	}
	const FVector3d Q = P + Hi * U;
	if (!Terrain->SampleHeight(Q.X, Q.Y, Ground) || !std::isfinite(Ground)) return false;
	Run = Hi;
	Dz = Ground - Extra - P.Z;
	return true;
}

/** edge._wall_section / edge._square_section share this: v = cumulative section length. */
FStreetSection MakeSection(bool bClosed, const TArray<FVector2d>& Pts, const TArray<FName>& Mats, const TArray<bool>& Smooth)
{
	FStreetSection Sec;
	Sec.bClosed = bClosed;
	double V = 0.0;
	for (int32 I = 0; I < Pts.Num(); ++I)
	{
		if (I > 0) V += std::hypot(Pts[I].X - Pts[I - 1].X, Pts[I].Y - Pts[I - 1].Y);
		FStreetSectionPoint P;
		P.O = Pts[I].X; P.H = Pts[I].Y;
		P.Mat = Mats.Num() == Pts.Num() ? Mats[I] : (Mats.Num() ? Mats[0] : NAME_None);
		P.V = V;
		P.bSmooth = Smooth.Num() == Pts.Num() ? Smooth[I] : (Smooth.Num() == 1 ? Smooth[0] : false);
		Sec.Points.Add(P);
	}
	return Sec;
}
}   // namespace

// ---------------------------------------------------------------------------------------------------------------
// FStreetInstance
// ---------------------------------------------------------------------------------------------------------------

FTransform FStreetInstance::ToUETransform() const
{
	// JSON -> UE mirrors Y; the mirrored (t_h, n, b) basis has determinant -1, so the local Y axis is negated to keep
	// a proper rotation. Every instance box/card is symmetric across its local Y, so this is invisible.
	const FVector Xa(Th.X, -Th.Y, Th.Z);
	const FVector Ya(-N.X, N.Y, -N.Z);
	const FVector Za(B.X, -B.Y, B.Z);
	const double Sx = Size.X > 0 ? Size.X : 1.0;
	const double Sy = Size.Y > 0 ? Size.Y : 1.0;
	const double Sz = Size.Z > 0 ? Size.Z : 1.0;
	const FVector3d Origin = FVector3d(P.X + 0.5 * Size.Z * B.X, P.Y + 0.5 * Size.Z * B.Y, P.Z + 0.5 * Size.Z * B.Z);
	FMatrix M = FMatrix::Identity;
	M.SetAxis(0, Xa * Sx);
	M.SetAxis(1, Ya * Sy);
	M.SetAxis(2, Za * Sz);
	M.SetOrigin(FVector(100.0 * Origin.X, -100.0 * Origin.Y, 100.0 * Origin.Z));
	return FTransform(M);
}

// ---------------------------------------------------------------------------------------------------------------
// Renderer A - road.py
// ---------------------------------------------------------------------------------------------------------------

void FStreetRenderBuild::RibbonRows(const FStreetSamples& Sp, TArray<double>& OutD, TArray<double>& OutH, TArray<FName>& OutGroups, int32& OutNInt, int32& OutR)
{
	const int32 N = Sp.Num();
	const TArray<double> EL = Sp.EdgeOffset(EStreetSide::Left);
	const TArray<double> ER = Sp.EdgeOffset(EStreetSide::Right);
	double WMax = 0.0;
	for (int32 I = 0; I < N; ++I) WMax = FMath::Max(WMax, EL[I] + ER[I]);
	const double Lss = Sp.LateralStationSpacingM;
	const int32 NInt = FMath::Max(7, 2 * (int32)FMath::CeilToDouble(WMax / (2.0 * Lss)) + 1);
	const int32 R = NInt + 2;
	OutNInt = NInt;
	OutR = R;
	OutD.SetNumUninitialized(N * R);
	OutH.SetNumUninitialized(N * R);
	for (int32 I = 0; I < N; ++I)
	{
		const double Sd = Sp.SkirtDropM[I];
		const double Ov = Sp.OverlapM[I];
		OutD[I * R + 0] = -(ER[I] + Ov);
		OutH[I * R + 0] = Sp.SurfaceHAt(I, -ER[I]) - Sd;
		for (int32 K = 0; K < NInt; ++K)
		{
			const double Frac = (double)K / (double)(NInt - 1);
			const double D = -ER[I] + (EL[I] + ER[I]) * Frac;
			OutD[I * R + 1 + K] = D;
			OutH[I * R + 1 + K] = Sp.SurfaceHAt(I, D);
		}
		OutD[I * R + R - 1] = EL[I] + Ov;
		OutH[I * R + R - 1] = Sp.SurfaceHAt(I, EL[I]) - Sd;
	}
	OutGroups.Reset();
	OutGroups.Add(TEXT("skirt_right"));
	for (int32 K = 0; K < NInt - 1; ++K) OutGroups.Add(TEXT("road"));
	OutGroups.Add(TEXT("skirt_left"));
}

double FStreetRenderBuild::MeshSurfaceH(const FStreetSamples& Sp, const TArray<double>& D, const TArray<double>& H, int32 R, double SQ, double DQ)
{
	const TArray<double>& S = Sp.S;
	const int32 N = S.Num();
	if (N < 2) return NAN;
	int32 I = FMath::Clamp(FStreetSplineMath::SearchSortedRight(S, SQ) - 1, 0, N - 2);
	double T = (SQ - S[I]) / (S[I + 1] - S[I]);
	T = FMath::Clamp(T, 0.0, 1.0);
	// row d at the query station (linear between the two station rows)
	TArray<double> D0;
	D0.SetNumUninitialized(R);
	for (int32 K = 0; K < R; ++K) D0[K] = (1.0 - T) * D[I * R + K] + T * D[(I + 1) * R + K];
	const int32 K = FMath::Clamp(FStreetSplineMath::SearchSortedRight(D0, DQ) - 1, 0, R - 2);
	const double Cx[4] = { 0.0, 1.0, 1.0, 0.0 };
	const double Cy[4] = { D[I * R + K], D[(I + 1) * R + K], D[(I + 1) * R + K + 1], D[I * R + K + 1] };
	const double Ch[4] = { H[I * R + K], H[(I + 1) * R + K], H[(I + 1) * R + K + 1], H[I * R + K + 1] };
	const int32 Tris[2][3] = { { 0, 1, 2 }, { 0, 2, 3 } };
	bool bHave = false;
	double BestM = 0.0, BestH = NAN;
	for (int32 Q = 0; Q < 2; ++Q)
	{
		const int32 A = Tris[Q][0], B = Tris[Q][1], C = Tris[Q][2];
		const double X1 = Cx[A], Y1 = Cy[A], H1 = Ch[A];
		const double X2 = Cx[B], Y2 = Cy[B], H2 = Ch[B];
		const double X3 = Cx[C], Y3 = Cy[C], H3 = Ch[C];
		const double Det = (Y2 - Y3) * (X1 - X3) + (X3 - X2) * (Y1 - Y3);
		if (FMath::Abs(Det) < 1e-18) continue;
		const double L1 = ((Y2 - Y3) * (T - X3) + (X3 - X2) * (DQ - Y3)) / Det;
		const double L2 = ((Y3 - Y1) * (T - X3) + (X1 - X3) * (DQ - Y3)) / Det;
		const double L3 = 1.0 - L1 - L2;
		const double Mn = FMath::Min3(L1, L2, L3);
		if (!bHave || Mn > BestM)
		{
			bHave = true;
			BestM = Mn;
			BestH = L1 * H1 + L2 * H2 + L3 * H3;
		}
	}
	return bHave ? BestH : NAN;
}

TArray<TPair<double, double>> FStreetRenderBuild::MarkingIntervals(const FStreetMarking& M, double A, double B, double L)
{
	TArray<TPair<double, double>> Out;
	const double Lo = FMath::Max(A, M.S0M.IsSet() ? M.S0M.GetValue() : 0.0);
	const double Hi = FMath::Min(B, M.S1M.IsSet() ? M.S1M.GetValue() : L);
	if (Hi - Lo <= 1e-9) return Out;
	if (M.Pattern == EStreetMarkingPattern::Solid || M.Pattern == EStreetMarkingPattern::Double)
	{
		Out.Add(TPair<double, double>(Lo, Hi));
		return Out;
	}
	if (M.Pattern == EStreetMarkingPattern::Dashed)
	{
		const double Dash = M.DashM.IsSet() ? M.DashM.GetValue() : 0.0;
		const double Gap = M.GapM.IsSet() ? M.GapM.GetValue() : 0.0;
		const double Period = Dash + Gap;
		if (Period <= 0) return Out;
		const double Phase = M.PhaseM;
		int32 K = (int32)FMath::FloorToDouble((Lo - Phase) / Period);
		while (Phase + K * Period < Hi - 1e-9)
		{
			const double A0 = Phase + K * Period;
			const double B0 = A0 + Dash;
			const double X0 = FMath::Max(Lo, A0), X1 = FMath::Min(Hi, B0);
			if (X1 - X0 > 1e-9) Out.Add(TPair<double, double>(X0, X1));
			++K;
		}
	}
	return Out;
}

void FStreetRenderBuild::BuildRoad(const FStreetSamples& Sp, FStreetRenderResult& Out)
{
	if (Sp.bHasKind && Sp.Kind == EStreetRoadKind::Rail)
	{
		BuildRail(Sp, Out);
		return;
	}
	if (!Sp.bHasKind) return;   // profile_ids.road null -> no carriageway (SCHEMA.md 4.13)

	FStreetMeshBuilder& Buf = Out.Buffer;
	const int32 N = Sp.Num();
	TArray<double> D, H;
	TArray<FName> Groups;
	int32 NInt = 0, R = 0;
	RibbonRows(Sp, D, H, Groups, NInt, R);

	// UV v of a ribbon row = its lateral offset at station 0 (road.py builds the section from row 0).
	{
		FStreetSection Section;
		Section.bClosed = false;
		for (int32 Rw = 0; Rw < R; ++Rw)
		{
			FStreetSectionPoint P;
			P.O = D[Rw]; P.H = H[Rw]; P.Mat = TEXT("tarmac"); P.V = D[Rw]; P.bSmooth = true;
			Section.Points.Add(P);
		}
		FStreetSweepParams Pr;
		Pr.Side = +1;
		Pr.LateralScalar = 0.0;
		Pr.HeightScalar = 0.0;
		Pr.PointO = D;
		Pr.PointH = H;
		// the junction trim is a mask on the SHARED spline: the carriageway stops at the junction boundary and never
		// crosses it; the hole it leaves is filled by BuildJunctionPatch, in THIS buffer, with THIS material.
		Pr.Mask = Sp.Active;
		Pr.bCapStart = false;
		Pr.bCapEnd = false;
		Pr.Groups = Groups;
		Pr.EdgeMatStation.SetNumUninitialized(N * (R - 1));
		for (int32 I = 0; I < N; ++I)
		{
			for (int32 K = 0; K < R - 1; ++K) Pr.EdgeMatStation[I * (R - 1) + K] = Sp.SurfaceMaterial[I];
		}
		FStreetSweep::Sweep(Buf, Section, Sp.Frames, Pr);
	}

	// -- markings: strips on interpolated frames, heights on the actual road mesh + lift --------------------------
	const double L = Sp.LengthM;
	struct FPlan { const FStreetMarking* M; TArray<TPair<double, double>> Ivs; };
	TArray<FPlan> Plan;
	TArray<double> Ends;
	const double ALo = Sp.STrim[0], AHi = Sp.STrim[1];
	for (const TStreetInterval<TArray<FStreetMarking>>& Iv : Sp.Road.MarkingIntervals)
	{
		if (!Iv.bHas) continue;
		const double IvA = FMath::Max(Iv.A, ALo);
		const double IvB = FMath::Min(Iv.B, AHi);
		if (IvB - IvA <= 1e-9) continue;    // the whole interval is inside a junction
		for (const FStreetMarking& M : Iv.Value)
		{
			if (M.Pattern == EStreetMarkingPattern::None) continue;
			TArray<TPair<double, double>> Ivs = FStreetRenderBuild::MarkingIntervals(M, IvA, IvB, L);
			if (Ivs.Num() == 0) continue;
			for (const TPair<double, double>& X : Ivs) { Ends.Add(X.Key); Ends.Add(X.Value); }
			Plan.Add({ &M, MoveTemp(Ivs) });
		}
	}
	int32 NStrips = 0;
	if (Plan.Num())
	{
		const FStreetFrames Fr = Sp.Frames.Insert(Ends);
		const TArray<double>& SM = Fr.S;
		const int32 M = SM.Num();
		const TArray<double> EoL = Sp.EdgeOffset(EStreetSide::Left);
		const TArray<double> EoR = Sp.EdgeOffset(EStreetSide::Right);
		TArray<double> EL, ER;
		EL.SetNumUninitialized(M); ER.SetNumUninitialized(M);
		for (int32 Q = 0; Q < M; ++Q)
		{
			EL[Q] = InterpAt(Sp.S, EoL, SM[Q]);
			ER[Q] = InterpAt(Sp.S, EoR, SM[Q]);
		}
		for (const FPlan& Pl : Plan)
		{
			const FStreetMarking& Mk = *Pl.M;
			TArray<double> C;
			C.SetNumUninitialized(M);
			for (int32 Q = 0; Q < M; ++Q)
			{
				switch (Mk.Anchor)
				{
				case EStreetMarkingAnchor::Centre: C[Q] = Mk.OffsetM; break;
				case EStreetMarkingAnchor::EdgeLeft: C[Q] = EL[Q] - Mk.OffsetM; break;
				default: C[Q] = -ER[Q] + Mk.OffsetM; break;
				}
			}
			const double Half = 0.5 * Mk.WidthM;
			TArray<TArray<double>> Centres;
			if (Mk.Pattern == EStreetMarkingPattern::Double)
			{
				const double Sep = 0.5 * ((Mk.DoubleGapM.IsSet() ? Mk.DoubleGapM.GetValue() : 0.0) + Mk.WidthM);
				TArray<double> A, B;
				A.SetNumUninitialized(M); B.SetNumUninitialized(M);
				for (int32 Q = 0; Q < M; ++Q) { A[Q] = C[Q] - Sep; B[Q] = C[Q] + Sep; }
				Centres.Add(MoveTemp(A));
				Centres.Add(MoveTemp(B));
			}
			else
			{
				Centres.Add(C);
			}
			const FString GName = Mk.Id.IsEmpty()
				? FString::Printf(TEXT("marking:%s_%s"), FStreetEnums::ToString(Mk.Anchor), FStreetEnums::ToString(Mk.Pattern))
				: FString::Printf(TEXT("marking:%s"), *Mk.Id);
			const TArray<bool> Qm = FStreetSweep::RunsToQuadMask(SM, Pl.Ivs);
			for (const TArray<double>& Cc : Centres)
			{
				TArray<double> PointO, PointH;
				PointO.SetNumUninitialized(M * 2);
				PointH.SetNumUninitialized(M * 2);
				for (int32 Q = 0; Q < M; ++Q)
				{
					PointO[Q * 2 + 0] = -Half;
					PointO[Q * 2 + 1] = Half;
					PointH[Q * 2 + 0] = MeshSurfaceH(Sp, D, H, R, SM[Q], Cc[Q] - Half) + Mk.LiftM;
					PointH[Q * 2 + 1] = MeshSurfaceH(Sp, D, H, R, SM[Q], Cc[Q] + Half) + Mk.LiftM;
				}
				FStreetSection Sec = MakeSection(false, { FVector2d(-Half, 0.0), FVector2d(Half, 0.0) }, { Mk.Material, Mk.Material }, { true, true });
				Sec.Points[1].V = Mk.WidthM;
				FStreetSweepParams Pr;
				Pr.Side = +1;
				Pr.Lateral = Cc;
				Pr.HeightScalar = 0.0;
				Pr.PointO = PointO;
				Pr.PointH = PointH;
				Pr.QuadMask = Qm;
				Pr.bCapStart = false;
				Pr.bCapEnd = false;
				Pr.Group = FName(*GName);
				const FStreetSweepResult Res = FStreetSweep::Sweep(Buf, Sec, Fr, Pr);
				NStrips += Res.Runs.Num();
			}
		}
	}
	Out.MarkingStrips = NStrips;
}

// ---------------------------------------------------------------------------------------------------------------
// Rail - a road-profile kind, inside Renderer A (DESIGN.md 6)
// ---------------------------------------------------------------------------------------------------------------

void FStreetRenderBuild::BuildRail(const FStreetSamples& Sp, FStreetRenderResult& Out)
{
	if (!Sp.RoadProfile) return;
	FStreetMeshBuilder& Buf = Out.Buffer;
	const FStreetRailSpec& Spec = Sp.RoadProfile->Rail;
	const int32 N = Sp.Num();
	const TArray<double> EL = Sp.EdgeOffset(EStreetSide::Left);
	const TArray<double> ER = Sp.EdgeOffset(EStreetSide::Right);
	const double Depth = Spec.Ballast.DepthM;
	const double K = Spec.Ballast.ShoulderSlope;

	// -- ballast: open 4-point section, shoulders hard, no caps
	TArray<double> O, Hh;
	O.SetNumUninitialized(N * 4);
	Hh.SetNumUninitialized(N * 4);
	for (int32 I = 0; I < N; ++I)
	{
		O[I * 4 + 0] = -(ER[I] + Depth * K); O[I * 4 + 1] = -ER[I]; O[I * 4 + 2] = EL[I]; O[I * 4 + 3] = EL[I] + Depth * K;
		Hh[I * 4 + 0] = -Depth; Hh[I * 4 + 1] = 0.0; Hh[I * 4 + 2] = 0.0; Hh[I * 4 + 3] = -Depth;
	}
	{
		const FName Bm = Spec.Ballast.Material;
		FStreetSection Sec;
		Sec.bClosed = false;
		const double Oo[4] = { O[0], O[1], O[2], O[3] };
		const double Hho[4] = { -Depth, 0.0, 0.0, -Depth };
		const bool Sm[4] = { true, false, false, true };
		for (int32 Kx = 0; Kx < 4; ++Kx)
		{
			FStreetSectionPoint P;
			P.O = Oo[Kx]; P.H = Hho[Kx]; P.Mat = Bm; P.V = (double)Kx; P.bSmooth = Sm[Kx];
			Sec.Points.Add(P);
		}
		FStreetSweepParams Pr;
		Pr.Side = +1;
		Pr.PointO = O;
		Pr.PointH = Hh;
		// a rail spline never stands in a tarmac junction (the plan drops rail arms), so Active is all-true here; the
		// mask is carried anyway so a rail that ever did stop at one would stop in both renderers (rail.py:45-48).
		Pr.Mask = Sp.Active;
		Pr.bCapStart = false;
		Pr.bCapEnd = false;
		Pr.Group = TEXT("ballast");
		FStreetSweep::Sweep(Buf, Sec, Sp.Frames, Pr);
	}

	// -- sleepers
	const FStreetSleeper& Sl = Spec.Sleeper;
	const double L = Sp.LengthM;
	TArray<double> Js;
	for (int32 J = 0; Sl.PhaseM + J * Sl.PitchM <= L + 1e-9; ++J)
	{
		const double Sj = Sl.PhaseM + J * Sl.PitchM;
		if (Sj >= -1e-9) Js.Add(Sj);
		if (Sl.PitchM <= 0) break;
	}
	if (Js.Num())
	{
		const FStreetFrames Fr = Sp.Frames.At(Js);
		for (int32 Q = 0; Q < Js.Num(); ++Q)
		{
			const FVector3d Pp(Fr.P[Q].X - Sl.EmbedM * Fr.B[Q].X, Fr.P[Q].Y - Sl.EmbedM * Fr.B[Q].Y, Fr.P[Q].Z - Sl.EmbedM * Fr.B[Q].Z);
			if (Sl.Mode == EStreetSleeperMode::Merged)
			{
				// box_mesh: 8 corners, 12 outward triangles, merged into the buffer
				const double Sx = Sl.WidthM, Sy = Sl.LengthM, Sz = Sl.HeightM;
				const double Cn[8][3] = { { -Sx / 2, -Sy / 2, 0 }, { Sx / 2, -Sy / 2, 0 }, { Sx / 2, Sy / 2, 0 }, { -Sx / 2, Sy / 2, 0 },
					{ -Sx / 2, -Sy / 2, Sz }, { Sx / 2, -Sy / 2, Sz }, { Sx / 2, Sy / 2, Sz }, { -Sx / 2, Sy / 2, Sz } };
				TArray<FVector3d> Vs; TArray<FVector2d> Uv; TArray<double> Sa, Da, Ha;
				for (int32 Ci = 0; Ci < 8; ++Ci)
				{
					const FVector3d Pt(Pp.X + Cn[Ci][0] * Fr.Th[Q].X + Cn[Ci][1] * Fr.N[Q].X + Cn[Ci][2] * Fr.B[Q].X,
						Pp.Y + Cn[Ci][0] * Fr.Th[Q].Y + Cn[Ci][1] * Fr.N[Q].Y + Cn[Ci][2] * Fr.B[Q].Y,
						Pp.Z + Cn[Ci][0] * Fr.Th[Q].Z + Cn[Ci][1] * Fr.N[Q].Z + Cn[Ci][2] * Fr.B[Q].Z);
					Vs.Add(Pt); Uv.Add(FVector2d::ZeroVector); Sa.Add(Js[Q]); Da.Add(0.0); Ha.Add(-Sl.EmbedM);
				}
				const int32 V0 = Buf.AppendVertices(Vs, Uv, Sa, Da, Ha);
				static const int32 Fi[12][3] = { { 0, 2, 1 }, { 0, 3, 2 }, { 4, 5, 6 }, { 4, 6, 7 }, { 0, 1, 5 }, { 0, 5, 4 },
					{ 1, 2, 6 }, { 1, 6, 5 }, { 2, 3, 7 }, { 2, 7, 6 }, { 3, 0, 4 }, { 3, 4, 7 } };
				TArray<UE::Geometry::FIndex3i> Tr;
				for (int32 Ti = 0; Ti < 12; ++Ti) Tr.Add(UE::Geometry::FIndex3i(V0 + Fi[Ti][0], V0 + Fi[Ti][1], V0 + Fi[Ti][2]));
				Buf.AppendTriangles(Tr, Buf.MaterialId(Sl.Material), Buf.GroupId(TEXT("sleeper")));
			}
			else
			{
				FStreetInstance In;
				In.Kind = TEXT("sleeper");
				In.Th = Fr.Th[Q]; In.N = Fr.N[Q]; In.B = Fr.B[Q]; In.P = Pp;
				In.Size = FVector3d(Sl.WidthM, Sl.LengthM, Sl.HeightM);
				In.Material = Sl.Material;
				In.SplineId = Sp.Id;
				In.Side = 0;
				Out.Instances.Add(In);
			}
		}
	}

	// -- rails: closed 12-point BS113A section at +-(gauge/2 + head_width/2)
	{
		const FStreetRailSection& Rs = Spec.Rail;
		const double Fw = Rs.FootWidthM, Ft = Rs.FootThicknessM, Wt = Rs.WebThicknessM;
		const double Hgt = Rs.HeightM, Hd = Rs.HeadDepthM, Hw = Rs.HeadWidthM;
		const double Hf = 0.5 * Fw, Hwt = 0.5 * Wt, Hh2 = 0.5 * Hw;
		const TArray<FVector2d> Pts = {
			FVector2d(-Hf, 0.0), FVector2d(-Hf, Ft), FVector2d(-Hwt, Ft + 0.019), FVector2d(-Hwt, Hgt - Hd), FVector2d(-Hh2, Hgt - Hd), FVector2d(-Hh2, Hgt),
			FVector2d(Hh2, Hgt), FVector2d(Hh2, Hgt - Hd), FVector2d(Hwt, Hgt - Hd), FVector2d(Hwt, Ft + 0.019), FVector2d(Hf, Ft), FVector2d(Hf, 0.0) };
		TArray<FName> Mats;
		TArray<bool> Smooth;
		for (int32 I = 0; I < Pts.Num(); ++I) { Mats.Add(Rs.Material); Smooth.Add(false); }
		const FStreetSection RSec = MakeSection(true, Pts, Mats, Smooth);
		const double Lat = 0.5 * Spec.GaugeM + 0.5 * Rs.HeadWidthM;
		const double Height = (Sl.HeightM - Sl.EmbedM) + Spec.PadM;
		const TCHAR* Names[2] = { TEXT("rail:left"), TEXT("rail:right") };
		const double Signs[2] = { +1.0, -1.0 };
		for (int32 Q = 0; Q < 2; ++Q)
		{
			FStreetSweepParams Pr;
			Pr.Side = +1;
			Pr.LateralScalar = Signs[Q] * Lat;
			Pr.HeightScalar = Height;
			Pr.Mask = Sp.Active;
			Pr.bCapStart = true;
			Pr.bCapEnd = true;
			Pr.CapMat = Rs.Material;
			Pr.Group = Names[Q];
			FStreetSweep::Sweep(Buf, RSec, Sp.Frames, Pr);
		}
	}
	Out.MarkingStrips = 0;
}

// ---------------------------------------------------------------------------------------------------------------
// Renderer B - edge.py
// ---------------------------------------------------------------------------------------------------------------

void FStreetRenderBuild::KerbLayout(int32 M, TArray<bool>& OutSmooth, TArray<FName>& OutGroups, int32& OutNInnerEdges)
{
	OutNInnerEdges = 2 + (M + 1);          // A-B, B-C, C..D
	OutGroups.Reset();
	for (int32 K = 0; K < OutNInnerEdges + 2; ++K) OutGroups.Add(TEXT("kerb"));
	OutGroups.Add(TEXT("pavement"));
	OutGroups.Add(TEXT("pavement"));
	OutSmooth.Reset();
	OutSmooth.Add(false); OutSmooth.Add(false); OutSmooth.Add(true);
	for (int32 J = 0; J < M; ++J) OutSmooth.Add(true);
	OutSmooth.Add(true); OutSmooth.Add(true); OutSmooth.Add(true); OutSmooth.Add(false); OutSmooth.Add(false);
}

void FStreetRenderBuild::KerbColumns(TConstArrayView<double> KerbWidth, TConstArrayView<double> Hk, TConstArrayView<double> LipR,
	TConstArrayView<double> PavementWidth, TConstArrayView<double> HkBack, TConstArrayView<double> TuckIn,
	TConstArrayView<double> TuckDepth, TConstArrayView<double> Skirt, TConstArrayView<double> Frac,
	TConstArrayView<EStreetLipKind> LipKind, int32 M, TArray<double>& OutO, TArray<double>& OutH)
{
	const int32 Rows = Hk.Num();
	const int32 P = 3 + M + 5;
	OutO.SetNumUninitialized(Rows * P);
	OutH.SetNumUninitialized(Rows * P);
	for (int32 I = 0; I < Rows; ++I)
	{
		const double Kw = KerbWidth[I], H = Hk[I], Rr = LipR[I];
		const double Pw = PavementWidth[I], Hkb = HkBack[I];
		const double Ti = TuckIn[I], Td = TuckDepth[I], Sk = Skirt[I];
		double* Or = &OutO[I * P];
		double* Hr = &OutH[I * P];
		Or[0] = -Ti;   Hr[0] = -Td;
		Or[1] = 0.0;   Hr[1] = -Td;
		Or[2] = 0.0;   Hr[2] = H - Rr;
		for (int32 J = 1; J <= M; ++J)
		{
			const double Th = (90.0 * (double)J / (double)(M + 1)) * (kPiD / 180.0);
			double Lo = 0.0, Lh = H;
			if (LipKind[I] == EStreetLipKind::Radius)
			{
				Lo = Rr - Rr * std::cos(Th);
				Lh = H - Rr + Rr * std::sin(Th);
			}
			else if (LipKind[I] == EStreetLipKind::Chamfer)
			{
				const double F = (double)J / (double)(M + 1);
				Lo = Rr * F;
				Lh = H - Rr + Rr * F;
			}
			Or[2 + J] = Lo; Hr[2 + J] = Lh;
		}
		Or[3 + M] = Rr;           Hr[3 + M] = H;
		Or[4 + M] = Kw * Frac[I]; Hr[4 + M] = H;
		Or[5 + M] = Kw;           Hr[5 + M] = H;
		Or[6 + M] = Kw + Pw;      Hr[6 + M] = Hkb;
		Or[7 + M] = Kw + Pw;      Hr[7 + M] = -Sk;
	}
}

TArray<double> FStreetRenderBuild::PostStations(double A, double B, double Pitch)
{
	TArray<double> Out;
	const double D = B - A;
	if (D <= 1e-9 || Pitch <= 0)
	{
		if (D <= 1e-9) { Out.Add(A); }
		else { Out.Add(A); Out.Add(B); }
		return Out;
	}
	const double Q = D / Pitch;
	const double Fl = FMath::FloorToDouble(Q + 1e-9);
	const int32 Nn = (int32)Fl + 1 + (((Q - Fl) > 0.5) ? 1 : 0);
	for (int32 J = 0; J < FMath::Max(Nn - 1, 0); ++J) Out.Add(A + J * Pitch);
	Out.Add(B);
	return Out;
}

void FStreetRenderBuild::BuildEdge(const FStreetSamples& Sp, EStreetSide SideEnum, const IStreetTerrainSource* Terrain, FStreetRenderResult& Out)
{
	FStreetMeshBuilder& Buf = Out.Buffer;
	const int32 SideIdx = StreetSideIndex(SideEnum);
	const int32 Side = StreetSideSigma(SideEnum);
	const FStreetSideSpec& Spec = Sp.SideSpec[SideIdx];
	// the junction trim is a mask on the SHARED spline, so Renderer B stops exactly where Renderer A does: kerb and
	// pavement never run on into the middle of a junction (edge.build_edge: present = spec.present & spline.active).
	TArray<bool> Present = Spec.Present;
	for (int32 I = 0; I < Present.Num(); ++I) Present[I] = Present[I] && (Sp.Active.IsValidIndex(I) ? Sp.Active[I] : true);
	if (!AnyTrue(Present)) return;
	const TArray<double> O0 = Sp.EdgeOffset(SideEnum);
	const TArray<double> H0 = Sp.EdgeHeight(SideEnum);
	const TArray<double>& S = Sp.S;
	const int32 N = Sp.Num();
	const FStreetFrames& Frames = Sp.Frames;

	// -- kerb + pavement -----------------------------------------------------------------------------------------
	if (Spec.bHasKerbOrPavement)
	{
		const int32 M = Spec.ArcPoints;
		const int32 P = 3 + M + 5;
		const int32 E = P - 1;
		TArray<double> Frac;
		Frac.SetNumUninitialized(N);
		for (int32 I = 0; I < N; ++I) Frac[I] = Spec.Split[I] ? Spec.SplitFrac[I] : 0.5;
		TArray<double> O, Hh;
		KerbColumns(Spec.KerbWidth, Spec.Hk, Spec.LipR, Spec.PavementWidth, Spec.HkBack, Spec.TuckIn, Spec.TuckDepth,
			Spec.Skirt, Frac, Spec.LipKind, M, O, Hh);
		TArray<FName> Mats;
		Mats.SetNumUninitialized(N * E);
		TArray<bool> Smooth;
		TArray<FName> Groups;
		int32 NInnerEdges = 0;
		KerbLayout(M, Smooth, Groups, NInnerEdges);
		for (int32 I = 0; I < N; ++I)
		{
			const FName Inner = Spec.MatInner[I];
			const FName TopOut = Spec.Split[I] ? Spec.MatOuter[I] : Spec.MatKerb[I];
			const FName PavMat = Spec.Split[I] ? Spec.MatOuter[I] : Spec.MatPavement[I];
			FName* Mr = &Mats[I * E];
			for (int32 K = 0; K < NInnerEdges; ++K) Mr[K] = Inner;
			Mr[NInnerEdges] = Inner;
			Mr[NInnerEdges + 1] = TopOut;
			Mr[NInnerEdges + 2] = PavMat;
			Mr[NInnerEdges + 3] = PavMat;
		}
		// section from station 0 (materials of the first station; the per-station table overrides them)
		FStreetSection Section;
		Section.bClosed = false;
		double V = 0.0;
		for (int32 K = 0; K < P; ++K)
		{
			if (K > 0) V += std::hypot(O[K] - O[K - 1], Hh[K] - Hh[K - 1]);
			FStreetSectionPoint Pt;
			Pt.O = O[K]; Pt.H = Hh[K]; Pt.Mat = Mats[FMath::Min(K, E - 1)]; Pt.V = V; Pt.bSmooth = Smooth[K];
			Section.Points.Add(Pt);
		}
		FStreetSweepParams Pr;
		Pr.Side = Side;
		Pr.Lateral = O0;
		Pr.Height = H0;
		Pr.PointO = O;
		Pr.PointH = Hh;
		Pr.Mask = Present;
		Pr.bCapStart = true;
		Pr.bCapEnd = true;
		Pr.Groups = Groups;
		Pr.EdgeMatStation = Mats;
		FStreetSweep::Sweep(Buf, Section, Frames, Pr);
	}

	// -- barriers ------------------------------------------------------------------------------------------------
	TArray<double> HbAll;
	HbAll.SetNumUninitialized(N);
	for (int32 I = 0; I < N; ++I) HbAll[I] = H0[I] + Spec.HkBack[I];
	for (const TStreetInterval<FStreetBarrier>& Iv : Spec.BarrierTimeline)
	{
		if (!Iv.bHas) continue;
		const FStreetBarrier& Bar = Iv.Value;
		if (Bar.Type == EStreetBarrierType::None) continue;
		TArray<bool> Mask = RangeMask(S, Iv.A, Iv.B);
		for (int32 I = 0; I < Mask.Num(); ++I) Mask[I] = Mask[I] && (Sp.Active.IsValidIndex(I) ? Sp.Active[I] : true);
		if (!AnyTrue(Mask)) continue;
		TArray<double> Ob;
		Ob.SetNumUninitialized(N);
		for (int32 I = 0; I < N; ++I) Ob[I] = O0[I] + Spec.BackOffset[I] + Bar.OffsetM;
		const double Hgt = Bar.HeightM.IsSet() ? Bar.HeightM.GetValue() : 0.0;
		const double Th = Bar.ThicknessM.IsSet() ? Bar.ThicknessM.GetValue() : 0.0;
		const FString GName = FString::Printf(TEXT("barrier:%s:%s"), FStreetEnums::ToString(Bar.Type), *FmtG(Iv.A));
		if (Bar.IsWall())
		{
			const double Ov = Bar.CopingOverhangM, Ch = Bar.CopingHeightM, Sk = Bar.SkirtM;
			const TArray<FVector2d> Pts = { FVector2d(0.0, -Sk), FVector2d(0.0, Hgt), FVector2d(-Ov, Hgt), FVector2d(-Ov, Hgt + Ch),
				FVector2d(Th + Ov, Hgt + Ch), FVector2d(Th + Ov, Hgt), FVector2d(Th, Hgt), FVector2d(Th, -Sk) };
			const TArray<FName> Mats = { Bar.Material, Bar.CopingMaterial, Bar.CopingMaterial, Bar.CopingMaterial,
				Bar.CopingMaterial, Bar.CopingMaterial, Bar.Material, Bar.Material };
			TArray<bool> Smooth; Smooth.Init(false, 8);
			const FStreetSection Sec = MakeSection(true, Pts, Mats, Smooth);
			FStreetSweepParams Pr;
			Pr.Side = Side;
			Pr.Lateral = Ob;
			Pr.Height = HbAll;
			Pr.Mask = Mask;
			Pr.bCapStart = true;
			Pr.bCapEnd = true;
			Pr.CapMat = Bar.Material;
			Pr.Group = FName(*GName);
			FStreetSweep::Sweep(Buf, Sec, Frames, Pr);
		}
		else
		{
			const bool bFence = Bar.IsFence();
			const FName Kind = bFence ? FName(TEXT("post_round")) : FName(TEXT("post_square"));
			const double Ps = Bar.PostSizeM;
			const double PostH = bFence ? Hgt + 0.05 : Hgt;
			const TArray<double> Sj = PostStations(Iv.A, Iv.B, Bar.PostPitchM.IsSet() ? Bar.PostPitchM.GetValue() : 0.0);
			const FStreetFrames Fr = Frames.At(Sj);
			for (int32 Q = 0; Q < Sj.Num(); ++Q)
			{
				const double ObJ = InterpAt(S, Ob, Sj[Q]);
				const double HbJ = InterpAt(S, HbAll, Sj[Q]);
				const double Dl = Side * (ObJ + 0.5 * Th);
				const FVector3d Pp(Fr.P[Q].X + Dl * Fr.N[Q].X + HbJ * Fr.B[Q].X,
					Fr.P[Q].Y + Dl * Fr.N[Q].Y + HbJ * Fr.B[Q].Y,
					Fr.P[Q].Z + Dl * Fr.N[Q].Z + HbJ * Fr.B[Q].Z);
				FStreetInstance In;
				In.Kind = Kind;
				In.Th = Fr.Th[Q]; In.N = Fr.N[Q]; In.B = Fr.B[Q]; In.P = Pp;
				In.Size = FVector3d(Ps, Ps, PostH);
				In.Material = Bar.PostMaterial;
				In.SplineId = Sp.Id;
				In.Side = Side;
				Out.Instances.Add(In);
			}
			if (bFence)
			{
				FStreetSection Sec = MakeSection(false, { FVector2d(0.5 * Th, 0.05), FVector2d(0.5 * Th, Hgt) }, { Bar.Material, Bar.Material }, { true, true });
				Sec.Points[0].V = 0.0;
				Sec.Points[1].V = Hgt - 0.05;
				FStreetSweepParams Pr;
				Pr.Side = Side;
				Pr.Lateral = Ob;
				Pr.Height = HbAll;
				Pr.Mask = Mask;
				Pr.bCapStart = false;
				Pr.bCapEnd = false;
				Pr.Group = FName(*GName);
				Pr.bTwoSided = true;
				FStreetSweep::Sweep(Buf, Sec, Frames, Pr);
			}
			else
			{
				const double Ar = 0.5 * Bar.RailSizeM;
				for (double Hr : Bar.EffectiveRails())
				{
					const double Oc = 0.5 * Th;
					const TArray<FVector2d> Pts = { FVector2d(Oc - Ar, Hr - Ar), FVector2d(Oc - Ar, Hr + Ar), FVector2d(Oc + Ar, Hr + Ar), FVector2d(Oc + Ar, Hr - Ar) };
					FStreetSection Sec = MakeSection(true, Pts, { Bar.Material, Bar.Material, Bar.Material, Bar.Material }, { false, false, false, false });
					Sec.Points[0].V = 0.0; Sec.Points[1].V = 2 * Ar; Sec.Points[2].V = 4 * Ar; Sec.Points[3].V = 6 * Ar;
					FStreetSweepParams Pr;
					Pr.Side = Side;
					Pr.Lateral = Ob;
					Pr.Height = HbAll;
					Pr.Mask = Mask;
					Pr.bCapStart = true;
					Pr.bCapEnd = true;
					Pr.CapMat = Bar.Material;
					Pr.Group = FName(*GName);
					FStreetSweep::Sweep(Buf, Sec, Frames, Pr);
				}
			}
		}
	}

	// -- embankments ---------------------------------------------------------------------------------------------
	if (Terrain)
	{
		for (const TStreetInterval<FStreetEmbankment>& Iv : Spec.EmbankmentTimeline)
		{
			if (!Iv.bHas) continue;
			const FStreetEmbankment& Emb = Iv.Value;
			const EStreetSide EmbSide = SideEnum;
			if ((Emb.Side == EStreetEmbankmentSide::Left || Emb.Side == EStreetEmbankmentSide::Right) &&
				((Emb.Side == EStreetEmbankmentSide::Left) != (EmbSide == EStreetSide::Left))) continue;
			const TArray<bool> Rng = RangeMask(S, Iv.A, Iv.B);
			TArray<double> Dz, Ground;
			TArray<FVector3d> Start;
			TArray<bool> Valid;
			Dz.SetNumUninitialized(N);
			Ground.SetNumUninitialized(N);
			Start.SetNumUninitialized(N);
			Valid.SetNumUninitialized(N);
			for (int32 I = 0; I < N; ++I)
			{
				const double Ob = O0[I] + Spec.BackOffset[I];
				Start[I] = Frames.P[I] + Side * Ob * Frames.N[I] + HbAll[I] * Frames.B[I];
				double Zt = 0.0;
				const bool bOk = Terrain->SampleHeight(Start[I].X, Start[I].Y, Zt);
				Ground[I] = Zt;
				Dz[I] = bOk ? (Start[I].Z - Zt) : NAN;
				if (Rng[I] && (Sp.Active.IsValidIndex(I) ? Sp.Active[I] : true) && (!bOk || !std::isfinite(Dz[I])))
				{
					Out.Problems.Add(FString::Printf(TEXT("embankment edge at s=%g has missing terrain"), S[I]));
					return;
				}
				Valid[I] = bOk && std::isfinite(Dz[I]) && Rng[I] && (Sp.Active.IsValidIndex(I) ? Sp.Active[I] : true);
			}
			const double Thr = Emb.ThresholdM;
			const bool bWantBatter = Emb.Kind == EStreetEmbankmentKind::Batter || Emb.Kind == EStreetEmbankmentKind::Auto;
			const bool bWantWall = Emb.Kind == EStreetEmbankmentKind::RetainingWall || Emb.Kind == EStreetEmbankmentKind::Auto;
			const bool bAllowDown = Emb.Side != EStreetEmbankmentSide::Uphill;
			const bool bAllowUp = Emb.Side != EStreetEmbankmentSide::Downhill;
			TArray<double> Ob;
			Ob.SetNumUninitialized(N);
			for (int32 I = 0; I < N; ++I) Ob[I] = O0[I] + Spec.BackOffset[I];
			if (bWantBatter && bAllowDown)
			{
				TArray<bool> Mask;
				Mask.SetNumUninitialized(N);
				for (int32 I = 0; I < N; ++I) Mask[I] = Valid[I] && Dz[I] > Thr;
				if (AnyTrue(Mask))
				{
					TArray<double> O, Hh;
					O.SetNumUninitialized(N * 2);
					Hh.SetNumUninitialized(N * 2);
					for (int32 I = 0; I < N; ++I)
					{
						double Run = 0.0, Drop = 0.0;
						if (Mask[I] && !BatterToe(Terrain, Start[I], Side * Frames.NFlat[I], Emb.SlopeRatio, Emb.ToeExtraM, Run, Drop))
						{
							Out.Problems.Add(FString::Printf(TEXT("batter at s=%g has no terrain contact within 64 m or crosses missing terrain"), S[I]));
							return;
						}
						const FVector2d Toe = SupportSection(Frames, I, Side, Run, Drop);
						O[I * 2 + 0] = 0.0; O[I * 2 + 1] = Toe.X;
						Hh[I * 2 + 0] = 0.0; Hh[I * 2 + 1] = Toe.Y;
					}
					FStreetSection Sec = MakeSection(false, { FVector2d(0.0, 0.0), FVector2d(1.0, -1.0) }, { Emb.Material, Emb.Material }, { true, true });
					Sec.Points[0].V = 0.0; Sec.Points[1].V = 1.0;
					FStreetSweepParams Pr;
					Pr.Side = Side;
					Pr.Lateral = Ob;
					Pr.Height = HbAll;
					Pr.PointO = O;
					Pr.PointH = Hh;
					Pr.Mask = Mask;
					Pr.bCapStart = false;
					Pr.bCapEnd = false;
					Pr.Group = FName(*FString::Printf(TEXT("embankment:batter:%s"), *FmtG(Iv.A)));
					FStreetSweep::Sweep(Buf, Sec, Frames, Pr);
				}
			}
			if (bWantWall)
			{
				TArray<bool> Mask;
				Mask.SetNumUninitialized(N);
				for (int32 I = 0; I < N; ++I) Mask[I] = Valid[I] && ((Dz[I] < -Thr && bAllowUp) ||
					(Dz[I] > Thr && bAllowDown && Emb.Kind == EStreetEmbankmentKind::RetainingWall));
				if (AnyTrue(Mask))
				{
					const double Wt = Emb.WallThicknessM;
					TArray<double> O, Hh;
					O.SetNumUninitialized(N * 4);
					Hh.SetNumUninitialized(N * 4);
					for (int32 I = 0; I < N; ++I)
					{
						const FVector3d Outer = Start[I] + Side * Wt * Frames.NFlat[I];
						double ZOuter = 0.0;
						if (Mask[I] && (!Terrain->SampleHeight(Outer.X, Outer.Y, ZOuter) || !std::isfinite(ZOuter)))
						{
							Out.Problems.Add(FString::Printf(TEXT("retaining wall at s=%g has no terrain under its footing"), S[I]));
							return;
						}
						const double Top = (Mask[I] ? FMath::Max3(Start[I].Z, Ground[I], ZOuter) - Start[I].Z : 0.0) + Emb.WallCopingM;
						const double Base = (Mask[I] ? FMath::Min3(Start[I].Z, Ground[I], ZOuter) - Start[I].Z : 0.0) - Emb.ToeExtraM;
						const double Runs[4] = {0.0, 0.0, Wt, Wt};
						const double Heights[4] = {Base, Top, Top, Base};
						for (int32 J = 0; J < 4; ++J)
						{
							const FVector2d P = SupportSection(Frames, I, Side, Runs[J], Heights[J]);
							O[I * 4 + J] = P.X; Hh[I * 4 + J] = P.Y;
						}
					}
					FStreetSection Sec = MakeSection(true, { FVector2d(0.0, -0.3), FVector2d(0.0, 1.0), FVector2d(Wt, 1.0), FVector2d(Wt, -0.3) },
						{ Emb.Material, Emb.Material, Emb.Material, Emb.Material }, { false, false, false, false });
					Sec.Points[0].V = 0.0; Sec.Points[1].V = 1.0; Sec.Points[2].V = 2.0; Sec.Points[3].V = 3.0;
					FStreetSweepParams Pr;
					Pr.Side = Side;
					Pr.Lateral = Ob;
					Pr.Height = HbAll;
					Pr.PointO = O;
					Pr.PointH = Hh;
					Pr.Mask = Mask;
					Pr.bCapStart = true;
					Pr.bCapEnd = true;
					Pr.CapMat = Emb.Material;
					Pr.Group = FName(*FString::Printf(TEXT("embankment:retaining_wall:%s"), *FmtG(Iv.A)));
					FStreetSweep::Sweep(Buf, Sec, Frames, Pr);
				}
			}
		}
	}
}

// ---------------------------------------------------------------------------------------------------------------
// Renderer C - hedge.py
// ---------------------------------------------------------------------------------------------------------------

TArray<FVector2d> FStreetRenderBuild::HedgeSectionPoints(double W, double H, double R, int32 M, EStreetTopProfile Top)
{
	TArray<FVector2d> Pts;
	Pts.Add(FVector2d(0.0, 0.0));
	if (Top == EStreetTopProfile::Rounded)
	{
		const double Cy = H - 0.5 * W;
		Pts.Add(FVector2d(0.0, Cy));
		const int32 Nn = 2 * M + 3;
		for (int32 J = 1; J < Nn - 1; ++J)
		{
			const double Th = kPiD - kPiD * (double)J / (double)(Nn - 1);
			Pts.Add(FVector2d(0.5 * W + (0.5 * W) * std::cos(Th), Cy + (0.5 * W) * std::sin(Th)));
		}
		Pts.Add(FVector2d(W, Cy));
	}
	else
	{
		Pts.Add(FVector2d(0.0, H - R));
		for (int32 J = 1; J <= M; ++J)
		{
			const double Th = kPiD - (0.5 * kPiD) * (double)J / (double)(M + 1);
			Pts.Add(FVector2d(R + R * std::cos(Th), H - R + R * std::sin(Th)));
		}
		if (Top == EStreetTopProfile::Domed)
		{
			const double Rise = 0.15 * W;
			const double X0 = R, X1 = W - R;
			const int32 Nn = 2 * M + 1;
			for (int32 J = 0; J < Nn; ++J)
			{
				const double F = (double)J / (double)(Nn - 1);
				const double X = X0 + (X1 - X0) * F;
				Pts.Add(FVector2d(X, H + Rise * std::sin(kPiD * F)));
			}
		}
		else
		{
			Pts.Add(FVector2d(R, H));
			Pts.Add(FVector2d(W - R, H));
		}
		for (int32 J = 1; J <= M; ++J)
		{
			const double Th = (0.5 * kPiD) - (0.5 * kPiD) * (double)J / (double)(M + 1);
			Pts.Add(FVector2d(W - R + R * std::cos(Th), H - R + R * std::sin(Th)));
		}
		Pts.Add(FVector2d(W, H - R));
	}
	Pts.Add(FVector2d(W, 0.0));
	TArray<FVector2d> Outp;
	Outp.Add(Pts[0]);
	for (int32 I = 1; I < Pts.Num(); ++I)
	{
		if (std::hypot(Pts[I].X - Outp.Last().X, Pts[I].Y - Outp.Last().Y) > 1e-12) Outp.Add(Pts[I]);
	}
	return Outp;
}

TArray<FVector2d> FStreetRenderBuild::SectionOutwardNormals(const TArray<FVector2d>& Pts)
{
	const int32 Nn = Pts.Num();
	TArray<FVector2d> Out;
	Out.SetNum(Nn);
	for (int32 K = 0; K < Nn; ++K)
	{
		const FVector2d Prev = Pts[(K - 1 + Nn) % Nn];
		const FVector2d Next = Pts[(K + 1) % Nn];
		const FVector2d Dp = Pts[K] - Prev;
		const FVector2d Dn = Next - Pts[K];
		const double Lp = FMath::Max(std::hypot(Dp.X, Dp.Y), 1e-12);
		const double Ln = FMath::Max(std::hypot(Dn.X, Dn.Y), 1e-12);
		const FVector2d Perp(-Dp.Y / Lp + -Dn.Y / Ln, Dp.X / Lp + Dn.X / Ln);
		const double Nl = std::hypot(Perp.X, Perp.Y);
		Out[K] = Nl > 1e-12 ? FVector2d(Perp.X / Nl, Perp.Y / Nl) : FVector2d::ZeroVector;
	}
	return Out;
}

void FStreetRenderBuild::BuildHedge(const FStreetSamples& Sp, EStreetSide SideEnum, FStreetRenderResult& Out)
{
	FStreetMeshBuilder& Buf = Out.Buffer;
	const int32 SideIdx = StreetSideIndex(SideEnum);
	const int32 Side = StreetSideSigma(SideEnum);
	const FStreetSideSpec& Spec = Sp.SideSpec[SideIdx];
	const TArray<double> O0 = Sp.EdgeOffset(SideEnum);
	const TArray<double> H0 = Sp.EdgeHeight(SideEnum);
	const TArray<double>& S = Sp.S;
	const int32 N = Sp.Num();
	const FStreetFrames& Frames = Sp.Frames;
	TArray<double> BarStep;
	BarStep.SetNumUninitialized(N);
	for (int32 I = 0; I < N; ++I)
	{
		const FStreetBarrier* B = Spec.BarrierAt(S[I]);
		BarStep[I] = (B && B->Type != EStreetBarrierType::None)
			? ((B->OffsetM) + (B->ThicknessM.IsSet() ? B->ThicknessM.GetValue() : 0.0)) : 0.0;
	}
	for (const TStreetInterval<FStreetHedgeSpec>& Iv : Spec.HedgeTimeline)
	{
		if (!Iv.bHas || Iv.Value.Profile == nullptr) continue;
		const FStreetHedgeSpec& Hs = Iv.Value;
		const FHedgeProfileData& Prof = *Hs.Profile;
		TArray<bool> Mask = RangeMask(S, Iv.A, Iv.B);
		for (int32 I = 0; I < Mask.Num(); ++I) Mask[I] = Mask[I] && (Sp.Active.IsValidIndex(I) ? Sp.Active[I] : true);
		if (CountTrue(Mask) < 2) continue;
		const double W = Hs.WidthM;
		const double H = Hs.HeightM + Prof.BaseSinkM;
		const double R = FMath::Min3(Prof.CornerRadiusM, 0.5 * W, 0.5 * H);
		const int32 M = Prof.CornerPoints;
		const TArray<FVector2d> Pts = HedgeSectionPoints(W, H, R, M, Prof.TopProfile);
		TArray<FName> Mats; TArray<bool> Smooth;
		for (int32 I = 0; I < Pts.Num(); ++I) { Mats.Add(Prof.Material); Smooth.Add(true); }
		const FStreetSection Sec = MakeSection(true, Pts, Mats, Smooth);
		TArray<double> Oh, Hb;
		Oh.SetNumUninitialized(N); Hb.SetNumUninitialized(N);
		for (int32 I = 0; I < N; ++I)
		{
			Oh[I] = O0[I] + Spec.BackOffset[I] + BarStep[I] + Hs.OffsetM;
			Hb[I] = H0[I] + Spec.HkBack[I] - Prof.BaseSinkM;
		}
		const int32 TFirst = Buf.F.Num();
		FStreetSweepParams Pr;
		Pr.Side = Side;
		Pr.Lateral = Oh;
		Pr.Height = Hb;
		Pr.Mask = Mask;
		Pr.bCapStart = true;
		Pr.bCapEnd = true;
		Pr.CapMat = Prof.Material;
		Pr.Group = FName(*FString::Printf(TEXT("hedge:%s"), *FmtG(Iv.A)));
		const FStreetSweepResult Res = FStreetSweep::Sweep(Buf, Sec, Frames, Pr);

		// -- noise displacement along the section-space outward normal (base row h <= 0.05 fixed)
		const double A = Prof.NoiseAmplitudeM;
		if (A > 0)
		{
			const TArray<FVector2d> Normals2 = SectionOutwardNormals(Pts);
			for (int32 I = 0; I < N; ++I)
			{
				if (!Mask[I]) continue;
				for (int32 Rw = 0; Rw < Res.R; ++Rw)
				{
					const int32 Vi = Res.VIdx[I * Res.R + Rw];
					if (Vi < 0) continue;
					const int32 Pk = Res.RowPoint[Rw];
					if (!(Pts[Pk].Y > 0.05)) continue;
					const FVector3d DirW(Side * Normals2[Pk].X * Frames.N[I].X + Normals2[Pk].Y * Frames.B[I].X,
						Side * Normals2[Pk].X * Frames.N[I].Y + Normals2[Pk].Y * Frames.B[I].Y,
						Side * Normals2[Pk].X * Frames.N[I].Z + Normals2[Pk].Y * Frames.B[I].Z);
					const FVector3d Q(Buf.V[Vi].X / Prof.NoiseScaleM, Buf.V[Vi].Y / Prof.NoiseScaleM, Buf.V[Vi].Z / Prof.NoiseScaleM);
					const double Delta = A * FMath::Clamp(FStreetNoise::Fbm3(Q, (uint32)Prof.NoiseSeed), -1.0, 1.0);
					Buf.V[Vi] = FVector3d(Buf.V[Vi].X + Delta * DirW.X, Buf.V[Vi].Y + Delta * DirW.Y, Buf.V[Vi].Z + Delta * DirW.Z);
				}
			}
		}

		// -- leaf cards
		const FStreetFoliage& Fol = Prof.Foliage;
		if ((Fol.Mode == EStreetFoliageMode::Cards || Fol.Mode == EStreetFoliageMode::Instances) && Fol.DensityPerM2 > 0)
		{
			const uint32 Seed = (uint32)Fol.Seed;
			const FName Kind = Fol.Mode == EStreetFoliageMode::Cards ? FName(TEXT("leaf_card")) : FName(*FString::Printf(TEXT("foliage_mesh:%s"), *Fol.MeshId));
			const FName Mat = Fol.Material.IsNone() ? Prof.Material : Fol.Material;
			const FVector3d Size(Fol.CardSizeM, Fol.CardSizeM, 0.0);
			for (int32 T = TFirst; T < Buf.F.Num(); ++T)
			{
				const UE::Geometry::FIndex3i& Fi = Buf.F[T];
				const FVector3d Pa = Buf.V[Fi.A], Pb = Buf.V[Fi.B], Pc = Buf.V[Fi.C];
				const FVector3d Fn = Cross3(Pb - Pa, Pc - Pa);
				const double Area = 0.5 * Norm3(Fn);
				const double B0 = Buf.VH[Fi.A] - InterpAt(S, Hb, Buf.VS[Fi.A]);
				const double B1 = Buf.VH[Fi.B] - InterpAt(S, Hb, Buf.VS[Fi.B]);
				const double B2 = Buf.VH[Fi.C] - InterpAt(S, Hb, Buf.VS[Fi.C]);
				const double HRel = (B0 + B1 + B2) / 3.0;
				const double Frac = FStreetNoise::UnitNoise01((uint32)T, Seed);
				int32 Count = (int32)FMath::FloorToDouble(Area * Fol.DensityPerM2 + Frac);
				if (HRel <= 0.05) Count = 0;
				if (Count <= 0) continue;
				const double Fl = FMath::Max(Norm3(Fn), 1e-12);
				const FVector3d Nrm(Fn.X / Fl, Fn.Y / Fl, Fn.Z / Fl);
				for (int32 Ci = 0; Ci < Count; ++Ci)
				{
					const int64 Base = (int64)T * 4096 + 3 * (int64)Ci;
					const double U1 = FStreetNoise::UnitNoise01((uint32)(Base + 1), Seed);
					const double U2 = FStreetNoise::UnitNoise01((uint32)(Base + 2), Seed);
					const double Rot = 2.0 * kPiD * FStreetNoise::UnitNoise01((uint32)(Base + 3), Seed);
					const double R1 = std::sqrt(U1);
					const double L1 = 1.0 - R1, L2 = R1 * (1.0 - U2), L3 = R1 * U2;
					const FVector3d Pp(L1 * Pa.X + L2 * Pb.X + L3 * Pc.X, L1 * Pa.Y + L2 * Pb.Y + L3 * Pc.Y, L1 * Pa.Z + L2 * Pb.Z + L3 * Pc.Z);
					FVector3d Ee = Pb - Pa;
					const double Dt = Dot3(Ee, Nrm);
					Ee = FVector3d(Ee.X - Dt * Nrm.X, Ee.Y - Dt * Nrm.Y, Ee.Z - Dt * Nrm.Z);
					const double El = FMath::Max(Norm3(Ee), 1e-12);
					Ee = FVector3d(Ee.X / El, Ee.Y / El, Ee.Z / El);
					const FVector3d F2 = Cross3(Nrm, Ee);
					const double Cr = std::cos(Rot), Sr = std::sin(Rot);
					const FVector3d Tx(Cr * Ee.X + Sr * F2.X, Cr * Ee.Y + Sr * F2.Y, Cr * Ee.Z + Sr * F2.Z);
					const FVector3d Ty = Cross3(Nrm, Tx);
					FStreetInstance In;
					In.Kind = Kind;
					In.Th = Tx; In.N = Ty; In.B = Nrm; In.P = Pp;
					In.Size = Size;
					In.Material = Mat;
					In.SplineId = Sp.Id;
					In.Side = Side;
					Out.Instances.Add(In);
				}
			}
		}
	}
}

// ---------------------------------------------------------------------------------------------------------------
// Junctions - Renderer A's patch (road.py) and Renderer B's corner (edge.py). NO fourth renderer, NO fourth buffer.
// ---------------------------------------------------------------------------------------------------------------

TArray<FVector3d> FStreetRenderBuild::ArmEndRow(const FStreetSamples& Sp, int32 I, bool bReverse)
{
	TArray<double> D, H;
	TArray<FName> Groups;
	int32 NInt = 0, R = 0;
	RibbonRows(Sp, D, H, Groups, NInt, R);
	const FVector3d& Pp = Sp.Frames.P[I];
	const FVector3d& Nn = Sp.Frames.N[I];
	const FVector3d& Bb = Sp.Frames.B[I];
	TArray<FVector3d> Out;
	Out.Reserve(R);
	for (int32 K = 0; K < R; ++K)
	{
		const int32 C = bReverse ? (R - 1 - K) : K;
		const double Dv = D[I * R + C], Hv = H[I * R + C];
		Out.Add(FVector3d(Pp.X + Dv * Nn.X + Hv * Bb.X, Pp.Y + Dv * Nn.Y + Hv * Bb.Y, Pp.Z + Dv * Nn.Z + Hv * Bb.Z));
	}
	return Out;
}

bool FStreetRenderBuild::JunctionBoundary(const FStreetJunctionSpec& Spec, const TMap<FString, const FStreetSamples*>& Splines,
	TArray<FStreetArmFrame>& OutFrames, TArray<FVector3d>& OutLoop, TArray<FIntPoint>& OutArmSlices, TArray<FStreetJunctionCornerSpec>& OutCorners)
{
	OutFrames.Reset(); OutLoop.Reset(); OutArmSlices.Reset(); OutCorners.Reset();
	if (!FStreetJunctionMath::ResolveArmFrames(Spec, Splines, OutFrames)) return false;
	if (!Spec.IsValid()) return false;
	const FStreetJunction* J = &Spec.Junction;
	const FVector2d Node(J->X, J->Y);
	const FStreetJunctionDefaults& Cfg = Spec.Cfg;
	const int32 NA = OutFrames.Num();
	for (int32 K = 0; K < NA; ++K)
	{
		const FStreetArmFrame& Af = OutFrames[K];
		const TArray<FVector3d> Rows = ArmEndRow(*Af.Spline, Af.I, Af.Arm->End != EStreetSplineEnd::Start);
		OutArmSlices.Add(FIntPoint(OutLoop.Num(), OutLoop.Num() + Rows.Num()));
		OutLoop.Append(Rows);
		const FStreetArmFrame& Nx = OutFrames[(K + 1) % NA];
		FStreetJunctionCornerSpec Cs;
		Cs.A = K; Cs.B = (K + 1) % NA;
		if (!FStreetJunctionMath::CornerCurve(Af.PHi, Nx.PLo, FVector2d(-Af.U.X, -Af.U.Y), FVector2d(Nx.U.X, Nx.U.Y), Node,
			Cfg.CornerStepDeg, Spec.CornerHandleFraction(), Cs.P, Cs.T)) return false;
		Cs.Fr = FStreetJunctionMath::CornerFrames(Cs.P, Cs.T, Af.NHi, Nx.NLo);
		const double Ov0 = Af.Spline->OverlapM[Af.I], Ov1 = Nx.Spline->OverlapM[Nx.I];
		const double Sd0 = Af.Spline->SkirtDropM[Af.I], Sd1 = Nx.Spline->SkirtDropM[Nx.I];
		const int32 M = Cs.P.Num();
		Cs.Ov.SetNumUninitialized(M);
		Cs.Sd.SetNumUninitialized(M);
		for (int32 Q = 0; Q < M; ++Q)
		{
			const double T = (M > 1) ? ((Q == M - 1) ? 1.0 : (double)Q * (1.0 / (double)(M - 1))) : 0.0;
			Cs.Ov[Q] = (1.0 - T) * Ov0 + T * Ov1;
			Cs.Sd[Q] = (1.0 - T) * Sd0 + T * Sd1;
		}
		for (int32 Q = 1; Q + 1 < M; ++Q)
		{
			OutLoop.Add(FVector3d(Cs.Fr.P[Q].X - Cs.Ov[Q] * Cs.Fr.N[Q].X - Cs.Sd[Q] * Cs.Fr.B[Q].X,
				Cs.Fr.P[Q].Y - Cs.Ov[Q] * Cs.Fr.N[Q].Y - Cs.Sd[Q] * Cs.Fr.B[Q].Y,
				Cs.Fr.P[Q].Z - Cs.Ov[Q] * Cs.Fr.N[Q].Z - Cs.Sd[Q] * Cs.Fr.B[Q].Z));
		}
		OutCorners.Add(MoveTemp(Cs));
	}
	return true;
}

FStreetJunctionInfo FStreetRenderBuild::BuildJunctionPatch(const FStreetJunctionSpec& Spec,
	const TMap<FString, const FStreetSamples*>& Splines, FStreetMeshBuilder& Buf, const FName* Material)
{
	FStreetJunctionInfo Out;
	TArray<FStreetArmFrame> Frames;
	TArray<FVector3d> Loop;
	TArray<FIntPoint> Slices;
	TArray<FStreetJunctionCornerSpec> Corners;
	if (!JunctionBoundary(Spec, Splines, Frames, Loop, Slices, Corners)) return Out;
	const int32 K = Loop.Num();
	if (K < 3) return Out;
	const FStreetJunction* J = &Spec.Junction;
	double ZApex = -TNumericLimits<double>::Max();
	for (const FStreetArmFrame& Af : Frames) ZApex = FMath::Max(ZApex, Af.Spline->Frames.P[Af.I].Z);
	const FVector3d Centre(J->X, J->Y, ZApex);

	// angular monotonicity about the node: what says whether the fan double-covers anything
	{
		TArray<double> Ang;
		Ang.SetNumUninitialized(K);
		for (int32 Q = 0; Q < K; ++Q) Ang[Q] = std::atan2(Loop[Q].Y - J->Y, Loop[Q].X - J->X);
		double Sum = 0.0;
		bool bAllPos = true;
		for (int32 Q = 0; Q < K; ++Q)
		{
			double St = Ang[(Q + 1) % K] - Ang[Q];
			St = std::fmod(St + kPiD, 2.0 * kPiD);
			if (St < 0.0) St += 2.0 * kPiD;
			St -= kPiD;
			Sum += St;
			bAllPos = bAllPos && (St > 1e-12);
		}
		Out.bMonotone = bAllPos && FMath::Abs(Sum - 2.0 * kPiD) < 1e-6;
	}

	const FName Mat = Material ? *Material : Frames[0].Spline->SurfaceMaterial[Frames[0].I];
	const int32 Gid = Buf.GroupId(FName(*FString::Printf(TEXT("junction:%s"), *Spec.Junction.Id)));
	const int32 Mid = Buf.MaterialId(Mat);
	TArray<FVector3d> V;
	V.Reserve(K + 1);
	V.Add(Centre);
	V.Append(Loop);
	TArray<FVector2d> Uv;
	TArray<double> Vs, Vd, Vh;
	const double SOwner = Frames[0].Spline->S[Frames[0].I];
	Uv.SetNumUninitialized(V.Num()); Vs.SetNumUninitialized(V.Num()); Vd.Init(0.0, V.Num()); Vh.Init(0.0, V.Num());
	for (int32 Q = 0; Q < V.Num(); ++Q) { Uv[Q] = FVector2d(V[Q].X - J->X, V[Q].Y - J->Y); Vs[Q] = SOwner; }
	const int32 First = Buf.AppendVertices(V, Uv, Vs, Vd, Vh);

	// plan areas of what is actually emitted: the boundary's own area is the shoelace of the loop, so the excess is
	// the area some triangle covers twice (0 when nothing is inverted)
	double SumAbs = 0.0, Shoe = 0.0;
	for (int32 Q = 0; Q < K; ++Q)
	{
		const FVector3d& A1 = Loop[Q];
		const FVector3d& A2 = Loop[(Q + 1) % K];
		SumAbs += FMath::Abs(0.5 * ((A1.X - Centre.X) * (A2.Y - Centre.Y) - (A2.X - Centre.X) * (A1.Y - Centre.Y)));
		Shoe += Loop[Q].X * Loop[(Q + 1) % K].Y - Loop[(Q + 1) % K].X * Loop[Q].Y;
	}
	Shoe *= 0.5;
	Out.AreaM2 = FMath::Abs(Shoe);
	Out.OverlapAreaM2 = FMath::Max(0.0, SumAbs - FMath::Abs(Shoe));

	TArray<UE::Geometry::FIndex3i> Tris;
	Tris.Reserve(K);
	for (int32 Q = 0; Q < K; ++Q)
	{
		int32 Ia = First, Ib = First + 1 + Q, Ic = First + 1 + ((Q + 1) % K);
		const FVector3d& Pa = Buf.V[Ia];
		const FVector3d& Pb = Buf.V[Ib];
		const FVector3d& Pc = Buf.V[Ic];
		const FVector3d Fn = Cross3(FVector3d(Pb.X - Pa.X, Pb.Y - Pa.Y, Pb.Z - Pa.Z), FVector3d(Pc.X - Pa.X, Pc.Y - Pa.Y, Pc.Z - Pa.Z));
		if (Fn.Z < 0) Swap(Ib, Ic);
		if (0.5 * Norm3(Fn) < 1e-10) continue;
		Tris.Add(UE::Geometry::FIndex3i(Ia, Ib, Ic));
	}
	Buf.AppendTriangles(Tris, Mid, Gid);
	Out.bBuilt = true;
	Out.Verts = V.Num();
	Out.Tris = Tris.Num();
	Out.Arms = Frames.Num();
	Out.Boundary = K;
	Out.TrimRadiusM = Spec.TrimRadiusM;
	Out.ZApex = ZApex;
	return Out;
}

bool FStreetRenderBuild::JunctionSurface(const FStreetJunctionSpec& Spec, const TMap<FString, const FStreetSamples*>& Splines,
	TArray<FVector3d>& OutLoop, FVector3d& OutApex)
{
	TArray<FStreetArmFrame> Frames;
	TArray<FIntPoint> Slices;
	TArray<FStreetJunctionCornerSpec> Corners;
	if (!JunctionBoundary(Spec, Splines, Frames, OutLoop, Slices, Corners)) return false;
	if (OutLoop.Num() < 3) return false;
	const FStreetJunction* J = &Spec.Junction;
	double ZApex = -TNumericLimits<double>::Max();
	for (const FStreetArmFrame& Af : Frames) ZApex = FMath::Max(ZApex, Af.Spline->Frames.P[Af.I].Z);
	OutApex = FVector3d(J->X, J->Y, ZApex);
	return true;
}

double FStreetRenderBuild::JunctionTargetZ(const TArray<FVector3d>& Loop, const FVector3d& Apex, double X, double Y)
{
	const int32 K = Loop.Num();
	const double Ax = Apex.X, Ay = Apex.Y, Az = Apex.Z;
	for (int32 Q = 0; Q < K; ++Q)
	{
		const FVector3d& B = Loop[Q];
		const FVector3d& C = Loop[(Q + 1) % K];
		const double Det = (B.Y - C.Y) * (Ax - C.X) + (C.X - B.X) * (Ay - C.Y);
		if (FMath::Abs(Det) < 1e-18) continue;
		const double L1 = ((B.Y - C.Y) * (X - C.X) + (C.X - B.X) * (Y - C.Y)) / Det;
		const double L2 = ((C.Y - Ay) * (X - C.X) + (Ax - C.X) * (Y - C.Y)) / Det;
		const double L3 = 1.0 - L1 - L2;
		if (L1 >= -1e-9 && L2 >= -1e-9 && L3 >= -1e-9) return L1 * Az + L2 * B.Z + L3 * C.Z;
	}
	return NAN;
}

FStreetJunctionInfo FStreetRenderBuild::BuildJunctionCorners(const FStreetJunctionSpec& Spec,
	const TMap<FString, const FStreetSamples*>& Splines, FStreetMeshBuilder& Buf)
{
	FStreetJunctionInfo Out;
	TArray<FStreetArmFrame> Frames;
	if (!FStreetJunctionMath::ResolveArmFrames(Spec, Splines, Frames)) return Out;
	if (!Spec.IsValid()) return Out;
	const FStreetJunction* J = &Spec.Junction;
	const FVector2d Node(J->X, J->Y);
	const FStreetJunctionDefaults& Cfg = Spec.Cfg;
	const int32 V0 = Buf.V.Num(), T0 = Buf.F.Num();
	const int32 NA = Frames.Num();
	for (int32 K = 0; K < NA; ++K)
	{
		const FStreetArmFrame& Af = Frames[K];
		const FStreetArmFrame& Nx = Frames[(K + 1) % NA];
		const FStreetSideSpec* Sa = &Af.Spline->SideSpec[StreetSideIndex(Af.SideHi)];
		int32 Ia = Af.I;
		const FStreetSideSpec* Sb = &Nx.Spline->SideSpec[StreetSideIndex(Nx.SideLo)];
		int32 Ib = Nx.I;
		const bool bUseA = Sa->bHasKerbOrPavement && Sa->Present[Ia];
		const bool bUseB = Sb->bHasKerbOrPavement && Sb->Present[Ib];
		if (!bUseA && !bUseB) { ++Out.CornersSkippedNoKerb; continue; }
		// one arm kerbed and the other not (a footway meeting a street): run THAT arm's section round the corner
		// unchanged and cap the far end, rather than leaving the kerb hanging at the trim
		bool bCapStart = false, bCapEnd = false;
		if (!bUseB) { Sb = Sa; Ib = Ia; bCapEnd = true; }
		else if (!bUseA) { Sa = Sb; Ia = Ib; bCapStart = true; }
		if (Sa->ArcPoints != Sb->ArcPoints) { ++Out.CornersSkippedIncompatible; continue; }

		TArray<FVector3d> P, T;
		if (!FStreetJunctionMath::CornerCurve(Af.PHi, Nx.PLo, FVector2d(-Af.U.X, -Af.U.Y), FVector2d(Nx.U.X, Nx.U.Y), Node,
			Cfg.CornerStepDeg, Spec.CornerHandleFraction(), P, T)) return Out;
		FStreetFrames Fr = FStreetJunctionMath::CornerFrames(P, T, Af.NHi, Nx.NLo);
		const double SBase = Af.Spline->S[Af.I];       // UV u keeps running in metres across the join
		for (int32 Q = 0; Q < Fr.S.Num(); ++Q) Fr.S[Q] += SBase;
		const int32 M = P.Num();
		TArray<double> Tt;
		Tt.SetNumUninitialized(M);
		for (int32 Q = 0; Q < M; ++Q) Tt[Q] = (M > 1) ? ((Q == M - 1) ? 1.0 : (double)Q * (1.0 / (double)(M - 1))) : 0.0;
		auto Lerp = [&Tt, M](const TArray<double>& Va, int32 A, const TArray<double>& Vb, int32 B)
		{
			TArray<double> R;
			R.SetNumUninitialized(M);
			for (int32 Q = 0; Q < M; ++Q) R[Q] = (1.0 - Tt[Q]) * Va[A] + Tt[Q] * Vb[B];
			return R;
		};
		const double FracA = Sa->Split[Ia] ? Sa->SplitFrac[Ia] : 0.5;
		const double FracB = Sb->Split[Ib] ? Sb->SplitFrac[Ib] : 0.5;
		TArray<double> FracArr;
		FracArr.SetNumUninitialized(M);
		for (int32 Q = 0; Q < M; ++Q) FracArr[Q] = (1.0 - Tt[Q]) * FracA + Tt[Q] * FracB;
		const int32 Mp = Sa->ArcPoints;
		const int32 Half = M / 2;
		TArray<EStreetLipKind> LipKind;
		LipKind.SetNumUninitialized(M);
		for (int32 Q = 0; Q < M; ++Q) LipKind[Q] = (Q < Half) ? Sa->LipKind[Ia] : Sb->LipKind[Ib];
		TArray<double> O, Hh;
		KerbColumns(Lerp(Sa->KerbWidth, Ia, Sb->KerbWidth, Ib), Lerp(Sa->Hk, Ia, Sb->Hk, Ib), Lerp(Sa->LipR, Ia, Sb->LipR, Ib),
			Lerp(Sa->PavementWidth, Ia, Sb->PavementWidth, Ib), Lerp(Sa->HkBack, Ia, Sb->HkBack, Ib),
			Lerp(Sa->TuckIn, Ia, Sb->TuckIn, Ib), Lerp(Sa->TuckDepth, Ia, Sb->TuckDepth, Ib),
			Lerp(Sa->Skirt, Ia, Sb->Skirt, Ib), FracArr, LipKind, Mp, O, Hh);
		const int32 Pp = 3 + Mp + 5;
		const int32 E = Pp - 1;
		TArray<bool> Smooth;
		TArray<FName> Groups;
		int32 NInner = 0;
		KerbLayout(Mp, Smooth, Groups, NInner);
		TArray<FName> Mats;
		Mats.SetNumUninitialized(M * E);
		for (int32 Row = 0; Row < M; ++Row)
		{
			const FStreetSideSpec* Spec = (Row < Half) ? Sa : Sb;
			const int32 Idx = (Row < Half) ? Ia : Ib;
			const bool bSplit = Spec->Split[Idx];
			const FName Inner = Spec->MatInner[Idx];
			FName* Mr = &Mats[Row * E];
			for (int32 C = 0; C <= NInner; ++C) Mr[C] = Inner;
			Mr[NInner + 1] = bSplit ? Spec->MatOuter[Idx] : Spec->MatKerb[Idx];
			const FName Pav = bSplit ? Spec->MatOuter[Idx] : Spec->MatPavement[Idx];
			Mr[NInner + 2] = Pav;
			Mr[NInner + 3] = Pav;
		}
		FStreetSection Section;
		Section.bClosed = false;
		double Vv = 0.0;
		for (int32 C = 0; C < Pp; ++C)
		{
			if (C > 0) Vv += std::hypot(O[C] - O[C - 1], Hh[C] - Hh[C - 1]);
			FStreetSectionPoint Pt;
			Pt.O = O[C]; Pt.H = Hh[C]; Pt.Mat = Mats[FMath::Min(C, E - 1)]; Pt.V = Vv; Pt.bSmooth = Smooth[C];
			Section.Points.Add(Pt);
		}
		TArray<FName> GNames;
		for (const FName& G : Groups) GNames.Add(FName(*FString::Printf(TEXT("corner_%s:%s:%d"), *G.ToString(), *Spec.Junction.Id, K)));
		FStreetSweepParams Pr;
		Pr.Side = -1;
		Pr.LateralScalar = 0.0;
		Pr.HeightScalar = 0.0;
		Pr.PointO = O;
		Pr.PointH = Hh;
		Pr.bCapStart = bCapStart;
		Pr.bCapEnd = bCapEnd;
		Pr.Groups = GNames;
		Pr.EdgeMatStation = Mats;
		FStreetSweep::Sweep(Buf, Section, Fr, Pr);
		++Out.Corners;
	}
	Out.CornerVerts = Buf.V.Num() - V0;
	Out.CornerTris = Buf.F.Num() - T0;
	return Out;
}

// ---------------------------------------------------------------------------------------------------------------
// The components
// ---------------------------------------------------------------------------------------------------------------

UStreetRendererBase::UStreetRendererBase()
{
	PrimaryComponentTick.bCanEverTick = false;
	SetMobility(EComponentMobility::Static);
	bUseAsyncCooking = false;
}

void UStreetRendererBase::Commit(const FStreetRenderResult& In, const UStreetMaterialTable* Materials)
{
	const double T0 = FPlatformTime::Seconds();
	FDynamicMesh3 Mesh;
	FStreetGeometry::ToDynamicMesh(In.Buffer, Mesh);
	SetMesh(MoveTemp(Mesh));
	MaterialSlotIds = In.Buffer.MaterialNames;
	if (!Materials && MaterialSlotIds.Num())
	{
		// every slot would fall back to WorldGridMaterial, which is invisible in the stats and obvious in a render
		UE_LOG(LogStreetscape, Warning, TEXT("%s: no UStreetMaterialTable on the site actor - %d material slots left unset"),
			*GetPathName(), MaterialSlotIds.Num());
	}
	TArray<UMaterialInterface*> Mats;
	for (FName Nm : MaterialSlotIds) Mats.Add(Materials ? Materials->Resolve(Nm) : nullptr);
	ConfigureMaterialSet(Mats);
	SetTangentsType(EDynamicMeshComponentTangentsMode::AutoCalculated);
	SetMeshDrawPath(EDynamicMeshDrawPath::StaticDraw);
	ApplyCollision();
	Stats = In.Buffer.Stats();
	LastVertexCount = Stats.Verts;
	LastTriangleCount = Stats.Tris;
	Instances = In.Instances;
	LastBuffer = In.Buffer;
	MarkingStrips = In.MarkingStrips;
	Stash.Reset();
	LastBuildMs = (FPlatformTime::Seconds() - T0) * 1000.0;
}

void UStreetRendererBase::Clear()
{
	GetDynamicMesh()->Reset();
	Stats = FStreetBuildStats();
	LastVertexCount = 0;
	LastTriangleCount = 0;
	Instances.Reset();
	LastBuffer = FStreetMeshBuilder();
	MarkingStrips = 0;
}

void UStreetRendererBase::Rebuild()
{
	if (AStreetscapeActor* Actor = Cast<AStreetscapeActor>(GetOwner()))
	{
		Actor->RebuildAll();
	}
}

void UStreetRendererBase::OnRegister()
{
	Super::OnRegister();
	if (bRebuildOnLoad && GetDynamicMesh() && GetDynamicMesh()->IsEmpty())
	{
		if (AStreetscapeActor* Actor = Cast<AStreetscapeActor>(GetOwner()))
		{
			Actor->RequestRebuildOnRegister();
		}
	}
}

void UStreetRendererBase::PreSave(FObjectPreSaveContext ObjectSaveContext)
{
	if (bRebuildOnLoad && !ObjectSaveContext.IsCooking() && !ObjectSaveContext.IsProceduralSave() && GetDynamicMesh() && !GetDynamicMesh()->IsEmpty())
	{
		Stash = GetDynamicMesh()->ExtractMesh();
		GetDynamicMesh()->Reset();
	}
	Super::PreSave(ObjectSaveContext);
}

void UStreetRendererBase::RestoreAfterSave()
{
	if (Stash.IsValid())
	{
		SetMesh(MoveTemp(*Stash));
		Stash.Reset();
		ApplyCollision();
	}
}

void UStreetRendererBase::ApplyCollision()
{
	// UDynamicMeshComponent's constructor sets UCollisionProfile::NoCollision_ProfileName
	// (GeometryFramework/Private/Components/DynamicMeshComponent.cpp:92). SetComplexAsSimpleCollisionEnabled only
	// says WHICH geometry the body uses; without a profile that queries, the cooked triangle mesh is unreachable
	// and a downward line trace over a finished road hits the landscape underneath it.
	SetComplexAsSimpleCollisionEnabled(bCollision, true);          // GeometryFramework/DynamicMeshComponent.h:722
	SetCollisionProfileName(bCollision ? UCollisionProfile::BlockAll_ProfileName : UCollisionProfile::NoCollision_ProfileName);
	SetCollisionEnabled(bCollision ? ECollisionEnabled::QueryAndPhysics : ECollisionEnabled::NoCollision);
}

void UStreetRoadRenderer::BuildFrom(const FStreetSamples& Samples, const IStreetTerrainSource* Terrain, FStreetRenderResult& Out) const
{
	FStreetRenderBuild::BuildRoad(Samples, Out);
}

void UStreetEdgeRenderer::BuildFrom(const FStreetSamples& Samples, const IStreetTerrainSource* Terrain, FStreetRenderResult& Out) const
{
	FStreetRenderBuild::BuildEdge(Samples, Side, Terrain, Out);
}

void UStreetHedgeRenderer::BuildFrom(const FStreetSamples& Samples, const IStreetTerrainSource* Terrain, FStreetRenderResult& Out) const
{
	FStreetRenderBuild::BuildHedge(Samples, Side, Out);
}
