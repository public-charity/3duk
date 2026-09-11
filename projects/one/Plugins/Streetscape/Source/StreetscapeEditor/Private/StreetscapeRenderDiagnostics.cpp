// Headless capture diagnostics. Collision probes cannot prove which heightmap mip the GPU reads.
#include "StreetscapeEditorLibrary.h"
#include "StreetscapeJson.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Editor.h"
#include "Engine/Texture2D.h"
#include "EngineUtils.h"
#include "LandscapeComponent.h"
#include "LandscapeProxy.h"
#include "TextureCompiler.h"
#include "RenderingThread.h"
#include "AssetCompilingManager.h"

int32 UStreetscapeEditorLibrary::FinishRenderAssetCompilation()
{
	const int32 Before = FAssetCompilingManager::Get().GetNumRemainingAssets();
	FAssetCompilingManager::Get().FinishAllCompilation();
	FlushRenderingCommands();
	return FAssetCompilingManager::Get().GetNumRemainingAssets() == 0 ? Before : -1;
}

FString UStreetscapeEditorLibrary::LandscapeHeightmapResidencyJson(bool bMakeResident)
{
	TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		Root->SetStringField(TEXT("error"), TEXT("no editor world"));
		return FStreetscapeJson::ToText(Root, false, 1, -1);
	}
	TSet<UTexture2D*> Textures;
	int32 Components = 0, MissingHeightmaps = 0;
	for (TActorIterator<ALandscapeProxy> It(World); It; ++It)
	{
		for (ULandscapeComponent* C : It->LandscapeComponents)
		{
			if (!C) continue;
			++Components;
			// LandscapeComponent.h:810, actual render heightmap, not an edit-layer texture.
			if (UTexture2D* Texture = C->GetHeightmap(false)) Textures.Add(Texture);
			else ++MissingHeightmaps;
		}
	}
	TArray<TSharedPtr<FJsonValue>> Rows;
	bool bReady = MissingHeightmaps == 0;
	for (UTexture2D* Texture : Textures)
	{
		TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
		Row->SetStringField(TEXT("texture"), Texture->GetPathName());
		Row->SetNumberField(TEXT("mips_before"), Texture->GetNumMips());
		Row->SetNumberField(TEXT("resident_before"), Texture->GetNumResidentMips());
		Row->SetNumberField(TEXT("lod_bias"), Texture->GetCachedLODBias());
		if (bMakeResident)
		{
			// TextureCompiler.h:51. Shader completion does not apply asynchronous
			// heightmap compilation; until then GetNumMips can describe a placeholder.
			TArray<UTexture*> Pending = { Texture };
			FTextureCompilingManager::Get().FinishCompilation(Pending);
			// Engine/StreamableRenderAsset.h:181,231. Processes streaming work on the
			// game thread; sleeping in Python cannot apply its pending completion.
			Texture->SetForceMipLevelsToBeResident(120.0f);
			Texture->WaitForStreaming();
		}
		Row->SetNumberField(TEXT("mips"), Texture->GetNumMips());
		Row->SetNumberField(TEXT("resident_after"), Texture->GetNumResidentMips());
		Row->SetBoolField(TEXT("fully_streamed"), Texture->IsFullyStreamedIn());
		const bool bTextureReady = !Texture->IsCompiling() && Texture->IsFullyStreamedIn()
			&& Texture->GetNumResidentMips() == Texture->GetNumMips();
		Row->SetBoolField(TEXT("ready"), bTextureReady);
		bReady &= bTextureReady;
		Rows.Add(MakeShared<FJsonValueObject>(Row));
	}
	Root->SetNumberField(TEXT("components"), Components);
	Root->SetNumberField(TEXT("missing_heightmaps"), MissingHeightmaps);
	Root->SetBoolField(TEXT("ready"), bReady);
	Root->SetBoolField(TEXT("requested_residency"), bMakeResident);
	Root->SetArrayField(TEXT("textures"), Rows);
	if (bMakeResident) FlushRenderingCommands();
	return FStreetscapeJson::ToText(Root, false, 1, -1);
}
