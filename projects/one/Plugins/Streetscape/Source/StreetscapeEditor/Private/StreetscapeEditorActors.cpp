// UStreetscapeEditorLibrary, phase 3: the actor-facing half (UE_PLAN.md 2.12, 5.3) - import a document into
// AStreetscapeActors, report the stats.json of DESIGN.md 14, place a player start, load a World Partition region
// (commandlets skip LoadLastLoadedRegions) and reproduce render.py's three fixed cameras in UE centimetres.

#include "StreetscapeEditorLibrary.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Editor.h"
#include "EngineUtils.h"
#include "GameFramework/PlayerStart.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "ObjectTools.h"
#include "StreetGeometry.h"
#include "StreetMaterialTable.h"
#include "StreetProfiles.h"
#include "StreetRenderers.h"
#include "StreetOverlayComponent.h"
#include "StreetSpline.h"
#include "StreetTerrainSource.h"
#include "StreetscapeActor.h"
#include "StreetscapeEditorModule.h"
#include "StreetscapeJson.h"
#include "StreetscapeSiteActor.h"
#include "WorldPartition/LoaderAdapter/LoaderAdapterShape.h"
#include "WorldPartition/WorldPartition.h"

namespace
{
UWorld* EditorWorld()
{
	return GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
}

AStreetscapeActor* FindActorById(const FString& Id)
{
	UWorld* World = EditorWorld();
	if (!World) return nullptr;
	for (TActorIterator<AStreetscapeActor> It(World); It; ++It)
	{
		if (It->StreetId == Id) return *It;
	}
	return nullptr;
}

void CollectActorsById(const FString& Id, TArray<AActor*>& Out)
{
	UWorld* World = EditorWorld();
	if (!World) return;
	for (TActorIterator<AStreetscapeActor> It(World); It; ++It)
	{
		if (It->StreetId == Id) Out.Add(*It);
	}
}

TSharedRef<FJsonValue> NumV(double V) { return MakeShared<FJsonValueNumber>(V); }
double R4(double V) { return FMath::RoundToDouble(V * 1e4) / 1e4; }
double R6(double V) { return FMath::RoundToDouble(V * 1e6) / 1e6; }
double R9(double V) { return FMath::RoundToDouble(V * 1e9) / 1e9; }
FString KeyG(double V) { return FString::Printf(TEXT("%g"), V); }

/** {tris, verts} per name, exactly mesh.MeshBuffer.stats(). */
TSharedRef<FJsonObject> PerNameObj(const TMap<FName, FIntPoint>& In)
{
	TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
	for (const TPair<FName, FIntPoint>& Kv : In)
	{
		TSharedRef<FJsonObject> E = MakeShared<FJsonObject>();
		E->SetNumberField(TEXT("tris"), Kv.Value.X);
		E->SetNumberField(TEXT("verts"), Kv.Value.Y);
		O->SetObjectField(Kv.Key.ToString(), E);
	}
	return O;
}

TSharedRef<FJsonValue> BBoxV(const FVector3d& Mn, const FVector3d& Mx)
{
	TArray<TSharedPtr<FJsonValue>> A, B, Outer;
	A.Add(NumV(Mn.X)); A.Add(NumV(Mn.Y)); A.Add(NumV(Mn.Z));
	B.Add(NumV(Mx.X)); B.Add(NumV(Mx.Y)); B.Add(NumV(Mx.Z));
	Outer.Add(MakeShared<FJsonValueArray>(A));
	Outer.Add(MakeShared<FJsonValueArray>(B));
	return MakeShared<FJsonValueArray>(Outer);
}

/** Every profile DataAsset and material table the level can see, attached to the site actor once. */
void PopulateSiteFromAssetRegistry(AStreetscapeSiteActor* Site)
{
	if (!Site) return;
	IAssetRegistry& AR = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get();
	AR.SearchAllAssets(true);
	if (!Site->Materials)
	{
		TArray<FAssetData> Found;
		AR.GetAssetsByClass(UStreetMaterialTable::StaticClass()->GetClassPathName(), Found, true);
		if (Found.Num()) Site->Materials = Cast<UStreetMaterialTable>(Found[0].GetAsset());
	}
	if (Site->Profiles.Num() == 0)
	{
		TArray<FAssetData> Found;
		AR.GetAssetsByClass(UStreetProfileBase::StaticClass()->GetClassPathName(), Found, true);
		Found.Sort([](const FAssetData& A, const FAssetData& B) { return A.AssetName.LexicalLess(B.AssetName); });
		for (const FAssetData& D : Found)
		{
			if (UStreetProfileBase* P = Cast<UStreetProfileBase>(D.GetAsset())) Site->Profiles.Add(P);
		}
	}
}
}   // namespace

AStreetscapeSiteActor* UStreetscapeEditorLibrary::EnsureSiteActor(const FString& SiteName, double OriginE, double OriginN)
{
	UWorld* World = EditorWorld();
	if (!World) return nullptr;
	AStreetscapeSiteActor* Site = AStreetscapeSiteActor::Get(World, true);
	if (!Site) return nullptr;
	Site->Modify();
	if (!SiteName.IsEmpty()) Site->SiteName = SiteName;
	Site->OriginEN = FVector2D(OriginE, OriginN);
	PopulateSiteFromAssetRegistry(Site);
	Site->ResolveTerrainSource();
	// setting UPROPERTYs from C++ does not dirty the package on its own, so a later SaveDirtyPackages would skip
	// the site actor and the level would come back with no material table (every renderer slot -> WorldGridMaterial)
	Site->MarkPackageDirty();
	UE_LOG(LogStreetscapeEditor, Display, TEXT("site actor '%s' origin (%f, %f), materials %s, profiles %d"),
		*Site->SiteName, Site->OriginEN.X, Site->OriginEN.Y,
		Site->Materials ? *Site->Materials->GetPathName() : TEXT("NONE"), Site->Profiles.Num());
	return Site;
}

int32 UStreetscapeEditorLibrary::DeleteActorsAndPackages(const TArray<AActor*>& Actors)
{
	UWorld* World = EditorWorld();
	if (!World || Actors.Num() == 0) return 0;
	TArray<UPackage*> Packages;
	for (AActor* A : Actors)
	{
		if (!A) continue;
		// A World Partition actor lives in its own package under Content/__ExternalActors__/...
		if (UPackage* P = A->GetExternalPackage())
		{
			Packages.AddUnique(P);
		}
		World->EditorDestroyActor(A, false);
	}
	if (Packages.Num() == 0) return 0;
	// ObjectTools.h:313 - unloads the packages and deletes their files; without it EditorDestroyActor leaves the
	// .uasset on disk and the actor comes back the next time the map is loaded.
	ObjectTools::CleanupAfterSuccessfulDelete(Packages, /*bPerformReferenceCheck=*/false);
	return Packages.Num();
}

int32 UStreetscapeEditorLibrary::ImportStreetscapeJson(const FString& FileOrDir, bool bPlacePlayerStart)
{
	UWorld* World = EditorWorld();
	if (!World) { UE_LOG(LogStreetscapeEditor, Error, TEXT("ImportStreetscapeJson: no editor world")); return -1; }

	TArray<FString> Files;
	if (FPaths::DirectoryExists(FileOrDir))
	{
		TArray<FString> Names;
		IFileManager::Get().FindFiles(Names, *(FileOrDir / TEXT("*.json")), true, false);
		Names.Sort();
		for (const FString& N : Names) Files.Add(FileOrDir / N);
	}
	else
	{
		Files.Add(FileOrDir);
	}
	if (Files.Num() == 0) { UE_LOG(LogStreetscapeEditor, Error, TEXT("ImportStreetscapeJson: nothing to load at %s"), *FileOrDir); return -1; }

	// World Partition: a commandlet has nothing loaded after load_level (WorldPartition.cpp:880-886), so
	// FindActorById below would see an empty world and every re-import would leave the previous actor behind as a
	// second copy of the same street. Pull the whole site in first, then the replace-by-id is real.
	LoadRegion(FVector::ZeroVector, 2000000.f);

	int32 Spawned = 0;
	bool bPlacedStart = false;
	if (bPlacePlayerStart)
	{
		// the import is idempotent for streetscape actors (they are replaced by id); make it idempotent for the
		// spawn point too, or every re-import leaves another PlayerStart_Streetscape behind and the game picks
		// one of them at random (GameModeBase::ChoosePlayerStart_Implementation).
		TArray<AActor*> Stale;
		for (TActorIterator<APlayerStart> It(World); It; ++It)
		{
			if (It->GetActorLabel() == TEXT("PlayerStart_Streetscape")) Stale.Add(*It);
		}
		const int32 Gone = DeleteActorsAndPackages(Stale);
		if (Stale.Num())
		{
			UE_LOG(LogStreetscapeEditor, Log, TEXT("ImportStreetscapeJson: removed %d stale PlayerStart_Streetscape (%d packages deleted)"), Stale.Num(), Gone);
		}
	}
	for (const FString& File : Files)
	{
		TSharedPtr<FJsonObject> Obj;
		FText Err;
		if (!FStreetscapeJson::LoadFile(File, Obj, &Err)) { UE_LOG(LogStreetscapeEditor, Error, TEXT("%s: %s"), *File, *Err.ToString()); return -1; }
		FStreetSiteDoc Doc;
		TArray<FString> Problems;
		if (!FStreetscapeJson::ReadSite(Obj.ToSharedRef(), Doc, Problems))
		{
			UE_LOG(LogStreetscapeEditor, Error, TEXT("%s: %s"), *File, *FString::Join(Problems, TEXT(" | ")));
			return -1;
		}
		if (Doc.Frame != FStreetEnums::FrameConst())
		{
			UE_LOG(LogStreetscapeEditor, Error, TEXT("%s: frame is not the constant frame"), *File);
			return -1;
		}
		if (!Doc.SchemaVersion.StartsWith(TEXT("1.")))
		{
			UE_LOG(LogStreetscapeEditor, Error, TEXT("%s: schema_version %s is not 1.x"), *File, *Doc.SchemaVersion);
			return -1;
		}
		AStreetscapeSiteActor* Site = EnsureSiteActor(Doc.Site, Doc.Origin.E, Doc.Origin.N);
		if (!Site) return -1;
		if (!FMath::IsNearlyEqual(Site->OriginEN.X, Doc.Origin.E, 1e-6) || !FMath::IsNearlyEqual(Site->OriginEN.Y, Doc.Origin.N, 1e-6))
		{
			UE_LOG(LogStreetscapeEditor, Error, TEXT("%s: origin differs from the site actor"), *File);
			return -1;
		}
		Site->Crs = Doc.Crs;
		Site->VerticalDatum = Doc.VerticalDatum;

		for (const FStreetSplineDef& Def : Doc.Splines)
		{
			{
				TArray<AActor*> Existing;
				CollectActorsById(Def.Id, Existing);
				DeleteActorsAndPackages(Existing);
			}
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			AStreetscapeActor* A = World->SpawnActor<AStreetscapeActor>(AStreetscapeActor::StaticClass(), FTransform::Identity, Params);
			if (!A) { UE_LOG(LogStreetscapeEditor, Error, TEXT("cannot spawn an actor for %s"), *Def.Id); return -1; }
			A->ApplyDefinition(Def, Doc.Profiles, FVector2D(Doc.Origin.E, Doc.Origin.N));
			FString BuildErr;
			if (!A->RebuildAllChecked(&BuildErr))
			{
				UE_LOG(LogStreetscapeEditor, Error, TEXT("%s: build failed: %s"), *Def.Id, *BuildErr);
				return -1;
			}
			++Spawned;
			if (bPlacePlayerStart && !bPlacedStart && Def.Points.Num() >= 2)
			{
				const FStreetSamples* Sm = A->GetSamples();
				const double Z = (Sm && Sm->ZRef.Num()) ? Sm->ZRef[0] : 0.0;
				const double Dx = Def.Points[1].X - Def.Points[0].X;
				const double Dy = Def.Points[1].Y - Def.Points[0].Y;
				const double BearingDeg = FMath::RadiansToDegrees(FMath::Atan2(Dx, Dy));
				const FVector Loc = FStreetscapeJson::ToUE(FVector3d(Def.Points[0].X, Def.Points[0].Y, Z + 1.5));
				const FRotator Rot(0.0, FStreetscapeJson::YawFromBearingDeg(BearingDeg), 0.0);
				if (APlayerStart* PS = World->SpawnActor<APlayerStart>(APlayerStart::StaticClass(), Loc, Rot))
				{
					PS->SetActorLabel(TEXT("PlayerStart_Streetscape"));
					bPlacedStart = true;
				}
			}
		}
	}
	return Spawned;
}

TArray<FString> UStreetscapeEditorLibrary::StreetscapeActorIds()
{
	TArray<FString> Out;
	if (UWorld* World = EditorWorld())
	{
		for (TActorIterator<AStreetscapeActor> It(World); It; ++It) Out.Add(It->StreetId);
	}
	Out.Sort();
	return Out;
}

int32 UStreetscapeEditorLibrary::RebuildAllStreetscapeActors()
{
	int32 N = 0;
	if (UWorld* World = EditorWorld())
	{
		for (TActorIterator<AStreetscapeActor> It(World); It; ++It) { It->RebuildAll(); ++N; }
	}
	return N;
}

FString UStreetscapeEditorLibrary::ActorStatsJson(const FString& StreetId)
{
	AStreetscapeActor* A = FindActorById(StreetId);
	if (!A) { UE_LOG(LogStreetscapeEditor, Error, TEXT("ActorStatsJson: no actor %s"), *StreetId); return FString(); }
	const FStreetSamples* Sp = A->GetSamples();
	if (!Sp) { UE_LOG(LogStreetscapeEditor, Error, TEXT("ActorStatsJson: %s has no samples"), *StreetId); return FString(); }

	TSharedRef<FJsonObject> O = Sp->StatsJson();
	O->SetStringField(TEXT("spline_id"), Sp->Id);
	O->SetStringField(TEXT("out_dir_name"), Sp->Id.Replace(TEXT(":"), TEXT("~")));
	AStreetscapeSiteActor* Site = AStreetscapeSiteActor::Get(A->GetWorld());
	O->SetStringField(TEXT("site"), Site ? Site->SiteName : FString());
	{
		TSharedRef<FJsonObject> Or = MakeShared<FJsonObject>();
		Or->SetNumberField(TEXT("E"), A->DocOriginEN.X);
		Or->SetNumberField(TEXT("N"), A->DocOriginEN.Y);
		O->SetObjectField(TEXT("origin"), Or);
	}

	const TMap<FString, const FStreetMeshBuilder*> Bufs = A->Buffers();
	TSharedRef<FJsonObject> Ident = MakeShared<FJsonObject>();
	TSharedRef<FJsonObject> Buffers = MakeShared<FJsonObject>();
	TSharedRef<FJsonObject> Validate = MakeShared<FJsonObject>();
	for (const TPair<FString, const FStreetMeshBuilder*>& Kv : Bufs)
	{
		const FStreetMeshBuilder& Bf = *Kv.Value;
		const TArray<double> St = FStreetGeometry::StationValues(Bf);
		bool bSame = true;
		if (Kv.Key == TEXT("road"))
		{
			bSame = St.Num() == Sp->S.Num();
			for (int32 I = 0; bSame && I < St.Num(); ++I) bSame = St[I] == Sp->S[I];
		}
		else
		{
			for (double X : St)
			{
				bool bFound = false;
				for (double Y : Sp->S) { if (X == Y) { bFound = true; break; } }
				if (!bFound) { bSame = false; break; }
			}
		}
		Ident->SetBoolField(Kv.Key, bSame);

		const FStreetBuildStats S2 = Bf.Stats();
		TSharedRef<FJsonObject> Bo = MakeShared<FJsonObject>();
		Bo->SetNumberField(TEXT("verts"), S2.Verts);
		Bo->SetNumberField(TEXT("tris"), S2.Tris);
		Bo->SetField(TEXT("bbox"), BBoxV(S2.BBoxMin, S2.BBoxMax));
		Bo->SetObjectField(TEXT("per_material"), PerNameObj(S2.PerMaterial));
		Bo->SetObjectField(TEXT("per_group"), PerNameObj(S2.PerGroup));
		Buffers->SetObjectField(Kv.Key, Bo);

		TArray<TSharedPtr<FJsonValue>> Vs;
		for (const FString& Msg : Bf.Validate()) Vs.Add(MakeShared<FJsonValueString>(Msg));
		Validate->SetArrayField(Kv.Key, Vs);
	}
	O->SetObjectField(TEXT("stations_identical"), Ident);
	O->SetObjectField(TEXT("buffers"), Buffers);
	O->SetObjectField(TEXT("validate"), Validate);

	// -- overlap (DESIGN.md 5 rule 1)
	TSharedRef<FJsonObject> Ov = MakeShared<FJsonObject>();
	bool bAnyOverlap = false;
	double OvMin = 0, OvMax = 0;
	const TCHAR* SideKeys[2] = { TEXT("left"), TEXT("right") };
	const EStreetSide SideEnums[2] = { EStreetSide::Left, EStreetSide::Right };
	const UStreetEdgeRenderer* Edges[2] = { A->EdgeLeft, A->EdgeRight };
	for (int32 K = 0; K < 2; ++K)
	{
		if (!A->Road || !Edges[K]) continue;
		const FStreetMeshBuilder& Eb = Edges[K]->GetLastBuffer();
		if (Eb.FindGroupId(FName(TEXT("kerb"))) == INDEX_NONE) continue;
		const FStreetSideSpec& Spec = Sp->SideSpec[StreetSideIndex(SideEnums[K])];
		double Td = 0.03;
		for (int32 I = 0; I < Spec.TuckDepth.Num(); ++I) Td = (I == 0) ? Spec.TuckDepth[I] : FMath::Min(Td, Spec.TuckDepth[I]);
		const FStreetGeometry::FOverlap Mo = FStreetGeometry::MeasureLateralOverlap(A->Road->GetLastBuffer(), Eb, StreetSideSigma(SideEnums[K]), Td);
		TSharedRef<FJsonObject> E = MakeShared<FJsonObject>();
		E->SetNumberField(TEXT("min"), R9(Mo.MinM));
		E->SetNumberField(TEXT("max"), R9(Mo.MaxM));
		Ov->SetObjectField(SideKeys[K], E);
		OvMin = bAnyOverlap ? FMath::Min(OvMin, R9(Mo.MinM)) : R9(Mo.MinM);
		OvMax = bAnyOverlap ? FMath::Max(OvMax, R9(Mo.MaxM)) : R9(Mo.MaxM);
		bAnyOverlap = true;
	}
	O->SetObjectField(TEXT("overlap"), Ov);
	if (bAnyOverlap)
	{
		O->SetNumberField(TEXT("overlap_min"), OvMin);
		O->SetNumberField(TEXT("overlap_max"), OvMax);
	}
	else
	{
		O->SetField(TEXT("overlap_min"), MakeShared<FJsonValueNull>());
		O->SetField(TEXT("overlap_max"), MakeShared<FJsonValueNull>());
	}

	O->SetNumberField(TEXT("marking_strips"), A->MarkingStrips());
	{
		TSharedRef<FJsonObject> In = MakeShared<FJsonObject>();
		for (const TPair<FName, int32>& Kv : A->InstanceCounts()) In->SetNumberField(Kv.Key.ToString(), Kv.Value);
		O->SetObjectField(TEXT("instances"), In);
	}
	{
		UStreetTerrainSourceBase* Src = Site ? Site->ResolveTerrainSource() : nullptr;
		if (Src) O->SetStringField(TEXT("terrain"), Src->Describe());
		else O->SetField(TEXT("terrain"), MakeShared<FJsonValueNull>());
	}

	// -- probes every 10 m
	{
		TSharedRef<FJsonObject> Zr = MakeShared<FJsonObject>();
		TSharedRef<FJsonObject> Zw = MakeShared<FJsonObject>();
		TSharedRef<FJsonObject> Eo = MakeShared<FJsonObject>();
		const TArray<double> EoL = Sp->EdgeOffset(EStreetSide::Left);
		const TArray<double> EoR = Sp->EdgeOffset(EStreetSide::Right);
		for (int32 Qi = 0; Qi * 10.0 <= Sp->LengthM + 1e-9; ++Qi)
		{
			const double Q = Qi * 10.0;
			const FString Key = KeyG(Q);
			Zr->SetNumberField(Key, R4(FStreetSplineMath::Interp(Q, Sp->S, Sp->ZRef)));
			const double Raw = FStreetSplineMath::Interp(Q, Sp->S, Sp->ZRaw);
			if (FMath::IsFinite(Raw)) Zw->SetNumberField(Key, R4(Raw)); else Zw->SetField(Key, MakeShared<FJsonValueNull>());
			TArray<TSharedPtr<FJsonValue>> Pair;
			Pair.Add(NumV(R4(FStreetSplineMath::Interp(Q, Sp->S, EoL))));
			Pair.Add(NumV(R4(FStreetSplineMath::Interp(Q, Sp->S, EoR))));
			Eo->SetArrayField(Key, Pair);
		}
		O->SetObjectField(TEXT("z_ref_probe"), Zr);
		O->SetObjectField(TEXT("z_raw_probe"), Zw);
		O->SetObjectField(TEXT("edge_offset_probe"), Eo);
	}
	O->SetNumberField(TEXT("overlay_points"), A->Overlay ? A->Overlay->NumPoints() : 0);
	{
		const FStreetSamplingResolved& Sg = Sp->Sampling;
		TSharedRef<FJsonObject> So = MakeShared<FJsonObject>();
		So->SetNumberField(TEXT("step_m"), Sg.StepM);
		So->SetNumberField(TEXT("min_step_m"), Sg.MinStepM);
		So->SetNumberField(TEXT("curvature_gain"), Sg.CurvatureGain);
		So->SetNumberField(TEXT("smoothing_window_m"), Sg.SmoothingWindowM);
		So->SetNumberField(TEXT("smoothing_passes"), Sg.SmoothingPasses);
		So->SetNumberField(TEXT("width_ramp_m"), Sg.WidthRampM);
		So->SetNumberField(TEXT("bank_max_deg"), Sg.BankMaxDeg);
		So->SetNumberField(TEXT("bank_probe_min_half_width_m"), Sg.BankProbeMinHalfWidthM);
		So->SetNumberField(TEXT("bank_rate_max_deg_per_m"), Sg.BankRateMaxDegPerM);
		So->SetNumberField(TEXT("pin_blend_m"), Sg.PinBlendM);
		TArray<TSharedPtr<FJsonValue>> Ex;
		for (double X : Sg.ExtraStationsM) Ex.Add(NumV(X));
		So->SetArrayField(TEXT("extra_stations_m"), Ex);
		O->SetObjectField(TEXT("sampling"), So);
	}
	{
		TArray<TSharedPtr<FJsonValue>> Ms;
		for (double X : Sp->MandatorySet) Ms.Add(NumV(R6(X)));
		O->SetArrayField(TEXT("mandatory_stations"), Ms);
	}
	return FStreetscapeJson::ToText(O, false, 1, -1);
}

FString UStreetscapeEditorLibrary::WriteActorStatsJson(const FString& StreetId, const FString& OutPath)
{
	const FString Text = ActorStatsJson(StreetId);
	if (Text.IsEmpty()) return FString();
	if (!FFileHelper::SaveStringToFile(Text + TEXT("\n"), *OutPath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM)) return FString();
	return OutPath;
}

FString UStreetscapeEditorLibrary::ActorCameraJson(const FString& StreetId)
{
	AStreetscapeActor* A = FindActorById(StreetId);
	if (!A) return FString();
	const FStreetSamples* Sp = A->GetSamples();
	if (!Sp || Sp->Num() == 0) return FString();
	const FStreetFrames& Fr = Sp->Frames;
	const FVector3d Zu(0, 0, 1);
	const double L = Sp->LengthM;

	auto Emit = [](TSharedRef<FJsonObject> Root, const TCHAR* Name, const FVector3d& Eye, const FVector3d& Target, double Fov)
	{
		TSharedRef<FJsonObject> C = MakeShared<FJsonObject>();
		const FVector EyeUE = FStreetscapeJson::ToUE(Eye);
		const FVector TgtUE = FStreetscapeJson::ToUE(Target);
		const FRotator Rot = (TgtUE - EyeUE).Rotation();
		TArray<TSharedPtr<FJsonValue>> E, T;
		E.Add(NumV(EyeUE.X)); E.Add(NumV(EyeUE.Y)); E.Add(NumV(EyeUE.Z));
		T.Add(NumV(TgtUE.X)); T.Add(NumV(TgtUE.Y)); T.Add(NumV(TgtUE.Z));
		C->SetArrayField(TEXT("eye_ue"), E);
		C->SetArrayField(TEXT("target_ue"), T);
		C->SetNumberField(TEXT("pitch"), Rot.Pitch);
		C->SetNumberField(TEXT("yaw"), Rot.Yaw);
		C->SetNumberField(TEXT("roll"), 0.0);
		C->SetNumberField(TEXT("fov_deg"), Fov);
		Root->SetObjectField(Name, C);
	};

	TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	// cam1: eye level on the LEFT pavement at s = 10, 0.9 m behind the kerb line, 1.7 m up
	{
		const double S1 = FMath::Min(10.0, L * 0.25);
		const TArray<double> Q1 = { S1 };
		const FStreetFrames F1 = Fr.At(Q1);
		const double OL = FStreetSplineMath::Interp(S1, Sp->S, Sp->EdgeOffset(EStreetSide::Left));
		const FStreetSideSpec& Spec = Sp->SideSpec[0];
		double HPav = 0.0;
		if (Spec.Present.Num() && Spec.Present[0])
		{
			TArray<double> Hb = Sp->EdgeHeight(EStreetSide::Left);
			for (int32 I = 0; I < Hb.Num(); ++I) Hb[I] += Spec.HkBack[I];
			HPav = FStreetSplineMath::Interp(S1, Sp->S, Hb);
		}
		const FVector3d Eye = F1.P[0] + (OL + 0.9) * F1.NFlat[0] + (HPav + 1.7) * Zu;
		const TArray<double> Q2 = { FMath::Min(L, S1 + 30.0) };
		const FStreetFrames Ah = Fr.At(Q2);
		Emit(Root, TEXT("cam1"), Eye, Ah.P[0] + Zu, 60.0);
	}
	// cam2: three-quarter aerial at the first width knot
	{
		double Sk = L / 2.0;
		for (int32 I = 0; I + 1 < Sp->Width.Num(); ++I)
		{
			if (FMath::Abs(Sp->Width[I + 1] - Sp->Width[I]) > 1e-9) { Sk = Sp->S[I]; break; }
		}
		const TArray<double> Qk = { Sk };
		const FStreetFrames Fk = Fr.At(Qk);
		const FVector3d Eye = Fk.P[0] - 40.0 * Fk.Th[0] - 35.0 * Fk.NFlat[0] + 25.0 * Zu;
		Emit(Root, TEXT("cam2"), Eye, Fk.P[0], 50.0);
	}
	// cam3: kerb close-up at the first drop kerb
	{
		int32 Side = 1;
		double S3 = L / 2.0;
		bool bFound = false;
		double BestS = 0, BestLen = 0;
		for (int32 K = 0; K < 2; ++K)
		{
			for (const FStreetDropKerb& Dk : Sp->Sides[K].DropKerbs)
			{
				if (!bFound || Dk.SM < BestS)
				{
					bFound = true; BestS = Dk.SM; BestLen = Dk.LengthM; Side = (K == 0) ? 1 : -1;
				}
			}
		}
		if (bFound) S3 = BestS + BestLen / 2.0;
		const EStreetSide SideEnum = Side > 0 ? EStreetSide::Left : EStreetSide::Right;
		const TArray<double> Q3 = { S3 };
		const FStreetFrames F3 = Fr.At(Q3);
		const double O3 = FStreetSplineMath::Interp(S3, Sp->S, Sp->EdgeOffset(SideEnum));
		const FVector3d Kerb = F3.P[0] + (double)Side * O3 * F3.NFlat[0];
		const FVector3d Eye = Kerb - (double)Side * 6.0 * F3.NFlat[0] - 2.0 * F3.Th[0] + Zu;
		Emit(Root, TEXT("cam3"), Eye, Kerb, 45.0);
	}
	return FStreetscapeJson::ToText(Root, false, 1, -1);
}

bool UStreetscapeEditorLibrary::LoadRegion(FVector CenterUE, float RadiusCm)
{
	UWorld* World = EditorWorld();
	if (!World) return false;
	if (!World->GetWorldPartition()) return false;
	const FBox Box(CenterUE - FVector(RadiusCm), CenterUE + FVector(RadiusCm));
	static TArray<TUniquePtr<FLoaderAdapterShape>> Adapters;
	TUniquePtr<FLoaderAdapterShape> Ad = MakeUnique<FLoaderAdapterShape>(World, Box, TEXT("StreetscapeRegion"));
	Ad->Load();
	Adapters.Add(MoveTemp(Ad));
	return true;
}

FString UStreetscapeEditorLibrary::ExportSiteJson(const FString& Path)
{
	UWorld* World = EditorWorld();
	if (!World) return FString();
	AStreetscapeSiteActor* Site = AStreetscapeSiteActor::Get(World);
	FStreetSiteDoc Doc;
	Doc.Site = Site ? Site->SiteName : FString();
	Doc.Crs = Site ? Site->Crs : TEXT("EPSG:27700");
	Doc.VerticalDatum = Site ? Site->VerticalDatum : TEXT("ODN");
	Doc.Origin.E = Site ? Site->OriginEN.X : 0.0;
	Doc.Origin.N = Site ? Site->OriginEN.Y : 0.0;
	Doc.Generator = TEXT("Unreal StreetscapeEditorLibrary::ExportSiteJson");
	TArray<AStreetscapeActor*> Actors;
	for (TActorIterator<AStreetscapeActor> It(World); It; ++It) Actors.Add(*It);
	Actors.Sort([](const AStreetscapeActor& X, const AStreetscapeActor& Y) { return X.StreetId < Y.StreetId; });
	for (AStreetscapeActor* A : Actors)
	{
		Doc.Splines.Add(A->Spline->Def);
		for (const TPair<FString, FRoadProfileData>& Kv : A->DocProfiles.Road) Doc.Profiles.Road.Add(Kv.Key, Kv.Value);
		for (const TPair<FString, FEdgeProfileData>& Kv : A->DocProfiles.Edge) Doc.Profiles.Edge.Add(Kv.Key, Kv.Value);
		for (const TPair<FString, FHedgeProfileData>& Kv : A->DocProfiles.Hedge) Doc.Profiles.Hedge.Add(Kv.Key, Kv.Value);
	}
	if (!FStreetscapeJson::SaveFile(Path, FStreetscapeJson::WriteSite(Doc))) return FString();
	return Path;
}
