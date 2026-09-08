#include "StreetscapeSettings.h"
#include "Misc/Paths.h"

UStreetscapeSettings::UStreetscapeSettings()
{
	CategoryName = TEXT("Plugins");
	SectionName = TEXT("Streetscape");
}

FString UStreetscapeSettings::GetResolvedDataDir() const
{
	FString Resolved = DataDir;
	if (FPaths::IsRelative(Resolved))
	{
		const FString ProjectDir = FPaths::ConvertRelativePathToFull(FPaths::ProjectDir());
		Resolved = FPaths::ConvertRelativePathToFull(ProjectDir, Resolved);
	}
	FPaths::NormalizeDirectoryName(Resolved);
	FPaths::CollapseRelativeDirectories(Resolved);
	return Resolved;
}
