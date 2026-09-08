// Project One (3duk) - editor target (the one Tools/build.ps1 builds). UE_PLAN.md 1.2.

using UnrealBuildTool;
using System.Collections.Generic;

public class ThanetEditorTarget : TargetRules
{
	public ThanetEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.V7;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_8;
		ExtraModuleNames.Add("Thanet");
	}
}
