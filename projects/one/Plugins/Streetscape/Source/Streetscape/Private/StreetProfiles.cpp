#include "StreetProfiles.h"
#include "StreetscapeJson.h"
#include "Dom/JsonObject.h"

const FStreetSplineDef* FStreetSiteDoc::FindSpline(const FString& Id) const
{
	for (const FStreetSplineDef& S : Splines)
	{
		if (S.Id == Id) return &S;
	}
	return nullptr;
}

FString UStreetProfileBase::ToJsonString() const
{
	TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
	if (!ToJson(O)) return FString();
	return FStreetscapeJson::ToText(O, false, 1, -1);
}

TArray<FString> UStreetProfileBase::FromJsonString(const FString& Json)
{
	TSharedPtr<FJsonObject> O;
	FText Err;
	if (!FStreetscapeJson::ParseString(Json, O, &Err)) return { Err.ToString() };
	if (!FromJson(O.ToSharedRef(), &Err)) return { Err.ToString() };
	return {};
}

namespace
{
FText Join(const TArray<FString>& P) { return FText::FromString(FString::Join(P, TEXT("\n"))); }
}

bool URoadProfile::ToJson(TSharedRef<FJsonObject> Out) const
{
	Out->Values = FStreetscapeJson::WriteRoadProfile(Data)->Values;
	return true;
}
bool URoadProfile::FromJson(const TSharedRef<FJsonObject>& In, FText* Err)
{
	TArray<FString> P;
	if (!FStreetscapeJson::ReadRoadProfile(In, Data, P)) { if (Err) *Err = Join(P); return false; }
	return true;
}
bool UEdgeProfile::ToJson(TSharedRef<FJsonObject> Out) const
{
	Out->Values = FStreetscapeJson::WriteEdgeProfile(Data)->Values;
	return true;
}
bool UEdgeProfile::FromJson(const TSharedRef<FJsonObject>& In, FText* Err)
{
	TArray<FString> P;
	if (!FStreetscapeJson::ReadEdgeProfile(In, Data, P)) { if (Err) *Err = Join(P); return false; }
	return true;
}
bool UHedgeProfile::ToJson(TSharedRef<FJsonObject> Out) const
{
	Out->Values = FStreetscapeJson::WriteHedgeProfile(Data)->Values;
	return true;
}
bool UHedgeProfile::FromJson(const TSharedRef<FJsonObject>& In, FText* Err)
{
	TArray<FString> P;
	if (!FStreetscapeJson::ReadHedgeProfile(In, Data, P)) { if (Err) *Err = Join(P); return false; }
	return true;
}
