#include "StreetGeometry.h"
#include "DynamicMesh/DynamicMesh3.h"
#include "DynamicMesh/DynamicMeshAttributeSet.h"
#include "DynamicMesh/MeshNormals.h"
#include "StreetscapeModule.h"
#include <cmath>

using UE::Geometry::FIndex3i;

namespace
{
FVector3d Cross3(const FVector3d& A, const FVector3d& B)
{
	return FVector3d(A.Y * B.Z - A.Z * B.Y, A.Z * B.X - A.X * B.Z, A.X * B.Y - A.Y * B.X);
}
double Norm3(const FVector3d& V) { return std::sqrt((V.X * V.X + V.Y * V.Y) + V.Z * V.Z); }
double Dot3(const FVector3d& A, const FVector3d& B) { return (A.X * B.X + A.Y * B.Y) + A.Z * B.Z; }

struct FKey3
{
	int64 X, Y, Z;
	bool operator==(const FKey3& O) const { return X == O.X && Y == O.Y && Z == O.Z; }
};
uint32 GetTypeHash(const FKey3& K) { return HashCombine(HashCombine(::GetTypeHash(K.X), ::GetTypeHash(K.Y)), ::GetTypeHash(K.Z)); }
FKey3 Quantise(const FVector3d& V, double Tol)
{
	return FKey3{ (int64)FMath::RoundToDouble(V.X / Tol), (int64)FMath::RoundToDouble(V.Y / Tol), (int64)FMath::RoundToDouble(V.Z / Tol) };
}
}

// ---------------------------------------------------------------------------------------------------------------
// FStreetSection
// ---------------------------------------------------------------------------------------------------------------

FStreetSection FStreetSection::Make(bool bClosed, const TArray<TTuple<double, double, FName>>& Pts, const TArray<bool>& Smooth, const TArray<double>& V)
{
	FStreetSection S;
	S.bClosed = bClosed;
	TArray<double> Vv = V;
	if (Vv.Num() != Pts.Num())
	{
		Vv.Reset();
		Vv.Add(0.0);
		for (int32 I = 1; I < Pts.Num(); ++I)
		{
			Vv.Add(Vv.Last() + std::hypot(Pts[I].Get<0>() - Pts[I - 1].Get<0>(), Pts[I].Get<1>() - Pts[I - 1].Get<1>()));
		}
	}
	for (int32 I = 0; I < Pts.Num(); ++I)
	{
		FStreetSectionPoint P;
		P.O = Pts[I].Get<0>(); P.H = Pts[I].Get<1>(); P.Mat = Pts[I].Get<2>(); P.V = Vv[I];
		P.bSmooth = Smooth.Num() == Pts.Num() ? Smooth[I] : (Smooth.Num() == 1 ? Smooth[0] : false);
		S.Points.Add(P);
	}
	return S;
}

// ---------------------------------------------------------------------------------------------------------------
// FStreetMeshBuilder
// ---------------------------------------------------------------------------------------------------------------

int32 FStreetMeshBuilder::MaterialId(FName Name)
{
	const int32 I = MaterialNames.IndexOfByKey(Name);
	if (I != INDEX_NONE) return I;
	MaterialNames.Add(Name);
	return MaterialNames.Num() - 1;
}

int32 FStreetMeshBuilder::GroupId(FName Name)
{
	const int32 I = GroupNames.IndexOfByKey(Name);
	if (I != INDEX_NONE) return I;
	GroupNames.Add(Name);
	return GroupNames.Num() - 1;
}

int32 FStreetMeshBuilder::AppendVertices(TConstArrayView<FVector3d> P, TConstArrayView<FVector2d> InUV, TConstArrayView<double> S, TConstArrayView<double> D, TConstArrayView<double> H)
{
	const int32 N0 = V.Num();
	V.Append(P.GetData(), P.Num());
	UV.Append(InUV.GetData(), InUV.Num());
	VS.Append(S.GetData(), S.Num());
	VD.Append(D.GetData(), D.Num());
	VH.Append(H.GetData(), H.Num());
	return N0;
}

void FStreetMeshBuilder::AppendTriangles(TConstArrayView<FIndex3i> T, TConstArrayView<int32> MatIds, int32 GrpId)
{
	for (int32 I = 0; I < T.Num(); ++I)
	{
		F.Add(T[I]);
		Mat.Add(MatIds.Num() == T.Num() ? MatIds[I] : (MatIds.Num() ? MatIds[0] : 0));
		Grp.Add(GrpId);
	}
}

void FStreetMeshBuilder::AppendTriangles(TConstArrayView<FIndex3i> T, int32 MatId, int32 GrpId)
{
	for (const FIndex3i& Tri : T)
	{
		F.Add(Tri);
		Mat.Add(MatId);
		Grp.Add(GrpId);
	}
}

int32 FStreetMeshBuilder::AppendPolygon(TConstArrayView<int32> Ring, int32 MatId, int32 GrpId, const FVector3d& NormalHint)
{
	if (Ring.Num() < 3) return 0;
	TArray<FVector3d> P;
	for (int32 I : Ring) P.Add(V[I]);
	const FVector3d Nrm = FStreetGeometry::NewellNormal(P);
	if (Norm3(Nrm) < 1e-18) return 0;
	FVector3d U, W;
	FStreetGeometry::PlaneBasis(Nrm, U, W);
	TArray<FVector2d> Pts2;
	for (const FVector3d& X : P) Pts2.Add(FVector2d(Dot3(X, U), Dot3(X, W)));
	TArray<FIndex3i> Tris = FStreetGeometry::TriangulatePolygon2D(Pts2);
	if (Tris.Num() == 0) return 0;
	TArray<FIndex3i> T;
	int32 Kept = 0;
	for (const FIndex3i& Tr : Tris)
	{
		FIndex3i Ti(Ring[Tr.A], Ring[Tr.B], Ring[Tr.C]);
		const FVector3d Fn = Cross3(V[Ti.B] - V[Ti.A], V[Ti.C] - V[Ti.A]);
		if (Dot3(Fn, NormalHint) < 0) Ti = FIndex3i(Ti.A, Ti.C, Ti.B);
		if (0.5 * Norm3(Fn) >= 1e-10) { T.Add(Ti); ++Kept; }
	}
	AppendTriangles(T, MatId, GrpId);
	return Kept;
}

void FStreetMeshBuilder::Merge(const FStreetMeshBuilder& Other)
{
	if (Other.V.Num() == 0) return;
	const int32 N0 = V.Num();
	TArray<int32> MatMap, GrpMap;
	for (FName N : Other.MaterialNames) MatMap.Add(MaterialId(N));
	for (FName N : Other.GroupNames) GrpMap.Add(GroupId(N));
	AppendVertices(Other.V, Other.UV, Other.VS, Other.VD, Other.VH);
	for (int32 I = 0; I < Other.F.Num(); ++I)
	{
		F.Add(FIndex3i(Other.F[I].A + N0, Other.F[I].B + N0, Other.F[I].C + N0));
		Mat.Add(MatMap[Other.Mat[I]]);
		Grp.Add(GrpMap[Other.Grp[I]]);
	}
	TwoSided.Append(Other.TwoSided);
}

FVector3d FStreetMeshBuilder::FaceNormal(int32 T) const
{
	const FIndex3i& Tr = F[T];
	return Cross3(V[Tr.B] - V[Tr.A], V[Tr.C] - V[Tr.A]);
}

double FStreetMeshBuilder::FaceArea(int32 T) const { return 0.5 * Norm3(FaceNormal(T)); }

TArray<FString> FStreetMeshBuilder::Validate() const
{
	TArray<FString> Msgs;
	int32 NonFinite = 0;
	for (const FVector3d& X : V) { if (!std::isfinite(X.X) || !std::isfinite(X.Y) || !std::isfinite(X.Z)) ++NonFinite; }
	if (NonFinite) Msgs.Add(FString::Printf(TEXT("non-finite vertex coordinates: %d"), NonFinite));
	if (F.Num())
	{
		bool bRange = false;
		for (const FIndex3i& Tr : F) { if (Tr.A < 0 || Tr.B < 0 || Tr.C < 0 || Tr.A >= V.Num() || Tr.B >= V.Num() || Tr.C >= V.Num()) bRange = true; }
		if (bRange) Msgs.Add(TEXT("triangle index out of range"));
		else
		{
			int32 Deg = 0;
			for (int32 T = 0; T < F.Num(); ++T) { if (FaceArea(T) < 1e-10) ++Deg; }
			if (Deg) Msgs.Add(FString::Printf(TEXT("%d degenerate triangle(s) (< 1e-10 m^2)"), Deg));
			TSet<FKey3> Seen;
			int32 Dup = 0;
			TSet<FKey3> DupSeen;
			for (const FIndex3i& Tr : F)
			{
				int64 A = Tr.A, B = Tr.B, C = Tr.C;
				if (A > B) Swap(A, B); if (B > C) Swap(B, C); if (A > B) Swap(A, B);
				const FKey3 K{ A, B, C };
				if (Seen.Contains(K)) { if (!DupSeen.Contains(K)) { ++Dup; DupSeen.Add(K); } }
				else Seen.Add(K);
			}
			if (Dup) Msgs.Add(FString::Printf(TEXT("%d duplicate triangle(s)"), Dup));
		}
	}
	if (Mat.Num() != F.Num() || Grp.Num() != F.Num()) Msgs.Add(TEXT("material/group arrays do not match the triangle count"));
	return Msgs;
}

bool FStreetMeshBuilder::IsClosedManifold(const TSet<FName>* MatFilter, const TSet<FName>* GrpFilter, double Tol) const
{
	TArray<int32> MatIds, GrpIds;
	if (MatFilter) { for (FName N : *MatFilter) { const int32 I = MaterialNames.IndexOfByKey(N); if (I != INDEX_NONE) MatIds.Add(I); } }
	if (GrpFilter) { for (FName N : *GrpFilter) { const int32 I = GroupNames.IndexOfByKey(N); if (I != INDEX_NONE) GrpIds.Add(I); } }
	const TArray<int32> Weld = FStreetGeometry::WeldIndices(V, Tol);
	const int64 M = (int64)Weld.Num() + 1;
	TMap<int64, int32> Und, Dir;
	int32 Count = 0;
	for (int32 T = 0; T < F.Num(); ++T)
	{
		if (MatFilter && !MatIds.Contains(Mat[T])) continue;
		if (GrpFilter && !GrpIds.Contains(Grp[T])) continue;
		const int64 A = Weld[F[T].A], B = Weld[F[T].B], C = Weld[F[T].C];
		if (A == B || B == C || C == A) continue;
		++Count;
		const int64 Edges[3][2] = { { A, B }, { B, C }, { C, A } };
		for (const auto& E : Edges)
		{
			Und.FindOrAdd(FMath::Min(E[0], E[1]) * M + FMath::Max(E[0], E[1]))++;
			Dir.FindOrAdd(E[0] * M + E[1])++;
		}
	}
	if (Count == 0) return false;
	for (const auto& KV : Und) { if (KV.Value != 2) return false; }
	for (const auto& KV : Dir) { if (KV.Value != 1) return false; }
	return true;
}

FStreetBuildStats FStreetMeshBuilder::Stats() const
{
	FStreetBuildStats St;
	St.Verts = V.Num();
	St.Tris = F.Num();
	if (V.Num())
	{
		St.BBoxMin = V[0]; St.BBoxMax = V[0];
		for (const FVector3d& X : V)
		{
			St.BBoxMin = FVector3d(FMath::Min(St.BBoxMin.X, X.X), FMath::Min(St.BBoxMin.Y, X.Y), FMath::Min(St.BBoxMin.Z, X.Z));
			St.BBoxMax = FVector3d(FMath::Max(St.BBoxMax.X, X.X), FMath::Max(St.BBoxMax.Y, X.Y), FMath::Max(St.BBoxMax.Z, X.Z));
		}
	}
	for (int32 I = 0; I < MaterialNames.Num(); ++I)
	{
		TSet<int32> Vs; int32 Tris = 0;
		for (int32 T = 0; T < F.Num(); ++T) { if (Mat[T] == I) { ++Tris; Vs.Add(F[T].A); Vs.Add(F[T].B); Vs.Add(F[T].C); } }
		if (Tris) St.PerMaterial.Add(MaterialNames[I], FIntPoint(Tris, Vs.Num()));
	}
	for (int32 I = 0; I < GroupNames.Num(); ++I)
	{
		TSet<int32> Vs; int32 Tris = 0;
		for (int32 T = 0; T < F.Num(); ++T) { if (Grp[T] == I) { ++Tris; Vs.Add(F[T].A); Vs.Add(F[T].B); Vs.Add(F[T].C); } }
		if (Tris) St.PerGroup.Add(GroupNames[I], FIntPoint(Tris, Vs.Num()));
	}
	return St;
}

TArray<bool> FStreetMeshBuilder::GroupMaskTris(const FString& Prefix, const FName* Exact) const
{
	TArray<int32> Ids;
	for (int32 I = 0; I < GroupNames.Num(); ++I)
	{
		if (Exact ? GroupNames[I] == *Exact : GroupNames[I].ToString().StartsWith(Prefix, ESearchCase::CaseSensitive)) Ids.Add(I);
	}
	TArray<bool> Out;
	Out.SetNum(F.Num());
	for (int32 T = 0; T < F.Num(); ++T) Out[T] = Ids.Contains(Grp[T]);
	return Out;
}

TArray<int32> FStreetMeshBuilder::VerticesOfGroups(const FString& Prefix, const FName* Exact, const FString* ExcludePrefix) const
{
	TArray<bool> Sel;
	if (ExcludePrefix)
	{
		TArray<int32> Ids;
		for (int32 I = 0; I < GroupNames.Num(); ++I) { if (!GroupNames[I].ToString().StartsWith(*ExcludePrefix, ESearchCase::CaseSensitive)) Ids.Add(I); }
		Sel.SetNum(F.Num());
		for (int32 T = 0; T < F.Num(); ++T) Sel[T] = Ids.Contains(Grp[T]);
	}
	else
	{
		Sel = GroupMaskTris(Prefix, Exact);
	}
	TSet<int32> Vs;
	for (int32 T = 0; T < F.Num(); ++T) { if (Sel[T]) { Vs.Add(F[T].A); Vs.Add(F[T].B); Vs.Add(F[T].C); } }
	TArray<int32> Out = Vs.Array();
	Out.Sort();
	return Out;
}

// ---------------------------------------------------------------------------------------------------------------
// FStreetGeometry helpers (mesh.py)
// ---------------------------------------------------------------------------------------------------------------

FVector3d FStreetGeometry::NewellNormal(TConstArrayView<FVector3d> P)
{
	double Nx = 0, Ny = 0, Nz = 0;
	const int32 K = P.Num();
	for (int32 I = 0; I < K; ++I)
	{
		const FVector3d& A = P[I];
		const FVector3d& Q = P[(I + 1) % K];
		Nx += (A.Y - Q.Y) * (A.Z + Q.Z);
		Ny += (A.Z - Q.Z) * (A.X + Q.X);
		Nz += (A.X - Q.X) * (A.Y + Q.Y);
	}
	return FVector3d(Nx, Ny, Nz);
}

void FStreetGeometry::PlaneBasis(const FVector3d& InN, FVector3d& OutU, FVector3d& OutW)
{
	const double L = Norm3(InN);
	const FVector3d N(InN.X / L, InN.Y / L, InN.Z / L);
	const FVector3d A = FMath::Abs(N.X) < 0.9 ? FVector3d(1, 0, 0) : FVector3d(0, 1, 0);
	FVector3d U = Cross3(N, A);
	const double Lu = Norm3(U);
	U = FVector3d(U.X / Lu, U.Y / Lu, U.Z / Lu);
	OutU = U;
	OutW = Cross3(N, U);
}

double FStreetGeometry::PolygonArea2D(TConstArrayView<FVector2d> Pts)
{
	double Sum = 0;
	const int32 K = Pts.Num();
	for (int32 I = 0; I < K; ++I)
	{
		const FVector2d& A = Pts[I];
		const FVector2d& B = Pts[(I + 1) % K];
		Sum += A.X * B.Y - B.X * A.Y;
	}
	return 0.5 * Sum;
}

TArray<FIndex3i> FStreetGeometry::TriangulatePolygon2D(TConstArrayView<FVector2d> Pts)
{
	TArray<FIndex3i> Tris;
	const int32 K = Pts.Num();
	if (K < 3) return Tris;
	const double Area = PolygonArea2D(Pts);
	const double Sign = Area >= 0 ? 1.0 : -1.0;
	TArray<int32> Idx;
	for (int32 I = 0; I < K; ++I) Idx.Add(I);
	auto Cross = [&Pts](int32 O, int32 A, int32 B)
	{
		return (Pts[A].X - Pts[O].X) * (Pts[B].Y - Pts[O].Y) - (Pts[A].Y - Pts[O].Y) * (Pts[B].X - Pts[O].X);
	};
	auto Inside = [&](int32 P, int32 A, int32 B, int32 C)
	{
		const double D1 = Cross(A, B, P) * Sign, D2 = Cross(B, C, P) * Sign, D3 = Cross(C, A, P) * Sign;
		return D1 >= -1e-14 && D2 >= -1e-14 && D3 >= -1e-14;
	};
	int32 Guard = 0;
	while (Idx.Num() > 3 && Guard < 10 * K * K)
	{
		++Guard;
		bool bFound = false;
		const int32 N = Idx.Num();
		for (int32 I = 0; I < N; ++I)
		{
			const int32 A = Idx[(I - 1 + N) % N], B = Idx[I], C = Idx[(I + 1) % N];
			if (Cross(A, B, C) * Sign <= 1e-14) continue;
			bool bOk = true;
			for (int32 J : Idx)
			{
				if (J == A || J == B || J == C) continue;
				if (Inside(J, A, B, C)) { bOk = false; break; }
			}
			if (bOk)
			{
				Tris.Add(FIndex3i(A, B, C));
				Idx.RemoveAt(I);
				bFound = true;
				break;
			}
		}
		if (!bFound)
		{
			// degenerate polygon (collinear tail): clip the first vertex anyway
			Tris.Add(FIndex3i(Idx[0], Idx[1], Idx[2]));
			Idx.RemoveAt(1);
		}
	}
	if (Idx.Num() == 3) Tris.Add(FIndex3i(Idx[0], Idx[1], Idx[2]));
	return Tris;
}

TArray<int32> FStreetGeometry::WeldIndices(TConstArrayView<FVector3d> V, double Tol)
{
	TArray<int32> Out;
	Out.SetNum(V.Num());
	TMap<FKey3, int32> First;
	for (int32 I = 0; I < V.Num(); ++I)
	{
		const FKey3 K = Quantise(V[I], Tol);
		if (const int32* Found = First.Find(K)) Out[I] = *Found;
		else { First.Add(K, I); Out[I] = I; }
	}
	return Out;
}

TArray<FVector3d> FStreetGeometry::DistinctPositions(TConstArrayView<FVector3d> V, double Tol)
{
	TSet<FKey3> Seen;
	TArray<FVector3d> Out;
	for (const FVector3d& X : V)
	{
		const FKey3 K = Quantise(X, Tol);
		if (!Seen.Contains(K))
		{
			Seen.Add(K);
			Out.Add(FVector3d((double)K.X * Tol, (double)K.Y * Tol, (double)K.Z * Tol));
		}
	}
	return Out;
}

// ---------------------------------------------------------------------------------------------------------------
// FStreetSweep (sweep.py)
// ---------------------------------------------------------------------------------------------------------------

void FStreetSweep::Rows(const FStreetSection& Section, TArray<int32>& OutRowPoint, TArray<FIntPoint>& OutEdgeRows)
{
	const int32 P = Section.NumPoints();
	TArray<int32> Before, After;
	Before.SetNum(P); After.SetNum(P);
	OutRowPoint.Reset();
	int32 R = 0;
	for (int32 K = 0; K < P; ++K)
	{
		const FStreetSectionPoint& Pt = Section.Points[K];
		const bool bTwo = (!Pt.bSmooth) && (Section.bClosed || (0 < K && K < P - 1));
		Before[K] = R;
		OutRowPoint.Add(K);
		++R;
		if (bTwo)
		{
			After[K] = R;
			OutRowPoint.Add(K);
			++R;
		}
		else
		{
			After[K] = Before[K];
		}
	}
	const int32 E = Section.NumEdges();
	OutEdgeRows.SetNum(E);
	for (int32 K = 0; K < E; ++K)
	{
		const int32 K1 = (K + 1) % P;
		OutEdgeRows[K] = FIntPoint(After[K], Before[K1]);
	}
}

TArray<bool> FStreetSweep::RunsToQuadMask(TConstArrayView<double> S, const TArray<TPair<double, double>>& Intervals)
{
	TArray<bool> Qm;
	Qm.Init(false, FMath::Max(S.Num() - 1, 0));
	for (const TPair<double, double>& Iv : Intervals)
	{
		for (int32 I = 0; I + 1 < S.Num(); ++I)
		{
			if (S[I] >= Iv.Key - 1e-9 && S[I + 1] <= Iv.Value + 1e-9) Qm[I] = true;
		}
	}
	return Qm;
}

FStreetSweepResult FStreetSweep::Sweep(FStreetMeshBuilder& Buf, const FStreetSection& Section, const FStreetFrames& Frames, const FStreetSweepParams& Pr)
{
	FStreetSweepResult Res;
	const int32 N = Frames.Num();
	const int32 P = Section.NumPoints();
	const int32 E = Section.NumEdges();
	const TArray<FStreetSectionPoint>& Pts = Section.Points;
	auto O = [&](int32 I, int32 K) { return Pr.PointO.Num() == N * P ? Pr.PointO[I * P + K] : Pts[K].O; };
	auto Hh = [&](int32 I, int32 K) { return Pr.PointH.Num() == N * P ? Pr.PointH[I * P + K] : Pts[K].H; };
	auto Lat = [&](int32 I) { return Pr.Lateral.Num() == N ? Pr.Lateral[I] : Pr.LateralScalar; };
	auto Hgt = [&](int32 I) { return Pr.Height.Num() == N ? Pr.Height[I] : Pr.HeightScalar; };
	const double Side = (double)Pr.Side;
	TArray<bool> QuadOk;
	QuadOk.Init(false, FMath::Max(N - 1, 0));
	for (int32 I = 0; I + 1 < N; ++I)
	{
		const bool M0 = Pr.Mask.Num() == N ? Pr.Mask[I] : true;
		const bool M1 = Pr.Mask.Num() == N ? Pr.Mask[I + 1] : true;
		const bool Q = Pr.QuadMask.Num() == N - 1 ? Pr.QuadMask[I] : true;
		QuadOk[I] = M0 && M1 && Q;
	}
	TArray<bool> VOk;
	VOk.Init(false, N);
	for (int32 I = 0; I + 1 < N; ++I) { if (QuadOk[I]) { VOk[I] = true; VOk[I + 1] = true; } }

	Rows(Section, Res.RowPoint, Res.EdgeRows);
	const int32 R = Res.RowPoint.Num();
	Res.N = N; Res.R = R;
	Res.VIdx.Init(-1, N * R);
	const int32 Tri0 = Buf.F.Num();
	TArray<int32> StIdx;
	for (int32 I = 0; I < N; ++I) { if (VOk[I]) StIdx.Add(I); }
	if (StIdx.Num() == 0)
	{
		Res.TriRange = FIntPoint(Tri0, Tri0);
		return Res;
	}

	// -- vertices
	{
		TArray<FVector3d> Vs; TArray<FVector2d> Uv; TArray<double> Sa, Da, Ha;
		Vs.Reserve(StIdx.Num() * R); Uv.Reserve(StIdx.Num() * R); Sa.Reserve(StIdx.Num() * R); Da.Reserve(StIdx.Num() * R); Ha.Reserve(StIdx.Num() * R);
		for (int32 I : StIdx)
		{
			for (int32 Rw = 0; Rw < R; ++Rw)
			{
				const int32 K = Res.RowPoint[Rw];
				const double D = Side * (Lat(I) + O(I, K));
				const double HH = Hgt(I) + Hh(I, K);
				const FVector3d& Pp = Frames.P[I];
				const FVector3d& Nn = Frames.N[I];
				const FVector3d& Bb = Frames.B[I];
				Vs.Add(FVector3d(Pp.X + D * Nn.X + HH * Bb.X, Pp.Y + D * Nn.Y + HH * Bb.Y, Pp.Z + D * Nn.Z + HH * Bb.Z));
				Uv.Add(FVector2d(Frames.S[I], Pts[K].V));
				Sa.Add(Frames.S[I]); Da.Add(D); Ha.Add(HH);
			}
		}
		const int32 First = Buf.AppendVertices(Vs, Uv, Sa, Da, Ha);
		int32 C = 0;
		for (int32 I : StIdx)
		{
			for (int32 Rw = 0; Rw < R; ++Rw) Res.VIdx[I * R + Rw] = First + C++;
		}
	}

	// -- materials / groups per edge
	TArray<int32> GrpIds;
	if (Pr.Groups.Num() == E) { for (FName G : Pr.Groups) GrpIds.Add(Buf.GroupId(G)); }
	else { const int32 G = Buf.GroupId(Pr.Group); GrpIds.Init(G, E); }
	TArray<FName> EdgeMat = Pr.EdgeMat;
	if (EdgeMat.Num() != E) { EdgeMat.Reset(); for (int32 K = 0; K < E; ++K) EdgeMat.Add(Pts[K].Mat); }
	TArray<int32> MatDefault;
	for (FName M : EdgeMat) MatDefault.Add(Buf.MaterialId(M));
	if (Pr.bTwoSided) { for (FName M : EdgeMat) Buf.TwoSided.Add(M); }
	const bool bMatStation = Pr.EdgeMatStation.Num() == N * E;
	TMap<FName, int32> Lut;
	if (bMatStation)
	{
		TArray<FName> Names;
		for (FName M : Pr.EdgeMatStation) Names.AddUnique(M);
		Names.Sort(FNameLexicalLess());
		for (FName M : Names) { Lut.Add(M, Buf.MaterialId(M)); if (Pr.bTwoSided) Buf.TwoSided.Add(M); }
	}

	// -- quads
	TArray<int32> Qi;
	for (int32 I = 0; I + 1 < N; ++I) { if (QuadOk[I]) Qi.Add(I); }
	int32 NQuads = 0;
	if (Qi.Num())
	{
		for (int32 K = 0; K < E; ++K)
		{
			const int32 R0 = Res.EdgeRows[K].X, R1 = Res.EdgeRows[K].Y;
			struct FQ { int32 A, B, C, D, Q; };
			TArray<FQ> Ok;
			for (int32 Q : Qi)
			{
				const FQ Qd{ Res.VIdx[Q * R + R0], Res.VIdx[(Q + 1) * R + R0], Res.VIdx[(Q + 1) * R + R1], Res.VIdx[Q * R + R1], Q };
				if (Qd.A >= 0 && Qd.B >= 0 && Qd.C >= 0 && Qd.D >= 0) Ok.Add(Qd);
			}
			if (Ok.Num() == 0) continue;
			const int32 K1 = (K + 1) % P;
			TArray<FIndex3i> T; TArray<int32> Mids;
			auto Emit = [&](bool bFirstHalf)
			{
				for (const FQ& Qd : Ok)
				{
					FIndex3i Ti = bFirstHalf ? FIndex3i(Qd.A, Qd.B, Qd.C) : FIndex3i(Qd.A, Qd.C, Qd.D);
					int32 HintStation = Qd.Q;
					double Do = O(HintStation, K1) - O(HintStation, K);
					double Dh = Hh(HintStation, K1) - Hh(HintStation, K);
					// A section opening from zero width has no starting normal.
					// Orient its surviving triangle using the nonzero end section.
					if (FMath::Sqrt(Do * Do + Dh * Dh) <= 1e-12)
					{
						++HintStation;
						Do = O(HintStation, K1) - O(HintStation, K);
						Dh = Hh(HintStation, K1) - Hh(HintStation, K);
					}
					const FVector3d& Nn = Frames.N[HintStation];
					const FVector3d& Bb = Frames.B[HintStation];
					const double Sd = Side * (-Dh);
					const FVector3d Want(Sd * Nn.X + Do * Bb.X, Sd * Nn.Y + Do * Bb.Y, Sd * Nn.Z + Do * Bb.Z);
					const FVector3d Fn = Cross3(Buf.V[Ti.B] - Buf.V[Ti.A], Buf.V[Ti.C] - Buf.V[Ti.A]);
					if (Dot3(Fn, Want) < 0) Ti = FIndex3i(Ti.A, Ti.C, Ti.B);
					const double Area = 0.5 * Norm3(Fn);
					if (Area >= 1e-10)
					{
						T.Add(Ti);
						Mids.Add(bMatStation ? Lut[Pr.EdgeMatStation[Qd.Q * E + K]] : MatDefault[K]);
					}
				}
			};
			Emit(true);
			Emit(false);
			Buf.AppendTriangles(T, Mids, GrpIds[K]);
			NQuads += Ok.Num();
		}
	}
	Res.NumQuads = NQuads;

	// -- caps
	if (Qi.Num())
	{
		int32 Start = Qi[0], Prev = Start;
		for (int32 X = 1; X < Qi.Num(); ++X)
		{
			if (Qi[X] != Prev + 1) { Res.Runs.Add(FIntPoint(Start, Prev + 1)); Start = Qi[X]; }
			Prev = Qi[X];
		}
		Res.Runs.Add(FIntPoint(Start, Prev + 1));
	}
	if ((Pr.bCapStart || Pr.bCapEnd) && Res.Runs.Num())
	{
		const int32 CapMid = Buf.MaterialId(Pr.CapMat.IsNone() ? Pts[0].Mat : Pr.CapMat);
		const int32 CapGid = GrpIds[0];
		TArray<int32> RingRows;
		for (int32 K = 0; K < P; ++K) RingRows.Add(Res.RowPoint.IndexOfByKey(K));
		for (const FIntPoint& Run : Res.Runs)
		{
			for (int32 End = 0; End < 2; ++End)
			{
				const bool bStart = End == 0;
				const int32 I = bStart ? Run.X : Run.Y;
				if ((bStart && !Pr.bCapStart) || (!bStart && !Pr.bCapEnd)) continue;
				TArray<int32> Ring;
				bool bMissing = false;
				for (int32 Rw : RingRows) { const int32 Vi = Res.VIdx[I * R + Rw]; if (Vi < 0) bMissing = true; Ring.Add(Vi); }
				if (bMissing) continue;
				TArray<FVector2d> Pts2;
				for (int32 K = 0; K < P; ++K) Pts2.Add(FVector2d(O(I, K), Hh(I, K)));
				TArray<bool> Keep;
				Keep.Init(true, P);
				for (int32 K = 1; K < P; ++K)
				{
					if (std::hypot(Pts2[K].X - Pts2[K - 1].X, Pts2[K].Y - Pts2[K - 1].Y) < 1e-12) Keep[K] = false;
				}
				TArray<int32> KeptIdx;
				for (int32 K = 0; K < P; ++K) { if (Keep[K]) KeptIdx.Add(K); }
				if (KeptIdx.Num() >= 3 && std::hypot(Pts2[KeptIdx.Last()].X - Pts2[KeptIdx[0]].X, Pts2[KeptIdx.Last()].Y - Pts2[KeptIdx[0]].Y) < 1e-12)
				{
					KeptIdx.Pop();
				}
				if (KeptIdx.Num() < 3) continue;
				TArray<FVector2d> Poly;
				TArray<int32> RingK;
				for (int32 K : KeptIdx) { Poly.Add(Pts2[K]); RingK.Add(Ring[K]); }
				if (FMath::Abs(FStreetGeometry::PolygonArea2D(Poly)) < 1e-12) continue;
				const FVector3d Hint = bStart ? FVector3d(-Frames.Th[I].X, -Frames.Th[I].Y, -Frames.Th[I].Z) : Frames.Th[I];
				const TArray<FIndex3i> Tris = FStreetGeometry::TriangulatePolygon2D(Poly);
				TArray<FIndex3i> T;
				for (const FIndex3i& Tr : Tris)
				{
					FIndex3i Ti(RingK[Tr.A], RingK[Tr.B], RingK[Tr.C]);
					const FVector3d Fn = Cross3(Buf.V[Ti.B] - Buf.V[Ti.A], Buf.V[Ti.C] - Buf.V[Ti.A]);
					if (Dot3(Fn, Hint) < 0) Ti = FIndex3i(Ti.A, Ti.C, Ti.B);
					if (0.5 * Norm3(Fn) >= 1e-10) T.Add(Ti);
				}
				Buf.AppendTriangles(T, CapMid, CapGid);
			}
		}
	}
	Res.TriRange = FIntPoint(Tri0, Buf.F.Num());
	return Res;
}

// ---------------------------------------------------------------------------------------------------------------
// FStreetNoise (noise.py)
// ---------------------------------------------------------------------------------------------------------------

namespace
{
constexpr uint32 kGold = 0x9E3779B1u;
constexpr uint32 kK2 = 0x85EBCA77u;
constexpr uint32 kK3 = 0xC2B2AE3Du;
double ToUnit(uint32 H) { return (double)H / 4294967296.0 * 2.0 - 1.0; }
double SmoothstepN(double T) { return T * T * (3.0 - 2.0 * T); }
}

uint32 FStreetNoise::LowBias32(uint32 X)
{
	X ^= X >> 16;
	X *= 0x7FEB352Du;
	X ^= X >> 15;
	X *= 0x846CA68Bu;
	X ^= X >> 16;
	return X;
}

double FStreetNoise::UnitNoise(uint32 I, uint32 Seed)
{
	return ToUnit(LowBias32((I * kGold) ^ LowBias32(Seed)));
}

double FStreetNoise::Lattice(int64 Ix, int64 Iy, int64 Iz, uint32 Seed)
{
	const uint32 Ux = (uint32)Ix, Uy = (uint32)Iy, Uz = (uint32)Iz;
	return ToUnit(LowBias32((Ux * kGold) ^ LowBias32((Uy * kK2) ^ LowBias32((Uz * kK3) ^ Seed))));
}

double FStreetNoise::ValueNoise3(const FVector3d& P, uint32 Seed)
{
	const double P0x = std::floor(P.X), P0y = std::floor(P.Y), P0z = std::floor(P.Z);
	const double Fx = SmoothstepN(P.X - P0x), Fy = SmoothstepN(P.Y - P0y), Fz = SmoothstepN(P.Z - P0z);
	const int64 Ix = (int64)P0x, Iy = (int64)P0y, Iz = (int64)P0z;
	const double C000 = Lattice(Ix, Iy, Iz, Seed);
	const double C100 = Lattice(Ix + 1, Iy, Iz, Seed);
	const double C010 = Lattice(Ix, Iy + 1, Iz, Seed);
	const double C110 = Lattice(Ix + 1, Iy + 1, Iz, Seed);
	const double C001 = Lattice(Ix, Iy, Iz + 1, Seed);
	const double C101 = Lattice(Ix + 1, Iy, Iz + 1, Seed);
	const double C011 = Lattice(Ix, Iy + 1, Iz + 1, Seed);
	const double C111 = Lattice(Ix + 1, Iy + 1, Iz + 1, Seed);
	const double X00 = C000 + (C100 - C000) * Fx;
	const double X10 = C010 + (C110 - C010) * Fx;
	const double X01 = C001 + (C101 - C001) * Fx;
	const double X11 = C011 + (C111 - C011) * Fx;
	const double Y0 = X00 + (X10 - X00) * Fy;
	const double Y1 = X01 + (X11 - X01) * Fy;
	return Y0 + (Y1 - Y0) * Fz;
}

double FStreetNoise::Fbm3(const FVector3d& P, uint32 Seed)
{
	const FVector3d Q(2.0 * P.X + 17.3, 2.0 * P.Y + 17.3, 2.0 * P.Z + 17.3);
	return (ValueNoise3(P, Seed) + 0.5 * ValueNoise3(Q, Seed)) / 1.5;
}

// ---------------------------------------------------------------------------------------------------------------
// ToDynamicMesh
// ---------------------------------------------------------------------------------------------------------------

int32 FStreetGeometry::ToDynamicMesh(const FStreetMeshBuilder& In, UE::Geometry::FDynamicMesh3& Out)
{
	using namespace UE::Geometry;
	Out.Clear();
	Out.EnableTriangleGroups(0);                                 // GC/DynamicMesh/DynamicMesh3.h:1015
	Out.EnableAttributes();                                      // :1048
	Out.Attributes()->EnableMaterialID();                        // GC/DynamicMesh/DynamicMeshAttributeSet.h:360
	for (const FVector3d& V : In.V)
	{
		Out.AppendVertex(FVector3d(100.0 * V.X, -100.0 * V.Y, 100.0 * V.Z));   // :668
	}
	FDynamicMeshUVOverlay* UVs = Out.Attributes()->PrimaryUV();
	FDynamicMeshMaterialAttribute* MatIds = Out.Attributes()->GetMaterialID();
	int32 Skipped = 0;
	for (int32 T = 0; T < In.F.Num(); ++T)
	{
		const FIndex3i& Tr = In.F[T];
		// Winding is KEPT: the Y mirror flips the geometric handedness, and GeometryCore's front-face normal is
		// cross(v2 - v0, v1 - v0) (GC/VectorUtil.h:80-87, "Unreal has Left-Hand Coordinate System"), the mirror image of the
		// right-handed cross(v1 - v0, v2 - v0) the JSON frame uses - the two flips cancel, so the UE face normal is exactly the
		// mirrored JSON normal (Streetscape.Geometry.ToDynamicMesh asserts it on the left kerb face).
		const int32 Tid = Out.AppendTriangle(FIndex3i(Tr.A, Tr.B, Tr.C), In.Grp.IsValidIndex(T) ? In.Grp[T] : 0);   // :677
		if (Tid < 0)
		{
			++Skipped;
			continue;
		}
		if (MatIds) MatIds->SetValue(Tid, In.Mat.IsValidIndex(T) ? In.Mat[T] : 0);
		if (UVs && In.UV.Num() == In.V.Num())
		{
			const int32 E0 = UVs->AppendElement(FVector2f((float)In.UV[Tr.A].X, (float)In.UV[Tr.A].Y));
			const int32 E1 = UVs->AppendElement(FVector2f((float)In.UV[Tr.B].X, (float)In.UV[Tr.B].Y));
			const int32 E2 = UVs->AppendElement(FVector2f((float)In.UV[Tr.C].X, (float)In.UV[Tr.C].Y));
			UVs->SetTriangle(Tid, FIndex3i(E0, E1, E2));
		}
	}
	FMeshNormals::InitializeOverlayToPerVertexNormals(Out.Attributes()->PrimaryNormals(), false);   // GC/DynamicMesh/MeshNormals.h:188
	if (Skipped)
	{
		UE_LOG(LogStreetscape, Warning, TEXT("ToDynamicMesh: %d of %d triangles refused by FDynamicMesh3 (non-manifold or duplicate)"), Skipped, In.F.Num());
	}
	return Skipped;
}

// ---------------------------------------------------------------------------------------------------------------
// measurements (mesh.py)
// ---------------------------------------------------------------------------------------------------------------

TArray<double> FStreetGeometry::StationValues(const FStreetMeshBuilder& Buf, const FString& ExcludePrefix)
{
	// mesh.NON_STATION_PREFIXES = ("marking:", "junction:", "corner_"). A dash end is an INTERPOLATED station; a
	// junction patch and a kerb corner are not swept along this spline at all - their vertices carry the s of
	// whatever arm they came from. None of the three is one of this spline's own stations, so none of them may
	// take part in the DESIGN.md 5 rule 2 comparison. ExcludePrefix is the caller's own extra prefix.
	static const TCHAR* kNonStation[] = { TEXT("junction:"), TEXT("corner_") };
	TSet<int32> Skip;
	for (int32 I = 0; I < Buf.GroupNames.Num(); ++I)
	{
		const FString N = Buf.GroupNames[I].ToString();
		bool bSkip = !ExcludePrefix.IsEmpty() && N.StartsWith(ExcludePrefix, ESearchCase::CaseSensitive);
		for (const TCHAR* P : kNonStation) bSkip = bSkip || N.StartsWith(P, ESearchCase::CaseSensitive);
		if (bSkip) Skip.Add(I);
	}
	TSet<int32> Vi;
	for (int32 T = 0; T < Buf.F.Num(); ++T)
	{
		if (Skip.Contains(Buf.Grp[T])) continue;
		for (int32 K = 0; K < 3; ++K) Vi.Add(Buf.F[T][K]);
	}
	TArray<double> S;
	for (int32 I : Vi) S.Add(Buf.VS[I]);
	S.Sort();
	TArray<double> U;
	for (double X : S) { if (U.Num() == 0 || U.Last() != X) U.Add(X); }
	return U;
}

FStreetGeometry::FOverlap FStreetGeometry::MeasureLateralOverlap(const FStreetMeshBuilder& Road, const FStreetMeshBuilder& Edge, int32 Side, double TuckDepth)
{
	FOverlap Out;
	const FString Marking = TEXT("marking:");
	const TArray<int32> Rv = Road.VerticesOfGroups(TEXT(""), nullptr, &Marking);
	Out.Stations = StationValues(Road, Marking);
	const FName Kerb(TEXT("kerb"));
	const TArray<int32> Kv = Edge.VerticesOfGroups(TEXT(""), &Kerb, nullptr);
	Out.PerStation.Init(NAN, Out.Stations.Num());
	bool bAny = false;
	for (int32 Si = 0; Si < Out.Stations.Num(); ++Si)
	{
		const double S = Out.Stations[Si];
		// road rows at this station: the outermost is the skirt, the one below it is the road-edge row at h0.
		// h0 is the CAMBER height at the kerb line, so the visible kerb block starts at h0 - tuck_depth, not at
		// -tuck_depth: with a 2.5 % camber on an 8 m carriageway h0 is -0.05, and a 6 mm drop kerb top would fall
		// below a fixed -0.03 threshold and be missed entirely (mesh.measure_lateral_overlap).
		double RoadExtent = -TNumericLimits<double>::Max(), KerbFace = TNumericLimits<double>::Max();
		int32 Nr = 0, Nk = 0;
		TArray<int32> RSel;
		for (int32 I : Rv) { if (FMath::Abs(Road.VS[I] - S) <= 1e-9) { RSel.Add(I); RoadExtent = FMath::Max(RoadExtent, Side * Road.VD[I]); ++Nr; } }
		if (Nr == 0) continue;
		TArray<double> Levels;
		for (int32 I : RSel) Levels.AddUnique(FMath::RoundToDouble(Side * Road.VD[I] * 1e9) / 1e9);
		Levels.Sort();
		const double EdgeD = Levels.Num() >= 2 ? Levels[Levels.Num() - 2] : Levels.Last();
		double H0 = TNumericLimits<double>::Max();
		for (int32 I : RSel) { if (FMath::Abs(Side * Road.VD[I] - EdgeD) <= 1e-9) H0 = FMath::Min(H0, Road.VH[I]); }
		for (int32 I : Kv)
		{
			if (FMath::Abs(Edge.VS[I] - S) > 1e-9) continue;
			if (Edge.VH[I] <= H0 - TuckDepth + 1e-9) continue;
			KerbFace = FMath::Min(KerbFace, Side * Edge.VD[I]);
			++Nk;
		}
		if (Nk == 0) continue;
		Out.PerStation[Si] = RoadExtent - KerbFace;
		Out.MinM = bAny ? FMath::Min(Out.MinM, Out.PerStation[Si]) : Out.PerStation[Si];
		Out.MaxM = bAny ? FMath::Max(Out.MaxM, Out.PerStation[Si]) : Out.PerStation[Si];
		bAny = true;
	}
	return Out;
}

int32 FStreetGeometry::CoincidentXYPositions(const FStreetMeshBuilder& A, const FStreetMeshBuilder& B, double DLo, double DHi, int32 Side, double TolXY, double TolZ, double Dedup)
{
	auto Positions = [&](const FStreetMeshBuilder& Buf)
	{
		TArray<FVector3d> Sel;
		for (int32 I = 0; I < Buf.V.Num(); ++I)
		{
			const double D = Side * Buf.VD[I];
			if (D >= DLo - 1e-12 && D <= DHi + 1e-12) Sel.Add(Buf.V[I]);
		}
		return DistinctPositions(Sel, Dedup);
	};
	const TArray<FVector3d> Pa = Positions(A);
	const TArray<FVector3d> Pb = Positions(B);
	if (Pa.Num() == 0 || Pb.Num() == 0) return 0;
	TMap<TPair<int64, int64>, TArray<int32>> Buckets;
	for (int32 J = 0; J < Pb.Num(); ++J)
	{
		Buckets.FindOrAdd(TPair<int64, int64>((int64)FMath::RoundToDouble(Pb[J].X / TolXY), (int64)FMath::RoundToDouble(Pb[J].Y / TolXY))).Add(J);
	}
	int32 Count = 0;
	for (int32 I = 0; I < Pa.Num(); ++I)
	{
		const int64 Kx = (int64)FMath::RoundToDouble(Pa[I].X / TolXY), Ky = (int64)FMath::RoundToDouble(Pa[I].Y / TolXY);
		for (int64 Dx = -1; Dx <= 1; ++Dx)
		{
			for (int64 Dy = -1; Dy <= 1; ++Dy)
			{
				if (const TArray<int32>* L = Buckets.Find(TPair<int64, int64>(Kx + Dx, Ky + Dy)))
				{
					for (int32 J : *L)
					{
						if (std::hypot(Pa[I].X - Pb[J].X, Pa[I].Y - Pb[J].Y) <= TolXY && FMath::Abs(Pa[I].Z - Pb[J].Z) > TolZ) ++Count;
					}
				}
			}
		}
	}
	return Count;
}

double FStreetGeometry::SurfaceHeightAt(const FStreetMeshBuilder& Buf, double S, double D, const FString& GroupPrefixExclude)
{
	TArray<int32> Ids;
	for (int32 I = 0; I < Buf.GroupNames.Num(); ++I) { if (!Buf.GroupNames[I].ToString().StartsWith(GroupPrefixExclude, ESearchCase::CaseSensitive)) Ids.Add(I); }
	for (int32 T = 0; T < Buf.F.Num(); ++T)
	{
		if (!Ids.Contains(Buf.Grp[T])) continue;
		const FIndex3i& Tr = Buf.F[T];
		const double S0 = Buf.VS[Tr.A], S1 = Buf.VS[Tr.B], S2 = Buf.VS[Tr.C];
		const double D0 = Buf.VD[Tr.A], D1 = Buf.VD[Tr.B], D2 = Buf.VD[Tr.C];
		if (FMath::Min3(S0, S1, S2) > S + 1e-9 || FMath::Max3(S0, S1, S2) < S - 1e-9 || FMath::Min3(D0, D1, D2) > D + 1e-9 || FMath::Max3(D0, D1, D2) < D - 1e-9) continue;
		const double X1 = S0, Y1 = D0, X2 = S1, Y2 = D1, X3 = S2, Y3 = D2;
		const double Det = (Y2 - Y3) * (X1 - X3) + (X3 - X2) * (Y1 - Y3);
		if (FMath::Abs(Det) < 1e-18) continue;
		const double L1 = ((Y2 - Y3) * (S - X3) + (X3 - X2) * (D - Y3)) / Det;
		const double L2 = ((Y3 - Y1) * (S - X3) + (X1 - X3) * (D - Y3)) / Det;
		const double L3 = 1.0 - L1 - L2;
		if (FMath::Min3(L1, L2, L3) >= -1e-9) return L1 * Buf.VH[Tr.A] + L2 * Buf.VH[Tr.B] + L3 * Buf.VH[Tr.C];
	}
	return NAN;
}
