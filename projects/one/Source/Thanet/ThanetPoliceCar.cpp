#include "ThanetPoliceCar.h"
#include "ThanetExplorerPawn.h"
#include "Camera/CameraComponent.h"
#include "Components/BoxComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/PointLightComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/SpringArmComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "UObject/ConstructorHelpers.h"

namespace { constexpr float Mass = 1950.f; constexpr float Radius = 33.5f;
constexpr float SuspensionReach = 74.5f;
FVector WheelMount(int32 I) { return FVector(I < 2 ? 147.05 : -147.05, I % 2 ? 81.7 : -81.7, 0); } }

AThanetPoliceCar::AThanetPoliceCar()
{
    PrimaryActorTick.bCanEverTick = true;
    PrimaryActorTick.TickGroup = TG_PrePhysics;
    bUseControllerRotationPitch=false;bUseControllerRotationYaw=false;bUseControllerRotationRoll=false;
    AutoPossessAI=EAutoPossessAI::Disabled;
    Chassis = CreateDefaultSubobject<UBoxComponent>(TEXT("Chassis"));
    SetRootComponent(Chassis);
    Chassis->SetBoxExtent(FVector(231, 91, 46));
    Chassis->SetCollisionProfileName(TEXT("PhysicsActor"));
    Chassis->SetSimulatePhysics(true);
    Chassis->SetLinearDamping(.12f);
    Chassis->SetAngularDamping(2.5f);
    Chassis->BodyInstance.bUseCCD = true;
    auto* CabinCollision=CreateDefaultSubobject<UBoxComponent>(TEXT("CabinCollision"));
    CabinCollision->SetupAttachment(Chassis);
    CabinCollision->SetBoxExtent(FVector(130,74,32));
    CabinCollision->SetRelativeLocation(FVector(-64,0,50));
    CabinCollision->SetCollisionProfileName(TEXT("PhysicsActor"));
    CabinCollision->BodyInstance.bAutoWeld=true;
    Body = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Body"));
    Body->SetupAttachment(Chassis);
    Body->SetRelativeLocation(FVector(0,0,-60));
    Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    static ConstructorHelpers::FObjectFinder<UStaticMesh> BodyAsset(TEXT("/Game/Thanet/Vehicles/KentPoliceV90/SM_KentPoliceV90_Body"));
    static ConstructorHelpers::FObjectFinder<UStaticMesh> WheelAsset(TEXT("/Game/Thanet/Vehicles/KentPoliceV90/SM_KentPoliceV90_Wheel"));
    if (BodyAsset.Succeeded()) Body->SetStaticMesh(BodyAsset.Object);
    for (int32 I=0; I<4; ++I)
    {
        auto* W = CreateDefaultSubobject<UStaticMeshComponent>(*FString::Printf(TEXT("Wheel%d"),I));
        W->SetupAttachment(Chassis); W->SetRelativeLocation(WheelMount(I)+FVector(0,0,-26.5));
        W->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        if (WheelAsset.Succeeded()) W->SetStaticMesh(WheelAsset.Object);
        Wheels.Add(W);
    }
    Boom = CreateDefaultSubobject<USpringArmComponent>(TEXT("ChaseBoom"));
    Boom->SetupAttachment(Chassis); Boom->SetRelativeLocation(FVector(0,0,110));
    Boom->TargetArmLength=650; Boom->bUsePawnControlRotation=true;
    Boom->bEnableCameraLag=true; Boom->CameraLagSpeed=6; Boom->ProbeSize=18;
    Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("ChaseCamera"));
    Camera->SetupAttachment(Boom); Camera->FieldOfView=80;
    for (int32 I=0;I<2;++I)
    {
        auto* L=CreateDefaultSubobject<UPointLightComponent>(*FString::Printf(TEXT("Beacon%d"),I));
        L->SetupAttachment(Chassis);L->SetRelativeLocation(FVector(-10,I ? 46 : -46,102));
        L->SetLightColor(FLinearColor(.02f,.12f,1));L->SetIntensity(0);L->AttenuationRadius=650;L->SetCastShadows(false);
        Beacons.Add(L);
    }
}
void AThanetPoliceCar::BeginPlay()
{
    Super::BeginPlay();LastSafeTransform=GetActorTransform();
    Chassis->SetMassOverrideInKg(NAME_None, Mass);
    Chassis->SetCenterOfMass(FVector(0,0,-22));
    if (!Body->GetStaticMesh()) Notify(TEXT("Car mesh missing: run 10_import_police_car.py."));
}
void AThanetPoliceCar::Notify(const FString& Message) const
{
    if(GEngine) GEngine->AddOnScreenDebugMessage(-1,4,FColor::Cyan,Message);
}
void AThanetPoliceCar::SetupPlayerInputComponent(UInputComponent* Input)
{
    Super::SetupPlayerInputComponent(Input);
    Input->BindKey(EKeys::E,IE_Pressed,this,&AThanetPoliceCar::ExitInput);
    Input->BindKey(EKeys::R,IE_Pressed,this,&AThanetPoliceCar::Recover);
    Input->BindKey(EKeys::L,IE_Pressed,this,&AThanetPoliceCar::ToggleLights);
}
void AThanetPoliceCar::ExitInput() { Exit(); }
void AThanetPoliceCar::ToggleLights() { bEmergencyLights=!bEmergencyLights; }

bool AThanetPoliceCar::FindParkingSpot(const FVector& Near,float Yaw,FTransform& Out) const
{
    FCollisionQueryParams Q(SCENE_QUERY_STAT(CarParking),true,this);
    if(Walker) Q.AddIgnoredActor(Walker);
    for(int32 I=0;I<12;++I)
    {
        const float A=FMath::DegreesToRadians(Yaw+I*30.f);
        const FVector P=Near+FVector(FMath::Cos(A),FMath::Sin(A),0)*450.f;
        FHitResult Hit;
        if(!GetWorld()->LineTraceSingleByChannel(Hit,P+FVector(0,0,300),P-FVector(0,0,600),ECC_Visibility,Q)
           || Hit.ImpactNormal.Z<.88f) continue;
        const FVector Location=Hit.ImpactPoint+FVector(0,0,68);
        const FQuat Rotation=FRotator(0,Yaw,0).Quaternion();
        if(GetWorld()->OverlapBlockingTestByChannel(Location,Rotation,ECC_Pawn,FCollisionShape::MakeBox(FVector(248,106,50)),Q)) continue;
        // Require support under all four wheels, avoiding cliff-edge spawns.
        bool Supported=true;
        for(int32 W=0;W<4;++W)
        {
            const FVector Mount=Location+Rotation.RotateVector(WheelMount(W));
            FHitResult Support;
            if(!GetWorld()->LineTraceSingleByChannel(Support,Mount,Mount-FVector(0,0,105),ECC_Visibility,Q)
               || Support.ImpactNormal.Z<.8f) { Supported=false;break; }
        }
        if(Supported) {Out=FTransform(Rotation,Location);return true;}
    }
    return false;
}
bool AThanetPoliceCar::Enter(AThanetExplorerPawn* Character)
{
    if(!Character || GetController() || FVector::Dist(Character->GetActorLocation(),GetActorLocation())>800) return false;
    APlayerController* PC=Cast<APlayerController>(Character->GetController());
    if(!PC) return false;
    Walker=Character;
    Walker->GetCharacterMovement()->StopMovementImmediately();
    Walker->GetCharacterMovement()->DisableMovement();
    Walker->SetActorEnableCollision(false);Walker->SetActorHiddenInGame(true);
    PC->Possess(this);PC->SetControlRotation(FRotator(-12,GetActorRotation().Yaw,0));
    Notify(TEXT("W/S accelerate, brake/reverse | A/D steer | Space handbrake | E exit | R recover | L blue lights"));
    return true;
}
bool AThanetPoliceCar::Exit()
{
    auto* PC=Cast<APlayerController>(GetController());
    if(!PC || !Walker) return false;
    if(Chassis->GetPhysicsLinearVelocity().Size()>120) {Notify(TEXT("Stop the car before getting out."));return false;}
    FCollisionQueryParams Q(SCENE_QUERY_STAT(CarExit),true,this);Q.AddIgnoredActor(Walker);
    const float Half=Walker->GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
    const float Rad=Walker->GetCapsuleComponent()->GetScaledCapsuleRadius();
    for(const FVector Offset : {FVector(20,170,0),FVector(20,-170,0),FVector(-330,0,0)})
    {
        const FVector P=GetActorLocation()+FRotator(0,GetActorRotation().Yaw,0).RotateVector(Offset);
        FHitResult Hit;
        if(!GetWorld()->LineTraceSingleByChannel(Hit,P+FVector(0,0,150),P-FVector(0,0,230),ECC_Visibility,Q)
           || Hit.ImpactNormal.Z<.72f) continue;
        const FVector Spot=Hit.ImpactPoint+FVector(0,0,Half+4);
        if(GetWorld()->OverlapBlockingTestByChannel(Spot,FQuat::Identity,ECC_Pawn,FCollisionShape::MakeCapsule(Rad,Half),Q)) continue;
        Walker->SetActorLocation(Spot,false,nullptr,ETeleportType::TeleportPhysics);
        Walker->bSprinting=false;
        Walker->SetActorHiddenInGame(false);Walker->SetActorEnableCollision(true);Walker->SetFlying(false);
        PC->Possess(Walker);PC->SetControlRotation(FRotator(0,GetActorRotation().Yaw,0));
        Notify(TEXT("Walking | E enter police car | F fly | Shift sprint"));return true;
    }
    Notify(TEXT("No clear space to get out. Move away from the obstacle."));return false;
}
void AThanetPoliceCar::Recover()
{
    FTransform Spot;
    if(!FindParkingSpot(GetActorLocation(),GetActorRotation().Yaw,Spot)
       && !FindParkingSpot(LastSafeTransform.GetLocation(),LastSafeTransform.Rotator().Yaw,Spot))
    {Notify(TEXT("No loaded, clear ground for recovery."));return;}
    SetActorTransform(Spot,false,nullptr,ETeleportType::TeleportPhysics);
    Chassis->SetPhysicsLinearVelocity(FVector::ZeroVector);Chassis->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
    LastSafeTransform=Spot;
}
void AThanetPoliceCar::Tick(float Dt)
{
    Super::Tick(Dt);
    auto* PC=Cast<APlayerController>(GetController());
    float Throttle=0,Steer=0;bool Brake=!PC;
    if(PC)
    {
        Throttle=(PC->IsInputKeyDown(EKeys::W)?1.f:0.f)-(PC->IsInputKeyDown(EKeys::S)?1.f:0.f);
        Steer=(PC->IsInputKeyDown(EKeys::D)?1.f:0.f)-(PC->IsInputKeyDown(EKeys::A)?1.f:0.f);
        Brake=PC->IsInputKeyDown(EKeys::SpaceBar);
        float MX,MY;PC->GetInputMouseDelta(MX,MY);PC->AddYawInput(MX);PC->AddPitchInput(-MY);
        // Keep the dormant explorer with the current streaming source, never at a stale tile.
        if(Walker) Walker->SetActorLocation(GetActorLocation(),false,nullptr,ETeleportType::TeleportPhysics);
    }
    AdvanceVehiclePhysics(Dt,Throttle,Steer,Brake);
    LightClock+=Dt;
    for(int32 I=0;I<Beacons.Num();++I) Beacons[I]->SetIntensity(bEmergencyLights && (int32(LightClock*8)%2==I)?18000:0);
    if(PC && GEngine) GEngine->AddOnScreenDebugMessage(74001,0,FColor::White,
        FString::Printf(TEXT("KENT POLICE  |  %.0f mph  |  E exit   R recover   L lights"),SpeedMPH));
}
void AThanetPoliceCar::AdvanceVehiclePhysics(float Dt,float Throttle,float Steer,bool Brake)
{
    Throttle=FMath::Clamp(Throttle,-1.f,1.f);Steer=FMath::Clamp(Steer,-1.f,1.f);
    const FVector Velocity=Chassis->GetPhysicsLinearVelocity();
    const float ForwardSpeed=FVector::DotProduct(Velocity,GetActorForwardVector());
    SpeedMPH=Velocity.Size()*.0223694f;
    const float MaxSteer=FMath::Lerp(30.f,9.f,FMath::Clamp(FMath::Abs(ForwardSpeed)/3200.f,0.f,1.f));
    Steering=FMath::FInterpTo(Steering,Steer*MaxSteer,Dt,6);
    GroundedWheels=0;
    FCollisionQueryParams Q(SCENE_QUERY_STAT(CarSuspension),true,this);if(Walker)Q.AddIgnoredActor(Walker);
    for(int32 I=0;I<4;++I)
    {
        const FVector Mount=GetActorTransform().TransformPosition(WheelMount(I));
        const FVector Up=GetActorUpVector();FHitResult Hit;
        const bool Contact=GetWorld()->LineTraceSingleByChannel(Hit,Mount,Mount-Up*110,ECC_Visibility,Q)
            && FVector::DotProduct(Hit.ImpactNormal,Up)>.45f;
        float WheelZ=Radius-SuspensionReach;
        if(Contact && Hit.Distance<SuspensionReach)
        {
            ++GroundedWheels;
            const FVector V=Chassis->GetPhysicsLinearVelocityAtPoint(Mount);
            const float Compression=SuspensionReach-Hit.Distance;
            const float Load=FMath::Clamp(Compression*35000-FVector::DotProduct(V,Up)*11000,0.f,Mass*980.f);
            Chassis->AddForceAtLocation(Up*Load,Mount);
            const FVector Forward=FVector::VectorPlaneProject(FRotator(0,I<2?Steering:0,0).RotateVector(GetActorForwardVector()),Hit.ImpactNormal).GetSafeNormal();
            const FVector Right=FVector::CrossProduct(Hit.ImpactNormal,Forward).GetSafeNormal();
            const float LongSpeed=FVector::DotProduct(V,Forward);
            float Drive=Throttle*Mass*650.f/4;
            if((LongSpeed>3500 && Throttle>0)||(LongSpeed<-1000 && Throttle<0)) Drive=0;
            if(Brake) Drive=-LongSpeed*Mass*3.f/4;
            else if(FMath::IsNearlyZero(Throttle)) Drive=-LongSpeed*Mass*.35f/4;
            // Combined tyre friction bound prevents limitless grip on steep ground.
            FVector Tyre=Forward*Drive-Right*FVector::DotProduct(V,Right)*Mass*(Brake?2.f:7.f)/4;
            Tyre=Tyre.GetClampedToMaxSize(Load*1.1f);
            Chassis->AddForceAtLocation(Tyre,Mount);
            WheelZ=Radius-Hit.Distance;
        }
        Wheels[I]->SetRelativeLocation(WheelMount(I)+FVector(0,0,WheelZ));
        Wheels[I]->SetRelativeRotation(FRotator(WheelAngle,I<2?Steering:0,0));
    }
    WheelAngle=FMath::Fmod(WheelAngle-FMath::RadiansToDegrees(ForwardSpeed/Radius)*Dt,360.f);
    if(GroundedWheels==4 && GetActorUpVector().Z>.92 && Velocity.Size()<600) LastSafeTransform=GetActorTransform();
}
