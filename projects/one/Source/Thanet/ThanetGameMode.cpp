#include "ThanetGameMode.h"

#include "ThanetExplorerPawn.h"

AThanetGameMode::AThanetGameMode()
{
	// UE_PLAN.md 7 / DESIGN.md 11: the explorer is the default pawn, so Play In Editor on
	// /Game/Thanet/Maps/Thanet spawns it at the PlayerStart that 03_import_streetscape.py placed.
	DefaultPawnClass = AThanetExplorerPawn::StaticClass();
}
