#include "StreetOverlayComponent.h"

#include "Components/LineBatchComponent.h"
#include "Engine/World.h"
#include "HAL/IConsoleManager.h"
#include "Misc/Crc.h"
#include "SceneManagement.h"
#include "StreetTerrainSource.h"
#include "StreetscapeJson.h"
#include "StreetscapeSettings.h"
#include "StreetscapeSiteActor.h"
#include "UObject/UObjectIterator.h"

namespace
{
void RefreshStreetOverlays(IConsoleVariable*)
{
	for (TObjectIterator<UStreetOverlayComponent> It; It; ++It)
	{
		if (It->IsRegistered()) It->Redraw();
	}
}

// A process-wide opt-in also covers existing saved actors and newly streamed cells.
// Engine/Source/Runtime/Core/Public/HAL/IConsoleManager.h:1598 callback constructor.
FAutoConsoleVariable CVarStreetOverlay(TEXT("streetscape.Overlay"), 0,
	TEXT("OSM debug lines: 0 hidden (default), 1 visible. Also controlled by the explorer O key."),
	FConsoleVariableDelegate::CreateStatic(&RefreshStreetOverlays));
}

UStreetOverlayComponent::UStreetOverlayComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
	SetMobility(EComponentMobility::Static);
}

void UStreetOverlayComponent::SetPointsJson(const TArray<FVector>& Pts, const FString& StreetId)
{
	PtsJson = Pts;
	const uint32 Crc = FCrc::StrCrc32(*StreetId);
	OverlayBatchId = Crc != 0 ? Crc : 1u;
	Redraw();
}

void UStreetOverlayComponent::Redraw()
{
	ClearDraw();
	DrapedUE.Reset();
	if (PtsJson.Num() < 2) return;

	const UStreetscapeSettings* Settings = GetDefault<UStreetscapeSettings>();
	const double Lift = Settings ? (double)Settings->OverlayLiftM : 0.3;
	const IStreetTerrainSource* Terrain = nullptr;
	AStreetscapeSiteActor* Site = AStreetscapeSiteActor::Get(GetWorld());
	if (Site)
	{
		Terrain = Site->TerrainForOrigin(Site->OriginEN.X, Site->OriginEN.Y);
	}
	TArray<double> Z;
	Z.SetNumUninitialized(PtsJson.Num());
	for (int32 I = 0; I < PtsJson.Num(); ++I)
	{
		double Zs = 0.0;
		Z[I] = (Terrain && Terrain->SampleHeight(PtsJson[I].X, PtsJson[I].Y, Zs)) ? Zs : PtsJson[I].Z;
	}
	for (int32 I = 0; I < PtsJson.Num(); ++I)
	{
		DrapedUE.Add(FStreetscapeJson::ToUE(FVector3d(PtsJson[I].X, PtsJson[I].Y, Z[I] + Lift)));
	}
	IConsoleVariable* Enabled = IConsoleManager::Get().FindConsoleVariable(TEXT("streetscape.Overlay"));
	if (!Enabled || Enabled->GetInt() == 0 || !IsVisible() || !bShow || !Site || !Site->bShowOverlay) return;
	UWorld* World = GetWorld();
	if (!World) return;
	ULineBatchComponent* Batcher = World->GetLineBatcher(UWorld::ELineBatcherType::WorldPersistent);
	if (!Batcher) return;
	for (int32 I = 0; I + 1 < DrapedUE.Num(); ++I)
	{
		Batcher->DrawLine(DrapedUE[I], DrapedUE[I + 1], Colour, SDPG_World, ThicknessCm, 0.0f, OverlayBatchId);
	}
}

void UStreetOverlayComponent::ClearDraw()
{
	if (UWorld* World = GetWorld())
	{
		if (ULineBatchComponent* Batcher = World->GetLineBatcher(UWorld::ELineBatcherType::WorldPersistent))
		{
			Batcher->ClearBatch(OverlayBatchId);
		}
	}
}

void UStreetOverlayComponent::OnRegister()
{
	Super::OnRegister();
	Redraw();
}

void UStreetOverlayComponent::OnUnregister()
{
	ClearDraw();
	Super::OnUnregister();
}

void UStreetOverlayComponent::OnVisibilityChanged()
{
	Super::OnVisibilityChanged();
	if (IsRegistered()) Redraw();
}
