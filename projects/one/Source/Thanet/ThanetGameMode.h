// Game mode referenced by Config/DefaultEngine.ini GlobalDefaultGameMode (UE_PLAN.md 1.3, 7).
// Phase 4: DefaultPawnClass = AThanetExplorerPawn (DESIGN.md 11); the config reference is
// Config/DefaultEngine.ini GlobalDefaultGameMode=/Script/Thanet.ThanetGameMode.

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
