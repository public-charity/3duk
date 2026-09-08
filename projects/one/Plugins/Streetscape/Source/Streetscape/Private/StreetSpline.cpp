#include "StreetSpline.h"
#include "StreetTerrainSource.h"
#include "StreetscapeJson.h"
#include "StreetscapeModule.h"
#include "Dom/JsonObject.h"

// ---------------------------------------------------------------------------------------------------------------
// UStreetSplineMetadata
// ---------------------------------------------------------------------------------------------------------------

namespace
{
FStreetPoint LerpPoint(const FStreetPoint& A, const FStreetPoint& B, double T)
{
	FStreetPoint P;
	P.X = A.X + (B.X - A.X) * T;
	P.Y = A.Y + (B.Y - A.Y) * T;
	if (A.Z.IsSet() && B.Z.IsSet()) P.Z = A.Z.GetValue() + (B.Z.GetValue() - A.Z.GetValue()) * T;
	if (A.RollDeg.IsSet() && B.RollDeg.IsSet()) P.RollDeg = A.RollDeg.GetValue() + (B.RollDeg.GetValue() - A.RollDeg.GetValue()) * T;
	if (A.WidthM.IsSet() && B.WidthM.IsSet()) P.WidthM = A.WidthM.GetValue() + (B.WidthM.GetValue() - A.WidthM.GetValue()) * T;
	return P;
}
}

void UStreetSplineMetadata::InsertPoint(int32 Index, float t, bool bClosedLoop)
{
	Modify();
	const int32 Prev = Index - 1;
	FStreetPoint P;
	if (Points.IsValidIndex(Prev) && Points.IsValidIndex(Index)) P = LerpPoint(Points[Prev], Points[Index], t);
	else if (Points.IsValidIndex(Prev)) P = Points[Prev];
	else if (Points.IsValidIndex(Index)) P = Points[Index];
	Points.Insert(P, FMath::Clamp(Index, 0, Points.Num()));
}

void UStreetSplineMetadata::UpdatePoint(int32 Index, float t, bool bClosedLoop)
{
	if (!Points.IsValidIndex(Index)) return;
	Modify();
	const int32 Prev = Index - 1, Next = Index + 1;
	if (Points.IsValidIndex(Prev) && Points.IsValidIndex(Next))
	{
		const FStreetPoint L = LerpPoint(Points[Prev], Points[Next], t);
		Points[Index].WidthM = L.WidthM;
		Points[Index].RollDeg = L.RollDeg;
	}
}

void UStreetSplineMetadata::AddPoint(float InputKey)
{
	Modify();
	const int32 Index = FMath::Clamp((int32)InputKey, 0, Points.Num());
	FStreetPoint P;
	if (Points.Num() > 0) P = Points[FMath::Min(Index, Points.Num() - 1)];
	P.Tags.Reset();
	Points.Insert(P, Index);
}

void UStreetSplineMetadata::RemovePoint(int32 Index)
{
	if (!Points.IsValidIndex(Index)) return;
	Modify();
	Points.RemoveAt(Index);
}

void UStreetSplineMetadata::DuplicatePoint(int32 Index)
{
	if (!Points.IsValidIndex(Index)) return;
	Modify();
	Points.Insert(Points[Index], Index);
}

void UStreetSplineMetadata::CopyPoint(const USplineMetadata* FromSplineMetadata, int32 FromIndex, int32 ToIndex)
{
	const UStreetSplineMetadata* From = Cast<UStreetSplineMetadata>(FromSplineMetadata);
	if (!From || !From->Points.IsValidIndex(FromIndex) || !Points.IsValidIndex(ToIndex)) return;
	Modify();
	Points[ToIndex] = From->Points[FromIndex];
}

void UStreetSplineMetadata::Reset(int32 NumPoints)
{
	Modify();
	Points.Reset();
	Points.SetNum(NumPoints);
}

void UStreetSplineMetadata::Fixup(int32 NumPoints, USplineComponent* SplineComp)
{
	if (Points.Num() != NumPoints)
	{
		Points.SetNum(NumPoints);
	}
	for (int32 I = 0; I < NumPoints && SplineComp; ++I)
	{
		const FVector3d M = FStreetscapeJson::ToJson(SplineComp->GetLocationAtSplinePoint(I, ESplineCoordinateSpace::Local));
		Points[I].X = M.X;
		Points[I].Y = M.Y;
	}
}

// ---------------------------------------------------------------------------------------------------------------
// UStreetSplineComponent
// ---------------------------------------------------------------------------------------------------------------

UStreetSplineComponent::UStreetSplineComponent(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
	Metadata = ObjectInitializer.CreateDefaultSubobject<UStreetSplineMetadata>(this, TEXT("StreetMetadata"));
	bSplineHasBeenEdited = true;
}

const FStreetSamples* UStreetSplineComponent::Build(const IStreetTerrainSource* Terrain, const FStreetSiteProfiles& Profiles, FString* Error, bool bForce)
{
	const FString Key = FStreetscapeJson::Canonical(FStreetscapeJson::WriteSpline(Def)) + TEXT("|") + (Terrain ? Terrain->Describe() : TEXT("no-terrain"))
		+ FString::Printf(TEXT("|profiles:%d/%d/%d"), Profiles.Road.Num(), Profiles.Edge.Num(), Profiles.Hedge.Num());
	if (!bForce && Samples.IsValid() && Key == CacheKey)
	{
		return Samples.Get();
	}
	TUniquePtr<FStreetSamples> S = MakeUnique<FStreetSamples>();
	FString Err;
	if (!FStreetSplineMath::Build(Def, Profiles, Terrain, *S, &Err))
	{
		UE_LOG(LogStreetscape, Error, TEXT("StreetSplineComponent %s: %s"), *Def.Id, *Err);
		if (Error) *Error = Err;
		Samples.Reset();
		CacheKey.Reset();
		return nullptr;
	}
	Samples = MoveTemp(S);
	CacheKey = Key;
	return Samples.Get();
}

FVector3d UStreetSplineComponent::WaypointJson(int32 Index) const
{
	if (!Def.Points.IsValidIndex(Index)) return FVector3d::ZeroVector;
	const FStreetPoint& P = Def.Points[Index];
	return FVector3d(P.X, P.Y, P.Z.Get(0.0));
}

void UStreetSplineComponent::SetWaypointsJson(const TArray<FStreetPoint>& Points)
{
	Def.Points = Points;
	SyncComponentFromDef();
	MarkDirty();
}

void UStreetSplineComponent::SyncComponentFromDef()
{
	ClearSplinePoints(false);
	for (int32 I = 0; I < Def.Points.Num(); ++I)
	{
		AddSplinePoint(FStreetscapeJson::ToUE(WaypointJson(I)), ESplineCoordinateSpace::Local, false);
		SetSplinePointType(I, ESplinePointType::CurveClamped, false);
	}
	if (Metadata)
	{
		Metadata->Points = Def.Points;
	}
	UpdateSpline();
}

void UStreetSplineComponent::SyncDefFromComponent()
{
	const int32 N = GetNumberOfSplinePoints();
	TArray<FStreetPoint> Points;
	Points.SetNum(N);
	for (int32 I = 0; I < N; ++I)
	{
		if (Def.Points.IsValidIndex(I)) Points[I] = Def.Points[I];
		else if (Metadata && Metadata->Points.IsValidIndex(I)) Points[I] = Metadata->Points[I];
		const FVector3d M = FStreetscapeJson::ToJson(GetLocationAtSplinePoint(I, ESplineCoordinateSpace::Local));
		Points[I].X = M.X;
		Points[I].Y = M.Y;
	}
	Def.Points = Points;
	if (Metadata) Metadata->Points = Points;
	MarkDirty();
}
