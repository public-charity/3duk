// Streetscape editor module (UE_PLAN.md 2.12). Phase 1: module boundary only; the ToolMenus entry,
// details customisations and the Python-callable importer library arrive with the landscape/streetscape phases.

#pragma once

#include "CoreMinimal.h"
#include "Logging/LogMacros.h"
#include "Modules/ModuleInterface.h"

STREETSCAPEEDITOR_API DECLARE_LOG_CATEGORY_EXTERN(LogStreetscapeEditor, Log, All);

class FStreetscapeEditorModule : public IModuleInterface
{
public:
	//~ IModuleInterface
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};
