#include "StreetscapeDocumentEdit.h"
#include "StreetscapeEditorLibrary.h"
#include "StreetscapeEditorModule.h"
#include "StreetscapeActor.h"
#include "StreetscapeSiteActor.h"
#include "StreetscapeJson.h"
#include "StreetSpline.h"
#include "StreetSplineMath.h"
#include "StreetJunctionBuild.h"
#include "Editor.h"
#include "EngineUtils.h"
#include "Misc/Paths.h"
#include "ScopedTransaction.h"
#include "UObject/Package.h"
#include "UObject/UObjectIterator.h"

namespace
{
template<typename T, typename Writer>
bool MergeProfile(const FString& Id, const TMap<FString, T>& Available, TMap<FString, T>& Out,
	TMap<FString, FString>& Seen, Writer Write, FString& Error)
{
	if (Id.IsEmpty()) return true;
	const T* P = Available.Find(Id);
	if (!P) { Error = TEXT("missing resolved profile: ") + Id; return false; }
	const FString Text = FStreetscapeJson::ToText(Write(*P), true, -1, -1);
	if (const FString* Previous = Seen.Find(Id))
		if (*Previous != Text) { Error = TEXT("conflicting actor definitions for profile: ") + Id; return false; }
	Seen.Add(Id, Text);
	Out.Add(Id, *P);
	return true;
}
}

bool StreetDocumentEdit::Assemble(const FStreetSiteDoc& Source, const TArray<FStreetDocumentActorState>& States,
	FStreetSiteDoc& Out, FString& Error)
{
	Error.Reset();
	if (Source.Splines.IsEmpty()) { Error = TEXT("source document has no splines"); return false; }
	TMap<FString, const FStreetDocumentActorState*> ById;
	for (const FStreetDocumentActorState& S : States)
	{
		if (ById.Contains(S.Id) || S.Id != S.Def.Id || !Source.FindSpline(S.Id))
		{ Error = TEXT("duplicate, renamed or unexpected actor: ") + S.Id; return false; }
		if (!FMath::IsNearlyEqual(S.OriginEN.X, Source.Origin.E, 1e-6) ||
			!FMath::IsNearlyEqual(S.OriginEN.Y, Source.Origin.N, 1e-6))
		{ Error = TEXT("actor origin differs from source: ") + S.Id; return false; }
		ById.Add(S.Id, &S);
	}
	FStreetSiteDoc Candidate = Source;
	TMap<FString, FString> RoadSeen, EdgeSeen, HedgeSeen;
	for (FStreetSplineDef& D : Candidate.Splines)
	{
		const FStreetDocumentActorState* const* Found = ById.Find(D.Id);
		if (!Found) { Error = TEXT("source actor is not loaded: ") + D.Id; return false; }
		const FStreetDocumentActorState& S = **Found;
		D = S.Def;
		auto Road = [&](const FString& Id) { return MergeProfile(Id, S.Profiles.Road, Candidate.Profiles.Road,
			RoadSeen, FStreetscapeJson::WriteRoadProfile, Error); };
		auto Edge = [&](const FString& Id) { return MergeProfile(Id, S.Profiles.Edge, Candidate.Profiles.Edge,
			EdgeSeen, FStreetscapeJson::WriteEdgeProfile, Error); };
		auto Hedge = [&](const FString& Id) { return MergeProfile(Id, S.Profiles.Hedge, Candidate.Profiles.Hedge,
			HedgeSeen, FStreetscapeJson::WriteHedgeProfile, Error); };
		if (!Road(D.ProfileIds.Road) || !Edge(D.ProfileIds.EdgeLeft) || !Edge(D.ProfileIds.EdgeRight) ||
			!Hedge(D.ProfileIds.HedgeLeft) || !Hedge(D.ProfileIds.HedgeRight)) return false;
		for (const FStreetSegment& Segment : D.Segments)
		{
			if ((Segment.bHasRoad && !Road(Segment.Road.ProfileId)) ||
				(Segment.bHasEdge && !Edge(Segment.Edge.ProfileId)) ||
				(Segment.bHasHedge && !Hedge(Segment.Hedge.ProfileId))) return false;
		}
	}
	TArray<FString> Problems;
	FStreetSiteDoc Validated;
	if (!FStreetscapeJson::ReadSite(FStreetscapeJson::WriteSite(Candidate), Validated, Problems))
	{ Error = FString::Join(Problems, TEXT("; ")); return false; }
	Out = MoveTemp(Validated);
	return true;
}

bool StreetDocumentEdit::ValidatePreview(const FStreetSiteDoc& Source, const FStreetSiteDoc& Candidate, FString& Error)
{
	Error.Reset();
	if (Source.Site != Candidate.Site || Source.Crs != Candidate.Crs || Source.VerticalDatum != Candidate.VerticalDatum ||
		Source.Origin.E != Candidate.Origin.E || Source.Origin.N != Candidate.Origin.N ||
		Source.Splines.Num() != Candidate.Splines.Num() || Source.Splines.IsEmpty())
	{ Error = TEXT("preview must preserve source registration and spline count"); return false; }
	auto JunctionText = [](const FStreetSiteDoc& Doc)
	{
		const auto All = FStreetscapeJson::WriteSite(Doc);
		const auto Only = MakeShared<FJsonObject>();
		if (const TSharedPtr<FJsonValue> Value = All->TryGetField(TEXT("junctions"))) Only->SetField(TEXT("junctions"),Value);
		return FStreetscapeJson::Canonical(Only);
	};
	FStreetSiteDoc Comparable = Candidate;
	if (Source.Junctions.Num() != Candidate.Junctions.Num())
	{ Error = TEXT("preview must preserve all junctions"); return false; }
	for (int32 I=0; I<Candidate.Junctions.Num(); ++I)
	{
		const auto& Trim = Candidate.Junctions[I].TrimRadiusM;
		if (Trim.IsSet() && (!FMath::IsFinite(Trim.GetValue()) || Trim.GetValue()<=0. || Trim.GetValue()>32.))
		{ Error = TEXT("preview junction trim must be finite and within (0,32] m"); return false; }
		Comparable.Junctions[I].TrimRadiusM = Source.Junctions[I].TrimRadiusM;
	}
	if (JunctionText(Source) != JunctionText(Comparable))
	{ Error = TEXT("preview must preserve junction topology and registration; only trim radius may change"); return false; }
	TSet<FString> Seen;
	for (const FStreetSplineDef& D : Candidate.Splines)
	{
		const FStreetSplineDef* Original = Source.FindSpline(D.Id);
		if (!Original || Seen.Contains(D.Id)) { Error = TEXT("renamed, duplicate or unexpected preview spline: ") + D.Id; return false; }
		Seen.Add(D.Id);
		const auto& A = Original->ProfileIds;
		const auto& B = D.ProfileIds;
		if (A.Road.IsEmpty() != B.Road.IsEmpty() || A.EdgeLeft.IsEmpty() != B.EdgeLeft.IsEmpty() ||
			A.EdgeRight.IsEmpty() != B.EdgeRight.IsEmpty() || A.HedgeLeft.IsEmpty() != B.HedgeLeft.IsEmpty() ||
			A.HedgeRight.IsEmpty() != B.HedgeRight.IsEmpty() || Original->JunctionStart != D.JunctionStart || Original->JunctionEnd != D.JunctionEnd)
		{ Error = TEXT("preview cannot change component slots or junction bindings: ") + D.Id; return false; }
	}
	return true;
}

namespace
{
const TArray<FStreetJunction>* PreviewJunctions(const FString& SourcePath);
bool CurrentDocument(const FString& SourcePath, FStreetSiteDoc& Source, FStreetSiteDoc& Current,
	TArray<AStreetscapeActor*>& Actors, FString& Error)
{
	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	TSharedPtr<FJsonObject> Obj;
	FText ReadError;
	TArray<FString> Problems;
	if (!World || !FStreetscapeJson::LoadFile(SourcePath, Obj, &ReadError) ||
		!FStreetscapeJson::ReadSite(Obj.ToSharedRef(), Source, Problems))
	{ Error = ReadError.ToString() + FString::Join(Problems, TEXT("; ")); return false; }
	// The active preview owns its complete junction settings in memory. Never write
	// them over the source document; exports/refreshes use the same preview model.
	if (const auto* Junctions = PreviewJunctions(SourcePath)) Source.Junctions = *Junctions;
	AStreetscapeSiteActor* Site = AStreetscapeSiteActor::Get(World);
	if (!Site || Site->SiteName != Source.Site || Site->Crs != Source.Crs || Site->VerticalDatum != Source.VerticalDatum ||
		!FMath::IsNearlyEqual(Site->OriginEN.X, Source.Origin.E, 1e-6) ||
		!FMath::IsNearlyEqual(Site->OriginEN.Y, Source.Origin.N, 1e-6))
	{ Error = TEXT("source/site registration mismatch"); return false; }
	TArray<FStreetDocumentActorState> States;
	for (TActorIterator<AStreetscapeActor> It(World); It; ++It)
	{
		AStreetscapeActor* A = *It;
		if (!Source.FindSpline(A->StreetId)) continue;
		if (!A->Spline || !A->GetActorTransform().Equals(FTransform::Identity))
		{ Error = TEXT("missing spline or transformed actor: ") + A->StreetId; return false; }
		States.Add({A->StreetId, A->DocOriginEN, A->Spline->Def, A->ResolveProfiles()});
		Actors.Add(A);
	}
	return StreetDocumentEdit::Assemble(Source, States, Current, Error);
}

bool PlanCurrent(const FStreetSiteDoc& Source, const FStreetSiteDoc& Current,
	TMap<FString, FVector2D>& Trims, TMap<FString, TArray<FStreetOwnedJunction>>& Owned, FString& Error)
{
	FStreetJunctionPlan Before, After;
	Before.Build(Source);
	After.Build(Current);
	const TArray<FString> AfterIds = After.BuiltJunctionIds();
	for (const FString& Id : Before.BuiltJunctionIds())
		if (!AfterIds.Contains(Id)) { Error = TEXT("edit removes a previously buildable junction: ") + Id; return false; }
	FStreetJunctionBuild::Distribute(Current, After, Trims, Owned);
	return true;
}
}

FString UStreetscapeEditorLibrary::ExportDocumentJson(const FString& SourcePath, const FString& OutPath)
{
	if (FPaths::IsSamePath(FPaths::ConvertRelativePathToFull(SourcePath), FPaths::ConvertRelativePathToFull(OutPath)))
	{ UE_LOG(LogStreetscapeEditor, Error, TEXT("ExportDocumentJson requires a separate output path")); return FString(); }
	FStreetSiteDoc Source, Current;
	TArray<AStreetscapeActor*> Actors;
	FString Error;
	TMap<FString, FVector2D> Trims;
	TMap<FString, TArray<FStreetOwnedJunction>> Owned;
	if (!CurrentDocument(SourcePath, Source, Current, Actors, Error) || !PlanCurrent(Source, Current, Trims, Owned, Error))
	{ UE_LOG(LogStreetscapeEditor, Error, TEXT("ExportDocumentJson: %s"), *Error); return FString(); }
	return FStreetscapeJson::SaveFile(OutPath, FStreetscapeJson::WriteSite(Current)) ? OutPath : FString();
}

int32 UStreetscapeEditorLibrary::RefreshDocumentJunctions(const FString& SourcePath)
{
	FStreetSiteDoc Source, Current;
	TArray<AStreetscapeActor*> Actors;
	FString Error;
	TMap<FString, FVector2D> Trims;
	TMap<FString, TArray<FStreetOwnedJunction>> Owned;
	if (!CurrentDocument(SourcePath, Source, Current, Actors, Error) || !PlanCurrent(Source, Current, Trims, Owned, Error))
	{ UE_LOG(LogStreetscapeEditor, Error, TEXT("RefreshDocumentJunctions: %s"), *Error); return -1; }
	AStreetscapeSiteActor* Site = AStreetscapeSiteActor::Get(Actors[0]->GetWorld());
	const IStreetTerrainSource* Terrain = Site->TerrainForOrigin(Current.Origin.E, Current.Origin.N);
	// Build every affected spline and junction BEFORE changing any actor or package dirty flag.
	for (const FStreetSplineDef& Def : Current.Splines)
	{
		const FVector2D Trim = Trims.FindRef(Def.Id);
		const double T[2] = { Trim.X, Trim.Y };
		FStreetSamples Samples;
		if (!FStreetSplineMath::Build(Def, Current.Profiles, Terrain, Samples, &Error, T))
		{ UE_LOG(LogStreetscapeEditor, Error, TEXT("RefreshDocumentJunctions preflight: %s %s"), *Def.Id, *Error); return -1; }
		if (const TArray<FStreetOwnedJunction>* Mine = Owned.Find(Def.Id))
		{
			FStreetMeshBuilder Road, Edge;
			FStreetActorJunctionStats Stats;
			TArray<FString> Skips;
			FStreetJunctionBuild::BuildOwned(*Mine, Def.Id, Samples, Current.Profiles, Terrain, Road, Edge, Stats, Skips);
			if (Stats.Built != Mine->Num() || !Skips.IsEmpty())
			{ UE_LOG(LogStreetscapeEditor, Error, TEXT("RefreshDocumentJunctions preflight: incomplete junctions for %s"), *Def.Id); return -1; }
		}
	}
	struct FBackup { FVector2D Trim; TArray<FStreetOwnedJunction> Owned; FStreetSiteProfiles Profiles; bool Dirty; };
	TArray<FBackup> Before;
	auto Package = [](AStreetscapeActor* A) { return A->GetExternalPackage() ? A->GetExternalPackage() : A->GetPackage(); };
	const FScopedTransaction Transaction(NSLOCTEXT("Streetscape", "RefreshDocument", "Refresh streetscape document junctions"));
	for (AStreetscapeActor* A : Actors)
	{
		Before.Add({A->JunctionTrimM, A->OwnedJunctions, A->DocProfiles, Package(A)->IsDirty()});
		A->Modify();
		A->DocProfiles = Current.Profiles;
		A->SetJunctionData(Trims.FindRef(A->StreetId), Owned.FindRef(A->StreetId));
	}
	for (AStreetscapeActor* A : Actors)
	{
		if (A->RebuildAllChecked(&Error)) continue;
		for (int32 I = 0; I < Actors.Num(); ++I)
		{
			Actors[I]->DocProfiles = Before[I].Profiles;
			Actors[I]->SetJunctionData(Before[I].Trim, MoveTemp(Before[I].Owned));
			Actors[I]->RebuildAll();
			Package(Actors[I])->SetDirtyFlag(Before[I].Dirty);
		}
		UE_LOG(LogStreetscapeEditor, Error, TEXT("RefreshDocumentJunctions rolled back: %s"), *Error);
		return -1;
	}
	// Changes remain unsaved, with stable actor identities. The caller owns the normal editor save step.
	return Actors.Num();
}

namespace
{
struct FDocumentPreviewSnapshot
{
	FString SourcePath;
	TArray<FStreetJunction> Junctions;
	bool bRestoring = false;
	TArray<TWeakObjectPtr<AStreetscapeActor>> Actors;
	TArray<FStreetSplineDef> Definitions;
	TArray<FStreetSiteProfiles> Profiles;
	TArray<TPair<TWeakObjectPtr<UPackage>,bool>> Dirty;
};
TUniquePtr<FDocumentPreviewSnapshot> DocumentPreview;

const TArray<FStreetJunction>* PreviewJunctions(const FString& SourcePath)
{
	if (DocumentPreview && !DocumentPreview->bRestoring &&
		FPaths::IsSamePath(FPaths::ConvertRelativePathToFull(SourcePath),FPaths::ConvertRelativePathToFull(DocumentPreview->SourcePath)))
		return &DocumentPreview->Junctions;
	return nullptr;
}

FString PreviewReply(const TSharedRef<FJsonObject>& Report, const FString& Error = FString())
{
	Report->SetBoolField(TEXT("ok"),Error.IsEmpty());
	Report->SetBoolField(TEXT("saved"),false);
	if (!Error.IsEmpty()) Report->SetStringField(TEXT("error"),Error);
	return FStreetscapeJson::ToText(Report,false,1,-1);
}

void RestorePreviewDirty()
{
	for (const auto& Pair : DocumentPreview->Dirty) if (UPackage* Package = Pair.Key.Get()) Package->SetDirtyFlag(Pair.Value);
}
}

FString UStreetscapeEditorLibrary::RestoreDocumentPreviewJson()
{
	const auto Report = MakeShared<FJsonObject>();
	if (!IsRunningCommandlet()) return PreviewReply(Report,TEXT("document previews are restricted to commandlets"));
	if (!DocumentPreview)
	{
		Report->SetBoolField(TEXT("nothing_to_restore"),true);
		Report->SetBoolField(TEXT("restored"),true);
		return PreviewReply(Report);
	}
	for (const auto& Weak : DocumentPreview->Actors)
		if (!Weak.IsValid()) return PreviewReply(Report,TEXT("preview actor no longer loaded"));
	DocumentPreview->bRestoring = true;
	for (int32 I=0;I<DocumentPreview->Actors.Num();++I)
	{
		AStreetscapeActor* A = DocumentPreview->Actors[I].Get();
		A->DocProfiles = DocumentPreview->Profiles[I];
		A->Spline->Def = DocumentPreview->Definitions[I];
		A->Spline->SyncComponentFromDef();
	}
	const int32 Count = RefreshDocumentJunctions(DocumentPreview->SourcePath);
	RestorePreviewDirty();
	if (Count != DocumentPreview->Actors.Num()) return PreviewReply(Report,TEXT("document restoration refresh failed"));
	Report->SetBoolField(TEXT("restored"),true);
	Report->SetNumberField(TEXT("actors"),Count);
	DocumentPreview.Reset();
	return PreviewReply(Report);
}

FString UStreetscapeEditorLibrary::PreviewDocumentJson(const FString& SourcePath, const FString& CandidatePath)
{
	const auto Report = MakeShared<FJsonObject>();
	if (!IsRunningCommandlet()) return PreviewReply(Report,TEXT("document previews are restricted to commandlets"));
	if (DocumentPreview) return PreviewReply(Report,TEXT("restore the current document preview first"));
	FStreetSiteDoc Source, Current, Candidate;
	TArray<AStreetscapeActor*> Actors;
	FString Error;
	if (!CurrentDocument(SourcePath,Source,Current,Actors,Error)) return PreviewReply(Report,Error);
	if (FStreetscapeJson::Canonical(FStreetscapeJson::WriteSite(Source)) != FStreetscapeJson::Canonical(FStreetscapeJson::WriteSite(Current)))
		return PreviewReply(Report,TEXT("loaded document differs from source; preserve the existing edits before preview"));
	TSharedPtr<FJsonObject> Object;
	FText ReadError;
	TArray<FString> Problems;
	if (!FStreetscapeJson::LoadFile(CandidatePath,Object,&ReadError) || !FStreetscapeJson::ReadSite(Object.ToSharedRef(),Candidate,Problems))
		return PreviewReply(Report,ReadError.ToString()+FString::Join(Problems,TEXT("; ")));
	if (!StreetDocumentEdit::ValidatePreview(Source,Candidate,Error)) return PreviewReply(Report,Error);
	TMap<FString,FVector2D> Trims;
	TMap<FString,TArray<FStreetOwnedJunction>> Owned;
	if (!PlanCurrent(Source,Candidate,Trims,Owned,Error)) return PreviewReply(Report,Error);
	auto Snapshot = MakeUnique<FDocumentPreviewSnapshot>();
	Snapshot->SourcePath = SourcePath;
	Snapshot->Junctions = Candidate.Junctions;
	int32 Changed = 0;
	for (AStreetscapeActor* A : Actors)
	{
		const FStreetSplineDef* D = Candidate.FindSpline(A->StreetId);
		const auto& P = D->ProfileIds;
		if ((!P.Road.IsEmpty() && !A->Road) || (!P.EdgeLeft.IsEmpty() && !A->EdgeLeft) ||
			(!P.EdgeRight.IsEmpty() && !A->EdgeRight) || (!P.HedgeLeft.IsEmpty() && !A->HedgeLeft) ||
			(!P.HedgeRight.IsEmpty() && !A->HedgeRight) || (!A->OwnedJunctions.IsEmpty() && (!A->Road || !A->EdgeLeft)))
			return PreviewReply(Report,TEXT("missing existing renderer component: ")+A->StreetId);
		if (FStreetscapeJson::Canonical(FStreetscapeJson::WriteSpline(A->Spline->Def)) != FStreetscapeJson::Canonical(FStreetscapeJson::WriteSpline(*D))) ++Changed;
		Snapshot->Actors.Add(A);
		Snapshot->Definitions.Add(A->Spline->Def);
		Snapshot->Profiles.Add(A->DocProfiles);
	}
	for (TObjectIterator<UPackage> It;It;++It) Snapshot->Dirty.Add({*It,It->IsDirty()});
	DocumentPreview = MoveTemp(Snapshot);
	for (AStreetscapeActor* A : Actors)
	{
		A->DocProfiles = Candidate.Profiles;
		A->Spline->Def = *Candidate.FindSpline(A->StreetId);
		A->Spline->SyncComponentFromDef();
	}
	const int32 Count = RefreshDocumentJunctions(SourcePath);
	RestorePreviewDirty();
	if (Count != Actors.Num())
	{
		Report->SetStringField(TEXT("rollback"),RestoreDocumentPreviewJson());
		return PreviewReply(Report,TEXT("candidate document refresh failed"));
	}
	Report->SetNumberField(TEXT("actors"),Count);
	Report->SetNumberField(TEXT("changed_definitions"),Changed);
	return PreviewReply(Report);
}
