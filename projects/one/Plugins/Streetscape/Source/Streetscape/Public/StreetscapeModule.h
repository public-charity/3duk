// Streetscape runtime module (UE_PLAN.md 2.3). Log category LogStreetscape is shared by every file of the module.

#pragma once

#include "CoreMinimal.h"
#include "Logging/LogMacros.h"
#include "Modules/ModuleInterface.h"

STREETSCAPE_API DECLARE_LOG_CATEGORY_EXTERN(LogStreetscape, Log, All);

class FStreetscapeModule : public IModuleInterface
{
public:
	//~ IModuleInterface
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};
