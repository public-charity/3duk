// Game mode referenced by Config/DefaultEngine.ini GlobalDefaultGameMode (UE_PLAN.md 1.3, 7).
// Phase 1: an empty AGameModeBase so the config reference resolves; the explorer phase sets
// DefaultPawnClass = AThanetExplorerPawn (DESIGN.md 11).

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "ThanetGameMode.generated.h"

UCLASS()
class THANET_API AThanetGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AThanetGameMode();
};
