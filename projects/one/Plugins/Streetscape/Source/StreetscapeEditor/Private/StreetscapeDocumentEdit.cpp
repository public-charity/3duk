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

namespace
{
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
