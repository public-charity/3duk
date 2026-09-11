#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "StreetDocumentPatchLibrary.generated.h"

/** Apply explicit independent-spline edits without replacing World Partition actors. */
UCLASS()
class STREETSCAPEEDITOR_API UStreetDocumentPatchLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()
public:
    /** Existing IDs only; registration and component slots must match. No save, spawn or delete. */
    UFUNCTION(BlueprintCallable, Category = "Streetscape|Documents")
    static FString ApplyIndependentDocument(const FString& JsonPath);
};
