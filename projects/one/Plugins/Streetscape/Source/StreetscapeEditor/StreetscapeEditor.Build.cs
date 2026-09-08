// Editor module (UE_PLAN.md 2.2, 2.12, 3): details-panel Rebuild buttons, the "Streetscape -> Import site"
// menu, and the landscape importer UFUNCTIONs that Tools/ue/*.py call headlessly.

using UnrealBuildTool;

public class StreetscapeEditor : ModuleRules
{
	public StreetscapeEditor(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		IWYUSupport = IWYUSupport.Full;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"Streetscape"
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"UnrealEd",
			"LevelEditor",
			"ToolMenus",
			"PropertyEditor",
			"EditorSubsystem",
			"EditorFramework",
			"Slate",
			"SlateCore",
			"Landscape",
			"LandscapeEditor",
			"Foliage",   // LandscapeEdit.h includes InstancedFoliageActor.h
			"AssetRegistry",
			"AssetTools",
			"Json",
			"Projects"
		});
	}
}
