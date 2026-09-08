#include "StreetscapeMassingActor.h"

#include "StreetGeometry.h"
#include "StreetscapeModule.h"

#include "Algo/Reverse.h"
#include "Components/DynamicMeshComponent.h"
#include "DynamicMesh/DynamicMesh3.h"
#include "Dom/JsonObject.h"
#include "Materials/MaterialInterface.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

using UE::Geometry::FIndex3i;
using UE::Geometry::FDynamicMesh3;

AStreetscapeMassingActor::AStreetscapeMassingActor()
{
	PrimaryActorTick.bCanEverTick = false;
	Mesh = CreateDefaultSubobject<UDynamicMeshComponent>(TEXT("Massing"));
	Mesh->SetMobility(EComponentMobility::Static);
	SetRootComponent(Mesh);
	bIsSpatiallyLoaded = true;
}

namespace
{
/** Signed area of a ring in the JSON frame (x east, y north); > 0 = counter-clockwise. */
double SignedArea(const TArray<FVector2d>& P)
{
	double A = 0.0;
	for (int32 I = 0, N = P.Num(); I < N; ++I)
	{
		const FVector2d& A0 = P[I];
		const FVector2d& A1 = P[(I + 1) % N];
		A += A0.X * A1.Y - A1.X * A0.Y;
	}
	return 0.5 * A;
}

bool ReadRing(const TSharedPtr<FJsonObject>& RingObj, TArray<FVector2d>& Out, bool& bHole)
{
	bHole = false;
	RingObj->TryGetBoolField(TEXT("hole"), bHole);
	const TArray<TSharedPtr<FJsonValue>>* Pts = nullptr;
	if (!RingObj->TryGetArrayField(TEXT("pts"), Pts)) return false;
	Out.Reset();
	for (const TSharedPtr<FJsonValue>& V : *Pts)
	{
		const TArray<TSharedPtr<FJsonValue>>* P = nullptr;
		if (!V->TryGetArray(P) || P->Num() < 2) continue;
		Out.Add(FVector2d((*P)[0]->AsNumber(), (*P)[1]->AsNumber()));
	}
	// the adapter closes every ring (last point == first): drop the repeat
	while (Out.Num() >= 2 && FMath::Abs(Out[0].X - Out.Last().X) < 1e-9 && FMath::Abs(Out[0].Y - Out.Last().Y) < 1e-9)
	{
		Out.Pop();
	}
	return Out.Num() >= 3;
}
}   // namespace

bool AStreetscapeMassingActor::BuildFromFile(const FString& Path)
{
	const double T0 = FPlatformTime::Seconds();
	SourceFile = Path;
	Stats = FStreetMassingStats();

	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		UE_LOG(LogStreetscape, Error, TEXT("MassingActor: cannot read %s"), *Path);
		return false;
	}
	// buildings_x{i}_y{j}.jsonl -> tile indices, for the label and the report
	{
		FString Base = FPaths::GetBaseFilename(Path);
		FString Rest;
		if (Base.Split(TEXT("_x"), nullptr, &Rest))
		{
			FString Xs, Ys;
			if (Rest.Split(TEXT("_y"), &Xs, &Ys))
			{
				TileX = FCString::Atoi(*Xs);
				TileY = FCString::Atoi(*Ys);
			}
		}
	}

	TArray<FString> Lines;
	Text.ParseIntoArrayLines(Lines);
	Text.Empty();

	FStreetMeshBuilder B;
	const int32 MatId = B.MaterialId(FName(TEXT("massing_grey")));
	const int32 GrpId = B.GroupId(FName(TEXT("massing")));
	double MinZ = TNumericLimits<double>::Max(), MaxZ = -TNumericLimits<double>::Max();

	TArray<FVector3d> Pos;
	TArray<FVector2d> Uv;
	TArray<double> Zero;
	TArray<FIndex3i> Tris;
	TArray<int32> TopRing, BotRing;
	TArray<FVector2d> Ring;

	for (const FString& Line : Lines)
	{
		if (Line.TrimStartAndEnd().IsEmpty()) continue;
		TSharedPtr<FJsonObject> Obj;
		TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Line);
		if (!FJsonSerializer::Deserialize(Reader, Obj) || !Obj.IsValid()) continue;

		double BaseZ = 0, H = 0, Skirt = 0;
		Obj->TryGetNumberField(TEXT("base_z"), BaseZ);
		Obj->TryGetNumberField(TEXT("h"), H);
		if (!Obj->TryGetNumberField(TEXT("skirt"), Skirt)) Skirt = BaseZ - 1.0;
		double Top = BaseZ + H;
		if (Top < Skirt + MinHeightM)
		{
			Top = Skirt + MinHeightM;
			Stats.ClampedHeights++;
		}
		const TArray<TSharedPtr<FJsonValue>>* Rings = nullptr;
		if (!Obj->TryGetArrayField(TEXT("rings"), Rings)) continue;
		Stats.Buildings++;

		for (const TSharedPtr<FJsonValue>& RV : *Rings)
		{
			const TSharedPtr<FJsonObject>* RO = nullptr;
			if (!RV->TryGetObject(RO)) continue;
			bool bHole = false;
			if (!ReadRing(*RO, Ring, bHole))
			{
				Stats.SkippedRings++;
				continue;
			}
			Stats.Rings++;
			if (bHole) Stats.HoleRings++;

			// outer rings counter-clockwise (walls face out), hole rings clockwise (walls face into the courtyard)
			const bool bWantCCW = !bHole;
			if ((SignedArea(Ring) > 0.0) != bWantCCW) Algo::Reverse(Ring);

			const int32 N = Ring.Num();
			Pos.Reset(); Uv.Reset(); Zero.Reset();
			for (int32 I = 0; I < N; ++I) { Pos.Add(FVector3d(Ring[I].X, Ring[I].Y, Skirt)); Uv.Add(FVector2d(Ring[I].X, Skirt)); }
			for (int32 I = 0; I < N; ++I) { Pos.Add(FVector3d(Ring[I].X, Ring[I].Y, Top)); Uv.Add(FVector2d(Ring[I].X, Top)); }
			Zero.SetNumZeroed(Pos.Num());
			const int32 V0 = B.AppendVertices(Pos, Uv, Zero, Zero, Zero);

			Tris.Reset();
			for (int32 I = 0; I < N; ++I)
			{
				const int32 J = (I + 1) % N;
				const int32 B0 = V0 + I, B1 = V0 + J, T1 = V0 + N + J, Tp0 = V0 + N + I;
				Tris.Add(FIndex3i(B0, B1, T1));
				Tris.Add(FIndex3i(B0, T1, Tp0));
			}
			B.AppendTriangles(Tris, MatId, GrpId);

			if (!bHole)
			{
				TopRing.Reset(); BotRing.Reset();
				for (int32 I = 0; I < N; ++I) TopRing.Add(V0 + N + I);
				for (int32 I = N - 1; I >= 0; --I) BotRing.Add(V0 + I);
				B.AppendPolygon(TopRing, MatId, GrpId, FVector3d(0, 0, 1));
				B.AppendPolygon(BotRing, MatId, GrpId, FVector3d(0, 0, -1));
			}
			MinZ = FMath::Min(MinZ, Skirt);
			MaxZ = FMath::Max(MaxZ, Top);
		}
	}

	Stats.Verts = B.V.Num();
	Stats.Tris = B.F.Num();
	Stats.MinZM = Stats.Buildings ? MinZ : 0.0;
	Stats.MaxZM = Stats.Buildings ? MaxZ : 0.0;

	FDynamicMesh3 DM;
	FStreetGeometry::ToDynamicMesh(B, DM);
	Mesh->SetMesh(MoveTemp(DM));
	TArray<UMaterialInterface*> Mats;
	Mats.Add(MassingMaterial);
	Mesh->ConfigureMaterialSet(Mats);
	Mesh->SetTangentsType(EDynamicMeshComponentTangentsMode::AutoCalculated);
	Mesh->SetMeshDrawPath(EDynamicMeshDrawPath::StaticDraw);
	Mesh->SetComplexAsSimpleCollisionEnabled(true, true);
	Stats.BuildMs = (FPlatformTime::Seconds() - T0) * 1000.0;
	UE_LOG(LogStreetscape, Verbose, TEXT("MassingActor %s: %d buildings, %d rings (%d holes), %d verts / %d tris in %.0f ms"),
		*FPaths::GetCleanFilename(Path), Stats.Buildings, Stats.Rings, Stats.HoleRings, Stats.Verts, Stats.Tris, Stats.BuildMs);
	return true;
}
