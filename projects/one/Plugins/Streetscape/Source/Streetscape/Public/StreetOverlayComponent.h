// UStreetOverlayComponent - the OSM debug overlay (UE_PLAN.md 2.8; DESIGN.md 5.5). The raw polyline in document
// metres, re-draped on the site terrain source and lifted UStreetscapeSettings::OverlayLiftM (0.3 m), drawn into
// the world's persistent line batcher under a per-street batch id. No geometry, no collision.

#pragma once

#include "CoreMinimal.h"
#include "Components/SceneComponent.h"
#include "StreetOverlayComponent.generated.h"

UCLASS(ClassGroup = Streetscape, meta = (BlueprintSpawnableComponent))
class STREETSCAPE_API UStreetOverlayComponent : public USceneComponent
{
	GENERATED_BODY()
public:
	UStreetOverlayComponent();

	/** overlay.pts in the document frame (metres, X east, Y north, Z up); Z is informative and re-draped. */
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TArray<FVector> PtsJson;
	UPROPERTY(EditAnywhere, Category = "Streetscape") FLinearColor Colour = FLinearColor(1.0f, 0.25f, 0.9f, 1.0f);
	UPROPERTY(EditAnywhere, Category = "Streetscape") float ThicknessCm = 12.0f;
	UPROPERTY(EditAnywhere, Category = "Streetscape") bool bShow = true;
	/** FCrc::StrCrc32(*StreetId), forced non-zero (LineBatchComponent.h:143 INVALID_ID = 0). */
	UPROPERTY() uint32 OverlayBatchId = 1;
	/** Points after the last drape, in UE centimetres (what the tests and the screenshots see). */
	UPROPERTY(VisibleAnywhere, Category = "Streetscape") TArray<FVector> DrapedUE;

	UFUNCTION(BlueprintCallable, Category = "Streetscape") void SetPointsJson(const TArray<FVector>& Pts, const FString& StreetId);
	UFUNCTION(BlueprintCallable, Category = "Streetscape") void Redraw();
	UFUNCTION(BlueprintCallable, Category = "Streetscape") void ClearDraw();
	UFUNCTION(BlueprintCallable, Category = "Streetscape") int32 NumPoints() const { return PtsJson.Num(); }

protected:
	virtual void OnRegister() override;
	virtual void OnUnregister() override;
	virtual void OnVisibilityChanged() override;
};
