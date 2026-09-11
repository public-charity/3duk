// UStreetscapeEditorLibrary, phase 3: the actor-facing half (UE_PLAN.md 2.12, 5.3) - import a document into
// AStreetscapeActors, report the stats.json of DESIGN.md 14, place a player start, load a World Partition region
// (commandlets skip LoadLastLoadedRegions) and reproduce render.py's three fixed cameras in UE centimetres.

#include "StreetscapeEditorLibrary.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Editor.h"
#include "EngineUtils.h"
#include "GameFramework/PlayerStart.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "ObjectTools.h"
#include "StreetGeometry.h"
#include "StreetJunctionBuild.h"
#include "StreetJunctions.h"
#include "StreetMaterialTable.h"
#include "StreetProfiles.h"
#include "StreetRenderers.h"
#include "StreetOverlayComponent.h"
#include "StreetSpline.h"
#include "StreetTerrainSource.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "StreetscapeActor.h"
#include "StreetscapeMassingActor.h"
#include "StreetscapeEditorModule.h"
#include "StreetscapeJson.h"
#include "StreetscapeSiteActor.h"
#include "WorldPartition/LoaderAdapter/LoaderAdapterShape.h"
#include "WorldPartition/WorldPartition.h"

namespace
{
FString JsonText(const TSharedRef<FJsonObject>& O)
{
	FString Out;
	TSharedRef<TJsonWriter<>> W = TJsonWriterFactory<>::Create(&Out);
	FJsonSerializer::Serialize(O, W);
	return Out;
}

UWorld* EditorWorld()
{
	return GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
}

/**
 * What the last ImportStreetscapeJson call did about junctions, so a headless run can assert on it.
 *
 * A file static and not an actor property because the number that matters spans documents: an isle import is twelve
 * slices of about twenty documents each, and the claim to be checked is "1,642 junctions, 5,168 trimmed ends".
 */
struct FJunctionImportTotals
{
	int32 Documents = 0, DocumentsWithJunctions = 0;
	int32 InDocuments = 0, PlanBuilt = 0, SkippedKind = 0, SkippedArms = 0;
	int32 Arms = 0, ArmsDropped = 0, ArmsUnseparable = 0;
	int32 SplinesTrimmed = 0, SplinesDegenerate = 0, SplinesUntrimmable = 0, TrimmedEnds = 0;
	double TrimTotalM = 0.0;
	int32 Owners = 0;
	FStreetActorJunctionStats Geo;
	TArray<FString> Skips;

	void Reset() { *this = FJunctionImportTotals(); }
};
FJunctionImportTotals GJunctionTotals;

TSharedRef<FJsonObject> JunctionTotalsJson(const FJunctionImportTotals& T)
{
	TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
	O->SetNumberField(TEXT("documents"), T.Documents);
	O->SetNumberField(TEXT("documents_with_junctions"), T.DocumentsWithJunctions);
	O->SetNumberField(TEXT("junctions_in_documents"), T.InDocuments);
	O->SetNumberField(TEXT("junctions_planned"), T.PlanBuilt);
	O->SetNumberField(TEXT("junctions_built"), T.Geo.Built);
	O->SetNumberField(TEXT("junctions_owned"), T.Geo.Owned);
	O->SetNumberField(TEXT("junctions_skipped_kind"), T.SkippedKind);
	O->SetNumberField(TEXT("junctions_skipped_arms"), T.SkippedArms);
	O->SetNumberField(TEXT("junctions_skipped_build"), T.Geo.Skipped);
	O->SetNumberField(TEXT("owners"), T.Owners);
	O->SetNumberField(TEXT("arms"), T.Arms);
	O->SetNumberField(TEXT("arms_dropped"), T.ArmsDropped);
	O->SetNumberField(TEXT("arms_unseparable"), T.ArmsUnseparable);
	O->SetNumberField(TEXT("trimmed_ends"), T.TrimmedEnds);
	O->SetNumberField(TEXT("trim_total_m"), T.TrimTotalM);
	O->SetNumberField(TEXT("splines_trimmed"), T.SplinesTrimmed);
	O->SetNumberField(TEXT("splines_degenerate"), T.SplinesDegenerate);
	O->SetNumberField(TEXT("splines_untrimmable"), T.SplinesUntrimmable);
	O->SetNumberField(TEXT("non_monotone"), T.Geo.NonMonotone);
	O->SetNumberField(TEXT("patch_verts"), T.Geo.PatchVerts);
	O->SetNumberField(TEXT("patch_tris"), T.Geo.PatchTris);
	O->SetNumberField(TEXT("corners"), T.Geo.Corners);
	O->SetNumberField(TEXT("corners_skipped_no_kerb"), T.Geo.CornersSkippedNoKerb);
	O->SetNumberField(TEXT("corners_skipped_incompatible"), T.Geo.CornersSkippedIncompatible);
	O->SetNumberField(TEXT("corner_verts"), T.Geo.CornerVerts);
	O->SetNumberField(TEXT("corner_tris"), T.Geo.CornerTris);
	O->SetNumberField(TEXT("patch_area_m2"), T.Geo.PatchAreaM2);
	O->SetNumberField(TEXT("patch_overlap_area_m2"), T.Geo.PatchOverlapAreaM2);
	TArray<TSharedPtr<FJsonValue>> Sk;
	for (const FString& X : T.Skips) Sk.Add(MakeShared<FJsonValueString>(X));
	O->SetArrayField(TEXT("skipped"), Sk);
	return O;
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

int32 UStreetscapeEditorLibrary::ImportStreetscapeJson(const FString& FileOrDir, bool bPlacePlayerStart, bool bPreloadWorld, int32 MaxNoTerrainActors)
{
	UWorld* World = EditorWorld();
	if (!World) { UE_LOG(LogStreetscapeEditor, Error, TEXT("ImportStreetscapeJson: no editor world")); return -1; }

	TArray<FString> Files;
	if (FPaths::DirectoryExists(FileOrDir))
	{
		TArray<FString> Names;
		IFileManager::Get().FindFiles(Names, *(FileOrDir / TEXT("*.json")), true, false);
		Names.Sort();
		// the adapter writes streetscape_manifest.json beside the documents; it is not one of them, and feeding it
		// to the strict loader is a hard failure at the end of an hour-long site import
		for (const FString& N : Names)
		{
			if (N.EndsWith(TEXT("_manifest.json"))) continue;
			Files.Add(FileOrDir / N);
		}
	}
	else
	{
		Files.Add(FileOrDir);
	}
	if (Files.Num() == 0) { UE_LOG(LogStreetscapeEditor, Error, TEXT("ImportStreetscapeJson: nothing to load at %s"), *FileOrDir); return -1; }

	// World Partition: a commandlet has nothing loaded after load_level (WorldPartition.cpp:880-886), so
	// FindActorById below would see an empty world and every re-import would leave the previous actor behind as a
	// second copy of the same street. Pull the whole site in first, then the replace-by-id is real.
	if (bPreloadWorld)
	{
		LoadRegion(FVector::ZeroVector, 2000000.f);
	}
	else
	{
		UE_LOG(LogStreetscapeEditor, Warning,
			TEXT("ImportStreetscapeJson: bPreloadWorld=false - existing actors are NOT streamed in, so nothing is replaced by id. "
				 "Only correct when the level is known to hold no streetscape actor for these ids."));
	}

	int32 Spawned = 0;
	bool bPlacedStart = false;
	// A street whose stations all sampled NaN is built flat at z = 0 - geometry that looks fine and is wrong.
	// FStreetSamples records it as a warning; collect them and refuse the import rather than let it through.
	TArray<FString> NoTerrainIds;
	int32 PartialTerrainActors = 0;
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
	// NOT reset here. A site import calls this function ONCE PER DOCUMENT (03_import_streetscape.py loops over the
	// slice's files), so resetting per call left the caller reading the last document's junctions and reporting 79
	// for the isle instead of 1,642. The totals accumulate; ResetImportJunctionTotals() is the caller's to call.
	const double TStart = FPlatformTime::Seconds();
	int32 FileIndex = 0;
	for (const FString& File : Files)
	{
		++FileIndex;
		const double TFile = FPlatformTime::Seconds();
		const int32 SpawnedBefore = Spawned;
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

		// -- SCHEMA.md 4.18: solve this document's junctions BEFORE any spline is built -------------------------
		//
		// This is the only place in the engine where a whole document exists at once. The plan is a per-DOCUMENT
		// solve - a spline trimmed at both ends has its two trims scaled by ONE factor, which couples two different
		// junctions - so it can only be done here; and every junction's arms are in the same document by
		// construction, measured over the isle at 0 of 5,185 ends naming a spline outside their own file. What the
		// solve decides is then written ONTO the actors (AStreetscapeActor::SetJunctionData) rather than used here,
		// so a street World Partition streams back in later rebuilds the same junction with no importer, no
		// document and no other actor resident.
		FStreetJunctionPlan Plan;
		if (!Plan.Build(Doc)) { UE_LOG(LogStreetscapeEditor, Error, TEXT("invalid junction plan: %s"), *Plan.Error); return -1; }
		TMap<FString, FVector2D> Trims;
		TMap<FString, TArray<FStreetOwnedJunction>> Owned;
		FStreetJunctionBuild::Distribute(Doc, Plan, Trims, Owned);
		const int32 DocPlanned = Plan.Stats[TEXT("junctions_built")];
		{
			FJunctionImportTotals& T = GJunctionTotals;
			++T.Documents;
			if (Doc.Junctions.Num()) ++T.DocumentsWithJunctions;
			T.InDocuments += Plan.Stats[TEXT("junctions")];
			T.PlanBuilt += DocPlanned;
			T.SkippedKind += Plan.Stats[TEXT("junctions_skipped_kind")];
			T.SkippedArms += Plan.Stats[TEXT("junctions_skipped_arms")];
			T.Arms += Plan.Stats[TEXT("arms")];
			T.ArmsDropped += Plan.Stats[TEXT("arms_dropped")];
			T.ArmsUnseparable += Plan.Stats[TEXT("arms_unseparable")];
			T.SplinesTrimmed += Plan.Stats[TEXT("splines_trimmed")];
			T.SplinesDegenerate += Plan.Stats[TEXT("splines_degenerate")];
			T.SplinesUntrimmable += Plan.Stats[TEXT("splines_untrimmable")];
			T.Owners += Owned.Num();
			for (const TPair<FString, FVector2D>& Kv : Trims)
			{
				if (Kv.Value.X > 0.0) { ++T.TrimmedEnds; T.TrimTotalM += Kv.Value.X; }
				if (Kv.Value.Y > 0.0) { ++T.TrimmedEnds; T.TrimTotalM += Kv.Value.Y; }
			}
		}
		int32 DocBuilt = 0;

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
			{
				const FVector2D* Tr = Trims.Find(Def.Id);
				TArray<FStreetOwnedJunction> Mine;
				if (TArray<FStreetOwnedJunction>* O = Owned.Find(Def.Id)) Mine = MoveTemp(*O);
				A->SetJunctionData(Tr ? *Tr : FVector2D::ZeroVector, MoveTemp(Mine), Plan.InteriorBendsFor(Def.Id));
			}
			FString BuildErr;
			if (!A->RebuildAllChecked(&BuildErr))
			{
				UE_LOG(LogStreetscapeEditor, Error, TEXT("%s: build failed: %s"), *Def.Id, *BuildErr);
				return -1;
			}
			++Spawned;
			DocBuilt += A->JunctionStats.Built;
			GJunctionTotals.Geo.Add(A->JunctionStats);
			for (const FString& Why : A->JunctionSkips())
			{
				if (GJunctionTotals.Skips.Num() < 200) GJunctionTotals.Skips.Add(Why);
			}
			if (const FStreetSamples* Sm0 = A->GetSamples())
			{
				for (const FString& W : Sm0->Warnings)
				{
					if (W.StartsWith(TEXT("no terrain under any station")))
					{
						// no per-spline log here: whether this is an Error or an accepted Warning is only known
						// once they have all been counted, and an Error line would fail the run either way
						NoTerrainIds.Add(FString::Printf(TEXT("%s (%s)"), *Def.Id, *FPaths::GetCleanFilename(File)));
					}
					else if (W.Contains(TEXT("without terrain filled along s")))
					{
						++PartialTerrainActors;
					}
				}
			}
			if (bPlacePlayerStart && !bPlacedStart && Def.Points.Num() >= 2)
			{
				const FStreetSamples* Sm = A->GetSamples();
				const double Z = (Sm && Sm->ZRef.Num()) ? Sm->ZRef[0] : 0.0;
				const double Dx = Def.Points[1].X - Def.Points[0].X;
				const double Dy = Def.Points[1].Y - Def.Points[0].Y;
				const double BearingDeg = FMath::RadiansToDegrees(FMath::Atan2(Dx, Dy));
				// BRIEF/STAGES FD.4 and Tools/ue/README: the spawn point stands 2 m above the first waypoint
				const FVector Loc = FStreetscapeJson::ToUE(FVector3d(Def.Points[0].X, Def.Points[0].Y, Z + 2.0));
				const FRotator Rot(0.0, FStreetscapeJson::YawFromBearingDeg(BearingDeg), 0.0);
				if (APlayerStart* PS = World->SpawnActor<APlayerStart>(APlayerStart::StaticClass(), Loc, Rot))
				{
					PS->SetActorLabel(TEXT("PlayerStart_Streetscape"));
					bPlacedStart = true;
				}
			}
		}
		// -- THE GATE. A document whose junctions the plan solved and the level then drew none of is the exact
		// defect this round exists to close: the layer was written, ported, tested and called by nothing, and the
		// import reported success on a level with zero junctions in it. Success on zero is never a pass.
		if (DocPlanned != DocBuilt)
		{
			UE_LOG(LogStreetscapeEditor, Error,
				TEXT("%s: the junction plan solved %d junction(s) and the level built %d - an import that does not "
					 "draw the junctions it planned is a failure, not a pass"),
				*FPaths::GetCleanFilename(File), DocPlanned, DocBuilt);
			return -1;
		}
		if (DocPlanned > 0)
		{
			UE_LOG(LogStreetscapeEditor, Log, TEXT("%s: %d junction(s) built, %d spline(s) trimmed"),
				*FPaths::GetCleanFilename(File), DocBuilt, Plan.Stats[TEXT("splines_trimmed")]);
		}
		if (Files.Num() > 1)
		{
			// a site import is 246 documents and about an hour: say where it is, so a run can be watched
			UE_LOG(LogStreetscapeEditor, Display, TEXT("ImportStreetscapeJson [%d/%d] %s: %d spline(s) in %.1f s (total %d actors, %.0f s, rss %.0f MB)"),
				FileIndex, Files.Num(), *FPaths::GetCleanFilename(File), Spawned - SpawnedBefore,
				FPlatformTime::Seconds() - TFile, Spawned, FPlatformTime::Seconds() - TStart,
				(double)FPlatformMemory::GetStats().UsedPhysical / (1024.0 * 1024.0));
		}
	}
	if (PartialTerrainActors)
	{
		UE_LOG(LogStreetscapeEditor, Warning, TEXT("ImportStreetscapeJson: %d of %d actor(s) had station(s) without terrain, filled along s"),
			PartialTerrainActors, Spawned);
	}
	if (NoTerrainIds.Num())
	{
		const bool bTooMany = NoTerrainIds.Num() > MaxNoTerrainActors;
		const FString Msg = FString::Printf(
			TEXT("ImportStreetscapeJson: %d of %d actor(s) sampled NO terrain at any station and were built flat at z = 0 (limit %d): %s"),
			NoTerrainIds.Num(), Spawned, MaxNoTerrainActors, *FString::Join(NoTerrainIds, TEXT(", ")));
		if (bTooMany)
		{
			UE_LOG(LogStreetscapeEditor, Error, TEXT("%s"), *Msg);
			return -1;
		}
		UE_LOG(LogStreetscapeEditor, Warning, TEXT("ACCEPTED %s"), *Msg);
	}
	UE_LOG(LogStreetscapeEditor, Display, TEXT("ImportStreetscapeJson junctions: %s"), *JsonText(JunctionTotalsJson(GJunctionTotals)));
	// THE WHOLE-RUN GATE. "Records present, none built" is NOT by itself the defect: the plan legitimately drops a
	// record with fewer than three usable arms (junctions_skipped_arms) or a kind it does not fill
	// (junctions_skipped_kind), exactly as the numpy JunctionPlan does - the authored test stretch is one such
	// document. What must never pass is a record that disappears without one of those reasons, or a plan that
	// solved junctions the level then did not draw.
	{
		const FJunctionImportTotals& T = GJunctionTotals;
		const int32 Accounted = T.PlanBuilt + T.SkippedKind + T.SkippedArms;
		if (T.PlanBuilt > 0 && T.Geo.Built == 0)
		{
			UE_LOG(LogStreetscapeEditor, Error,
				TEXT("ImportStreetscapeJson: the plan solved %d junction(s) across %d document(s) and NOT ONE was built"),
				T.PlanBuilt, T.Documents);
			return -1;
		}
		if (T.InDocuments != Accounted)
		{
			UE_LOG(LogStreetscapeEditor, Error,
				TEXT("ImportStreetscapeJson: %d junction record(s) but only %d accounted for (%d built, %d skipped on kind, "
					 "%d skipped on arms) - a record vanished without a reason"),
				T.InDocuments, Accounted, T.PlanBuilt, T.SkippedKind, T.SkippedArms);
			return -1;
		}
	}
	return Spawned;
}

FString UStreetscapeEditorLibrary::LastImportJunctionsJson()
{
	return JsonText(JunctionTotalsJson(GJunctionTotals));
}

void UStreetscapeEditorLibrary::ResetImportJunctionTotals()
{
	GJunctionTotals.Reset();
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
			// build._assert_stations: equality against spline.s[spline.active], so a trimmed arm is not a mismatch
			TArray<double> ActiveS;
			for (int32 I = 0; I < Sp->S.Num(); ++I)
			{
				if (!Sp->Active.IsValidIndex(I) || Sp->Active[I]) ActiveS.Add(Sp->S[I]);
			}
			bSame = St.Num() == ActiveS.Num();
			for (int32 I = 0; bSame && I < St.Num(); ++I) bSame = St[I] == ActiveS[I];
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

// ---------------------------------------------------------------------------------------------------------------
// Census: the size of the network the level actually holds (D5). ActorStatsJson is the per-actor truth but it
// recomputes station sets and lateral overlaps, which is minutes at 15,422 actors; this walks the built buffers
// only.
// ---------------------------------------------------------------------------------------------------------------

FString UStreetscapeEditorLibrary::StreetscapeCensusJson()
{
	TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
	UWorld* World = EditorWorld();
	if (!World)
	{
		O->SetStringField(TEXT("error"), TEXT("no editor world"));
		return JsonText(O);
	}
	const double T0 = FPlatformTime::Seconds();
	int32 Actors = 0, WithoutSamples = 0, EmptyBuffers = 0, Components = 0, Overlays = 0, InstanceComps = 0;
	int64 Verts = 0, Tris = 0, Instances = 0, MarkingStrips = 0, Stations = 0;
	double LengthM = 0.0;
	TMap<FString, int64> VertsByBuffer, TrisByBuffer;
	TMap<FString, int32> ActorsByLayer;      // roads / rail / barriers, from the id prefix
	TMap<FName, int64> InstancesByKind;
	FStreetActorJunctionStats Jn;
	int32 TrimmedSplines = 0, TrimmedEnds = 0;
	double TrimTotalM = 0.0;
	for (TActorIterator<AStreetscapeActor> It(World); It; ++It)
	{
		AStreetscapeActor* A = *It;
		++Actors;
		Jn.Add(A->JunctionStats);
		if (A->JunctionTrimM.X > 0.0) { ++TrimmedEnds; TrimTotalM += A->JunctionTrimM.X; }
		if (A->JunctionTrimM.Y > 0.0) { ++TrimmedEnds; TrimTotalM += A->JunctionTrimM.Y; }
		if (A->JunctionTrimM.X > 0.0 || A->JunctionTrimM.Y > 0.0) ++TrimmedSplines;
		FString Layer, Rest;
		ActorsByLayer.FindOrAdd(A->StreetId.Split(TEXT(":"), &Layer, &Rest) ? Layer : FString(TEXT("?")))++;
		const FStreetSamples* Sm = A->GetSamples();
		if (!Sm) { ++WithoutSamples; continue; }
		Stations += Sm->S.Num();
		LengthM += Sm->LengthM;
		MarkingStrips += A->MarkingStrips();
		const TMap<FString, const FStreetMeshBuilder*> Bufs = A->Buffers();
		if (Bufs.Num() == 0) ++EmptyBuffers;
		for (const TPair<FString, const FStreetMeshBuilder*>& Kv : Bufs)
		{
			const FStreetBuildStats St = Kv.Value->Stats();
			Verts += St.Verts;
			Tris += St.Tris;
			VertsByBuffer.FindOrAdd(Kv.Key) += St.Verts;
			TrisByBuffer.FindOrAdd(Kv.Key) += St.Tris;
		}
		for (const TPair<FName, int32>& Kv : A->InstanceCounts())
		{
			Instances += Kv.Value;
			InstancesByKind.FindOrAdd(Kv.Key) += Kv.Value;
		}
		for (UActorComponent* C : A->GetComponents())
		{
			if (Cast<UStreetRendererBase>(C)) ++Components;
			else if (Cast<UStreetOverlayComponent>(C)) ++Overlays;
			else if (Cast<UInstancedStaticMeshComponent>(C)) ++InstanceComps;
		}
	}
	int32 Massing = 0;
	int64 MassingVerts = 0, MassingTris = 0, MassingBuildings = 0;
	for (TActorIterator<AStreetscapeMassingActor> It(World); It; ++It)
	{
		++Massing;
		MassingVerts += It->Stats.Verts;
		MassingTris += It->Stats.Tris;
		MassingBuildings += It->Stats.Buildings;
	}
	O->SetNumberField(TEXT("actors"), Actors);
	O->SetNumberField(TEXT("actors_without_samples"), WithoutSamples);
	O->SetNumberField(TEXT("actors_with_no_buffer"), EmptyBuffers);
	O->SetNumberField(TEXT("renderer_components"), Components);
	O->SetNumberField(TEXT("overlay_components"), Overlays);
	O->SetNumberField(TEXT("instanced_mesh_components"), InstanceComps);
	O->SetNumberField(TEXT("verts"), (double)Verts);
	O->SetNumberField(TEXT("tris"), (double)Tris);
	O->SetNumberField(TEXT("instances"), (double)Instances);
	O->SetNumberField(TEXT("marking_strips"), (double)MarkingStrips);
	O->SetNumberField(TEXT("stations"), (double)Stations);
	O->SetNumberField(TEXT("length_m"), LengthM);
	// the junction layer, read off the actors themselves: this is the number that was zero for a whole round
	O->SetNumberField(TEXT("junctions_owned"), Jn.Owned);
	O->SetNumberField(TEXT("junctions_built"), Jn.Built);
	O->SetNumberField(TEXT("junctions_skipped"), Jn.Skipped);
	O->SetNumberField(TEXT("junction_non_monotone"), Jn.NonMonotone);
	O->SetNumberField(TEXT("junction_patch_verts"), Jn.PatchVerts);
	O->SetNumberField(TEXT("junction_patch_tris"), Jn.PatchTris);
	O->SetNumberField(TEXT("junction_corners"), Jn.Corners);
	O->SetNumberField(TEXT("junction_corners_skipped_no_kerb"), Jn.CornersSkippedNoKerb);
	O->SetNumberField(TEXT("junction_corners_skipped_incompatible"), Jn.CornersSkippedIncompatible);
	O->SetNumberField(TEXT("junction_corner_verts"), Jn.CornerVerts);
	O->SetNumberField(TEXT("junction_corner_tris"), Jn.CornerTris);
	O->SetNumberField(TEXT("junction_patch_area_m2"), Jn.PatchAreaM2);
	O->SetNumberField(TEXT("junction_patch_overlap_area_m2"), Jn.PatchOverlapAreaM2);
	O->SetNumberField(TEXT("splines_trimmed"), TrimmedSplines);
	O->SetNumberField(TEXT("trimmed_ends"), TrimmedEnds);
	O->SetNumberField(TEXT("trim_total_m"), TrimTotalM);
	O->SetNumberField(TEXT("massing_actors"), Massing);
	O->SetNumberField(TEXT("massing_verts"), (double)MassingVerts);
	O->SetNumberField(TEXT("massing_tris"), (double)MassingTris);
	O->SetNumberField(TEXT("massing_buildings"), (double)MassingBuildings);
	O->SetNumberField(TEXT("rss_mb"), (double)FPlatformMemory::GetStats().UsedPhysical / (1024.0 * 1024.0));
	O->SetNumberField(TEXT("peak_rss_mb"), (double)FPlatformMemory::GetStats().PeakUsedPhysical / (1024.0 * 1024.0));
	O->SetNumberField(TEXT("seconds"), FPlatformTime::Seconds() - T0);
	{
		TSharedRef<FJsonObject> B = MakeShared<FJsonObject>();
		for (const TPair<FString, int64>& Kv : VertsByBuffer)
		{
			TSharedRef<FJsonObject> E = MakeShared<FJsonObject>();
			E->SetNumberField(TEXT("verts"), (double)Kv.Value);
			E->SetNumberField(TEXT("tris"), (double)TrisByBuffer.FindRef(Kv.Key));
			B->SetObjectField(Kv.Key, E);
		}
		O->SetObjectField(TEXT("by_buffer"), B);
	}
	{
		TSharedRef<FJsonObject> B = MakeShared<FJsonObject>();
		for (const TPair<FString, int32>& Kv : ActorsByLayer) B->SetNumberField(Kv.Key, Kv.Value);
		O->SetObjectField(TEXT("actors_by_layer"), B);
	}
	{
		TSharedRef<FJsonObject> B = MakeShared<FJsonObject>();
		for (const TPair<FName, int64>& Kv : InstancesByKind) B->SetNumberField(Kv.Key.ToString(), (double)Kv.Value);
		O->SetObjectField(TEXT("instances_by_kind"), B);
	}
	return JsonText(O);
}

int32 UStreetscapeEditorLibrary::PurgeStreetscapeActors()
{
	UWorld* World = EditorWorld();
	if (!World) return 0;
	// a commandlet has nothing loaded, and an actor that is not loaded is not destroyed - it comes straight back
	// the next time the map is opened, which is exactly how a "fresh" import ends up doubled.
	LoadRegion(FVector::ZeroVector, 2000000.f);
	TArray<AActor*> All;
	for (TActorIterator<AStreetscapeActor> It(World); It; ++It) All.Add(*It);
	const int32 N = All.Num();
	const int32 Packages = DeleteActorsAndPackages(All);
	UE_LOG(LogStreetscapeEditor, Display, TEXT("PurgeStreetscapeActors: destroyed %d actor(s), deleted %d package(s)"), N, Packages);
	return N;
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
		if (!A->Spline || !A->OwnedJunctions.IsEmpty() || !A->JunctionTrimM.IsNearlyZero() ||
			!A->Spline->Def.JunctionStart.IsEmpty() || !A->Spline->Def.JunctionEnd.IsEmpty())
		{
			UE_LOG(LogStreetscapeEditor, Error, TEXT("ExportSiteJson: junction data requires ExportDocumentJson with the source document"));
			return FString();
		}
		Doc.Splines.Add(A->Spline->Def);
		for (const TPair<FString, FRoadProfileData>& Kv : A->DocProfiles.Road) Doc.Profiles.Road.Add(Kv.Key, Kv.Value);
		for (const TPair<FString, FEdgeProfileData>& Kv : A->DocProfiles.Edge) Doc.Profiles.Edge.Add(Kv.Key, Kv.Value);
		for (const TPair<FString, FHedgeProfileData>& Kv : A->DocProfiles.Hedge) Doc.Profiles.Hedge.Add(Kv.Key, Kv.Value);
	}
	if (!FStreetscapeJson::SaveFile(Path, FStreetscapeJson::WriteSite(Doc))) return FString();
	return Path;
}
