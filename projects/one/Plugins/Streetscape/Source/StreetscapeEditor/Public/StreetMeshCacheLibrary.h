#pragma once
#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "StreetMeshCacheLibrary.generated.h"
class ADynamicMeshActor;

/** Load validated geometry cache output into a supplied actor; never saves or deletes assets. */
UCLASS()
class STREETSCAPEEDITOR_API UStreetMeshCacheLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()
public:
    UFUNCTION(BlueprintCallable, Category="Streetscape|GeometryCache")
    static FString ApplyMeshCache(ADynamicMeshActor* Actor, const FString& JsonPath);
};
