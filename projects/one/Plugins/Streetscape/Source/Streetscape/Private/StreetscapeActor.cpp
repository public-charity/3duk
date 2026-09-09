#include "StreetscapeActor.h"

#include "Components/PrimitiveComponent.h"

#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "StreetGeometry.h"
#include "StreetMaterialTable.h"
#include "StreetOverlayComponent.h"
#include "StreetSpline.h"
#include "StreetTerrainSource.h"
#include "StreetscapeJson.h"
#include "StreetscapeModule.h"
#include "StreetscapeSettings.h"
#include "StreetscapeSiteActor.h"
#include "UObject/ObjectSaveContext.h"

namespace
{
/** The placeholder mesh an instance kind is drawn with until real assets exist (DESIGN.md 15). */
const TCHAR* MeshPathForKind(FName Kind)
{
	const FString K = Kind.ToString();
	if (K == TEXT("post_round")) return TEXT("/Engine/BasicShapes/Cylinder.Cylinder");
	if (K == TEXT("leaf_card") || K.StartsWith(TEXT("foliage_mesh"))) return TEXT("/Engine/BasicShapes/Plane.Plane");
	return TEXT("/Engine/BasicShapes/Cube.Cube");
}
}   // namespace

AStreetscapeActor::AStreetscapeActor()
{
	PrimaryActorTick.bCanEverTick = false;
	Spline = CreateDefaultSubobject<UStreetSplineComponent>(TEXT("Spline"));
	SetRootComponent(Spline);
	// Every child (the renderers, the overlay, the ISM components) is Static, and USceneComponent::AttachToComponent
	// refuses to attach a Static child to a Movable parent (SceneComponent.cpp, "is not static , cannot attach").
	// Left at the default Movable the root took none of them: the actor drew correctly only because every vertex
	// and instance transform is absolute world space at the identity, and each street logged ~16 attach warnings.
	Spline->SetMobility(EComponentMobility::Static);
#if WITH_EDITOR
	bIsSpatiallyLoaded = true;
	bEnableAutoLODGeneration = false;
#endif
}

UStreetRendererBase* AStreetscapeActor::MakeRenderer(UClass* Class, FName Name)
{
	UStreetRendererBase* C = NewObject<UStreetRendererBase>(this, Class, Name);
	C->SetupAttachment(GetRootComponent());
	C->RegisterComponent();
	AddInstanceComponent(C);
	return C;
}

void AStreetscapeActor::ApplyDefinition(const FStreetSplineDef& Def, const FStreetSiteProfiles& Profiles, const FVector2D& OriginEN)
{
	StreetId = Def.Id;
	DocOriginEN = OriginEN;
	DocProfiles = Profiles;
	Spline->Def = Def;
	Spline->SetWaypointsJson(Def.Points);
	Spline->MarkDirty();

	if (!Def.ProfileIds.Road.IsEmpty() && !Road)
	{
		Road = Cast<UStreetRoadRenderer>(MakeRenderer(UStreetRoadRenderer::StaticClass(), TEXT("Road")));
	}
	if (!Def.ProfileIds.EdgeLeft.IsEmpty() && !EdgeLeft)
	{
		EdgeLeft = Cast<UStreetEdgeRenderer>(MakeRenderer(UStreetEdgeRenderer::StaticClass(), TEXT("EdgeLeft")));
		EdgeLeft->Side = EStreetSide::Left;
	}
	if (!Def.ProfileIds.EdgeRight.IsEmpty() && !EdgeRight)
	{
		EdgeRight = Cast<UStreetEdgeRenderer>(MakeRenderer(UStreetEdgeRenderer::StaticClass(), TEXT("EdgeRight")));
		EdgeRight->Side = EStreetSide::Right;
	}
	if (!Def.ProfileIds.HedgeLeft.IsEmpty() && !HedgeLeft)
	{
		HedgeLeft = Cast<UStreetHedgeRenderer>(MakeRenderer(UStreetHedgeRenderer::StaticClass(), TEXT("HedgeLeft")));
		HedgeLeft->Side = EStreetSide::Left;
	}
	if (!Def.ProfileIds.HedgeRight.IsEmpty() && !HedgeRight)
	{
		HedgeRight = Cast<UStreetHedgeRenderer>(MakeRenderer(UStreetHedgeRenderer::StaticClass(), TEXT("HedgeRight")));
		HedgeRight->Side = EStreetSide::Right;
	}
	if (Def.bHasOverlay && Def.Overlay.Pts.Num() >= 2)
	{
		if (!Overlay)
		{
			Overlay = NewObject<UStreetOverlayComponent>(this, UStreetOverlayComponent::StaticClass(), TEXT("Overlay"));
			Overlay->SetupAttachment(GetRootComponent());
			Overlay->RegisterComponent();
			AddInstanceComponent(Overlay);
		}
		// build.build_overlay: densify the raw polyline at 2 m before draping (the drape and the 0.3 m lift are the
		// component's job, so the two engines lift by the same constant)
		const double StepM = 2.0;
		TArray<FVector> Dense;
		Dense.Add(FVector(Def.Overlay.Pts[0].X, Def.Overlay.Pts[0].Y, Def.Overlay.Pts[0].Z));
		for (int32 I = 0; I + 1 < Def.Overlay.Pts.Num(); ++I)
		{
			const FVector3d A = Def.Overlay.Pts[I];
			const FVector3d B = Def.Overlay.Pts[I + 1];
			const double D = FMath::Sqrt((B.X - A.X) * (B.X - A.X) + (B.Y - A.Y) * (B.Y - A.Y));
			const int32 Nn = D > 0 ? (int32)FMath::FloorToDouble(D / StepM) : 0;
			for (int32 K = 1; K <= Nn; ++K)
			{
				const double T = K * StepM / D;
				if (T < 1.0) Dense.Add(FVector(A.X + (B.X - A.X) * T, A.Y + (B.Y - A.Y) * T, A.Z + (B.Z - A.Z) * T));
			}
			Dense.Add(FVector(B.X, B.Y, B.Z));
		}
		Overlay->SetPointsJson(Dense, StreetId);
	}
#if WITH_EDITOR
	SetActorLabel(StreetId);
#endif
}

FStreetSiteProfiles AStreetscapeActor::ResolveProfiles() const
{
	FStreetSiteProfiles Out;
	if (AStreetscapeSiteActor* Site = AStreetscapeSiteActor::Get(GetWorld()))
	{
		Out = Site->AssetProfiles();
	}
	for (const TPair<FString, FRoadProfileData>& Kv : DocProfiles.Road) Out.Road.Add(Kv.Key, Kv.Value);
	for (const TPair<FString, FEdgeProfileData>& Kv : DocProfiles.Edge) Out.Edge.Add(Kv.Key, Kv.Value);
	for (const TPair<FString, FHedgeProfileData>& Kv : DocProfiles.Hedge) Out.Hedge.Add(Kv.Key, Kv.Value);
	return Out;
}

const FStreetSamples* AStreetscapeActor::GetSamples() const
{
	return Spline ? Spline->GetSamples() : nullptr;
}

void AStreetscapeActor::RebuildAll()
{
	FString Err;
	if (!RebuildAllChecked(&Err))
	{
		UE_LOG(LogStreetscape, Error, TEXT("RebuildAll(%s) failed: %s"), *StreetId, *Err);
	}
}

bool AStreetscapeActor::RebuildAllChecked(FString* Error)
{
	if (bRebuilding) return true;
	TGuardValue<bool> Guard(bRebuilding, true);
	bPendingRebuild = false;

	AStreetscapeSiteActor* Site = AStreetscapeSiteActor::Get(GetWorld());
	const IStreetTerrainSource* Terrain = Site ? Site->TerrainForOrigin(DocOriginEN.X, DocOriginEN.Y) : nullptr;
	const UStreetMaterialTable* Materials = Site ? Site->Materials.Get() : nullptr;
	const FStreetSiteProfiles Profiles = ResolveProfiles();

	FString BuildErr;
	const FStreetSamples* Samples = Spline->Build(Terrain, Profiles, &BuildErr, true);
	if (!Samples)
	{
		if (Error) *Error = BuildErr;
		return false;
	}

	UStreetRendererBase* Rs[5] = { Road, EdgeLeft, EdgeRight, HedgeLeft, HedgeRight };
	const TCHAR* RNames[5] = { TEXT("road"), TEXT("edge_left"), TEXT("edge_right"), TEXT("hedge_left"), TEXT("hedge_right") };
	// STAGES 5.7 / BRIEF 1.1 "shares the same spline": the edge renderer must sample the road's stations, not its
	// own. Checked here, on every build of every spline, instead of only for the actors whose stats are dumped.
	TSet<double> StationSet;
	StationSet.Reserve(Samples->S.Num());
	for (double V : Samples->S) StationSet.Add(V);
	for (int32 K = 0; K < 5; ++K)
	{
		UStreetRendererBase* R = Rs[K];
		if (!R) continue;
		FStreetRenderResult Res;
		R->BuildFrom(*Samples, Terrain, Res);
		const TArray<double> St = FStreetGeometry::StationValues(Res.Buffer);
		if (K == 0)
		{
			if (St.Num() != Samples->S.Num())
			{
				if (Error) *Error = FString::Printf(TEXT("%s: road buffer has %d stations, the spline has %d"), *StreetId, St.Num(), Samples->S.Num());
				return false;
			}
			for (int32 I = 0; I < St.Num(); ++I)
			{
				if (St[I] != Samples->S[I])
				{
					if (Error) *Error = FString::Printf(TEXT("%s: road station %d is %.17g, the spline's is %.17g"), *StreetId, I, St[I], Samples->S[I]);
					return false;
				}
			}
		}
		else
		{
			for (double V : St)
			{
				if (!StationSet.Contains(V))
				{
					if (Error) *Error = FString::Printf(TEXT("%s: %s buffer has station %.17g, which is not one of the spline's %d stations"),
						*StreetId, RNames[K], V, Samples->S.Num());
					return false;
				}
			}
		}
		R->Commit(Res, Materials);
	}
	RebuildInstanceMeshComponents();
	if (Overlay) Overlay->Redraw();
	UpdateStreamingBounds();
	return true;
}

bool AStreetscapeActor::UpdateStreamingBounds()
{
	FBox B(ForceInit);
	for (UActorComponent* C : GetComponents())
	{
		if (const UPrimitiveComponent* P = Cast<UPrimitiveComponent>(C))
		{
			// CalcBounds, not the cached Bounds: this runs immediately after Commit() replaced the mesh, and the
			// cached bounds are only refreshed when the render state is next updated.
			const FBoxSphereBounds Bs = P->CalcBounds(P->GetComponentTransform());
			if (Bs.SphereRadius <= 0.0) continue;
			B += Bs.GetBox();
		}
	}
	if (!B.IsValid) return false;
	// A metre of slack in XY and ten in Z: the box only has to put the actor in the right World Partition cell,
	// and being generous costs nothing while being short by a centimetre loses the street.
	StreamingBoundsUE = B.ExpandBy(FVector(100.0, 100.0, 1000.0));
	return true;
}

#if WITH_EDITOR
void AStreetscapeActor::GetStreamingBounds(FBox& OutRuntimeBounds, FBox& OutEditorBounds) const
{
	if (StreamingBoundsUE.IsValid)
	{
		OutRuntimeBounds = StreamingBoundsUE;
		OutEditorBounds = StreamingBoundsUE;
		return;
	}
	Super::GetStreamingBounds(OutRuntimeBounds, OutEditorBounds);
}
#endif

void AStreetscapeActor::RebuildInstanceMeshComponents()
{
	for (UInstancedStaticMeshComponent* C : InstanceMeshComponents)
	{
		if (C) C->DestroyComponent();
	}
	InstanceMeshComponents.Reset();

	struct FKey { FName Kind; FName Material; FVector3d Size; };
	TArray<FKey> Keys;
	TArray<TArray<FTransform>> Xf;
	AStreetscapeSiteActor* Site = AStreetscapeSiteActor::Get(GetWorld());
	const UStreetMaterialTable* Materials = Site ? Site->Materials.Get() : nullptr;

	UStreetRendererBase* Rs[5] = { Road, EdgeLeft, EdgeRight, HedgeLeft, HedgeRight };
	for (UStreetRendererBase* R : Rs)
	{
		if (!R) continue;
		for (const FStreetInstance& In : R->GetInstances())
		{
			int32 Idx = INDEX_NONE;
			for (int32 I = 0; I < Keys.Num(); ++I)
			{
				if (Keys[I].Kind == In.Kind && Keys[I].Material == In.Material && Keys[I].Size.Equals(In.Size, 1e-9)) { Idx = I; break; }
			}
			if (Idx == INDEX_NONE)
			{
				Idx = Keys.Add({ In.Kind, In.Material, In.Size });
				Xf.AddDefaulted();
			}
			Xf[Idx].Add(In.ToUETransform());
		}
	}
	for (int32 I = 0; I < Keys.Num(); ++I)
	{
		const bool bFoliage = Keys[I].Kind == FName(TEXT("leaf_card"));
		UClass* Class = bFoliage ? UHierarchicalInstancedStaticMeshComponent::StaticClass() : UInstancedStaticMeshComponent::StaticClass();
		const FName Name = MakeUniqueObjectName(this, Class, *FString::Printf(TEXT("ISM_%s_%d"), *Keys[I].Kind.ToString(), I));
		UInstancedStaticMeshComponent* C = NewObject<UInstancedStaticMeshComponent>(this, Class, Name);
		C->SetupAttachment(GetRootComponent());
		C->SetMobility(EComponentMobility::Static);
		C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		if (UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, MeshPathForKind(Keys[I].Kind)))
		{
			C->SetStaticMesh(Mesh);
		}
		if (Materials)
		{
			if (UMaterialInterface* M = Materials->Resolve(Keys[I].Material)) C->SetMaterial(0, M);
		}
		C->RegisterComponent();
		AddInstanceComponent(C);
		C->AddInstances(Xf[I], false, true);
		InstanceMeshComponents.Add(C);
	}
}

TMap<FString, const FStreetMeshBuilder*> AStreetscapeActor::Buffers() const
{
	TMap<FString, const FStreetMeshBuilder*> Out;
	auto Add = [&Out](const FString& Name, const UStreetRendererBase* R)
	{
		if (R && R->GetLastBuffer().V.Num()) Out.Add(Name, &R->GetLastBuffer());
	};
	Add(TEXT("road"), Road);
	Add(TEXT("edge_left"), EdgeLeft);
	Add(TEXT("edge_right"), EdgeRight);
	Add(TEXT("hedge_left"), HedgeLeft);
	Add(TEXT("hedge_right"), HedgeRight);
	return Out;
}

TMap<FName, int32> AStreetscapeActor::InstanceCounts() const
{
	TMap<FName, int32> Out;
	const UStreetRendererBase* Rs[5] = { Road, EdgeLeft, EdgeRight, HedgeLeft, HedgeRight };
	for (const UStreetRendererBase* R : Rs)
	{
		if (!R) continue;
		for (const FStreetInstance& In : R->GetInstances()) Out.FindOrAdd(In.Kind) += 1;
	}
	return Out;
}

int32 AStreetscapeActor::MarkingStrips() const
{
	return Road ? Road->GetMarkingStrips() : 0;
}

bool AStreetscapeActor::ToJson(TSharedRef<FJsonObject> Out) const
{
	if (!Spline) return false;
	const TSharedRef<FJsonObject> S = FStreetscapeJson::WriteSpline(Spline->Def);
	for (const TPair<FString, TSharedPtr<FJsonValue>>& Kv : S->Values) Out->SetField(FString(*Kv.Key), Kv.Value);
	return true;
}

bool AStreetscapeActor::FromJson(const TSharedRef<FJsonObject>& In, FText* Err)
{
	FStreetSplineDef Def;
	TArray<FString> Problems;
	if (!FStreetscapeJson::ReadSpline(In, Def, Problems))
	{
		if (Err) *Err = FText::FromString(FString::Join(Problems, TEXT(" | ")));
		return false;
	}
	ApplyDefinition(Def, DocProfiles, DocOriginEN);
	return true;
}

void AStreetscapeActor::PostSaveRoot(FObjectPostSaveRootContext ObjectSaveContext)
{
	Super::PostSaveRoot(ObjectSaveContext);
	UStreetRendererBase* Rs[5] = { Road, EdgeLeft, EdgeRight, HedgeLeft, HedgeRight };
	for (UStreetRendererBase* R : Rs)
	{
		if (R) R->RestoreAfterSave();
	}
}

void AStreetscapeActor::PostRegisterAllComponents()
{
	Super::PostRegisterAllComponents();
	if (bPendingRebuild && !StreetId.IsEmpty())
	{
		RebuildAll();
	}
}
