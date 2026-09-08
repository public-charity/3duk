#include "UnrealMCPSettings.h"
#include "HAL/PlatformMisc.h"
#include "Misc/CString.h"

UUnrealMCPSettings::UUnrealMCPSettings()
{
	CategoryName = TEXT("Plugins");
	SectionName = TEXT("Unreal MCP");
}

int32 UUnrealMCPSettings::GetEffectivePort() const
{
	const FString EnvPort = FPlatformMisc::GetEnvironmentVariable(TEXT("UNREAL_MCP_PORT"));
	if (!EnvPort.IsEmpty())
	{
		const int32 Parsed = FCString::Atoi(*EnvPort);
		if (Parsed > 0 && Parsed <= 65535)
		{
			return Parsed;
		}
		UE_LOG(LogTemp, Warning, TEXT("UnrealMCPSettings: ignoring UNREAL_MCP_PORT='%s' (not a port number); using Port=%d"), *EnvPort, Port);
	}
	return Port;
}
