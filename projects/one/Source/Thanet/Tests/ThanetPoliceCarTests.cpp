#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "../ThanetPoliceCar.h"
#include "../ThanetExplorerPawn.h"
#include "Components/BoxComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/WorldSettings.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThanetPoliceCarPhysicsTest,"Thanet.Vehicle.PhysicsAndSwitching",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThanetPoliceCarPhysicsTest::RunTest(const FString& Parameters)
{
    const auto IVS=UWorld::InitializationValues().AllowAudioPlayback(false).CreatePhysicsScene(true)
        .RequiresHitProxies(false).CreateNavigation(false).CreateAISystem(false).ShouldSimulatePhysics(true).SetTransactional(false);
    UWorld* World=UWorld::CreateWorld(EWorldType::Game,false,FName(TEXT("VehiclePhysicsTestWorld")),nullptr,true,ERHIFeatureLevel::Num,&IVS);
    FWorldContext& Context=GEngine->CreateNewWorldContext(EWorldType::Game);Context.SetCurrentWorld(World);
    auto Box=[World](FVector P,FVector E)->AActor*
    {
        AActor* A=World->SpawnActor<AActor>();auto* B=NewObject<UBoxComponent>(A);
        A->SetRootComponent(B);B->SetBoxExtent(E);B->SetCollisionProfileName(TEXT("BlockAll"));B->RegisterComponent();A->SetActorLocation(P);return A;
    };
    Box(FVector(0,0,-50),FVector(30000,30000,50));
    FActorSpawnParameters Spawn;Spawn.SpawnCollisionHandlingOverride=ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
    auto* Car=World->SpawnActor<AThanetPoliceCar>(FVector(0,0,85),FRotator::ZeroRotator,Spawn);
    auto* Walker=World->SpawnActor<AThanetExplorerPawn>(FVector(0,220,92),FRotator::ZeroRotator,Spawn);
    auto* PC=World->SpawnActor<APlayerController>();
    World->InitializeActorsForPlay(FURL());World->BeginPlay();
    World->GetWorldSettings()->NotifyBeginPlay();
    Car->SetActorTickEnabled(false);
    auto Step=[&](int32 Frames,float Throttle,float Steering,bool Brake)
    {
        for(int32 I=0;I<Frames;++I)
        {
            // Tick tasks only run once per global frame, including Chaos scene ticks.
            ++GFrameCounter;
            Car->AdvanceVehiclePhysics(1.f/60,Throttle,Steering,Brake);
            World->Tick(LEVELTICK_All,1.f/60);
        }
    };
    TestTrue(TEXT("Imported body assigned"),Car->Body->GetStaticMesh()!=nullptr);
    Step(180,0,0,true);
    AddInfo(FString::Printf(TEXT("Settled z=%.2f contacts=%d"),Car->GetActorLocation().Z,Car->GroundedWheels));
    TestTrue(TEXT("Suspension holds chassis above ground"),Car->GetActorLocation().Z>55 && Car->GetActorLocation().Z<95);
    TestEqual(TEXT("Four wheel contacts"),Car->GroundedWheels,4);
    PC->Possess(Walker);
    AddInfo(FString::Printf(TEXT("Before enter walker=%s controller=%s pcPawn=%s carController=%s"),
        *Walker->GetActorLocation().ToString(),*GetNameSafe(Walker->GetController()),*GetNameSafe(PC->GetPawn()),*GetNameSafe(Car->GetController())));
    TestTrue(TEXT("Enter succeeds"),Car->Enter(Walker));TestTrue(TEXT("Controller possesses car"),PC->GetPawn()==Car);
    TestFalse(TEXT("Walker collision disabled in car"),Walker->GetActorEnableCollision());
    Step(180,1,0,false);
    const FVector Moving=Car->GetActorLocation();
    AddInfo(FString::Printf(TEXT("Driven position=%s velocity=%s"),*Moving.ToString(),*Car->Chassis->GetPhysicsLinearVelocity().ToString()));
    TestTrue(TEXT("Accelerates along nose"),Moving.X>500);
    TestFalse(TEXT("Cannot exit at speed"),Car->Exit());
    Step(120,0,0,true);
    TestTrue(TEXT("Handbrake stops car"),Car->Chassis->GetPhysicsLinearVelocity().Size()<120);
    TestTrue(TEXT("Exit succeeds when stopped"),Car->Exit());TestTrue(TEXT("Walking possession restored"),PC->GetPawn()==Walker);
    TestTrue(TEXT("Walker collision restored"),Walker->GetActorEnableCollision());
    TestTrue(TEXT("Re-enter same car"),Car->Enter(Walker));
    const float BeforeReverse=Car->GetActorLocation().X;
    Step(120,-1,0,false);TestTrue(TEXT("Reverse travels backwards"),Car->GetActorLocation().X<BeforeReverse-150);
    Step(120,0,0,true);
    const float Yaw=Car->GetActorRotation().Yaw;
    Step(120,1,.7f,false);TestTrue(TEXT("Front tyre steering turns chassis"),FMath::Abs(FMath::FindDeltaAngleDegrees(Yaw,Car->GetActorRotation().Yaw))>8);
    Step(180,0,0,true);
    // A full height wall must stop the chassis; wheel traces alone must not let it pass.
    Car->SetActorLocationAndRotation(FVector(0,0,85),FRotator::ZeroRotator,false,nullptr,ETeleportType::TeleportPhysics);
    Car->Chassis->SetPhysicsLinearVelocity(FVector::ZeroVector);Car->Chassis->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
    Box(FVector(1400,0,300),FVector(40,2000,300));
    Step(300,1,0,false);TestTrue(TEXT("Rigid chassis blocked by wall"),Car->GetActorLocation().X<1200);
    Car->Recover();Step(180,0,0,true);TestTrue(TEXT("Recovery lands upright"),Car->GetActorUpVector().Z>.95);
    World->EndPlay(EEndPlayReason::Quit);World->DestroyWorld(false);GEngine->DestroyWorldContext(World);
    return true;
}
#endif
