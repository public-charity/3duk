// Project settings for the MCP bridge (DESIGN.md 12, UE_PLAN.md 6). Added in the 3duk copy so that a second
// editor (this project) never binds the port of Alex's running MCPGameProject editor (55557).
// Config section: [/Script/UnrealMCP.UnrealMCPSettings] in Config/DefaultEngine.ini.

#pragma once

#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"
#include "UnrealMCPSettings.generated.h"

UCLASS(config = Engine, defaultconfig, meta = (DisplayName = "Unreal MCP"))
class UNREALMCP_API UUnrealMCPSettings : public UDeveloperSettings
{
	GENERATED_BODY()

public:
	UUnrealMCPSettings();

	/** TCP port the bridge listens on (127.0.0.1). The UNREAL_MCP_PORT environment variable overrides it. */
	UPROPERTY(config, EditAnywhere, BlueprintReadOnly, Category = "Server", meta = (ClampMin = "1024", ClampMax = "65535"))
	int32 Port = 55557;

	/** Start the bridge when the editor (GUI) starts. */
	UPROPERTY(config, EditAnywhere, BlueprintReadOnly, Category = "Server")
	bool bStartInEditor = true;

	/** Start the bridge inside commandlets (-run=...). Off: headless runs never open a socket. */
	UPROPERTY(config, EditAnywhere, BlueprintReadOnly, Category = "Server")
	bool bStartInCommandlets = false;

	/** Port after applying the UNREAL_MCP_PORT environment override (GenericPlatformMisc.h:619). */
	UFUNCTION(BlueprintCallable, Category = "Server")
	int32 GetEffectivePort() const;
};
