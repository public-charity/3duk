// AThanetExplorerPawn - the walk / fly explorer of DESIGN.md 11 and UE_PLAN.md 7.
//
// Everything Enhanced Input needs is built in C++ inside SetupPlayerInputComponent (UInputMappingContext and
// UInputAction are plain UObjects: NewObject + MapKey + modifiers), so the game has no input assets to keep in sync
// with a .uasset and the pawn works in any map without a Blueprint. Keys: WASD move, Mouse2D look, Space jump /
// ascend, LeftCtrl descend, LeftShift sprint, F fly toggle, O OSM-overlay toggle.
//
// The game module deliberately does NOT depend on the Streetscape plugin (Thanet.Build.cs), so the overlay toggle
// finds overlay components by class NAME through the reflection system rather than by including the plugin's header.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "ThanetExplorerPawn.generated.h"

class UCameraComponent;
class AThanetPoliceCar;
class UInputAction;
class UInputMappingContext;
struct FInputActionValue;

UCLASS()
class THANET_API AThanetExplorerPawn : public ACharacter
{
	GENERATED_BODY()

public:
	AThanetExplorerPawn();
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Thanet") TObjectPtr<AThanetPoliceCar> PoliceCar;
	UFUNCTION(BlueprintCallable, Category="Thanet") void EnterPoliceCar();

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Thanet") TObjectPtr<UCameraComponent> Camera;

	/** cm/s on foot (DESIGN.md 11: 300, sprint x2.5). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Thanet") float WalkSpeed = 300.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Thanet") float WalkSprintMultiplier = 2.5f;
	/** cm/s flying (1500, sprint 6000). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Thanet") float FlySpeed = 1500.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Thanet") float FlySprintSpeed = 6000.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Thanet") float LookSensitivity = 1.f;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Thanet") bool bFlying = false;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Thanet") bool bSprinting = false;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Thanet") bool bOverlayVisible = false;

	// The input objects, built in C++ and kept alive by these properties.
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Thanet|Input") TObjectPtr<UInputMappingContext> MappingContext;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Thanet|Input") TObjectPtr<UInputAction> IA_Move;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Thanet|Input") TObjectPtr<UInputAction> IA_Look;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Thanet|Input") TObjectPtr<UInputAction> IA_Up;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Thanet|Input") TObjectPtr<UInputAction> IA_Down;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Thanet|Input") TObjectPtr<UInputAction> IA_Sprint;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Thanet|Input") TObjectPtr<UInputAction> IA_ToggleFly;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Thanet|Input") TObjectPtr<UInputAction> IA_ToggleOverlay;

	/** MOVE_Flying <-> MOVE_Walking (CharacterMovementComponent.h SetMovementMode). */
	UFUNCTION(BlueprintCallable, Category = "Thanet") void SetFlying(bool bInFlying);
	UFUNCTION(BlueprintCallable, Category = "Thanet") void ToggleFly();
	/** Toggle the plugin's debug-line cvar, including future streamed cells; returns 1 if available. */
	UFUNCTION(BlueprintCallable, Category = "Thanet") int32 SetOverlayVisible(bool bVisible);
	/** The mapping context's "action -> keys" as text, so a headless run can prove the bindings exist. */
	UFUNCTION(BlueprintCallable, Category = "Thanet") FString DescribeBindings() const;

	/**
	 * Create the Enhanced Input mapping context, actions and modifiers (idempotent). SetupPlayerInputComponent
	 * calls it when a controller possesses the pawn; it is exposed so a commandlet, which cannot run Play In
	 * Editor, can still build the objects on a spawned pawn and read DescribeBindings() back.
	 */
	UFUNCTION(BlueprintCallable, Category = "Thanet|Input") void BuildInputObjects();

	virtual void SetupPlayerInputComponent(class UInputComponent* PlayerInputComponent) override;
	virtual void BeginPlay() override;

protected:
	void Move(const FInputActionValue& Value);
	void Look(const FInputActionValue& Value);
	void UpDown(float Sign);
	void OnUp(const FInputActionValue& Value);
	void OnDown(const FInputActionValue& Value);
	void OnSprintStart(const FInputActionValue& Value);
	void OnSprintStop(const FInputActionValue& Value);
	void OnToggleFly(const FInputActionValue& Value);
	void OnToggleOverlay(const FInputActionValue& Value);
	void ApplySpeeds();
};
