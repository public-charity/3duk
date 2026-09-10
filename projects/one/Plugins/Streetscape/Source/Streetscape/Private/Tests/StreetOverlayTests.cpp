// Exercise the actual world line batcher: hiding a scene component alone used to
// leave its lines visible, and newly streamed components ignored the explorer toggle.
#include "StreetTestUtil.h"
#include "StreetOverlayComponent.h"
#include "StreetscapeSiteActor.h"
#include "Components/LineBatchComponent.h"
#include "Engine/World.h"
#include "HAL/IConsoleManager.h"
#include "SceneManagement.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetOverlayLifecycleTest, "Streetscape.Overlay.Lifecycle",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)

bool FStreetOverlayLifecycleTest::RunTest(const FString& Parameters)
{
	IConsoleVariable* Toggle = IConsoleManager::Get().FindConsoleVariable(TEXT("streetscape.Overlay"));
	if (!TestNotNull(TEXT("overlay cvar registered"), Toggle)) return false;
	const int32 Previous = Toggle->GetInt();
	TestEqual(TEXT("overlay hidden in a fresh process"), Previous, 0);
	// World.h:3375 initializes a new transient world; no saved level is touched.
	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false);
	if (!TestNotNull(TEXT("transient world"), World)) return false;
	AStreetscapeSiteActor* Site = AStreetscapeSiteActor::Get(World, true);
	// No landscape => use the supplied Z, without loading the real survey.
	Site->TerrainSource = NewObject<UStreetLandscapeTerrain>(Site);
	Site->bShowOverlay = true;
	ULineBatchComponent* Batcher = World->GetLineBatcher(UWorld::ELineBatcherType::WorldPersistent);
	if (!TestNotNull(TEXT("world batcher"), Batcher)) { World->DestroyWorld(false); return false; }
	auto MakeOverlay = [&](const FString& Id)
	{
		AActor* Owner = World->SpawnActor<AActor>();
		UStreetOverlayComponent* C = NewObject<UStreetOverlayComponent>(Owner);
		Owner->AddInstanceComponent(C);
		C->RegisterComponent();
		C->SetPointsJson({FVector(0, 0, 1), FVector(10, 0, 1)}, Id);
		return C;
	};
	UStreetOverlayComponent* First = MakeOverlay(TEXT("overlay-test-first"));
	TestEqual(TEXT("default produces no debug lines"), Batcher->BatchedLines.Num(), 0);
	Toggle->Set(1, ECVF_SetByConsole);
	TestEqual(TEXT("toggle draws existing lines"), Batcher->BatchedLines.Num(), 1);
	if (Batcher->BatchedLines.Num())
		TestEqual(TEXT("world depth priority"), Batcher->BatchedLines[0].DepthPriority, (uint8)SDPG_World);
	First->SetVisibility(false);
	TestEqual(TEXT("component visibility clears real batch"), Batcher->BatchedLines.Num(), 0);
	First->SetVisibility(true);
	TestEqual(TEXT("component visibility redraws"), Batcher->BatchedLines.Num(), 1);
	UStreetOverlayComponent* Streamed = MakeOverlay(TEXT("overlay-test-streamed"));
	TestEqual(TEXT("new cell honours enabled state"), Batcher->BatchedLines.Num(), 2);
	Toggle->Set(0, ECVF_SetByConsole);
	TestEqual(TEXT("toggle clears every component batch"), Batcher->BatchedLines.Num(), 0);
	UStreetOverlayComponent* Hidden = MakeOverlay(TEXT("overlay-test-hidden"));
	TestEqual(TEXT("new cell honours disabled state"), Batcher->BatchedLines.Num(), 0);
	Toggle->Set(1, ECVF_SetByConsole);
	TestEqual(TEXT("second enable redraws all three"), Batcher->BatchedLines.Num(), 3);
	Streamed->UnregisterComponent();
	TestEqual(TEXT("unload clears only its own batch"), Batcher->BatchedLines.Num(), 2);
	First->UnregisterComponent();
	Hidden->UnregisterComponent();
	TestEqual(TEXT("no leaked lines"), Batcher->BatchedLines.Num(), 0);
	World->DestroyWorld(false);
	Toggle->Set(Previous, ECVF_SetByConsole);
	return true;
}
