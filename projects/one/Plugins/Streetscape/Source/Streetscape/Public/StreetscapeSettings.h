// Project settings for the plugin (UE_PLAN.md 2.3): where the adapter output lives, which site, overlay lift.
// Config section [/Script/Streetscape.StreetscapeSettings] in Config/DefaultEngine.ini.

#pragma once

#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"
#include "StreetscapeSettings.generated.h"

UCLASS(config = Engine, defaultconfig, meta = (DisplayName = "Streetscape"))
class STREETSCAPE_API UStreetscapeSettings : public UDeveloperSettings
{
	GENERATED_BODY()

public:
	UStreetscapeSettings();

	/**
	 * Directory written by sources/adapters/unreal.py (<repo>/data/<site>/out/unreal). A relative path is
	 * resolved against the project directory (FPaths::ProjectDir()), so the default reaches the repo's data/.
	 */
	UPROPERTY(config, EditAnywhere, BlueprintReadOnly, Category = "Streetscape")
	FString DataDir = TEXT("../../data/thanet/out/unreal");

	/** Site name as in sources/config/sites/<site>.json; documents whose header 'site' differs are refused. */
	UPROPERTY(config, EditAnywhere, BlueprintReadOnly, Category = "Streetscape")
	FString SiteName = TEXT("thanet");

	/** Height of the OSM debug overlay above the road surface, in metres (UE_PLAN.md 2.8). */
	UPROPERTY(config, EditAnywhere, BlueprintReadOnly, Category = "Streetscape", meta = (ClampMin = "0.0", ClampMax = "5.0"))
	float OverlayLiftM = 0.3f;

	/** DataDir as an absolute, normalised path (forward slashes, no trailing slash). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	FString GetResolvedDataDir() const;
};
