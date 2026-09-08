#include "ThanetExplorerPawn.h"

#include "Camera/CameraComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/PrimitiveComponent.h"
#include "EngineUtils.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "InputAction.h"
#include "InputMappingContext.h"
#include "InputModifiers.h"
#include "Engine/World.h"

DEFINE_LOG_CATEGORY_STATIC(LogThanetExplorer, Log, All);

AThanetExplorerPawn::AThanetExplorerPawn()
{
	PrimaryActorTick.bCanEverTick = false;

	// UE_PLAN.md 7: capsule 34 / 88, camera at 64 cm with pawn control rotation.
	GetCapsuleComponent()->InitCapsuleSize(34.f, 88.f);
	bUseControllerRotationPitch = false;
	bUseControllerRotationYaw = true;
	bUseControllerRotationRoll = false;

	Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
	Camera->SetupAttachment(GetCapsuleComponent());
	Camera->SetRelativeLocation(FVector(0.f, 0.f, 64.f));
	Camera->bUsePawnControlRotation = true;

	UCharacterMovementComponent* Move = GetCharacterMovement();
	Move->MaxWalkSpeed = WalkSpeed;
	Move->MaxFlySpeed = FlySpeed;
	Move->BrakingDecelerationFlying = 2000.f;
	Move->MaxStepHeight = 45.f;
	Move->JumpZVelocity = 420.f;
	Move->AirControl = 0.5f;
	Move->bOrientRotationToMovement = false;
}

void AThanetExplorerPawn::BeginPlay()
{
	Super::BeginPlay();
	ApplySpeeds();
}

void AThanetExplorerPawn::ApplySpeeds()
{
	UCharacterMovementComponent* Move = GetCharacterMovement();
	if (!Move) return;
	Move->MaxWalkSpeed = bSprinting ? WalkSpeed * WalkSprintMultiplier : WalkSpeed;
	Move->MaxFlySpeed = bSprinting ? FlySprintSpeed : FlySpeed;
}

void AThanetExplorerPawn::SetFlying(bool bInFlying)
{
	bFlying = bInFlying;
	if (UCharacterMovementComponent* Move = GetCharacterMovement())
	{
		Move->SetMovementMode(bFlying ? MOVE_Flying : MOVE_Walking);   // ENG/CharacterMovementComponent.h SetMovementMode
	}
	ApplySpeeds();
}

void AThanetExplorerPawn::ToggleFly()
{
	SetFlying(!bFlying);
}

int32 AThanetExplorerPawn::SetOverlayVisible(bool bVisible)
{
	bOverlayVisible = bVisible;
	int32 Touched = 0;
	UWorld* World = GetWorld();
	if (!World) return 0;
	// by class NAME: the game module does not depend on the Streetscape plugin (Thanet.Build.cs).
	for (TActorIterator<AActor> It(World); It; ++It)
	{
		for (UActorComponent* C : It->GetComponents())
		{
			if (!C || !C->GetClass()->GetName().Contains(TEXT("StreetOverlayComponent"))) continue;
			if (USceneComponent* S = Cast<USceneComponent>(C))
			{
				S->SetVisibility(bVisible, true);
				++Touched;
			}
		}
	}
	UE_LOG(LogThanetExplorer, Log, TEXT("overlay %s on %d component(s)"), bVisible ? TEXT("shown") : TEXT("hidden"), Touched);
	return Touched;
}

// ---------------------------------------------------------------------------------------------------------------
// Enhanced Input, built in C++ (UE_PLAN.md 7)
// ---------------------------------------------------------------------------------------------------------------

void AThanetExplorerPawn::BuildInputObjects()
{
	if (MappingContext) return;

	auto MakeAction = [this](const TCHAR* Name, EInputActionValueType Type) -> UInputAction*
	{
		UInputAction* A = NewObject<UInputAction>(this, Name);
		A->ValueType = Type;
		return A;
	};

	IA_Move = MakeAction(TEXT("IA_Move"), EInputActionValueType::Axis2D);
	IA_Look = MakeAction(TEXT("IA_Look"), EInputActionValueType::Axis2D);
	IA_Up = MakeAction(TEXT("IA_Up"), EInputActionValueType::Boolean);
	IA_Down = MakeAction(TEXT("IA_Down"), EInputActionValueType::Boolean);
	IA_Sprint = MakeAction(TEXT("IA_Sprint"), EInputActionValueType::Boolean);
	IA_ToggleFly = MakeAction(TEXT("IA_ToggleFly"), EInputActionValueType::Boolean);
	IA_ToggleOverlay = MakeAction(TEXT("IA_ToggleOverlay"), EInputActionValueType::Boolean);

	MappingContext = NewObject<UInputMappingContext>(this, TEXT("IMC_ThanetExplorer"));

	// Move is an Axis2D: X = right, Y = forward. A 1D key delivers its value on X, so W/S swizzle it onto Y
	// (UInputModifierSwizzleAxis, EI/InputModifiers.h) and S/A negate (UInputModifierNegate).
	auto Swizzle = [this]() { return NewObject<UInputModifierSwizzleAxis>(this); };
	auto Negate = [this]() { return NewObject<UInputModifierNegate>(this); };

	MappingContext->MapKey(IA_Move, EKeys::W).Modifiers.Add(Swizzle());
	{
		FEnhancedActionKeyMapping& M = MappingContext->MapKey(IA_Move, EKeys::S);
		M.Modifiers.Add(Swizzle());
		M.Modifiers.Add(Negate());
	}
	MappingContext->MapKey(IA_Move, EKeys::D);
	MappingContext->MapKey(IA_Move, EKeys::A).Modifiers.Add(Negate());

	// Look: Mouse2D gives (dX, dY); screen Y is down, so negate Y and feed AddControllerPitchInput directly.
	{
		FEnhancedActionKeyMapping& M = MappingContext->MapKey(IA_Look, EKeys::Mouse2D);
		UInputModifierNegate* N = Negate();
		N->bX = false;
		N->bY = true;
		N->bZ = false;
		M.Modifiers.Add(N);
	}

	MappingContext->MapKey(IA_Up, EKeys::SpaceBar);
	MappingContext->MapKey(IA_Down, EKeys::LeftControl);
	MappingContext->MapKey(IA_Sprint, EKeys::LeftShift);
	MappingContext->MapKey(IA_ToggleFly, EKeys::F);
	MappingContext->MapKey(IA_ToggleOverlay, EKeys::O);
}

FString AThanetExplorerPawn::DescribeBindings() const
{
	if (!MappingContext) return TEXT("(no mapping context - SetupPlayerInputComponent has not run)");
	TArray<FString> Parts;
	for (const FEnhancedActionKeyMapping& M : MappingContext->GetMappings())
	{
		Parts.Add(FString::Printf(TEXT("%s=%s"), M.Action ? *M.Action->GetName() : TEXT("?"), *M.Key.ToString()));
	}
	return FString::Join(Parts, TEXT(", "));
}

void AThanetExplorerPawn::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	Super::SetupPlayerInputComponent(PlayerInputComponent);
	BuildInputObjects();

	if (APlayerController* PC = Cast<APlayerController>(GetController()))
	{
		if (UEnhancedInputLocalPlayerSubsystem* Subsystem = ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(PC->GetLocalPlayer()))
		{
			Subsystem->AddMappingContext(MappingContext, 0);
		}
	}

	UEnhancedInputComponent* EI = Cast<UEnhancedInputComponent>(PlayerInputComponent);
	if (!EI)
	{
		UE_LOG(LogThanetExplorer, Error, TEXT("the input component is not a UEnhancedInputComponent - check DefaultInput.ini"));
		return;
	}
	EI->BindAction(IA_Move, ETriggerEvent::Triggered, this, &AThanetExplorerPawn::Move);
	EI->BindAction(IA_Look, ETriggerEvent::Triggered, this, &AThanetExplorerPawn::Look);
	EI->BindAction(IA_Up, ETriggerEvent::Triggered, this, &AThanetExplorerPawn::OnUp);
	EI->BindAction(IA_Down, ETriggerEvent::Triggered, this, &AThanetExplorerPawn::OnDown);
	EI->BindAction(IA_Sprint, ETriggerEvent::Started, this, &AThanetExplorerPawn::OnSprintStart);
	EI->BindAction(IA_Sprint, ETriggerEvent::Completed, this, &AThanetExplorerPawn::OnSprintStop);
	EI->BindAction(IA_ToggleFly, ETriggerEvent::Started, this, &AThanetExplorerPawn::OnToggleFly);
	EI->BindAction(IA_ToggleOverlay, ETriggerEvent::Started, this, &AThanetExplorerPawn::OnToggleOverlay);
	UE_LOG(LogThanetExplorer, Log, TEXT("explorer input: %s"), *DescribeBindings());
}

void AThanetExplorerPawn::Move(const FInputActionValue& Value)
{
	const FVector2D V = Value.Get<FVector2D>();
	if (!Controller || V.IsNearlyZero()) return;
	const FRotator Control = Controller->GetControlRotation();
	// walking follows the yaw only; flying follows the full look direction so you can climb by looking up
	const FRotator Forward = bFlying ? Control : FRotator(0.f, Control.Yaw, 0.f);
	AddMovementInput(FRotationMatrix(Forward).GetUnitAxis(EAxis::X), V.Y);
	AddMovementInput(FRotationMatrix(FRotator(0.f, Control.Yaw, 0.f)).GetUnitAxis(EAxis::Y), V.X);
}

void AThanetExplorerPawn::Look(const FInputActionValue& Value)
{
	const FVector2D V = Value.Get<FVector2D>();
	AddControllerYawInput(V.X * LookSensitivity);
	AddControllerPitchInput(V.Y * LookSensitivity);
}

void AThanetExplorerPawn::UpDown(float Sign)
{
	if (bFlying)
	{
		AddMovementInput(FVector::UpVector, Sign);
	}
	else if (Sign > 0.f)
	{
		Jump();
	}
}

void AThanetExplorerPawn::OnUp(const FInputActionValue& Value) { UpDown(+1.f); }
void AThanetExplorerPawn::OnDown(const FInputActionValue& Value) { UpDown(-1.f); }

void AThanetExplorerPawn::OnSprintStart(const FInputActionValue& Value) { bSprinting = true; ApplySpeeds(); }
void AThanetExplorerPawn::OnSprintStop(const FInputActionValue& Value) { bSprinting = false; ApplySpeeds(); }
void AThanetExplorerPawn::OnToggleFly(const FInputActionValue& Value) { ToggleFly(); }
void AThanetExplorerPawn::OnToggleOverlay(const FInputActionValue& Value) { SetOverlayVisible(!bOverlayVisible); }
