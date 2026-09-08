#include "StreetscapeEditorModule.h"
#include "Modules/ModuleManager.h"

DEFINE_LOG_CATEGORY(LogStreetscapeEditor);

void FStreetscapeEditorModule::StartupModule()
{
	UE_LOG(LogStreetscapeEditor, Log, TEXT("StreetscapeEditor module started"));
}

void FStreetscapeEditorModule::ShutdownModule()
{
	UE_LOG(LogStreetscapeEditor, Log, TEXT("StreetscapeEditor module shut down"));
}

IMPLEMENT_MODULE(FStreetscapeEditorModule, StreetscapeEditor)
