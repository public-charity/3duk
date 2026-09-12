#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Pawn.h"
#include "ThanetPoliceCar.generated.h"

class UBoxComponent;
class UStaticMeshComponent;
class USpringArmComponent;
class UCameraComponent;
class UPointLightComponent;
class AThanetExplorerPawn;

/** Single-player exploration vehicle: rigid chassis, four traced suspension contacts.
 * Units: cm, kg, seconds. Physics uses the existing landscape/road collision.
 */
UCLASS()
class THANET_API AThanetPoliceCar : public APawn
{
    GENERATED_BODY()
public:
    AThanetPoliceCar();
    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;
    virtual void SetupPlayerInputComponent(UInputComponent* Input) override;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly) TObjectPtr<UBoxComponent> Chassis;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly) TObjectPtr<UStaticMeshComponent> Body;
    UPROPERTY(VisibleAnywhere) TArray<TObjectPtr<UStaticMeshComponent>> Wheels;
    UPROPERTY(VisibleAnywhere) TObjectPtr<USpringArmComponent> Boom;
    UPROPERTY(VisibleAnywhere) TObjectPtr<UCameraComponent> Camera;
    UPROPERTY(VisibleAnywhere) TArray<TObjectPtr<UPointLightComponent>> Beacons;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly) TObjectPtr<AThanetExplorerPawn> Walker;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly) bool bEmergencyLights = false;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly) int32 GroundedWheels = 0;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly) float SpeedMPH = 0;
    UFUNCTION(BlueprintCallable) bool Enter(AThanetExplorerPawn* Character);
    UFUNCTION(BlueprintCallable) bool Exit();
    UFUNCTION(BlueprintCallable) void Recover();
    UFUNCTION(BlueprintCallable) void ToggleLights();
    /** Same collision guard used by initial spawn and recovery. */
    bool FindParkingSpot(const FVector& Near, float Yaw, FTransform& Out) const;
    /** Controller-independent drive step; also used by the physics regression fixture. */
    void AdvanceVehiclePhysics(float Dt, float Throttle, float Steer, bool Brake);
private:
    float WheelAngle = 0;
    float Steering = 0;
    float LightClock = 0;
    FTransform LastSafeTransform;
    void ExitInput();
    void Notify(const FString& Message) const;
};
