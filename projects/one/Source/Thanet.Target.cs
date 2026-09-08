// Project One (3duk) - game target. As TP_Blank.Target.cs on the installed 5.8.2:
// BuildSettingsVersion.V7 and EngineIncludeOrderVersion.Unreal5_8 are mandatory (UE_PLAN.md 1.2).

using UnrealBuildTool;
using System.Collections.Generic;

public class ThanetTarget : TargetRules
{
	public ThanetTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.V7;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_8;
		ExtraModuleNames.Add("Thanet");
	}
}
