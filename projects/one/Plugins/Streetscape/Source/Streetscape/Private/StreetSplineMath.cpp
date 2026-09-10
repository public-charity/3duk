#include "StreetSplineMath.h"
#include "StreetTerrainSource.h"
#include "StreetscapeJson.h"
#include "Dom/JsonObject.h"
#include <cmath>

namespace
{
constexpr double kPi = 3.141592653589793;
const FVector3d ZAxis(0.0, 0.0, 1.0);

FVector3d Cross3(const FVector3d& A, const FVector3d& B)
{
	// np.cross
	return FVector3d(A.Y * B.Z - A.Z * B.Y, A.Z * B.X - A.X * B.Z, A.X * B.Y - A.Y * B.X);
}

double PairwiseSum(const double* A, int32 N)
{
	if (N < 8)
	{
		double Res = 0.0;
		for (int32 I = 0; I < N; ++I) Res += A[I];
		return Res;
	}
	if (N <= 128)
	{
		double R[8];
		for (int32 J = 0; J < 8; ++J) R[J] = A[J];
		int32 I = 8;
		for (; I < N - (N % 8); I += 8)
		{
			for (int32 J = 0; J < 8; ++J) R[J] += A[I + J];
		}
		double Res = ((R[0] + R[1]) + (R[2] + R[3])) + ((R[4] + R[5]) + (R[6] + R[7]));
		for (; I < N; ++I) Res += A[I];
		return Res;
	}
	int32 N2 = N / 2;
	N2 -= N2 % 8;
	return PairwiseSum(A, N2) + PairwiseSum(A + N2, N - N2);
}
}

// ---------------------------------------------------------------------------------------------------------------
// primitives
// ---------------------------------------------------------------------------------------------------------------

double FStreetSplineMath::Hypot(double X, double Y) { return std::hypot(X, Y); }

double FStreetSplineMath::NumpySum(TConstArrayView<double> A) { return PairwiseSum(A.GetData(), A.Num()); }

int32 FStreetSplineMath::SearchSortedRight(TConstArrayView<double> A, double V)
{
	int32 Lo = 0, Hi = A.Num();
	while (Lo < Hi)
	{
		const int32 Mid = (Lo + Hi) / 2;
		if (A[Mid] <= V) Lo = Mid + 1; else Hi = Mid;
	}
	return Lo;
}

int32 FStreetSplineMath::SearchSortedLeft(TConstArrayView<double> A, double V)
{
	int32 Lo = 0, Hi = A.Num();
	while (Lo < Hi)
	{
		const int32 Mid = (Lo + Hi) / 2;
		if (A[Mid] < V) Lo = Mid + 1; else Hi = Mid;
	}
	return Lo;
}

double FStreetSplineMath::Interp(double X, TConstArrayView<double> XP, TConstArrayView<double> FP)
{
	const int32 N = XP.Num();
	check(N == FP.Num() && N > 0);
	if (N == 1 || X <= XP[0]) return FP[0];
	if (X >= XP[N - 1]) return FP[N - 1];
	const int32 J = SearchSortedRight(XP, X) - 1;
	const double Slope = (FP[J + 1] - FP[J]) / (XP[J + 1] - XP[J]);
	double R = Slope * (X - XP[J]) + FP[J];
	if (std::isnan(R))
	{
		R = Slope * (X - XP[J + 1]) + FP[J + 1];
		if (std::isnan(R) && FP[J] == FP[J + 1]) R = FP[J];
	}
	return R;
}

FVector3d FStreetSplineMath::Unit3(const FVector3d& V)
{
	double N = std::sqrt((V.X * V.X + V.Y * V.Y) + V.Z * V.Z);
	if (N == 0.0) N = 1.0;
	return FVector3d(V.X / N, V.Y / N, V.Z / N);
}

FVector2d FStreetSplineMath::Unit2(const FVector2d& V)
{
	double N = std::sqrt(V.X * V.X + V.Y * V.Y);
	if (N == 0.0) N = 1.0;
	return FVector2d(V.X / N, V.Y / N);
}

TArray<double> FStreetSplineMath::Gradient(TConstArrayView<double> F)
{
	const int32 N = F.Num();
	TArray<double> G;
	G.SetNumUninitialized(N);
	if (N == 1) { G[0] = 0.0; return G; }
	for (int32 I = 1; I + 1 < N; ++I) G[I] = (F[I + 1] - F[I - 1]) / 2.0;
	G[0] = (F[1] - F[0]) / 1.0;
	G[N - 1] = (F[N - 1] - F[N - 2]) / 1.0;
	return G;
}

// ---------------------------------------------------------------------------------------------------------------
// spline.py
// ---------------------------------------------------------------------------------------------------------------

int32 FStreetSplineMath::MergePoints(const TArray<FStreetPoint>& In, TArray<FStreetPoint>& Out, double Tol)
{
	Out.Reset();
	int32 Merged = 0;
	for (const FStreetPoint& P : In)
	{
		if (Out.Num() > 0 && Hypot(P.X - Out.Last().X, P.Y - Out.Last().Y) < Tol)
		{
			FStreetPoint& Q = Out.Last();
			FStreetPoint M;
			M.X = P.X; M.Y = P.Y;
			M.Z = P.Z.IsSet() ? P.Z : Q.Z;
			M.RollDeg = P.RollDeg.IsSet() ? P.RollDeg : Q.RollDeg;
			M.WidthM = P.WidthM.IsSet() ? P.WidthM : Q.WidthM;
			M.Tags = Q.Tags;
			for (const FString& T : P.Tags) M.Tags.AddUnique(T);
			Q = M;
			++Merged;
		}
		else
		{
			FStreetPoint C;
			C.X = P.X; C.Y = P.Y; C.Z = P.Z; C.RollDeg = P.RollDeg; C.WidthM = P.WidthM; C.Tags = P.Tags;
			Out.Add(C);
		}
	}
	return Merged;
}

bool FStreetSplineMath::CatmullRomDense(const TArray<FVector2d>& P, TArray<double>& OutSD, TArray<FVector2d>& OutXYD, TArray<double>& OutSKnots, double Alpha, double MaxChordM)
{
	const int32 K = P.Num();
	OutSD.Reset(); OutXYD.Reset(); OutSKnots.Reset();
	if (K < 2) return false;
	if (K == 2)
	{
		const double Chord = Hypot(P[1].X - P[0].X, P[1].Y - P[0].Y);
		const int32 N = FMath::Max(8, (int32)std::ceil(Chord / MaxChordM)) + 1;
		const double Step = 1.0 / (double)(N - 1);
		OutXYD.SetNum(N);
		const FVector2d D = P[1] - P[0];
		for (int32 I = 0; I < N; ++I)
		{
			const double T = (I == N - 1) ? 1.0 : (double)I * Step + 0.0;
			OutXYD[I] = FVector2d(P[0].X + T * D.X, P[0].Y + T * D.Y);
		}
		OutSD.SetNum(N);
		OutSD[0] = 0.0;
		for (int32 I = 1; I < N; ++I) OutSD[I] = OutSD[I - 1] + Hypot(OutXYD[I].X - OutXYD[I - 1].X, OutXYD[I].Y - OutXYD[I - 1].Y);
		OutSKnots = { 0.0, OutSD.Last() };
		return true;
	}
	TArray<FVector2d> Ext;
	Ext.Reserve(K + 2);
	Ext.Add(FVector2d(2.0 * P[0].X - P[1].X, 2.0 * P[0].Y - P[1].Y));
	Ext.Append(P);
	Ext.Add(FVector2d(2.0 * P[K - 1].X - P[K - 2].X, 2.0 * P[K - 1].Y - P[K - 2].Y));
	TArray<double> Knots = { 0.0 };
	double Total = 0.0;
	for (int32 I = 0; I < K - 1; ++I)
	{
		const FVector2d& P0 = Ext[I];
		const FVector2d& P1 = Ext[I + 1];
		const FVector2d& P2 = Ext[I + 2];
		const FVector2d& P3 = Ext[I + 3];
		const double Chord = Hypot(P2.X - P1.X, P2.Y - P1.Y);
		const int32 N = FMath::Max(8, (int32)std::ceil(Chord / MaxChordM)) + 1;
		const double T0 = 0.0;
		const double T1 = T0 + std::pow(Hypot(P1.X - P0.X, P1.Y - P0.Y), Alpha);
		const double T2 = T1 + std::pow(Chord, Alpha);
		const double T3 = T2 + std::pow(Hypot(P3.X - P2.X, P3.Y - P2.Y), Alpha);
		const double Step = (T2 - T1) / (double)(N - 1);
		TArray<FVector2d> C;
		C.SetNum(N);
		for (int32 J = 0; J < N; ++J)
		{
			const double T = (J == N - 1) ? T2 : (double)J * Step + T1;
			FVector2d Cc;
			for (int32 Ax = 0; Ax < 2; ++Ax)
			{
				const double p0 = P0[Ax], p1 = P1[Ax], p2 = P2[Ax], p3 = P3[Ax];
				const double a1 = (T1 - T) / (T1 - T0) * p0 + (T - T0) / (T1 - T0) * p1;
				const double a2 = (T2 - T) / (T2 - T1) * p1 + (T - T1) / (T2 - T1) * p2;
				const double a3 = (T3 - T) / (T3 - T2) * p2 + (T - T2) / (T3 - T2) * p3;
				const double b1 = (T2 - T) / (T2 - T0) * a1 + (T - T0) / (T2 - T0) * a2;
				const double b2 = (T3 - T) / (T3 - T1) * a2 + (T - T1) / (T3 - T1) * a3;
				Cc[Ax] = (T2 - T) / (T2 - T1) * b1 + (T - T1) / (T2 - T1) * b2;
			}
			C[J] = Cc;
		}
		C[0] = P1;
		C[N - 1] = P2;
		TArray<double> Seg;
		Seg.SetNum(N - 1);
		for (int32 J = 0; J + 1 < N; ++J) Seg[J] = Hypot(C[J + 1].X - C[J].X, C[J + 1].Y - C[J].Y);
		Total += NumpySum(Seg);
		Knots.Add(Total);
		if (I == 0) OutXYD.Append(C);
		else for (int32 J = 1; J < N; ++J) OutXYD.Add(C[J]);
	}
	const int32 D = OutXYD.Num();
	OutSD.SetNum(D);
	OutSD[0] = 0.0;
	for (int32 I = 1; I < D; ++I) OutSD[I] = OutSD[I - 1] + Hypot(OutXYD[I].X - OutXYD[I - 1].X, OutXYD[I].Y - OutXYD[I - 1].Y);
	Knots.Last() = OutSD.Last();
	OutSKnots = Knots;
	return true;
}

TArray<FVector2d> FStreetSplineMath::DenseTangents(const TArray<FVector2d>& XY)
{
	const int32 N = XY.Num();
	TArray<double> X, Y;
	X.SetNum(N); Y.SetNum(N);
	for (int32 I = 0; I < N; ++I) { X[I] = XY[I].X; Y[I] = XY[I].Y; }
	const TArray<double> Dx = Gradient(X), Dy = Gradient(Y);
	TArray<FVector2d> T;
	T.SetNum(N);
	for (int32 I = 0; I < N; ++I)
	{
		double Nn = Hypot(Dx[I], Dy[I]);
		if (Nn == 0.0) Nn = 1.0;
		T[I] = FVector2d(Dx[I] / Nn, Dy[I] / Nn);
	}
	return T;
}

void FStreetSplineMath::DenseCurvature(const TArray<double>& SD, const TArray<FVector2d>& XYD, TArray<double>& OutKappaAbs, TArray<double>& OutKappaSigned)
{
	const TArray<FVector2d> T = DenseTangents(XYD);
	const int32 N = T.Num();
	TArray<double> Tx, Ty;
	Tx.SetNum(N); Ty.SetNum(N);
	for (int32 I = 0; I < N; ++I) { Tx[I] = T[I].X; Ty[I] = T[I].Y; }
	const TArray<double> DTx = Gradient(Tx), DTy = Gradient(Ty);
	TArray<double> Ds = Gradient(SD);
	OutKappaAbs.SetNum(N); OutKappaSigned.SetNum(N);
	for (int32 I = 0; I < N; ++I)
	{
		if (Ds[I] == 0.0) Ds[I] = 1e-12;
		const double Kappa = Hypot(DTx[I], DTy[I]) / Ds[I];
		const double Cross = Tx[I] * DTy[I] - Ty[I] * DTx[I];
		OutKappaAbs[I] = Kappa;
		OutKappaSigned[I] = Cross >= 0 ? Kappa : -Kappa;
	}
}

double FStreetSplineMath::StepFor(double Kappa, const FStreetSamplingResolved& Sampling)
{
	return FMath::Min(FMath::Max(Sampling.StepM / (1.0 + Sampling.CurvatureGain * Kappa), Sampling.MinStepM), Sampling.StepM);
}

TArray<double> FStreetSplineMath::AdaptiveStations(const TArray<double>& SD, const TArray<double>& KappaD, const FStreetSamplingResolved& Sampling, const TArray<double>& Mandatory)
{
	const double L = SD.Last();
	const double MinStep = Sampling.MinStepM;
	auto StepAt = [&](double S) { return StepFor(Interp(S, SD, KappaD), Sampling); };
	TArray<double> Adaptive = { 0.0 };
	double S = 0.0;
	while (S + StepAt(S) < L - MinStep)
	{
		S += StepAt(S);
		Adaptive.Add(S);
	}
	Adaptive.Add(L);
	TArray<double> Mand;
	for (double M : Mandatory) { if (0.0 < M && M < L) Mand.Add(M); }
	Mand.Sort();
	TArray<double> Md;
	for (double M : Mand)
	{
		if (Md.Num() == 0 || M - Md.Last() > 1e-9) Md.Add(M);
		else if (Md.Num() > 0 && M == Md.Last()) {}   // python set already removed exact duplicates
	}
	Mand = Md;
	if (Mand.Num() > 0)
	{
		TArray<double> Keep;
		for (double A : Adaptive)
		{
			const int32 J = SearchSortedLeft(Mand, A);
			bool bNear = false;
			for (int32 JJ = J - 1; JJ <= J; ++JJ)
			{
				if (JJ >= 0 && JJ < Mand.Num() && FMath::Abs(A - Mand[JJ]) <= MinStep / 2 + 1e-12) bNear = true;
			}
			if (!bNear) Keep.Add(A);
		}
		Adaptive = Keep;
	}
	TArray<double> St = Adaptive;
	St.Append(Mand);
	St.Sort();
	TArray<double> U;
	for (double X : St) { if (U.Num() == 0 || U.Last() != X) U.Add(X); }
	if (U.Num() == 0 || U[0] != 0.0) U.Insert(0.0, 0);
	if (U.Last() != L) U.Add(L);
	return U;
}

TArray<double> FStreetSplineMath::FillNanAlong(const TArray<double>& Z, bool& bOutAllNan)
{
	const int32 N = Z.Num();
	TArray<double> Out;
	Out.SetNum(N);
	int32 First = -1;
	for (int32 I = 0; I < N; ++I) { if (std::isfinite(Z[I])) { First = I; break; } }
	if (First < 0)
	{
		for (int32 I = 0; I < N; ++I) Out[I] = 0.0;
		bOutAllNan = true;
		return Out;
	}
	bOutAllNan = false;
	int32 Last = -1;
	for (int32 I = 0; I < N; ++I)
	{
		if (std::isfinite(Z[I])) Last = I;
		Out[I] = Z[Last >= 0 ? Last : First];
	}
	return Out;
}

TArray<double> FStreetSplineMath::MovingAverageArcLength(const TArray<double>& S, const TArray<double>& InZ, double W, int32 Passes)
{
	TArray<double> Z = InZ;
	const int32 N = S.Num();
	if (Passes <= 0 || W <= 0 || N < 3) return Z;
	TArray<double> Hw, A, B;
	TArray<int32> Ka, Kb;
	Hw.SetNum(N); A.SetNum(N); B.SetNum(N); Ka.SetNum(N); Kb.SetNum(N);
	for (int32 I = 0; I < N; ++I)
	{
		Hw[I] = FMath::Min(FMath::Min(W / 2.0, S[I] - S[0]), S[N - 1] - S[I]);
		A[I] = S[I] - Hw[I];
		B[I] = S[I] + Hw[I];
		Ka[I] = FMath::Clamp(SearchSortedRight(S, A[I]) - 1, 0, N - 2);
		Kb[I] = FMath::Clamp(SearchSortedRight(S, B[I]) - 1, 0, N - 2);
	}
	TArray<double> Ds;
	Ds.SetNum(N - 1);
	for (int32 I = 0; I + 1 < N; ++I) Ds[I] = S[I + 1] - S[I];
	TArray<double> C;
	C.SetNum(N);
	for (int32 Pass = 0; Pass < Passes; ++Pass)
	{
		C[0] = 0.0;
		for (int32 K = 0; K + 1 < N; ++K)
		{
			const double Seg = 0.5 * (Z[K + 1] + Z[K]) * Ds[K];
			C[K + 1] = C[K] + Seg;
		}
		auto CumAt = [&](double X, int32 K)
		{
			const double Zx = Z[K] + (Z[K + 1] - Z[K]) * (X - S[K]) / Ds[K];
			return C[K] + (X - S[K]) * 0.5 * (Z[K] + Zx);
		};
		TArray<double> Out;
		Out.SetNum(N);
		for (int32 I = 0; I < N; ++I)
		{
			const double Ia = CumAt(A[I], Ka[I]);
			const double Ib = CumAt(B[I], Kb[I]);
			const double Width = B[I] - A[I];
			Out[I] = Width > 1e-12 ? (Ib - Ia) / Width : Z[I];
		}
		Z = Out;
	}
	return Z;
}

TArray<double> FStreetSplineMath::ApplyPins(const TArray<double>& InZ, const TArray<double>& S, const TArray<TPair<double, double>>& Pins, double Blend)
{
	TArray<double> Z = InZ;
	for (const TPair<double, double>& Pin : Pins)
	{
		const double ZAt = Interp(Pin.Key, S, Z);
		for (int32 I = 0; I < S.Num(); ++I)
		{
			const double Wt = FMath::Max(0.0, 1.0 - FMath::Abs(S[I] - Pin.Key) / Blend);
			Z[I] = Z[I] + (Pin.Value - ZAt) * Wt;
		}
	}
	return Z;
}

TArray<double> FStreetSplineMath::RateLimitBank(const TArray<double>& Beta, const TArray<double>& S, double R)
{
	TArray<double> B = Beta;
	const int32 N = B.Num();
	if (R <= 0 || N < 2) return B;
	for (int32 I = 1; I < N; ++I)
	{
		const double Lim = R * (S[I] - S[I - 1]);
		B[I] = FMath::Min(FMath::Max(B[I], B[I - 1] - Lim), B[I - 1] + Lim);
	}
	for (int32 I = N - 2; I >= 0; --I)
	{
		const double Lim = R * (S[I + 1] - S[I]);
		B[I] = FMath::Min(FMath::Max(B[I], B[I + 1] - Lim), B[I + 1] + Lim);
	}
	return B;
}

// ---------------------------------------------------------------------------------------------------------------
// FStreetFrames
// ---------------------------------------------------------------------------------------------------------------

FStreetFrames FStreetFrames::Build(const TArray<double>& InS, const TArray<FVector3d>& InP, const TArray<FVector3d>& InTh, const TArray<double>& BankDeg)
{
	FStreetFrames F;
	const int32 N = InS.Num();
	F.S = InS;
	F.P = InP;
	F.Th.SetNum(N); F.NFlat.SetNum(N); F.N.SetNum(N); F.B.SetNum(N);
	for (int32 I = 0; I < N; ++I)
	{
		const FVector3d Th = FStreetSplineMath::Unit3(InTh[I]);
		F.Th[I] = Th;
		const FVector3d NFlat(-Th.Y, Th.X, 0.0);
		F.NFlat[I] = NFlat;
		const double Beta = BankDeg[I] * (kPi / 180.0);
		const double Cb = std::cos(Beta), Sb = std::sin(Beta);
		const FVector3d Nn(NFlat.X * Cb + ZAxis.X * Sb, NFlat.Y * Cb + ZAxis.Y * Sb, NFlat.Z * Cb + ZAxis.Z * Sb);
		F.N[I] = Nn;
		F.B[I] = Cross3(Th, Nn);
	}
	return F;
}

FStreetFrames FStreetFrames::At(TConstArrayView<double> SQuery) const
{
	FStreetFrames F;
	const int32 M = SQuery.Num();
	F.S = TArray<double>(SQuery.GetData(), M);
	F.P.SetNum(M); F.Th.SetNum(M); F.NFlat.SetNum(M); F.N.SetNum(M); F.B.SetNum(M);
	TArray<double> Px, Py, Pz, Tx, Ty, Tz, Nx, Ny, Nz;
	const int32 Ns = S.Num();
	Px.SetNum(Ns); Py.SetNum(Ns); Pz.SetNum(Ns); Tx.SetNum(Ns); Ty.SetNum(Ns); Tz.SetNum(Ns); Nx.SetNum(Ns); Ny.SetNum(Ns); Nz.SetNum(Ns);
	for (int32 I = 0; I < Ns; ++I)
	{
		Px[I] = P[I].X; Py[I] = P[I].Y; Pz[I] = P[I].Z;
		Tx[I] = Th[I].X; Ty[I] = Th[I].Y; Tz[I] = Th[I].Z;
		Nx[I] = this->N[I].X; Ny[I] = this->N[I].Y; Nz[I] = this->N[I].Z;
	}
	for (int32 I = 0; I < M; ++I)
	{
		const double Sq = SQuery[I];
		F.P[I] = FVector3d(FStreetSplineMath::Interp(Sq, S, Px), FStreetSplineMath::Interp(Sq, S, Py), FStreetSplineMath::Interp(Sq, S, Pz));
		const FVector3d Thh = FStreetSplineMath::Unit3(FVector3d(FStreetSplineMath::Interp(Sq, S, Tx), FStreetSplineMath::Interp(Sq, S, Ty), FStreetSplineMath::Interp(Sq, S, Tz)));
		FVector3d Nn(FStreetSplineMath::Interp(Sq, S, Nx), FStreetSplineMath::Interp(Sq, S, Ny), FStreetSplineMath::Interp(Sq, S, Nz));
		const double Dot = (Nn.X * Thh.X + Nn.Y * Thh.Y) + Nn.Z * Thh.Z;
		Nn = FVector3d(Nn.X - Dot * Thh.X, Nn.Y - Dot * Thh.Y, Nn.Z - Dot * Thh.Z);
		Nn = FStreetSplineMath::Unit3(Nn);
		F.Th[I] = Thh;
		F.NFlat[I] = FStreetSplineMath::Unit3(Cross3(ZAxis, Thh));
		F.N[I] = Nn;
		F.B[I] = Cross3(Thh, Nn);
	}
	return F;
}

FStreetFrames FStreetFrames::Insert(TConstArrayView<double> SExtra) const
{
	TArray<double> Extra;
	for (double E : SExtra) { if (E >= S[0] && E <= S.Last()) Extra.Add(E); }
	Extra.Sort();
	TArray<double> Uniq;
	for (double E : Extra) { if (Uniq.Num() == 0 || Uniq.Last() != E) Uniq.Add(E); }
	TArray<double> New;
	for (double E : Uniq)
	{
		const int32 J = FStreetSplineMath::SearchSortedLeft(S, E);
		const bool bNear = (J < S.Num() && FMath::Abs(S[J] - E) <= 1e-9) || (J > 0 && FMath::Abs(S[J - 1] - E) <= 1e-9);
		if (!bNear && (New.Num() == 0 || E - New.Last() > 1e-9)) New.Add(E);
	}
	if (New.Num() == 0) return *this;
	const FStreetFrames Fx = At(New);
	FStreetFrames Out;
	// stable merge of two sorted sequences: on an exact tie the existing frame comes first
	int32 A = 0, Bi = 0;
	const int32 Na = S.Num(), Nb = Fx.S.Num();
	Out.S.Reserve(Na + Nb); Out.P.Reserve(Na + Nb); Out.Th.Reserve(Na + Nb); Out.NFlat.Reserve(Na + Nb); Out.N.Reserve(Na + Nb); Out.B.Reserve(Na + Nb);
	while (A < Na || Bi < Nb)
	{
		const bool bTakeA = Bi >= Nb || (A < Na && S[A] <= Fx.S[Bi]);
		if (bTakeA)
		{
			Out.S.Add(S[A]); Out.P.Add(P[A]); Out.Th.Add(Th[A]); Out.NFlat.Add(NFlat[A]); Out.N.Add(N[A]); Out.B.Add(B[A]);
			++A;
		}
		else
		{
			Out.S.Add(Fx.S[Bi]); Out.P.Add(Fx.P[Bi]); Out.Th.Add(Fx.Th[Bi]); Out.NFlat.Add(Fx.NFlat[Bi]); Out.N.Add(Fx.N[Bi]); Out.B.Add(Fx.B[Bi]);
			++Bi;
		}
	}
	return Out;
}

FStreetFrames FStreetFrames::Subset(const TArray<bool>& Mask) const
{
	FStreetFrames Out;
	for (int32 I = 0; I < S.Num(); ++I)
	{
		if (Mask.IsValidIndex(I) && Mask[I])
		{
			Out.S.Add(S[I]); Out.P.Add(P[I]); Out.Th.Add(Th[I]); Out.NFlat.Add(NFlat[I]); Out.N.Add(N[I]); Out.B.Add(B[I]);
		}
	}
	return Out;
}

// ---------------------------------------------------------------------------------------------------------------
// FStreetSamples
// ---------------------------------------------------------------------------------------------------------------

TArray<double> FStreetSamples::EdgeOffset(EStreetSide Side) const
{
	const TArray<double>& E = ExtraOf(Side);
	TArray<double> Out;
	Out.SetNum(Width.Num());
	for (int32 I = 0; I < Width.Num(); ++I) Out[I] = Width[I] / 2.0 + E[I];
	return Out;
}

TArray<double> FStreetSamples::EdgeHeight(EStreetSide Side) const
{
	TArray<double> D = EdgeOffset(Side);
	const double Sigma = (double)StreetSideSigma(Side);
	for (double& X : D) X = Sigma * X;
	return SurfaceH(D);
}

double FStreetSamples::SurfaceHAt(int32 I, double D) const
{
	const double W = Width[I];
	const double Cf = CrossfallPct[I];
	const double Cm = CamberM[I];
	const double C = std::isfinite(Cm) ? Cm : (Cf / 100.0) * W / 4.0;
	double Para = 0.0;
	if (W > 0)
	{
		const double R = 2.0 * D / W;
		Para = -C * (R * R);
	}
	const double Planar = -(Cf / 100.0) * FMath::Abs(D);
	switch (CamberKind[I])
	{
	case EStreetCamberKind::Parabolic: return Para;
	case EStreetCamberKind::Planar: return Planar;
	default: return 0.0;
	}
}

TArray<double> FStreetSamples::SurfaceH(TConstArrayView<double> D) const
{
	TArray<double> Out;
	Out.SetNum(D.Num());
	for (int32 I = 0; I < D.Num(); ++I) Out[I] = SurfaceHAt(I, D[I]);
	return Out;
}

TSharedRef<FJsonObject> FStreetSamples::StatsJson() const
{
	TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
	auto R6 = [](double X) { return FMath::RoundToDouble(X * 1e6) / 1e6; };
	double GMin = 0, GMax = 0, GMean = 0;
	if (S.Num() > 1)
	{
		GMin = TNumericLimits<double>::Max(); GMax = -GMin; double Sum = 0;
		for (int32 I = 0; I + 1 < S.Num(); ++I) { const double G = S[I + 1] - S[I]; GMin = FMath::Min(GMin, G); GMax = FMath::Max(GMax, G); Sum += G; }
		GMean = Sum / (S.Num() - 1);
	}
	double BMin = 0, BMax = 0;
	if (BankDeg.Num()) { BMin = TNumericLimits<double>::Max(); BMax = -BMin; for (double Bv : BankDeg) { BMin = FMath::Min(BMin, Bv); BMax = FMath::Max(BMax, Bv); } }
	const TArray<double> Eo = EdgeOffset(EStreetSide::Left), Er = EdgeOffset(EStreetSide::Right);
	double WMax = 0; for (int32 I = 0; I < Eo.Num(); ++I) WMax = FMath::Max(WMax, Eo[I] + Er[I]);
	O->SetNumberField(TEXT("length_m"), R6(LengthM));
	O->SetNumberField(TEXT("n_samples"), (double)S.Num());
	O->SetNumberField(TEXT("points_merged"), (double)PointsMerged);
	O->SetNumberField(TEXT("step_min"), R6(GMin));
	O->SetNumberField(TEXT("step_max"), R6(GMax));
	O->SetNumberField(TEXT("step_mean"), R6(GMean));
	O->SetNumberField(TEXT("z_raw_nan_count"), (double)ZRawNanCount);
	O->SetNumberField(TEXT("bank_min"), R6(BMin));
	O->SetNumberField(TEXT("bank_max"), R6(BMax));
	O->SetNumberField(TEXT("w_max"), R6(WMax));
	if (bHasKind) O->SetStringField(TEXT("kind"), FStreetEnums::ToString(Kind)); else O->SetField(TEXT("kind"), MakeShared<FJsonValueNull>());
	O->SetBoolField(TEXT("trimmed"), bTrimmed);
	{
		TArray<TSharedPtr<FJsonValue>> Tm, St;
		Tm.Add(MakeShared<FJsonValueNumber>(R6(TrimM[0]))); Tm.Add(MakeShared<FJsonValueNumber>(R6(TrimM[1])));
		St.Add(MakeShared<FJsonValueNumber>(R6(STrim[0]))); St.Add(MakeShared<FJsonValueNumber>(R6(STrim[1])));
		O->SetArrayField(TEXT("trim_m"), Tm);
		O->SetArrayField(TEXT("s_trim"), St);
	}
	{
		int32 NA = 0;
		for (bool A : Active) { if (A) ++NA; }
		O->SetNumberField(TEXT("n_active"), (double)(Active.Num() ? NA : S.Num()));
	}
	TArray<TSharedPtr<FJsonValue>> W;
	for (const FString& Wn : Warnings) W.Add(MakeShared<FJsonValueString>(Wn));
	O->SetArrayField(TEXT("warnings"), W);
	return O;
}

// ---------------------------------------------------------------------------------------------------------------
// the build (spline.Spline.__init__)
// ---------------------------------------------------------------------------------------------------------------

int32 FStreetSamples::ArmStationIndex(EStreetSplineEnd End) const
{
	const int32 N = S.Num();
	if (End == EStreetSplineEnd::Start)
	{
		for (int32 I = 0; I < N; ++I) { if (Active.IsValidIndex(I) ? Active[I] : true) return I; }
		return 0;
	}
	for (int32 I = N - 1; I >= 0; --I) { if (Active.IsValidIndex(I) ? Active[I] : true) return I; }
	return FMath::Max(0, N - 1);
}

void FStreetSplineMath::ResolveWidths(const TArray<FStreetPoint>& Points, const TArray<double>& SKnots, const FRoadProfileData* RoadProf,
	const FStreetRoadTimeline& RoadTl, TConstArrayView<double> S, TArray<double>& OutW, TArray<double> OutExtra[2])
{
	const int32 M = S.Num();
	const double BaseW = RoadProf ? RoadProf->WidthM : 0.0;
	TArray<double> WKnots;
	WKnots.Reserve(Points.Num());
	for (const FStreetPoint& Pt : Points) WKnots.Add((!Pt.WidthM.IsSet() || !RoadProf) ? BaseW : Pt.WidthM.GetValue());
	OutW.SetNum(M);
	for (int32 I = 0; I < M; ++I) OutW[I] = FStreetSplineMath::Interp(S[I], SKnots, WKnots);
	for (const FStreetScalarOverride& Ov : RoadTl.WidthOverrides) FStreetTimelineMath::ApplyRampedOverride(S, OutW, Ov.S0, Ov.S1, Ov.Ramp, Ov.Value);
	for (int32 Side = 0; Side < 2; ++Side)
	{
		OutExtra[Side].Init(0.0, M);
		for (const FStreetScalarOverride& Ov : RoadTl.ExtraOverrides[Side]) FStreetTimelineMath::ApplyRampedOverride(S, OutExtra[Side], Ov.S0, Ov.S1, Ov.Ramp, Ov.Value);
	}
}

bool FStreetSplineMath::Build(const FStreetSplineDef& Def, const FStreetSiteProfiles& Profiles, const IStreetTerrainSource* Terrain, FStreetSamples& O, FString* Error,
	const double* Trim)
{
	O = FStreetSamples();
	O.Id = Def.Id;

	// -- points and curve
	O.PointsMerged = MergePoints(Def.Points, O.Points);
	if (O.PointsMerged) O.Warnings.Add(FString::Printf(TEXT("%d consecutive duplicate point(s) merged"), O.PointsMerged));
	if (O.Points.Num() < 2)
	{
		if (Error) *Error = FString::Printf(TEXT("spline %s: fewer than 2 distinct points"), *Def.Id);
		return false;
	}
	TArray<FVector2d> P;
	for (const FStreetPoint& Pt : O.Points) P.Add(FVector2d(Pt.X, Pt.Y));
	CatmullRomDense(P, O.SDense, O.XYDense, O.SKnots);
	O.LengthM = O.SDense.Last();
	const double L = O.LengthM;
	TArray<double> ElevS, ElevZ, ElevBank;
	if (Def.ElevationProfile.Num())
	{
		bool bValid = Def.ElevationProfile.Num() >= 2 && Def.ElevationProfile[0].SM == 0.0
			&& FMath::Abs(Def.ElevationProfile.Last().SM - L) <= 1e-5;
		for (const FStreetElevationKnot& K : Def.ElevationProfile)
		{
			bValid &= FMath::IsFinite(K.SM) && FMath::IsFinite(K.ZM) && FMath::IsFinite(K.BankDeg)
				&& FMath::Abs(K.BankDeg) <= 45.0 && (ElevS.IsEmpty() || K.SM > ElevS.Last());
			ElevS.Add(K.SM); ElevZ.Add(K.ZM); ElevBank.Add(K.BankDeg);
		}
		if (!bValid)
		{
			if (Error) *Error = Def.Id + TEXT(": elevation_profile must cover exactly [0, length] with finite increasing knots and bank within +/-45 degrees");
			return false;
		}
		ElevS.Last() = L;
	}
	TArray<double> KappaAbsD, KappaSigD;
	DenseCurvature(O.SDense, O.XYDense, KappaAbsD, KappaSigD);

	// -- profiles, sampling, timelines
	const FRoadProfileData* RoadProf = Def.ProfileIds.Road.IsEmpty() ? nullptr : Profiles.Road.Find(Def.ProfileIds.Road);
	O.RoadProfile = RoadProf;
	O.Sampling = FStreetSamplingResolved::Resolve(RoadProf ? RoadProf->Kind : EStreetRoadKind::Road,
		(RoadProf && RoadProf->bHasSamplingDefaults) ? &RoadProf->SamplingDefaults : nullptr, Def.bHasSampling ? &Def.Sampling : nullptr);
	const double Ramp = O.Sampling.WidthRampM;
	O.Road = FStreetRoadTimeline::Resolve(Def, Profiles, L, Ramp);
	O.Sides[0] = FStreetSideTimeline::Resolve(Def, EStreetSide::Left, Profiles, L, Ramp);
	O.Sides[1] = FStreetSideTimeline::Resolve(Def, EStreetSide::Right, Profiles, L, Ramp);
	O.bHasKind = O.Road.bHasKind;
	O.Kind = O.Road.Kind;
	{
		FString Problem;
		if (!FStreetscapeJson::RoadKindsConsistent(Def, Profiles, Problem))
		{
			if (Error) *Error = Problem;
			return false;
		}
	}

	// -- junction trim (a mask on s, resolved by FStreetJunctionPlan; see FStreetSamples::TrimM)
	{
		const double T0 = Trim ? FMath::Max(0.0, Trim[0]) : 0.0;
		const double T1 = Trim ? FMath::Max(0.0, Trim[1]) : 0.0;
		O.TrimM[0] = T0; O.TrimM[1] = T1;
		O.STrim[0] = T0; O.STrim[1] = FMath::Max(T0, L - T1);
		O.bTrimmed = (T0 > 0.0) || (T1 > 0.0);
	}

	// -- stations
	TArray<double> Mand;
	for (int32 I = 1; I + 1 < O.SKnots.Num(); ++I) Mand.Add(O.SKnots[I]);
	Mand.Append(O.Sampling.ExtraStationsM);
	Mand.Append(ElevS);
	Mand.Append(O.Road.MandatoryStations());
	Mand.Append(O.Sides[0].MandatoryStations());
	Mand.Append(O.Sides[1].MandatoryStations());
	for (int32 K = 0; K < 2; ++K) { if (O.STrim[K] > 0.0 && O.STrim[K] < L) Mand.Add(O.STrim[K]); }
	int32 Clamped = 0;
	for (double M : Mand) { if (M > L + 0.01) ++Clamped; }
	if (Clamped) O.Warnings.Add(FString::Printf(TEXT("%d station(s) beyond L clamped"), Clamped));
	{
		TArray<double> Ms;
		for (double M : Mand) { if (0.0 < M && M < L) Ms.Add(M); }
		Ms.Sort();
		for (double M : Ms) { if (O.MandatorySet.Num() == 0 || O.MandatorySet.Last() != M) O.MandatorySet.Add(M); }
	}
	O.S = AdaptiveStations(O.SDense, KappaAbsD, O.Sampling, O.MandatorySet);
	const int32 N = O.S.Num();
	O.Mandatory.SetNum(N);
	for (int32 I = 0; I < N; ++I) O.Mandatory[I] = O.MandatorySet.Contains(O.S[I]);
	// the active (untrimmed) run: closed on both trim stations, which are in O.S exactly
	{
		const double A0 = O.STrim[0], A1 = O.STrim[1];
		O.Active.SetNum(N);
		int32 NActive = 0;
		for (int32 I = 0; I < N; ++I)
		{
			O.Active[I] = (O.S[I] >= A0 - 1e-12) && (O.S[I] <= A1 + 1e-12);
			NActive += O.Active[I] ? 1 : 0;
		}
		if (NActive < 2)
		{
			for (int32 I = 0; I < N; ++I) O.Active[I] = true;
			O.bTrimmed = false;
			O.STrim[0] = 0.0; O.STrim[1] = L;
			O.TrimM[0] = 0.0; O.TrimM[1] = 0.0;
			O.Warnings.Add(TEXT("junction trim would leave fewer than 2 stations: not trimmed"));
		}
	}
	TArray<double> Xd, Yd;
	Xd.SetNum(O.XYDense.Num()); Yd.SetNum(O.XYDense.Num());
	for (int32 I = 0; I < O.XYDense.Num(); ++I) { Xd[I] = O.XYDense[I].X; Yd[I] = O.XYDense[I].Y; }
	O.XY.SetNum(N); O.Kappa.SetNum(N); O.ThXY.SetNum(N);
	const TArray<FVector2d> Td = DenseTangents(O.XYDense);
	TArray<double> Tdx, Tdy;
	Tdx.SetNum(Td.Num()); Tdy.SetNum(Td.Num());
	for (int32 I = 0; I < Td.Num(); ++I) { Tdx[I] = Td[I].X; Tdy[I] = Td[I].Y; }
	for (int32 I = 0; I < N; ++I)
	{
		O.XY[I] = FVector2d(Interp(O.S[I], O.SDense, Xd), Interp(O.S[I], O.SDense, Yd));
		O.Kappa[I] = Interp(O.S[I], O.SDense, KappaSigD);
		O.ThXY[I] = Unit2(FVector2d(Interp(O.S[I], O.SDense, Tdx), Interp(O.S[I], O.SDense, Tdy)));
	}

	// -- width, extras, roll (ResolveWidths is the ONE definition; FStreetJunctionPlan calls the same static)
	ResolveWidths(O.Points, O.SKnots, RoadProf, O.Road, O.S, O.Width, O.Extra);
	{
		bool bAnyRoll = false;
		TArray<double> HasRoll, RollVals, SKnotsRoll, RollValsRoll;
		for (int32 K = 0; K < O.Points.Num(); ++K)
		{
			const bool bR = O.Points[K].RollDeg.IsSet();
			bAnyRoll |= bR;
			HasRoll.Add(bR ? 1.0 : 0.0);
			RollVals.Add(bR ? O.Points[K].RollDeg.GetValue() : 0.0);
			if (bR) { SKnotsRoll.Add(O.SKnots[K]); RollValsRoll.Add(O.Points[K].RollDeg.GetValue()); }
		}
		O.RollPl.SetNum(N); O.RollMask.SetNum(N);
		for (int32 I = 0; I < N; ++I)
		{
			O.RollPl[I] = bAnyRoll ? Interp(O.S[I], SKnotsRoll, RollValsRoll) : 0.0;
			O.RollMask[I] = bAnyRoll ? Interp(O.S[I], O.SKnots, HasRoll) : 0.0;
		}
	}

	// -- per-station road profile scalars
	O.ProfileAt = O.Road.ProfileAt(O.S);
	O.CamberKind.SetNum(N); O.SurfaceMaterial.SetNum(N); O.OverlapM.SetNum(N); O.SkirtDropM.SetNum(N);
	double MinLat = TNumericLimits<double>::Max();
	bool bAnyProf = false;
	for (int32 I = 0; I < N; ++I)
	{
		const FRoadProfileData* Pp = O.ProfileAt[I];
		O.CamberKind[I] = (!Pp || Pp->Kind == EStreetRoadKind::Rail) ? EStreetCamberKind::None : Pp->Camber.Kind;
		O.SurfaceMaterial[I] = Pp ? Pp->SurfaceMaterial : FName(TEXT("tarmac"));
		O.OverlapM[I] = Pp ? Pp->OverlapM : 0.04;
		O.SkirtDropM[I] = Pp ? Pp->SkirtDropM : 0.02;
		if (Pp) { bAnyProf = true; MinLat = FMath::Min(MinLat, Pp->LateralStationSpacingM); }
	}
	O.LateralStationSpacingM = bAnyProf ? MinLat : 1.0;
	const double BaseCf = (RoadProf && RoadProf->Camber.CrossfallPct.IsSet()) ? RoadProf->Camber.CrossfallPct.GetValue() : 0.0;
	O.CrossfallPct.Init(BaseCf, N);
	for (const FStreetScalarOverride& Ov : O.Road.CrossfallOverrides) FStreetTimelineMath::ApplyRampedOverride(O.S, O.CrossfallPct, Ov.S0, Ov.S1, Ov.Ramp, Ov.Value);
	const double BaseCm = (RoadProf && RoadProf->Camber.CamberM.IsSet()) ? RoadProf->Camber.CamberM.GetValue() : NAN;
	O.CamberM.Init(BaseCm, N);
	for (const FStreetScalarOverride& Ov : O.Road.CamberMOverrides) FStreetTimelineMath::ApplyRampedOverride(O.S, O.CamberM, Ov.S0, Ov.S1, Ov.Ramp, Ov.Value);

	// -- heights
	O.ZRaw.SetNum(N);
	for (int32 I = 0; I < N; ++I)
	{
		double Z = NAN;
		if (Terrain && !Terrain->SampleHeight(O.XY[I].X, O.XY[I].Y, Z)) Z = NAN;
		O.ZRaw[I] = Z;
	}
	O.ZRawNanCount = 0;
	for (double Z : O.ZRaw) { if (!std::isfinite(Z)) ++O.ZRawNanCount; }
	bool bAllNan = false;
	O.ZFill = FillNanAlong(O.ZRaw, bAllNan);
	if (bAllNan) O.Warnings.Add(TEXT("no terrain under any station: heights set to 0"));
	else if (O.ZRawNanCount) O.Warnings.Add(FString::Printf(TEXT("%d station(s) without terrain filled along s"), O.ZRawNanCount));
	const double W = O.Sampling.SmoothingWindowM;
	const int32 Passes = O.Sampling.SmoothingPasses;
	const TArray<double> Zs = MovingAverageArcLength(O.S, O.ZFill, W, Passes);
	for (int32 K = 0; K < O.Points.Num(); ++K)
	{
		if (O.Points[K].Z.IsSet()) O.Pins.Add(TPair<double, double>(O.SKnots[K], O.Points[K].Z.GetValue()));
	}
	O.ZRef = O.Pins.Num() ? ApplyPins(Zs, O.S, O.Pins, O.Sampling.PinBlendM) : Zs;
	if (ElevS.Num()) for (int32 I = 0; I < N; ++I) O.ZRef[I] = Interp(O.S[I], ElevS, ElevZ);

	// -- bank
	O.BankRaw.SetNum(N);
	for (int32 I = 0; I < N; ++I)
	{
		const FVector2d NFlat(-O.ThXY[I].Y, O.ThXY[I].X);
		const double HProbe = FMath::Max(O.Width[I] / 2.0, O.Sampling.BankProbeMinHalfWidthM);
		double Beta = 0.0;
		if (Terrain)
		{
			const FVector2d Pl(O.XY[I].X + HProbe * NFlat.X, O.XY[I].Y + HProbe * NFlat.Y);
			const FVector2d Pr(O.XY[I].X - HProbe * NFlat.X, O.XY[I].Y - HProbe * NFlat.Y);
			double Zl = NAN, Zr = NAN;
			if (!Terrain->SampleHeight(Pl.X, Pl.Y, Zl)) Zl = NAN;
			if (!Terrain->SampleHeight(Pr.X, Pr.Y, Zr)) Zr = NAN;
			Beta = std::atan2(Zl - Zr, 2.0 * HProbe) * (180.0 / kPi);
			if (!std::isfinite(Beta)) Beta = 0.0;
		}
		O.BankRaw[I] = Beta;
	}
	const double BMax = O.Sampling.BankMaxDeg;
	O.BankTerrain = MovingAverageArcLength(O.S, O.BankRaw, W, 1);
	for (double& Bv : O.BankTerrain) Bv = FMath::Min(FMath::Max(Bv, -BMax), BMax);
	O.BankUnlimited.SetNum(N);
	for (int32 I = 0; I < N; ++I) O.BankUnlimited[I] = (1.0 - O.RollMask[I]) * O.BankTerrain[I] + O.RollMask[I] * O.RollPl[I];
	O.BankDeg = RateLimitBank(O.BankUnlimited, O.S, O.Sampling.BankRateMaxDegPerM);
	if (ElevS.Num()) for (int32 I = 0; I < N; ++I) O.BankDeg[I] = Interp(O.S[I], ElevS, ElevBank);

	// -- frames
	TArray<FVector3d> P3, T3;
	P3.SetNum(N); T3.SetNum(N);
	for (int32 I = 0; I < N; ++I)
	{
		P3[I] = FVector3d(O.XY[I].X, O.XY[I].Y, O.ZRef[I]);
		T3[I] = FVector3d(O.ThXY[I].X, O.ThXY[I].Y, 0.0);
	}
	O.Frames = FStreetFrames::Build(O.S, P3, T3, O.BankDeg);

	// -- side specs (the one SideTimeline evaluation both B and C read)
	O.SideSpec[0] = O.Sides[0].Evaluate(O.S);
	O.SideSpec[1] = O.Sides[1].Evaluate(O.S);
	return true;
}
