// Game module: the explorer pawn, game mode and input only (UE_PLAN.md 1.3, 7).
// No dependency on Streetscape - the plugin must stay reusable without this game.

using UnrealBuildTool;

public class Thanet : ModuleRules
{
	public Thanet(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		IWYUSupport = IWYUSupport.Full;

		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "InputCore", "EnhancedInput" });

		PrivateDependencyModuleNames.AddRange(new string[] { });
	}
}
