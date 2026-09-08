// Runtime module (UE_PLAN.md 2.2): spline, profiles, renderers on UDynamicMeshComponent (GeometryFramework +
// GeometryCore, core engine modules), JSON loader, terrain sources (Landscape for the in-editor sampler).

using UnrealBuildTool;

public class Streetscape : ModuleRules
{
	public Streetscape(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		IWYUSupport = IWYUSupport.Full;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"GeometryCore",
			"GeometryFramework",
			"Json",
			"Landscape",
			"DeveloperSettings"
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"RenderCore",
			"RHI"
		});
	}
}
