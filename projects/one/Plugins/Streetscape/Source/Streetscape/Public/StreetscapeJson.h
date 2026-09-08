// StreetscapeJson - the one strict reader/writer of the Streetscape schema and the frame conversion for points
// (UE_PLAN.md 2.11; SCHEMA.md 8, 10). Mirrors Tools/blender/streetscape/io_json.py + schema.py SPEC tables:
// unknown non-'_' key -> error naming the path; missing required -> error; null honoured for nullable fields;
// enums via the explicit tables of FStreetEnums; ranges as in the schema file; the cross-references of SCHEMA.md 8.
//
// Frames (BRIEF 4.2): documents are local metres, X east, Y north, Z up. UE is centimetres, Y south:
// ToUE = (100 x, -100 y, 100 z); yaw = bearing - 90. This file and the landscape importer are the only places
// that convert; nothing is ever baked into the JSON.
//
// Text output is our own serialiser (FStreetscapeJson::ToText): schema key order, indent 1, LF, shortest doubles
// that round-trip (python's repr), integral doubles as integers - so SaveFile output is diff-friendly and the
// canonical form (sorted keys, 1e-6 rounding, compact) is what Streetscape.Json.RoundTrip compares byte for byte.

#pragma once

#include "CoreMinimal.h"
#include "StreetTypes.h"
#include "StreetProfiles.h"

class FJsonObject;
class FJsonValue;

struct STREETSCAPE_API FStreetscapeJson
{
	// -- frames ---------------------------------------------------------------------------------------------------
	static FVector ToUE(const FVector3d& M) { return FVector(100.0 * M.X, -100.0 * M.Y, 100.0 * M.Z); }
	static FVector3d ToJson(const FVector& C) { return FVector3d(C.X / 100.0, -C.Y / 100.0, C.Z / 100.0); }
	static double YawFromBearingDeg(double B) { return B - 90.0; }

	// -- files ----------------------------------------------------------------------------------------------------
	/** FFileHelper + FJsonSerializer::Deserialize (UE/Source/Runtime/Json/Public/Serialization/JsonSerializer.h:301). */
	static bool LoadFile(const FString& Path, TSharedPtr<FJsonObject>& Out, FText* Err);
	static bool ParseString(const FString& Text, TSharedPtr<FJsonObject>& Out, FText* Err);
	/** Pretty canonical text (indent 1, schema order as built, LF, UTF-8 without BOM). */
	static bool SaveFile(const FString& Path, const TSharedRef<FJsonObject>& In);

	/** Serialise any JSON value. IndentSpaces < 0 = compact; RoundDecimals >= 0 rounds every number first. */
	static FString ToText(const TSharedRef<FJsonValue>& Value, bool bSortKeys, int32 IndentSpaces, int32 RoundDecimals);
	static FString ToText(const TSharedRef<FJsonObject>& Object, bool bSortKeys, int32 IndentSpaces, int32 RoundDecimals);
	/** Sorted keys, compact, numbers rounded to 1e-6: the byte-comparable form of a document. */
	static FString Canonical(const TSharedRef<FJsonObject>& Object) { return ToText(Object, true, -1, 6); }
	/** python repr-like: shortest text that parses back to the same double; integral values without a fraction. */
	static FString FormatNumber(double V, int32 RoundDecimals = -1);

	// -- documents ------------------------------------------------------------------------------------------------
	/** Strict read of a whole document (structure + cross checks). False when Problems is non-empty. */
	static bool ReadSite(const TSharedRef<FJsonObject>& In, FStreetSiteDoc& Out, TArray<FString>& Problems);
	static TSharedRef<FJsonObject> WriteSite(const FStreetSiteDoc& Doc);
	/** One schema Spline object (used for hashing and per-spline export). */
	static TSharedRef<FJsonObject> WriteSpline(const FStreetSplineDef& Spline);
	static bool ReadSpline(const TSharedRef<FJsonObject>& In, FStreetSplineDef& Out, TArray<FString>& Problems, const FString& Path = TEXT("$"));
	/** == io_json.validate_structure: every structural problem (empty = valid). */
	static bool ValidateStructure(const TSharedRef<FJsonObject>& In, TArray<FString>& Problems);
	/** == io_json.validate_warnings (unhinted materials, overlay missing on a non-authored spline, lane widths). */
	static TArray<FString> ValidateWarnings(const FStreetSiteDoc& Doc);

	// -- profiles -------------------------------------------------------------------------------------------------
	static bool ReadRoadProfile(const TSharedRef<FJsonObject>& In, FRoadProfileData& Out, TArray<FString>& Problems, const FString& Path = TEXT("$"));
	static bool ReadEdgeProfile(const TSharedRef<FJsonObject>& In, FEdgeProfileData& Out, TArray<FString>& Problems, const FString& Path = TEXT("$"));
	static bool ReadHedgeProfile(const TSharedRef<FJsonObject>& In, FHedgeProfileData& Out, TArray<FString>& Problems, const FString& Path = TEXT("$"));
	static TSharedRef<FJsonObject> WriteRoadProfile(const FRoadProfileData& P);
	static TSharedRef<FJsonObject> WriteEdgeProfile(const FEdgeProfileData& P);
	static TSharedRef<FJsonObject> WriteHedgeProfile(const FHedgeProfileData& P);
	/** schema/profiles/<id>.json: {kind, id, profile}. */
	static bool ReadProfileFile(const TSharedRef<FJsonObject>& In, FStreetProfileFile& Out, TArray<FString>& Problems);
	static TSharedRef<FJsonObject> WriteProfileFile(const FStreetProfileFile& F);

	/** Every *.json of a directory -> profiles keyed by id (== io_json.load_profile_library). */
	static bool LoadProfileLibrary(const FString& Dir, FStreetSiteProfiles& Out, TArray<FString>& Problems);

	/** {kind, id, profile} -> the profile's dictionary, also usable standalone (schema.road_kinds_consistent etc.). */
	static bool RoadKindsConsistent(const FStreetSplineDef& Spline, const FStreetSiteProfiles& Profiles, FString& OutProblem);
};
