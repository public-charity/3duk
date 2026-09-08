#include "StreetscapeSiteActor.h"

#include "Engine/World.h"
#include "EngineUtils.h"
#include "StreetMaterialTable.h"
#include "StreetTerrainSource.h"
#include "StreetscapeModule.h"
#include "StreetscapeSettings.h"

AStreetscapeSiteActor::AStreetscapeSiteActor()
{
	PrimaryActorTick.bCanEverTick = false;
	USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetRootComponent(Root);
#if WITH_EDITOR
	bIsSpatiallyLoaded = false;
#endif
	const UStreetscapeSettings* Settings = GetDefault<UStreetscapeSettings>();
	SiteName = Settings ? Settings->SiteName : TEXT("thanet");
}

AStreetscapeSiteActor* AStreetscapeSiteActor::Get(UWorld* World, bool bCreate)
{
	if (!World) return nullptr;
	for (TActorIterator<AStreetscapeSiteActor> It(World); It; ++It)
	{
		return *It;
	}
	if (!bCreate) return nullptr;
	FActorSpawnParameters Params;
	Params.Name = TEXT("StreetscapeSite");
	AStreetscapeSiteActor* A = World->SpawnActor<AStreetscapeSiteActor>(AStreetscapeSiteActor::StaticClass(), FTransform::Identity, Params);
#if WITH_EDITOR
	if (A) A->SetActorLabel(TEXT("StreetscapeSite"));
#endif
	return A;
}

UStreetProfileBase* AStreetscapeSiteActor::FindProfile(FName Id) const
{
	for (const TObjectPtr<UStreetProfileBase>& P : Profiles)
	{
		if (P && P->ProfileId == Id) return P;
	}
	return nullptr;
}

UStreetTerrainSourceBase* AStreetscapeSiteActor::ResolveTerrainSource()
{
	if (TerrainSource)
	{
		// The instanced sub-object serialises, but FStreetHeightfield::Tiles is plain C++ and does not: a re-opened
		// map comes back with "heightfield (not loaded)" and 0 tiles, and every rebuild-on-load would sample no
		// ground and put the street at z = 0. Load it here, once, before anything samples it.
		if (UStreetHeightfieldTerrain* Hf = Cast<UStreetHeightfieldTerrain>(TerrainSource))
		{
			if (!Hf->IsLoaded() && !Hf->Load())
			{
				UE_LOG(LogStreetscape, Warning, TEXT("StreetscapeSiteActor: %s"), *Hf->Describe());
			}
		}
		return TerrainSource;
	}
	UStreetHeightfieldTerrain* Hf = NewObject<UStreetHeightfieldTerrain>(this, UStreetHeightfieldTerrain::StaticClass(), TEXT("HeightfieldTerrain"));
	if (Hf->Load())
	{
		TerrainSource = Hf;
		return TerrainSource;
	}
	UE_LOG(LogStreetscape, Warning, TEXT("StreetscapeSiteActor: no terrain source (adapter landscape dir not loadable)"));
	return nullptr;
}

const IStreetTerrainSource* AStreetscapeSiteActor::TerrainForOrigin(double E, double N)
{
	UStreetTerrainSourceBase* Src = ResolveTerrainSource();
	if (!Src) return nullptr;
	Src->SetDocumentOrigin(E, N);
	return Src;
}

FStreetSiteProfiles AStreetscapeSiteActor::AssetProfiles() const
{
	FStreetSiteProfiles Out;
	for (const TObjectPtr<UStreetProfileBase>& P : Profiles)
	{
		if (!P) continue;
		const FString Id = P->ProfileId.ToString();
		if (URoadProfile* R = Cast<URoadProfile>(P)) Out.Road.Add(Id, R->Data);
		else if (UEdgeProfile* Ed = Cast<UEdgeProfile>(P)) Out.Edge.Add(Id, Ed->Data);
		else if (UHedgeProfile* Hd = Cast<UHedgeProfile>(P)) Out.Hedge.Add(Id, Hd->Data);
	}
	return Out;
}

void AStreetscapeSiteActor::PostLoad()
{
	Super::PostLoad();
	if (Materials)
	{
		// pre-resolve every material id once (UE_PLAN.md 2.10) so the renderers never hitch on a soft-object load
		for (const TPair<FName, TSoftObjectPtr<UMaterialInterface>>& Kv : Materials->Materials)
		{
			Materials->Resolve(Kv.Key);
		}
	}
}
