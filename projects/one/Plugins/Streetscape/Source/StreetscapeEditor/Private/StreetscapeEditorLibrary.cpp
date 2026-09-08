#include "StreetscapeEditorLibrary.h"
#include "StreetscapeEditorModule.h"
#include "StreetProfiles.h"
#include "StreetMaterialTable.h"
#include "StreetscapeJson.h"
#include "StreetTerrainSource.h"
#include "StreetscapeSettings.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Dom/JsonObject.h"
#include "FileHelpers.h"
#include "HAL/FileManager.h"
#include "Materials/MaterialInterface.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "UObject/Package.h"
#include "UObject/SavePackage.h"

namespace
{
UPackage* PackageFor(const FString& PackagePath, const FString& AssetName)
{
	const FString PackageName = PackagePath / AssetName;
	UPackage* Pkg = CreatePackage(*PackageName);   // COU/UObject/UObjectGlobals.h:1225
	Pkg->FullyLoad();
	return Pkg;
}

bool SavePackageNow(UPackage* Pkg)
{
	return UEditorLoadingAndSavingUtils::SavePackages({ Pkg }, false);   // UED/Public/FileHelpers.h:86
}
}

int32 UStreetscapeEditorLibrary::ImportProfiles(const FString& JsonDir, const FString& PackagePath)
{
	TArray<FString> Files;
	IFileManager::Get().FindFiles(Files, *(JsonDir / TEXT("*.json")), true, false);
	Files.Sort();
	int32 Count = 0;
	for (const FString& Name : Files)
	{
		const FString Path = JsonDir / Name;
		TSharedPtr<FJsonObject> Obj;
		FText Err;
		if (!FStreetscapeJson::LoadFile(Path, Obj, &Err))
		{
			UE_LOG(LogStreetscapeEditor, Error, TEXT("ImportProfiles: %s"), *Err.ToString());
			continue;
		}
		FStreetProfileFile F;
		TArray<FString> Problems;
		if (!FStreetscapeJson::ReadProfileFile(Obj.ToSharedRef(), F, Problems))
		{
			UE_LOG(LogStreetscapeEditor, Error, TEXT("ImportProfiles: %s: %s"), *Name, *FString::Join(Problems, TEXT("; ")));
			continue;
		}
		UClass* Class = nullptr;
		switch (F.Kind)
		{
		case EStreetProfileKind::Road: Class = URoadProfile::StaticClass(); break;
		case EStreetProfileKind::Edge: Class = UEdgeProfile::StaticClass(); break;
		case EStreetProfileKind::Hedge: Class = UHedgeProfile::StaticClass(); break;
		}
		UPackage* Pkg = PackageFor(PackagePath, F.Id);
		UStreetProfileBase* Asset = FindObject<UStreetProfileBase>(Pkg, *F.Id);
		const bool bNew = Asset == nullptr || Asset->GetClass() != Class;
		if (bNew)
		{
			if (Asset)
			{
				Asset->Rename(nullptr, GetTransientPackage(), REN_DontCreateRedirectors | REN_NonTransactional);
			}
			Asset = NewObject<UStreetProfileBase>(Pkg, Class, *F.Id, RF_Public | RF_Standalone);
		}
		Asset->ProfileId = FName(*F.Id);
		if (const FString* Note = F.Notes.Find(TEXT("_note")))
		{
			TSharedPtr<FJsonObject> Dummy;
			FString NoteText = *Note;
			if (NoteText.Len() >= 2 && NoteText.StartsWith(TEXT("\"")) && NoteText.EndsWith(TEXT("\"")))
			{
				NoteText = NoteText.Mid(1, NoteText.Len() - 2).ReplaceEscapedCharWithChar();
			}
			Asset->Notes = NoteText;
		}
		switch (F.Kind)
		{
		case EStreetProfileKind::Road: CastChecked<URoadProfile>(Asset)->Data = F.Road; break;
		case EStreetProfileKind::Edge: CastChecked<UEdgeProfile>(Asset)->Data = F.Edge; break;
		case EStreetProfileKind::Hedge: CastChecked<UHedgeProfile>(Asset)->Data = F.Hedge; break;
		}
		Asset->MarkPackageDirty();
		if (bNew)
		{
			FAssetRegistryModule::AssetCreated(Asset);
		}
		if (!SavePackageNow(Pkg))
		{
			UE_LOG(LogStreetscapeEditor, Error, TEXT("ImportProfiles: could not save %s"), *Pkg->GetName());
			continue;
		}
		UE_LOG(LogStreetscapeEditor, Log, TEXT("ImportProfiles: %s %s -> %s"), bNew ? TEXT("created") : TEXT("updated"), *Name, *Asset->GetPathName());
		++Count;
	}
	return Count;
}

TArray<FString> UStreetscapeEditorLibrary::ProfileAssetIds(const FString& PackagePath)
{
	TArray<FString> Ids;
	IAssetRegistry& AR = FAssetRegistryModule::GetRegistry();
	TArray<FAssetData> Assets;
	AR.GetAssetsByPath(FName(*PackagePath), Assets, false, false);
	for (const FAssetData& A : Assets)
	{
		if (A.IsInstanceOf(UStreetProfileBase::StaticClass()))
		{
			Ids.Add(A.AssetName.ToString());
		}
	}
	Ids.Sort();
	return Ids;
}

UStreetMaterialTable* UStreetscapeEditorLibrary::CreateMaterialTable(const FString& PackagePath, const FString& AssetName, const TMap<FName, UMaterialInterface*>& Materials, UMaterialInterface* Fallback)
{
	UPackage* Pkg = PackageFor(PackagePath, AssetName);
	UStreetMaterialTable* Table = FindObject<UStreetMaterialTable>(Pkg, *AssetName);
	const bool bNew = Table == nullptr;
	if (bNew)
	{
		Table = NewObject<UStreetMaterialTable>(Pkg, *AssetName, RF_Public | RF_Standalone);
	}
	Table->Materials.Reset();
	for (const auto& KV : Materials)
	{
		if (KV.Value) Table->Materials.Add(KV.Key, TSoftObjectPtr<UMaterialInterface>(KV.Value));
	}
	Table->Fallback = TSoftObjectPtr<UMaterialInterface>(Fallback);
	Table->MarkPackageDirty();
	if (bNew) FAssetRegistryModule::AssetCreated(Table);
	if (!SavePackageNow(Pkg))
	{
		UE_LOG(LogStreetscapeEditor, Error, TEXT("CreateMaterialTable: could not save %s"), *Pkg->GetName());
		return nullptr;
	}
	const TArray<FName> Missing = Table->MissingNormativeNames();
	if (Missing.Num())
	{
		UE_LOG(LogStreetscapeEditor, Warning, TEXT("CreateMaterialTable: %d normative names missing: %s"), Missing.Num(), *FString::JoinBy(Missing, TEXT(", "), [](FName N) { return N.ToString(); }));
	}
	return Table;
}

bool UStreetscapeEditorLibrary::SaveAll()
{
	return UEditorLoadingAndSavingUtils::SaveDirtyPackages(true, true);   // UED/Public/FileHelpers.h:108
}

TArray<FString> UStreetscapeEditorLibrary::ValidateStreetscapeJson(const FString& Path)
{
	TSharedPtr<FJsonObject> Obj;
	FText Err;
	if (!FStreetscapeJson::LoadFile(Path, Obj, &Err)) return { Err.ToString() };
	TArray<FString> Problems;
	FStreetscapeJson::ValidateStructure(Obj.ToSharedRef(), Problems);
	return Problems;
}

TArray<FString> UStreetscapeEditorLibrary::StreetscapeJsonWarnings(const FString& Path)
{
	TSharedPtr<FJsonObject> Obj;
	FText Err;
	if (!FStreetscapeJson::LoadFile(Path, Obj, &Err)) return { Err.ToString() };
	FStreetSiteDoc Doc;
	TArray<FString> Problems;
	if (!FStreetscapeJson::ReadSite(Obj.ToSharedRef(), Doc, Problems)) return Problems;
	return FStreetscapeJson::ValidateWarnings(Doc);
}

FString UStreetscapeEditorLibrary::RewriteStreetscapeJson(const FString& InPath, const FString& OutPath)
{
	TSharedPtr<FJsonObject> Obj;
	FText Err;
	if (!FStreetscapeJson::LoadFile(InPath, Obj, &Err)) { UE_LOG(LogStreetscapeEditor, Error, TEXT("%s"), *Err.ToString()); return FString(); }
	FStreetSiteDoc Doc;
	TArray<FString> Problems;
	if (!FStreetscapeJson::ReadSite(Obj.ToSharedRef(), Doc, Problems)) { UE_LOG(LogStreetscapeEditor, Error, TEXT("%s"), *FString::Join(Problems, TEXT("\n"))); return FString(); }
	if (!FStreetscapeJson::SaveFile(OutPath, FStreetscapeJson::WriteSite(Doc))) return FString();
	return OutPath;
}

double UStreetscapeEditorLibrary::ProbeHeightfieldM(double XM, double YM)
{
	// plain C++ heightfield kept for the commandlet's lifetime (no UObject, nothing for the GC to collect)
	static FStreetHeightfield Field;
	static bool bTried = false, bLoaded = false;
	if (!bTried)
	{
		bTried = true;
		FText Err;
		const FString Dir = GetDefault<UStreetscapeSettings>()->GetResolvedDataDir() / TEXT("landscape");
		bLoaded = Field.LoadLandscapeDir(Dir, &Err);
		if (!bLoaded) UE_LOG(LogStreetscapeEditor, Warning, TEXT("ProbeHeightfieldM: %s"), *Err.ToString());
	}
	double Z = NAN;
	if (!bLoaded || !Field.Sample(XM, YM, Z)) return NAN;
	return Z;
}
