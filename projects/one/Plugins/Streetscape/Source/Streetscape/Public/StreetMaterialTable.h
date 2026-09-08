// StreetMaterialTable - schema material name -> UMaterialInterface (UE_PLAN.md 2.5.3; SCHEMA.md 7).
// Keys are exactly the SCHEMA.md 7 names; Resolve warns once per unknown id and returns the (magenta) Fallback.

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "StreetMaterialTable.generated.h"

class UMaterialInterface;

UCLASS(BlueprintType)
class STREETSCAPE_API UStreetMaterialTable : public UDataAsset
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, Category = "Streetscape") TMap<FName, TSoftObjectPtr<UMaterialInterface>> Materials;
	UPROPERTY(EditAnywhere, Category = "Streetscape") TSoftObjectPtr<UMaterialInterface> Fallback;

	/** Material for a schema name; unknown -> Fallback (warned once per name per table). */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	UMaterialInterface* Resolve(FName Name) const;

	/** Names of SCHEMA.md 7 that have no entry here. */
	UFUNCTION(BlueprintCallable, Category = "Streetscape")
	TArray<FName> MissingNormativeNames() const;

private:
	mutable TSet<FName> Warned;
};
