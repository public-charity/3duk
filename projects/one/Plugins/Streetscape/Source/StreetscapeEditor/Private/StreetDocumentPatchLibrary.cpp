#include "StreetDocumentPatchLibrary.h"
#include "StreetscapeActor.h"
#include "StreetscapeSiteActor.h"
#include "StreetscapeJson.h"
#include "StreetSpline.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "EngineUtils.h"

FString UStreetDocumentPatchLibrary::ApplyIndependentDocument(const FString& JsonPath)
{
    const auto Report = MakeShared<FJsonObject>();
    auto Reply = [&Report](const FString& Error)
    {
        Report->SetBoolField(TEXT("ok"), Error.IsEmpty());
        Report->SetBoolField(TEXT("saved"), false);
        if (!Error.IsEmpty()) Report->SetStringField(TEXT("error"), Error);
        return FStreetscapeJson::ToText(Report, false, 1, -1);
    };
    UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
    if (!World) return Reply(TEXT("No editor world"));
    TSharedPtr<FJsonObject> Object;
    FText ReadError;
    FStreetSiteDoc Doc;
    TArray<FString> Problems;
    if (!FStreetscapeJson::LoadFile(JsonPath, Object, &ReadError) ||
        !FStreetscapeJson::ReadSite(Object.ToSharedRef(), Doc, Problems))
        return Reply(ReadError.ToString() + FString::Join(Problems, TEXT("; ")));
    AStreetscapeSiteActor* Site = AStreetscapeSiteActor::Get(World);
    if (!Site || Doc.Splines.IsEmpty() || !Doc.Junctions.IsEmpty() ||
        Doc.Site != Site->SiteName || Doc.Crs != Site->Crs || Doc.VerticalDatum != Site->VerticalDatum ||
        !FMath::IsNearlyEqual(Doc.Origin.E, Site->OriginEN.X, 1e-6) ||
        !FMath::IsNearlyEqual(Doc.Origin.N, Site->OriginEN.Y, 1e-6))
        return Reply(TEXT("Independent document and matching site registration required"));
    TArray<AStreetscapeActor*> Actors;
    TArray<FStreetSplineDef> OldDefs;
    TArray<FStreetSiteProfiles> OldProfiles;
    TSet<FString> Seen;
    // Validate every target before changing any definition or component.
    for (const FStreetSplineDef& Def : Doc.Splines)
    {
        if (Seen.Contains(Def.Id) || !Def.JunctionStart.IsEmpty() || !Def.JunctionEnd.IsEmpty())
            return Reply(TEXT("Duplicate ID or junction binding: ") + Def.Id);
        Seen.Add(Def.Id);
        AStreetscapeActor* Found = nullptr;
        for (TActorIterator<AStreetscapeActor> It(World); It; ++It)
            if (It->StreetId == Def.Id)
            {
                if (Found) return Reply(TEXT("Duplicate loaded actor: ") + Def.Id);
                Found = *It;
            }
        if (!Found || !Found->OwnedJunctions.IsEmpty() ||
            !Found->Spline->Def.JunctionStart.IsEmpty() || !Found->Spline->Def.JunctionEnd.IsEmpty())
            return Reply(TEXT("Exactly one loaded independent actor required: ") + Def.Id);
        if (!FMath::IsNearlyEqual(Found->DocOriginEN.X, Doc.Origin.E, 1e-6) ||
            !FMath::IsNearlyEqual(Found->DocOriginEN.Y, Doc.Origin.N, 1e-6))
            return Reply(TEXT("Actor registration mismatch: ") + Def.Id);
        const auto& P = Def.ProfileIds;
        if (bool(Found->Road) != !P.Road.IsEmpty() || bool(Found->EdgeLeft) != !P.EdgeLeft.IsEmpty() ||
            bool(Found->EdgeRight) != !P.EdgeRight.IsEmpty() || bool(Found->HedgeLeft) != !P.HedgeLeft.IsEmpty() ||
            bool(Found->HedgeRight) != !P.HedgeRight.IsEmpty())
            return Reply(TEXT("Preserve existing renderer slots: ") + Def.Id);
        Actors.Add(Found);
        OldDefs.Add(Found->Spline->Def);
        OldProfiles.Add(Found->DocProfiles);
    }
    for (int32 I = 0; I < Actors.Num(); ++I)
    {
        AStreetscapeActor* A = Actors[I];
        A->Modify();
        A->ApplyDefinition(Doc.Splines[I], Doc.Profiles, A->DocOriginEN);
        FString Error;
        if (!A->RebuildAllChecked(&Error))
        {
            for (int32 J = 0; J <= I; ++J)
            {
                Actors[J]->ApplyDefinition(OldDefs[J], OldProfiles[J], Actors[J]->DocOriginEN);
                FString RollbackError;
                if (!Actors[J]->RebuildAllChecked(&RollbackError))
                    Error += TEXT("; rollback failed: ") + RollbackError;
            }
            return Reply(Error);
        }
    }
    Report->SetNumberField(TEXT("actors"), Actors.Num());
    Report->SetBoolField(TEXT("actor_identity_preserved"), true);
    return Reply(FString());
}
