#include "StreetscapeModule.h"
#include "Modules/ModuleManager.h"

DEFINE_LOG_CATEGORY(LogStreetscape);

void FStreetscapeModule::StartupModule()
{
	UE_LOG(LogStreetscape, Log, TEXT("Streetscape module started"));
}

void FStreetscapeModule::ShutdownModule()
{
	UE_LOG(LogStreetscape, Log, TEXT("Streetscape module shut down"));
}

IMPLEMENT_MODULE(FStreetscapeModule, Streetscape)
