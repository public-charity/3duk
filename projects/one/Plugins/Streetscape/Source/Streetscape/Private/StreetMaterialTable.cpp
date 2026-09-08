#include "StreetMaterialTable.h"
#include "Materials/MaterialInterface.h"
#include "StreetTypes.h"
#include "StreetscapeModule.h"

UMaterialInterface* UStreetMaterialTable::Resolve(FName Name) const
{
	if (const TSoftObjectPtr<UMaterialInterface>* Found = Materials.Find(Name))
	{
		if (UMaterialInterface* M = Found->LoadSynchronous())
		{
			return M;
		}
	}
	if (!Warned.Contains(Name))
	{
		Warned.Add(Name);
		UE_LOG(LogStreetscape, Warning, TEXT("StreetMaterialTable %s: no material for '%s' - using the fallback"), *GetPathName(), *Name.ToString());
	}
	return Fallback.LoadSynchronous();
}

TArray<FName> UStreetMaterialTable::MissingNormativeNames() const
{
	TArray<FName> Missing;
	for (const FName& N : FStreetEnums::MaterialNames())
	{
		if (!Materials.Contains(N))
		{
			Missing.Add(N);
		}
	}
	return Missing;
}
