#include "StreetscapeJson.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "HAL/FileManager.h"
#include "Internationalization/Regex.h"
#include "StreetscapeModule.h"

// =================================================================================================================
// text serialiser (python json.dumps(indent=1) look-alike; shortest round-trip doubles)
// =================================================================================================================

FString FStreetscapeJson::FormatNumber(double V, int32 RoundDecimals)
{
	if (RoundDecimals >= 0)
	{
		const double P = FMath::Pow(10.0, (double)RoundDecimals);
		V = FMath::RoundToDouble(V * P) / P;
	}
	if (!FMath::IsFinite(V))
	{
		return TEXT("null");
	}
	if (V == FMath::FloorToDouble(V) && FMath::Abs(V) < 1e15)
	{
		const int64 I = (int64)V;
		return FString::Printf(TEXT("%lld"), I);
	}
	for (int32 Precision = 1; Precision <= 17; ++Precision)
	{
		const FString S = FString::Printf(TEXT("%.*g"), Precision, V);
		if (FCString::Atod(*S) == V)
		{
			return S;
		}
	}
	return FString::Printf(TEXT("%.17g"), V);
}

namespace
{
void AppendEscaped(FString& Out, const FString& S)
{
	Out.AppendChar(TEXT('"'));
	for (const TCHAR C : S)
	{
		switch (C)
		{
		case TEXT('"'): Out.Append(TEXT("\\\"")); break;
		case TEXT('\\'): Out.Append(TEXT("\\\\")); break;
		case TEXT('\n'): Out.Append(TEXT("\\n")); break;
		case TEXT('\r'): Out.Append(TEXT("\\r")); break;
		case TEXT('\t'): Out.Append(TEXT("\\t")); break;
		case TEXT('\b'): Out.Append(TEXT("\\b")); break;
		case TEXT('\f'): Out.Append(TEXT("\\f")); break;
		default:
			if (C < 0x20)
			{
				Out.Append(FString::Printf(TEXT("\\u%04x"), (int32)C));
			}
			else
			{
				Out.AppendChar(C);
			}
		}
	}
	Out.AppendChar(TEXT('"'));
}

void AppendIndent(FString& Out, int32 IndentSpaces, int32 Depth)
{
	if (IndentSpaces >= 0)
	{
		Out.AppendChar(TEXT('\n'));
		for (int32 I = 0; I < IndentSpaces * Depth; ++I) Out.AppendChar(TEXT(' '));
	}
}

void AppendValue(FString& Out, const TSharedPtr<FJsonValue>& V, bool bSortKeys, int32 IndentSpaces, int32 RoundDecimals, int32 Depth)
{
	if (!V.IsValid() || V->Type == EJson::Null || V->Type == EJson::None)
	{
		Out.Append(TEXT("null"));
		return;
	}
	switch (V->Type)
	{
	case EJson::Boolean: Out.Append(V->AsBool() ? TEXT("true") : TEXT("false")); break;
	case EJson::Number: Out.Append(FStreetscapeJson::FormatNumber(V->AsNumber(), RoundDecimals)); break;
	case EJson::String: AppendEscaped(Out, V->AsString()); break;
	case EJson::Array:
	{
		const TArray<TSharedPtr<FJsonValue>>& Arr = V->AsArray();
		if (Arr.Num() == 0) { Out.Append(TEXT("[]")); break; }
		Out.AppendChar(TEXT('['));
		for (int32 I = 0; I < Arr.Num(); ++I)
		{
			if (I) Out.AppendChar(TEXT(','));
			AppendIndent(Out, IndentSpaces, Depth + 1);
			AppendValue(Out, Arr[I], bSortKeys, IndentSpaces, RoundDecimals, Depth + 1);
		}
		AppendIndent(Out, IndentSpaces, Depth);
		Out.AppendChar(TEXT(']'));
		break;
	}
	case EJson::Object:
	{
		const TSharedPtr<FJsonObject>& Obj = V->AsObject();
		if (!Obj.IsValid() || Obj->Values.Num() == 0) { Out.Append(TEXT("{}")); break; }
		TArray<TPair<FString, TSharedPtr<FJsonValue>>> Items;
		for (const auto& KV : Obj->Values) Items.Emplace(FString(*KV.Key), KV.Value);
		if (bSortKeys)
		{
			Items.Sort([](const TPair<FString, TSharedPtr<FJsonValue>>& A, const TPair<FString, TSharedPtr<FJsonValue>>& B) { return A.Key.Compare(B.Key, ESearchCase::CaseSensitive) < 0; });
		}
		Out.AppendChar(TEXT('{'));
		for (int32 I = 0; I < Items.Num(); ++I)
		{
			if (I) Out.AppendChar(TEXT(','));
			AppendIndent(Out, IndentSpaces, Depth + 1);
			AppendEscaped(Out, Items[I].Key);
			Out.Append(IndentSpaces >= 0 ? TEXT(": ") : TEXT(":"));
			AppendValue(Out, Items[I].Value, bSortKeys, IndentSpaces, RoundDecimals, Depth + 1);
		}
		AppendIndent(Out, IndentSpaces, Depth);
		Out.AppendChar(TEXT('}'));
		break;
	}
	default: Out.Append(TEXT("null"));
	}
}
}

FString FStreetscapeJson::ToText(const TSharedRef<FJsonValue>& Value, bool bSortKeys, int32 IndentSpaces, int32 RoundDecimals)
{
	FString Out;
	AppendValue(Out, Value, bSortKeys, IndentSpaces, RoundDecimals, 0);
	return Out;
}

FString FStreetscapeJson::ToText(const TSharedRef<FJsonObject>& Object, bool bSortKeys, int32 IndentSpaces, int32 RoundDecimals)
{
	return ToText(MakeShared<FJsonValueObject>(Object), bSortKeys, IndentSpaces, RoundDecimals);
}

bool FStreetscapeJson::ParseString(const FString& Text, TSharedPtr<FJsonObject>& Out, FText* Err)
{
	TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	if (!FJsonSerializer::Deserialize(Reader, Out) || !Out.IsValid())
	{
		if (Err) *Err = FText::FromString(FString::Printf(TEXT("JSON parse error: %s (line %d)"), *Reader->GetErrorMessage(), (int32)Reader->GetLineNumber()));
		return false;
	}
	return true;
}

bool FStreetscapeJson::LoadFile(const FString& Path, TSharedPtr<FJsonObject>& Out, FText* Err)
{
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		if (Err) *Err = FText::FromString(FString::Printf(TEXT("cannot read %s"), *Path));
		return false;
	}
	if (!ParseString(Text, Out, Err))
	{
		if (Err) *Err = FText::FromString(FString::Printf(TEXT("%s: %s"), *Path, *Err->ToString()));
		return false;
	}
	return true;
}

bool FStreetscapeJson::SaveFile(const FString& Path, const TSharedRef<FJsonObject>& In)
{
	const FString Text = ToText(In, false, 1, -1) + TEXT("\n");
	return FFileHelper::SaveStringToFile(Text, *Path, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

// =================================================================================================================
// strict reader helpers (== schema._convert and SchemaObject._from)
// =================================================================================================================

namespace
{
bool IsIdText(const FString& S)
{
	if (S.IsEmpty()) return false;
	for (const TCHAR C : S)
	{
		const bool bOk = (C >= TEXT('A') && C <= TEXT('Z')) || (C >= TEXT('a') && C <= TEXT('z')) || (C >= TEXT('0') && C <= TEXT('9')) || C == TEXT('_') || C == TEXT('.') || C == TEXT(':') || C == TEXT('-');
		if (!bOk) return false;
	}
	return true;
}

bool IsMaterialText(const FString& S)
{
	if (S.IsEmpty() || !(S[0] >= TEXT('a') && S[0] <= TEXT('z'))) return false;
	for (const TCHAR C : S)
	{
		const bool bOk = (C >= TEXT('a') && C <= TEXT('z')) || (C >= TEXT('0') && C <= TEXT('9')) || C == TEXT('_');
		if (!bOk) return false;
	}
	return true;
}

FString Compact(const TSharedPtr<FJsonValue>& V)
{
	return FStreetscapeJson::ToText(V.ToSharedRef(), false, -1, -1);
}

/** One object being read: records notes / keys / nulls on the FStreetJsonBase and reports unknown keys. */
struct FObj
{
	const FJsonObject& O;
	FString Path;
	TArray<FString>& Errs;
	FStreetJsonBase* Base;

	FObj(const FJsonObject& InO, const FString& InPath, TArray<FString>& InErrs, FStreetJsonBase* InBase, std::initializer_list<const TCHAR*> Known)
		: O(InO), Path(InPath), Errs(InErrs), Base(InBase)
	{
		for (const auto& KV : O.Values)
		{
			const FString K(*KV.Key);
			if (K.StartsWith(TEXT("_")))
			{
				if (Base) Base->Notes.Add(K, Compact(KV.Value));
				continue;
			}
			bool bKnown = false;
			for (const TCHAR* Kn : Known) { if (K.Equals(Kn, ESearchCase::CaseSensitive)) { bKnown = true; break; } }
			if (!bKnown)
			{
				Errs.Add(FString::Printf(TEXT("%s: unknown key '%s'"), *Path, *K));
				continue;
			}
			if (Base)
			{
				Base->JsonKeys.Add(K);
				if (!KV.Value.IsValid() || KV.Value->Type == EJson::Null) Base->NullKeys.Add(K);
			}
		}
	}

	FString P(const TCHAR* Key) const { return Path + TEXT(".") + Key; }
	const TSharedPtr<FJsonValue>* Find(const TCHAR* Key) const { return O.Values.Find(Key); }
	bool Has(const TCHAR* Key) const { return O.Values.Contains(Key); }
	bool IsNull(const TCHAR* Key) const { const TSharedPtr<FJsonValue>* V = Find(Key); return V && (!V->IsValid() || (*V)->Type == EJson::Null); }
	void Missing(const TCHAR* Key) { Errs.Add(FString::Printf(TEXT("%s: missing required key '%s'"), *Path, Key)); }
	void NullNotAllowed(const TCHAR* Key) { Errs.Add(FString::Printf(TEXT("%s: null is not allowed"), *P(Key))); }

	/** Present and non-null; reports null when !bNullable. Returns the value or nullptr. */
	const TSharedPtr<FJsonValue>* Get(const TCHAR* Key, bool bRequired, bool bNullable = false)
	{
		const TSharedPtr<FJsonValue>* V = Find(Key);
		if (!V) { if (bRequired) Missing(Key); return nullptr; }
		if (!V->IsValid() || (*V)->Type == EJson::Null) { if (!bNullable) NullNotAllowed(Key); return nullptr; }
		return V;
	}

	bool ReadNumber(const TCHAR* Key, const TSharedPtr<FJsonValue>& V, double& Out, double Lo, double Hi, bool bExclLo)
	{
		if (V->Type != EJson::Number) { Errs.Add(FString::Printf(TEXT("%s: expected number, got %s"), *P(Key), *Compact(V))); return false; }
		const double X = V->AsNumber();
		if (!FMath::IsFinite(X)) { Errs.Add(FString::Printf(TEXT("%s: expected finite number"), *P(Key))); return false; }
		if (!FMath::IsNaN(Lo) && (X < Lo || (bExclLo && X <= Lo)))
			Errs.Add(FString::Printf(TEXT("%s: %s %s minimum %s"), *P(Key), *FStreetscapeJson::FormatNumber(X), bExclLo ? TEXT("<=") : TEXT("<"), *FStreetscapeJson::FormatNumber(Lo)));
		if (!FMath::IsNaN(Hi) && X > Hi)
			Errs.Add(FString::Printf(TEXT("%s: %s > maximum %s"), *P(Key), *FStreetscapeJson::FormatNumber(X), *FStreetscapeJson::FormatNumber(Hi)));
		Out = X;
		return true;
	}

	/** Plain number with a fixed default (left untouched when absent). Lo/Hi NaN = unbounded. */
	void Num(const TCHAR* Key, double& Out, bool bRequired, double Lo = NAN, double Hi = NAN, bool bExclLo = false)
	{
		if (const TSharedPtr<FJsonValue>* V = Get(Key, bRequired)) ReadNumber(Key, *V, Out, Lo, Hi, bExclLo);
	}
	void OptNum(const TCHAR* Key, TOptional<double>& Out, bool bRequired, bool bNullable, double Lo = NAN, double Hi = NAN, bool bExclLo = false)
	{
		Out.Reset();
		if (const TSharedPtr<FJsonValue>* V = Get(Key, bRequired, bNullable)) { double X; if (ReadNumber(Key, *V, X, Lo, Hi, bExclLo)) Out = X; }
	}
	bool ReadInt(const TCHAR* Key, const TSharedPtr<FJsonValue>& V, int32& Out, double Lo, double Hi)
	{
		if (V->Type != EJson::Number || V->AsNumber() != FMath::FloorToDouble(V->AsNumber()))
		{
			Errs.Add(FString::Printf(TEXT("%s: expected integer, got %s"), *P(Key), *Compact(V)));
			return false;
		}
		const double X = V->AsNumber();
		if (!FMath::IsNaN(Lo) && X < Lo) Errs.Add(FString::Printf(TEXT("%s: %s < minimum %s"), *P(Key), *FStreetscapeJson::FormatNumber(X), *FStreetscapeJson::FormatNumber(Lo)));
		if (!FMath::IsNaN(Hi) && X > Hi) Errs.Add(FString::Printf(TEXT("%s: %s > maximum %s"), *P(Key), *FStreetscapeJson::FormatNumber(X), *FStreetscapeJson::FormatNumber(Hi)));
		Out = (int32)X;
		return true;
	}
	void Int(const TCHAR* Key, int32& Out, bool bRequired, double Lo = NAN, double Hi = NAN)
	{
		if (const TSharedPtr<FJsonValue>* V = Get(Key, bRequired)) ReadInt(Key, *V, Out, Lo, Hi);
	}
	void OptInt(const TCHAR* Key, TOptional<int32>& Out, bool bRequired, bool bNullable, double Lo = NAN, double Hi = NAN)
	{
		Out.Reset();
		if (const TSharedPtr<FJsonValue>* V = Get(Key, bRequired, bNullable)) { int32 X; if (ReadInt(Key, *V, X, Lo, Hi)) Out = X; }
	}
	void Bool(const TCHAR* Key, bool& Out, bool bRequired)
	{
		if (const TSharedPtr<FJsonValue>* V = Get(Key, bRequired))
		{
			if ((*V)->Type != EJson::Boolean) { Errs.Add(FString::Printf(TEXT("%s: expected boolean, got %s"), *P(Key), *Compact(*V))); return; }
			Out = (*V)->AsBool();
		}
	}
	/** String; bMinOne = at least one character. Nullable strings leave Out empty on null. */
	void Str(const TCHAR* Key, FString& Out, bool bRequired, bool bMinOne, bool bNullable = false)
	{
		if (const TSharedPtr<FJsonValue>* V = Get(Key, bRequired, bNullable))
		{
			if ((*V)->Type != EJson::String) { Errs.Add(FString::Printf(TEXT("%s: expected string, got %s"), *P(Key), *Compact(*V))); return; }
			Out = (*V)->AsString();
			if (bMinOne && Out.IsEmpty()) Errs.Add(FString::Printf(TEXT("%s: empty string"), *P(Key)));
		}
	}
	void Id(const TCHAR* Key, FString& Out, bool bRequired, bool bNullable = false)
	{
		if (const TSharedPtr<FJsonValue>* V = Get(Key, bRequired, bNullable))
		{
			if ((*V)->Type != EJson::String || !IsIdText((*V)->AsString()))
			{
				Errs.Add(FString::Printf(TEXT("%s: %s is not an Id (^[A-Za-z0-9_.:-]+$)"), *P(Key), *Compact(*V)));
				return;
			}
			Out = (*V)->AsString();
		}
	}
	void Mat(const TCHAR* Key, FName& Out, bool bRequired)
	{
		if (const TSharedPtr<FJsonValue>* V = Get(Key, bRequired))
		{
			if ((*V)->Type != EJson::String || !IsMaterialText((*V)->AsString()))
			{
				Errs.Add(FString::Printf(TEXT("%s: %s is not a material name (^[a-z][a-z0-9_]*$)"), *P(Key), *Compact(*V)));
				return;
			}
			Out = FName(*(*V)->AsString());
		}
	}
	template <typename TEnum>
	void Enum(const TCHAR* Key, TEnum& Out, bool bRequired, bool bNullable = false)
	{
		if (const TSharedPtr<FJsonValue>* V = Get(Key, bRequired, bNullable))
		{
			TEnum E;
			if ((*V)->Type != EJson::String || !FStreetEnums::Parse((*V)->AsString(), E))
			{
				Errs.Add(FString::Printf(TEXT("%s: %s not in enum"), *P(Key), *Compact(*V)));
				return;
			}
			Out = E;
		}
	}
	void Const(const TCHAR* Key, const TCHAR* Expected, FString& Out)
	{
		if (const TSharedPtr<FJsonValue>* V = Get(Key, true))
		{
			if ((*V)->Type != EJson::String || !(*V)->AsString().Equals(Expected, ESearchCase::CaseSensitive))
			{
				Errs.Add(FString::Printf(TEXT("%s: expected const '%s', got %s"), *P(Key), Expected, *Compact(*V)));
				return;
			}
			Out = (*V)->AsString();
		}
	}
	/** Sub-object; nullptr when absent / null / wrong type (wrong type reported). */
	const FJsonObject* Obj(const TCHAR* Key, bool bRequired, bool bNullable = false)
	{
		if (const TSharedPtr<FJsonValue>* V = Get(Key, bRequired, bNullable))
		{
			if ((*V)->Type != EJson::Object) { Errs.Add(FString::Printf(TEXT("%s: expected object, got %s"), *P(Key), *Compact(*V))); return nullptr; }
			return (*V)->AsObject().Get();
		}
		return nullptr;
	}
	const TArray<TSharedPtr<FJsonValue>>* Arr(const TCHAR* Key, bool bRequired, int32 MinItems = 0)
	{
		if (const TSharedPtr<FJsonValue>* V = Get(Key, bRequired))
		{
			if ((*V)->Type != EJson::Array) { Errs.Add(FString::Printf(TEXT("%s: expected array, got %s"), *P(Key), *Compact(*V))); return nullptr; }
			const TArray<TSharedPtr<FJsonValue>>& A = (*V)->AsArray();
			if (A.Num() < MinItems) Errs.Add(FString::Printf(TEXT("%s: %d items < minItems %d"), *P(Key), A.Num(), MinItems));
			return &A;
		}
		return nullptr;
	}
	void NumList(const TCHAR* Key, TArray<double>& Out, bool* bHas, bool bRequired, double Lo = NAN, double Hi = NAN, bool bExclLo = false)
	{
		if (const TArray<TSharedPtr<FJsonValue>>* A = Arr(Key, bRequired))
		{
			if (bHas) *bHas = true;
			Out.Reset();
			for (int32 I = 0; I < A->Num(); ++I)
			{
				const FString IKey = FString::Printf(TEXT("%s[%d]"), Key, I);
				double X = 0;
				if (!(*A)[I].IsValid() || (*A)[I]->Type == EJson::Null) { NullNotAllowed(*IKey); continue; }
				if (ReadNumber(*IKey, (*A)[I], X, Lo, Hi, bExclLo)) Out.Add(X);
			}
		}
	}
	void IntList(const TCHAR* Key, TArray<int32>& Out, bool* bHas, bool bRequired)
	{
		if (const TArray<TSharedPtr<FJsonValue>>* A = Arr(Key, bRequired))
		{
			if (bHas) *bHas = true;
			Out.Reset();
			for (int32 I = 0; I < A->Num(); ++I)
			{
				const FString IKey = FString::Printf(TEXT("%s[%d]"), Key, I);
				int32 X = 0;
				if (!(*A)[I].IsValid() || (*A)[I]->Type == EJson::Null) { NullNotAllowed(*IKey); continue; }
				if (ReadInt(*IKey, (*A)[I], X, NAN, NAN)) Out.Add(X);
			}
		}
	}
	void StrList(const TCHAR* Key, TArray<FString>& Out, bool* bHas, bool bRequired)
	{
		if (const TArray<TSharedPtr<FJsonValue>>* A = Arr(Key, bRequired))
		{
			if (bHas) *bHas = true;
			Out.Reset();
			for (int32 I = 0; I < A->Num(); ++I)
			{
				if (!(*A)[I].IsValid() || (*A)[I]->Type != EJson::String)
				{
					Errs.Add(FString::Printf(TEXT("%s[%d]: expected string, got %s"), *P(Key), I, *Compact((*A)[I])));
					continue;
				}
				Out.Add((*A)[I]->AsString());
			}
		}
	}
	/** [x, y] or [x, y, z] (bXYZ: exactly 3). */
	bool XY(const TCHAR* Key, const TSharedPtr<FJsonValue>& V, FVector3d& Out, bool& bHasZ, bool bXYZ)
	{
		bHasZ = false;
		if (!V.IsValid() || V->Type != EJson::Array) { Errs.Add(FString::Printf(TEXT("%s: expected [x, y%s] numbers"), *P(Key), bXYZ ? TEXT(", z") : TEXT("(, z)"))); return false; }
		const TArray<TSharedPtr<FJsonValue>>& A = V->AsArray();
		const bool bLenOk = bXYZ ? A.Num() == 3 : (A.Num() == 2 || A.Num() == 3);
		bool bNumOk = bLenOk;
		for (const TSharedPtr<FJsonValue>& E : A) { if (!E.IsValid() || E->Type != EJson::Number || !FMath::IsFinite(E->AsNumber())) bNumOk = false; }
		if (!bNumOk) { Errs.Add(FString::Printf(TEXT("%s: expected [x, y%s] numbers"), *P(Key), bXYZ ? TEXT(", z") : TEXT("(, z)"))); return false; }
		Out = FVector3d(A[0]->AsNumber(), A[1]->AsNumber(), A.Num() == 3 ? A[2]->AsNumber() : 0.0);
		bHasZ = A.Num() == 3;
		return true;
	}
};

// ---------------------------------------------------------------------------------------------------------------
// writer helpers
// ---------------------------------------------------------------------------------------------------------------

struct FW
{
	TSharedRef<FJsonObject> O;
	const FStreetJsonBase& B;
	FW(const FStreetJsonBase& InB) : O(MakeShared<FJsonObject>()), B(InB) {}

	bool Want(const TCHAR* Key) const { return B.JsonKeys.Contains(Key); }
	void Null(const TCHAR* Key) { O->SetField(Key, MakeShared<FJsonValueNull>()); }
	void Num(const TCHAR* Key, double V) { O->SetNumberField(Key, V); }
	/** optional plain number: present iff the document had it or it differs from the default */
	void NumD(const TCHAR* Key, double V, double Def) { if (Want(Key) || V != Def) O->SetNumberField(Key, V); }
	void Int(const TCHAR* Key, int32 V) { O->SetNumberField(Key, (double)V); }
	void IntD(const TCHAR* Key, int32 V, int32 Def) { if (Want(Key) || V != Def) O->SetNumberField(Key, (double)V); }
	void Opt(const TCHAR* Key, const TOptional<double>& V, bool bRequired = false)
	{
		if (V.IsSet()) O->SetNumberField(Key, V.GetValue());
		else if (bRequired || B.NullKeys.Contains(Key)) Null(Key);
	}
	void OptI(const TCHAR* Key, const TOptional<int32>& V, bool bRequired = false)
	{
		if (V.IsSet()) O->SetNumberField(Key, (double)V.GetValue());
		else if (bRequired || B.NullKeys.Contains(Key)) Null(Key);
	}
	void Bool(const TCHAR* Key, bool V) { O->SetBoolField(Key, V); }
	void BoolD(const TCHAR* Key, bool V, bool Def) { if (Want(Key) || V != Def) O->SetBoolField(Key, V); }
	void Str(const TCHAR* Key, const FString& V) { O->SetStringField(Key, V); }
	/** optional / nullable string: empty = absent unless the document carried it (then null or "") */
	void StrD(const TCHAR* Key, const FString& V, bool bRequired = false)
	{
		if (!V.IsEmpty() || (Want(Key) && !B.NullKeys.Contains(Key))) O->SetStringField(Key, V);
		else if (bRequired || B.NullKeys.Contains(Key)) Null(Key);
	}
	void Name(const TCHAR* Key, FName V) { O->SetStringField(Key, V.ToString()); }
	void NameD(const TCHAR* Key, FName V, FName Def) { if (Want(Key) || V != Def) O->SetStringField(Key, V.ToString()); }
	template <typename TEnum> void Enum(const TCHAR* Key, TEnum V) { O->SetStringField(Key, FStreetEnums::ToString(V)); }
	template <typename TEnum> void EnumD(const TCHAR* Key, TEnum V, TEnum Def) { if (Want(Key) || V != Def) O->SetStringField(Key, FStreetEnums::ToString(V)); }
	void NumList(const TCHAR* Key, const TArray<double>& V, bool bPresent)
	{
		if (!bPresent) return;
		TArray<TSharedPtr<FJsonValue>> A;
		for (double X : V) A.Add(MakeShared<FJsonValueNumber>(X));
		O->SetArrayField(Key, A);
	}
	void IntList(const TCHAR* Key, const TArray<int32>& V, bool bPresent)
	{
		if (!bPresent) return;
		TArray<TSharedPtr<FJsonValue>> A;
		for (int32 X : V) A.Add(MakeShared<FJsonValueNumber>((double)X));
		O->SetArrayField(Key, A);
	}
	void StrList(const TCHAR* Key, const TArray<FString>& V, bool bPresent)
	{
		if (!bPresent) return;
		TArray<TSharedPtr<FJsonValue>> A;
		for (const FString& X : V) A.Add(MakeShared<FJsonValueString>(X));
		O->SetArrayField(Key, A);
	}
	void Obj(const TCHAR* Key, const TSharedRef<FJsonObject>& V) { O->SetObjectField(Key, V); }
	void ObjList(const TCHAR* Key, const TArray<TSharedPtr<FJsonValue>>& V, bool bPresent) { if (bPresent) O->SetArrayField(Key, V); }
	/** '_' notes and remaining explicit nulls (keys the document had as null and nothing wrote). */
	TSharedRef<FJsonObject> Finish()
	{
		for (const FString& K : B.NullKeys)
		{
			if (!O->HasField(K)) Null(*K);
		}
		for (const auto& KV : B.Notes)
		{
			// the note is stored as compact JSON text of any value type; UE's reader only accepts a top-level object or array,
			// so parse it as the single element of an array
			TSharedPtr<FJsonValue> V;
			TArray<TSharedPtr<FJsonValue>> Arr;
			TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(TEXT("[") + KV.Value + TEXT("]"));
			if (FJsonSerializer::Deserialize(Reader, Arr) && Arr.Num() == 1 && Arr[0].IsValid())
			{
				V = Arr[0];
			}
			else
			{
				V = MakeShared<FJsonValueString>(KV.Value);
			}
			O->SetField(KV.Key, V);
		}
		return O;
	}
};

TSharedPtr<FJsonValue> ObjVal(const TSharedRef<FJsonObject>& O) { return MakeShared<FJsonValueObject>(O); }

// ---------------------------------------------------------------------------------------------------------------
// per-$def readers (numpy SPEC tables) and writers (same key order)
// ---------------------------------------------------------------------------------------------------------------

const double kNaN = NAN;

void ReadMaterialHint(const FJsonObject& O, const FString& Path, FStreetMaterialHint& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("base_color"), TEXT("roughness"), TEXT("two_sided"), TEXT("texture_repeat_m") });
	R.NumList(TEXT("base_color"), X.BaseColor, nullptr, false, 0.0, 1.0);
	R.OptNum(TEXT("roughness"), X.Roughness, false, false, 0.0, 1.0);
	R.Bool(TEXT("two_sided"), X.bTwoSided, false);
	R.OptNum(TEXT("texture_repeat_m"), X.TextureRepeatM, false, false, 0.0, kNaN, true);
}
TSharedRef<FJsonObject> WriteMaterialHint(const FStreetMaterialHint& X)
{
	FW W(X);
	W.NumList(TEXT("base_color"), X.BaseColor, X.BaseColor.Num() > 0 || W.Want(TEXT("base_color")));
	W.Opt(TEXT("roughness"), X.Roughness);
	W.BoolD(TEXT("two_sided"), X.bTwoSided, false);
	W.Opt(TEXT("texture_repeat_m"), X.TextureRepeatM);
	return W.Finish();
}

void ReadSampling(const FJsonObject& O, const FString& Path, FStreetSampling& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("step_m"), TEXT("min_step_m"), TEXT("curvature_gain"), TEXT("smoothing_window_m"), TEXT("smoothing_passes"), TEXT("width_ramp_m"),
		TEXT("bank_max_deg"), TEXT("bank_probe_min_half_width_m"), TEXT("bank_rate_max_deg_per_m"), TEXT("pin_blend_m"), TEXT("extra_stations_m") });
	R.OptNum(TEXT("step_m"), X.StepM, false, false, 0.0, kNaN, true);
	R.OptNum(TEXT("min_step_m"), X.MinStepM, false, false, 0.0, kNaN, true);
	R.OptNum(TEXT("curvature_gain"), X.CurvatureGain, false, false, 0.0);
	R.OptNum(TEXT("smoothing_window_m"), X.SmoothingWindowM, false, false, 0.0);
	R.OptInt(TEXT("smoothing_passes"), X.SmoothingPasses, false, false, 0, 4);
	R.OptNum(TEXT("width_ramp_m"), X.WidthRampM, false, false, 0.0, kNaN, true);
	R.OptNum(TEXT("bank_max_deg"), X.BankMaxDeg, false, false, 0.0, 30.0);
	R.OptNum(TEXT("bank_probe_min_half_width_m"), X.BankProbeMinHalfWidthM, false, false, 0.0, kNaN, true);
	R.OptNum(TEXT("bank_rate_max_deg_per_m"), X.BankRateMaxDegPerM, false, false, 0.0);
	R.OptNum(TEXT("pin_blend_m"), X.PinBlendM, false, false, 0.0, kNaN, true);
	R.NumList(TEXT("extra_stations_m"), X.ExtraStationsM, &X.bHasExtraStationsM, false, 0.0);
}
TSharedRef<FJsonObject> WriteSampling(const FStreetSampling& X)
{
	FW W(X);
	W.Opt(TEXT("step_m"), X.StepM); W.Opt(TEXT("min_step_m"), X.MinStepM); W.Opt(TEXT("curvature_gain"), X.CurvatureGain);
	W.Opt(TEXT("smoothing_window_m"), X.SmoothingWindowM); W.OptI(TEXT("smoothing_passes"), X.SmoothingPasses); W.Opt(TEXT("width_ramp_m"), X.WidthRampM);
	W.Opt(TEXT("bank_max_deg"), X.BankMaxDeg); W.Opt(TEXT("bank_probe_min_half_width_m"), X.BankProbeMinHalfWidthM);
	W.Opt(TEXT("bank_rate_max_deg_per_m"), X.BankRateMaxDegPerM); W.Opt(TEXT("pin_blend_m"), X.PinBlendM);
	W.NumList(TEXT("extra_stations_m"), X.ExtraStationsM, X.bHasExtraStationsM);
	return W.Finish();
}

void ReadCamber(const FJsonObject& O, const FString& Path, FStreetCamber& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("kind"), TEXT("crossfall_pct"), TEXT("camber_m") });
	R.Enum(TEXT("kind"), X.Kind, true);
	R.OptNum(TEXT("crossfall_pct"), X.CrossfallPct, false, false, 0.0, 10.0);
	R.OptNum(TEXT("camber_m"), X.CamberM, false, false, 0.0);
}
TSharedRef<FJsonObject> WriteCamber(const FStreetCamber& X)
{
	FW W(X);
	W.Enum(TEXT("kind"), X.Kind); W.Opt(TEXT("crossfall_pct"), X.CrossfallPct); W.Opt(TEXT("camber_m"), X.CamberM);
	return W.Finish();
}

void ReadMarking(const FJsonObject& O, const FString& Path, FStreetMarking& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("id"), TEXT("anchor"), TEXT("offset_m"), TEXT("width_m"), TEXT("pattern"), TEXT("dash_m"), TEXT("gap_m"), TEXT("phase_m"),
		TEXT("double_gap_m"), TEXT("material"), TEXT("lift_m"), TEXT("s0_m"), TEXT("s1_m") });
	R.Id(TEXT("id"), X.Id, false);
	R.Enum(TEXT("anchor"), X.Anchor, false);
	R.Num(TEXT("offset_m"), X.OffsetM, true);
	R.Num(TEXT("width_m"), X.WidthM, true, 0.0, kNaN, true);
	R.Enum(TEXT("pattern"), X.Pattern, true);
	R.OptNum(TEXT("dash_m"), X.DashM, false, false, 0.0, kNaN, true);
	R.OptNum(TEXT("gap_m"), X.GapM, false, false, 0.0, kNaN, true);
	R.Num(TEXT("phase_m"), X.PhaseM, false);
	R.OptNum(TEXT("double_gap_m"), X.DoubleGapM, false, false, 0.0, kNaN, true);
	R.Mat(TEXT("material"), X.Material, true);
	R.Num(TEXT("lift_m"), X.LiftM, false, 0.0, 0.02);
	R.OptNum(TEXT("s0_m"), X.S0M, false, false, 0.0);
	R.OptNum(TEXT("s1_m"), X.S1M, false, true, 0.0);
	if (X.Pattern == EStreetMarkingPattern::Dashed && (!X.DashM.IsSet() || !X.GapM.IsSet())) E.Add(Path + TEXT(": dashed marking needs dash_m and gap_m"));
	if (X.Pattern == EStreetMarkingPattern::Double && !X.DoubleGapM.IsSet()) E.Add(Path + TEXT(": double marking needs double_gap_m"));
}
TSharedRef<FJsonObject> WriteMarking(const FStreetMarking& X)
{
	FW W(X);
	W.StrD(TEXT("id"), X.Id); W.EnumD(TEXT("anchor"), X.Anchor, EStreetMarkingAnchor::Centre); W.Num(TEXT("offset_m"), X.OffsetM); W.Num(TEXT("width_m"), X.WidthM);
	W.Enum(TEXT("pattern"), X.Pattern); W.Opt(TEXT("dash_m"), X.DashM); W.Opt(TEXT("gap_m"), X.GapM); W.NumD(TEXT("phase_m"), X.PhaseM, 0.0);
	W.Opt(TEXT("double_gap_m"), X.DoubleGapM); W.Name(TEXT("material"), X.Material); W.NumD(TEXT("lift_m"), X.LiftM, 0.004);
	W.Opt(TEXT("s0_m"), X.S0M); W.Opt(TEXT("s1_m"), X.S1M);
	return W.Finish();
}
TArray<TSharedPtr<FJsonValue>> WriteMarkings(const TArray<FStreetMarking>& L)
{
	TArray<TSharedPtr<FJsonValue>> A;
	for (const FStreetMarking& M : L) A.Add(ObjVal(WriteMarking(M)));
	return A;
}
void ReadMarkings(FObj& R, const TCHAR* Key, TArray<FStreetMarking>& Out, bool* bHas, bool bRequired)
{
	if (const TArray<TSharedPtr<FJsonValue>>* A = R.Arr(Key, bRequired))
	{
		if (bHas) *bHas = true;
		Out.Reset();
		for (int32 I = 0; I < A->Num(); ++I)
		{
			const FString IP = FString::Printf(TEXT("%s.%s[%d]"), *R.Path, Key, I);
			if (!(*A)[I].IsValid() || (*A)[I]->Type != EJson::Object) { R.Errs.Add(IP + TEXT(": expected object")); continue; }
			FStreetMarking& M = Out.AddDefaulted_GetRef();
			ReadMarking(*(*A)[I]->AsObject(), IP, M, R.Errs);
		}
	}
}

void ReadRailSection(const FJsonObject& O, const FString& Path, FStreetRailSection& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("profile_id"), TEXT("height_m"), TEXT("head_width_m"), TEXT("foot_width_m"), TEXT("web_thickness_m"), TEXT("head_depth_m"), TEXT("foot_thickness_m"), TEXT("material") });
	R.Str(TEXT("profile_id"), X.ProfileId, false, false);
	R.Num(TEXT("height_m"), X.HeightM, true, 0.0, kNaN, true); R.Num(TEXT("head_width_m"), X.HeadWidthM, true, 0.0, kNaN, true);
	R.Num(TEXT("foot_width_m"), X.FootWidthM, true, 0.0, kNaN, true); R.Num(TEXT("web_thickness_m"), X.WebThicknessM, true, 0.0, kNaN, true);
	R.Num(TEXT("head_depth_m"), X.HeadDepthM, true, 0.0, kNaN, true); R.Num(TEXT("foot_thickness_m"), X.FootThicknessM, true, 0.0, kNaN, true);
	R.Mat(TEXT("material"), X.Material, true);
}
TSharedRef<FJsonObject> WriteRailSection(const FStreetRailSection& X)
{
	FW W(X);
	W.StrD(TEXT("profile_id"), X.ProfileId); W.Num(TEXT("height_m"), X.HeightM); W.Num(TEXT("head_width_m"), X.HeadWidthM); W.Num(TEXT("foot_width_m"), X.FootWidthM);
	W.Num(TEXT("web_thickness_m"), X.WebThicknessM); W.Num(TEXT("head_depth_m"), X.HeadDepthM); W.Num(TEXT("foot_thickness_m"), X.FootThicknessM); W.Name(TEXT("material"), X.Material);
	return W.Finish();
}

void ReadSleeper(const FJsonObject& O, const FString& Path, FStreetSleeper& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("length_m"), TEXT("width_m"), TEXT("height_m"), TEXT("pitch_m"), TEXT("phase_m"), TEXT("embed_m"), TEXT("mode"), TEXT("material") });
	R.Num(TEXT("length_m"), X.LengthM, true, 0.0, kNaN, true); R.Num(TEXT("width_m"), X.WidthM, true, 0.0, kNaN, true);
	R.Num(TEXT("height_m"), X.HeightM, true, 0.0, kNaN, true); R.Num(TEXT("pitch_m"), X.PitchM, true, 0.0, kNaN, true);
	R.Num(TEXT("phase_m"), X.PhaseM, false); R.Num(TEXT("embed_m"), X.EmbedM, false, 0.0); R.Enum(TEXT("mode"), X.Mode, false); R.Mat(TEXT("material"), X.Material, true);
}
TSharedRef<FJsonObject> WriteSleeper(const FStreetSleeper& X)
{
	FW W(X);
	W.Num(TEXT("length_m"), X.LengthM); W.Num(TEXT("width_m"), X.WidthM); W.Num(TEXT("height_m"), X.HeightM); W.Num(TEXT("pitch_m"), X.PitchM);
	W.NumD(TEXT("phase_m"), X.PhaseM, 0.0); W.NumD(TEXT("embed_m"), X.EmbedM, 0.10); W.EnumD(TEXT("mode"), X.Mode, EStreetSleeperMode::Instances); W.Name(TEXT("material"), X.Material);
	return W.Finish();
}

void ReadBallast(const FJsonObject& O, const FString& Path, FStreetBallast& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("shoulder_slope"), TEXT("depth_m"), TEXT("material") });
	R.Num(TEXT("shoulder_slope"), X.ShoulderSlope, true, 0.0, kNaN, true); R.Num(TEXT("depth_m"), X.DepthM, true, 0.0, kNaN, true); R.Mat(TEXT("material"), X.Material, true);
}
TSharedRef<FJsonObject> WriteBallast(const FStreetBallast& X)
{
	FW W(X);
	W.Num(TEXT("shoulder_slope"), X.ShoulderSlope); W.Num(TEXT("depth_m"), X.DepthM); W.Name(TEXT("material"), X.Material);
	return W.Finish();
}

void ReadRailSpec(const FJsonObject& O, const FString& Path, FStreetRailSpec& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("gauge_m"), TEXT("pad_m"), TEXT("rail"), TEXT("sleeper"), TEXT("ballast") });
	R.Num(TEXT("gauge_m"), X.GaugeM, true, 0.0, kNaN, true); R.Num(TEXT("pad_m"), X.PadM, false, 0.0);
	if (const FJsonObject* S = R.Obj(TEXT("rail"), true)) ReadRailSection(*S, R.P(TEXT("rail")), X.Rail, E);
	if (const FJsonObject* S = R.Obj(TEXT("sleeper"), true)) ReadSleeper(*S, R.P(TEXT("sleeper")), X.Sleeper, E);
	if (const FJsonObject* S = R.Obj(TEXT("ballast"), true)) ReadBallast(*S, R.P(TEXT("ballast")), X.Ballast, E);
}
TSharedRef<FJsonObject> WriteRailSpec(const FStreetRailSpec& X)
{
	FW W(X);
	W.Num(TEXT("gauge_m"), X.GaugeM); W.NumD(TEXT("pad_m"), X.PadM, 0.005);
	W.Obj(TEXT("rail"), WriteRailSection(X.Rail)); W.Obj(TEXT("sleeper"), WriteSleeper(X.Sleeper)); W.Obj(TEXT("ballast"), WriteBallast(X.Ballast));
	return W.Finish();
}

void ReadRoadProfileImpl(const FJsonObject& O, const FString& Path, FRoadProfileData& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("kind"), TEXT("lanes"), TEXT("lane_widths_m"), TEXT("width_m"), TEXT("surface_material"), TEXT("camber"), TEXT("overlap_m"), TEXT("skirt_drop_m"),
		TEXT("lateral_station_spacing_m"), TEXT("markings"), TEXT("rail"), TEXT("sampling_defaults") });
	R.Enum(TEXT("kind"), X.Kind, true);
	R.OptInt(TEXT("lanes"), X.Lanes, false, false, 0);
	R.NumList(TEXT("lane_widths_m"), X.LaneWidthsM, &X.bHasLaneWidthsM, false, 0.0, kNaN, true);
	R.Num(TEXT("width_m"), X.WidthM, true, 0.0);
	R.Mat(TEXT("surface_material"), X.SurfaceMaterial, true);
	if (const FJsonObject* S = R.Obj(TEXT("camber"), true)) ReadCamber(*S, R.P(TEXT("camber")), X.Camber, E);
	R.Num(TEXT("overlap_m"), X.OverlapM, false, 0.03, 0.10);
	R.Num(TEXT("skirt_drop_m"), X.SkirtDropM, false, 0.0, 0.03);
	R.Num(TEXT("lateral_station_spacing_m"), X.LateralStationSpacingM, false, 0.0, kNaN, true);
	ReadMarkings(R, TEXT("markings"), X.Markings, nullptr, true);
	if (const FJsonObject* S = R.Obj(TEXT("rail"), false)) { X.bHasRail = true; ReadRailSpec(*S, R.P(TEXT("rail")), X.Rail, E); }
	if (const FJsonObject* S = R.Obj(TEXT("sampling_defaults"), false)) { X.bHasSamplingDefaults = true; ReadSampling(*S, R.P(TEXT("sampling_defaults")), X.SamplingDefaults, E); }
	if (X.Kind == EStreetRoadKind::Rail && !X.bHasRail) E.Add(Path + TEXT(": kind rail requires 'rail'"));
}
TSharedRef<FJsonObject> WriteRoadProfileImpl(const FRoadProfileData& X)
{
	FW W(X);
	W.Enum(TEXT("kind"), X.Kind); W.OptI(TEXT("lanes"), X.Lanes); W.NumList(TEXT("lane_widths_m"), X.LaneWidthsM, X.bHasLaneWidthsM);
	W.Num(TEXT("width_m"), X.WidthM); W.Name(TEXT("surface_material"), X.SurfaceMaterial); W.Obj(TEXT("camber"), WriteCamber(X.Camber));
	W.NumD(TEXT("overlap_m"), X.OverlapM, 0.04); W.NumD(TEXT("skirt_drop_m"), X.SkirtDropM, 0.02); W.NumD(TEXT("lateral_station_spacing_m"), X.LateralStationSpacingM, 1.0);
	W.ObjList(TEXT("markings"), WriteMarkings(X.Markings), true);
	if (X.bHasRail) W.Obj(TEXT("rail"), WriteRailSpec(X.Rail));
	if (X.bHasSamplingDefaults) W.Obj(TEXT("sampling_defaults"), WriteSampling(X.SamplingDefaults));
	return W.Finish();
}

void ReadLip(const FJsonObject& O, const FString& Path, FStreetLip& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("kind"), TEXT("size_m"), TEXT("arc_points") });
	R.Enum(TEXT("kind"), X.Kind, true); R.Num(TEXT("size_m"), X.SizeM, false, 0.0); R.Int(TEXT("arc_points"), X.ArcPoints, false, 1, 8);
}
TSharedRef<FJsonObject> WriteLip(const FStreetLip& X)
{
	FW W(X);
	W.Enum(TEXT("kind"), X.Kind); W.NumD(TEXT("size_m"), X.SizeM, 0.02); W.IntD(TEXT("arc_points"), X.ArcPoints, 3);
	return W.Finish();
}

void ReadSplitMaterial(const FJsonObject& O, const FString& Path, FStreetSplitMaterial& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("enabled"), TEXT("inner"), TEXT("outer"), TEXT("boundary_frac") });
	R.Bool(TEXT("enabled"), X.bEnabled, true); R.Mat(TEXT("inner"), X.Inner, false); R.Mat(TEXT("outer"), X.Outer, false); R.Num(TEXT("boundary_frac"), X.BoundaryFrac, false, 0.0, 1.0);
	if (X.bEnabled && (X.Inner.IsNone() || X.Outer.IsNone())) E.Add(Path + TEXT(": enabled split needs inner and outer"));
}
TSharedRef<FJsonObject> WriteSplitMaterial(const FStreetSplitMaterial& X)
{
	FW W(X);
	W.Bool(TEXT("enabled"), X.bEnabled);
	if (!X.Inner.IsNone() || W.Want(TEXT("inner"))) W.Name(TEXT("inner"), X.Inner);
	if (!X.Outer.IsNone() || W.Want(TEXT("outer"))) W.Name(TEXT("outer"), X.Outer);
	W.NumD(TEXT("boundary_frac"), X.BoundaryFrac, 0.5);
	return W.Finish();
}

void ReadDropKerb(const FJsonObject& O, const FString& Path, FStreetDropKerb& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("s_m"), TEXT("length_m"), TEXT("ramp_m"), TEXT("target_height_m") });
	R.Num(TEXT("s_m"), X.SM, true, 0.0); R.Num(TEXT("length_m"), X.LengthM, false, 0.0); R.Num(TEXT("ramp_m"), X.RampM, false, 0.0, kNaN, true); R.Num(TEXT("target_height_m"), X.TargetHeightM, false, 0.0, 0.2);
}
TSharedRef<FJsonObject> WriteDropKerb(const FStreetDropKerb& X)
{
	FW W(X);
	W.Num(TEXT("s_m"), X.SM); W.NumD(TEXT("length_m"), X.LengthM, 1.83); W.NumD(TEXT("ramp_m"), X.RampM, 0.915); W.NumD(TEXT("target_height_m"), X.TargetHeightM, 0.006);
	return W.Finish();
}

void ReadSplineDropKerb(const FJsonObject& O, const FString& Path, FStreetSplineDropKerb& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("side"), TEXT("s_m"), TEXT("length_m"), TEXT("ramp_m"), TEXT("target_height_m") });
	R.Enum(TEXT("side"), X.Side, true); R.Num(TEXT("s_m"), X.SM, true, 0.0);
	R.OptNum(TEXT("length_m"), X.LengthM, false, false, 0.0); R.OptNum(TEXT("ramp_m"), X.RampM, false, false, 0.0, kNaN, true); R.OptNum(TEXT("target_height_m"), X.TargetHeightM, false, false, 0.0, 0.2);
}
TSharedRef<FJsonObject> WriteSplineDropKerb(const FStreetSplineDropKerb& X)
{
	FW W(X);
	W.Enum(TEXT("side"), X.Side); W.Num(TEXT("s_m"), X.SM); W.Opt(TEXT("length_m"), X.LengthM); W.Opt(TEXT("ramp_m"), X.RampM); W.Opt(TEXT("target_height_m"), X.TargetHeightM);
	return W.Finish();
}

/** bSegment: BarrierSegment (s0_m required, s1_m required nullable); else BarrierInline. */
void ReadBarrier(const FJsonObject& O, const FString& Path, FStreetBarrier& X, TArray<FString>& E, bool bSegment)
{
	FObj R(O, Path, E, &X, { TEXT("s0_m"), TEXT("s1_m"), TEXT("type"), TEXT("height_m"), TEXT("thickness_m"), TEXT("material"), TEXT("coping_material"), TEXT("coping_overhang_m"), TEXT("coping_height_m"),
		TEXT("post_pitch_m"), TEXT("post_size_m"), TEXT("post_material"), TEXT("rails_m"), TEXT("rail_size_m"), TEXT("offset_m"), TEXT("skirt_m") });
	if (bSegment)
	{
		R.OptNum(TEXT("s0_m"), X.S0M, true, false, 0.0);
		R.OptNum(TEXT("s1_m"), X.S1M, true, true, 0.0);
	}
	else
	{
		if (R.Has(TEXT("s0_m"))) E.Add(Path + TEXT(": unknown key 's0_m'"));
		if (R.Has(TEXT("s1_m"))) E.Add(Path + TEXT(": unknown key 's1_m'"));
	}
	R.Enum(TEXT("type"), X.Type, true);
	R.OptNum(TEXT("height_m"), X.HeightM, false, false, 0.0, kNaN, true);
	R.OptNum(TEXT("thickness_m"), X.ThicknessM, false, false, 0.0, kNaN, true);
	R.Mat(TEXT("material"), X.Material, false);
	R.Mat(TEXT("coping_material"), X.CopingMaterial, false);
	R.Num(TEXT("coping_overhang_m"), X.CopingOverhangM, false, 0.0); R.Num(TEXT("coping_height_m"), X.CopingHeightM, false, 0.0);
	R.OptNum(TEXT("post_pitch_m"), X.PostPitchM, false, false, 0.0, kNaN, true);
	R.Num(TEXT("post_size_m"), X.PostSizeM, false, 0.0, kNaN, true); R.Mat(TEXT("post_material"), X.PostMaterial, false);
	R.NumList(TEXT("rails_m"), X.RailsM, &X.bHasRailsM, false, 0.0);
	R.Num(TEXT("rail_size_m"), X.RailSizeM, false, 0.0, kNaN, true); R.Num(TEXT("offset_m"), X.OffsetM, false); R.Num(TEXT("skirt_m"), X.SkirtM, false, 0.0);
	if (X.Type != EStreetBarrierType::None)
	{
		if (!X.HeightM.IsSet()) E.Add(FString::Printf(TEXT("%s: barrier type %s requires height_m"), *Path, FStreetEnums::ToString(X.Type)));
		if (!X.ThicknessM.IsSet()) E.Add(FString::Printf(TEXT("%s: barrier type %s requires thickness_m"), *Path, FStreetEnums::ToString(X.Type)));
		if (X.Material.IsNone()) E.Add(FString::Printf(TEXT("%s: barrier type %s requires material"), *Path, FStreetEnums::ToString(X.Type)));
		if ((X.IsFence() || X.IsRailing()) && !X.PostPitchM.IsSet()) E.Add(FString::Printf(TEXT("%s: barrier type %s requires post_pitch_m"), *Path, FStreetEnums::ToString(X.Type)));
	}
}
TSharedRef<FJsonObject> WriteBarrier(const FStreetBarrier& X, bool bSegment)
{
	FW W(X);
	if (bSegment) { W.Opt(TEXT("s0_m"), X.S0M, true); W.Opt(TEXT("s1_m"), X.S1M, true); }
	W.Enum(TEXT("type"), X.Type); W.Opt(TEXT("height_m"), X.HeightM); W.Opt(TEXT("thickness_m"), X.ThicknessM);
	if (!X.Material.IsNone() || W.Want(TEXT("material"))) W.Name(TEXT("material"), X.Material);
	W.NameD(TEXT("coping_material"), X.CopingMaterial, TEXT("coping_concrete")); W.NumD(TEXT("coping_overhang_m"), X.CopingOverhangM, 0.025); W.NumD(TEXT("coping_height_m"), X.CopingHeightM, 0.05);
	W.Opt(TEXT("post_pitch_m"), X.PostPitchM); W.NumD(TEXT("post_size_m"), X.PostSizeM, 0.06); W.NameD(TEXT("post_material"), X.PostMaterial, TEXT("post_steel"));
	W.NumList(TEXT("rails_m"), X.RailsM, X.bHasRailsM); W.NumD(TEXT("rail_size_m"), X.RailSizeM, 0.04); W.NumD(TEXT("offset_m"), X.OffsetM, 0.0); W.NumD(TEXT("skirt_m"), X.SkirtM, 0.30);
	return W.Finish();
}

void ReadEmbankment(const FJsonObject& O, const FString& Path, FStreetEmbankment& X, TArray<FString>& E, bool bSegment)
{
	FObj R(O, Path, E, &X, { TEXT("s0_m"), TEXT("s1_m"), TEXT("side"), TEXT("kind"), TEXT("slope_ratio"), TEXT("wall_thickness_m"), TEXT("wall_coping_m"), TEXT("threshold_m"), TEXT("toe_extra_m"), TEXT("material") });
	if (bSegment)
	{
		R.OptNum(TEXT("s0_m"), X.S0M, true, false, 0.0);
		R.OptNum(TEXT("s1_m"), X.S1M, true, true, 0.0);
	}
	else
	{
		if (R.Has(TEXT("s0_m"))) E.Add(Path + TEXT(": unknown key 's0_m'"));
		if (R.Has(TEXT("s1_m"))) E.Add(Path + TEXT(": unknown key 's1_m'"));
	}
	R.Enum(TEXT("side"), X.Side, true); R.Enum(TEXT("kind"), X.Kind, true);
	R.Num(TEXT("slope_ratio"), X.SlopeRatio, false, 0.0, kNaN, true); R.Num(TEXT("wall_thickness_m"), X.WallThicknessM, false, 0.0, kNaN, true);
	R.Num(TEXT("wall_coping_m"), X.WallCopingM, false, 0.0); R.Num(TEXT("threshold_m"), X.ThresholdM, false, 0.0); R.Num(TEXT("toe_extra_m"), X.ToeExtraM, false, 0.0);
	R.Mat(TEXT("material"), X.Material, true);
}
TSharedRef<FJsonObject> WriteEmbankment(const FStreetEmbankment& X, bool bSegment)
{
	FW W(X);
	if (bSegment) { W.Opt(TEXT("s0_m"), X.S0M, true); W.Opt(TEXT("s1_m"), X.S1M, true); }
	W.Enum(TEXT("side"), X.Side); W.Enum(TEXT("kind"), X.Kind); W.NumD(TEXT("slope_ratio"), X.SlopeRatio, 1.5); W.NumD(TEXT("wall_thickness_m"), X.WallThicknessM, 0.30);
	W.NumD(TEXT("wall_coping_m"), X.WallCopingM, 0.10); W.NumD(TEXT("threshold_m"), X.ThresholdM, 0.35); W.NumD(TEXT("toe_extra_m"), X.ToeExtraM, 0.30); W.Name(TEXT("material"), X.Material);
	return W.Finish();
}

void ReadEdgeMaterials(const FJsonObject& O, const FString& Path, FStreetEdgeMaterials& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("kerb"), TEXT("pavement") });
	R.Mat(TEXT("kerb"), X.Kerb, true); R.Mat(TEXT("pavement"), X.Pavement, true);
}
TSharedRef<FJsonObject> WriteEdgeMaterials(const FStreetEdgeMaterials& X)
{
	FW W(X);
	W.Name(TEXT("kerb"), X.Kerb); W.Name(TEXT("pavement"), X.Pavement);
	return W.Finish();
}

template <typename T, typename FRead>
void ReadObjList(FObj& R, const TCHAR* Key, TArray<T>& Out, bool bRequired, FRead Read)
{
	if (const TArray<TSharedPtr<FJsonValue>>* A = R.Arr(Key, bRequired))
	{
		Out.Reset();
		for (int32 I = 0; I < A->Num(); ++I)
		{
			const FString IP = FString::Printf(TEXT("%s.%s[%d]"), *R.Path, Key, I);
			if (!(*A)[I].IsValid() || (*A)[I]->Type != EJson::Object) { R.Errs.Add(IP + TEXT(": expected object")); continue; }
			T& Item = Out.AddDefaulted_GetRef();
			Read(*(*A)[I]->AsObject(), IP, Item, R.Errs);
		}
	}
}

void ReadEdgeProfileImpl(const FJsonObject& O, const FString& Path, FEdgeProfileData& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("kerb_width_m"), TEXT("kerb_height_m"), TEXT("lip"), TEXT("pavement_width_m"), TEXT("pavement_crossfall_pct"), TEXT("pavement_max_crossfall_pct"),
		TEXT("tuck_depth_m"), TEXT("tuck_in_m"), TEXT("skirt_m"), TEXT("materials"), TEXT("split_material"), TEXT("drop_kerbs"), TEXT("barriers"), TEXT("embankments") });
	R.Num(TEXT("kerb_width_m"), X.KerbWidthM, true, 0.0); R.Num(TEXT("kerb_height_m"), X.KerbHeightM, true, 0.0);
	if (const FJsonObject* S = R.Obj(TEXT("lip"), false)) ReadLip(*S, R.P(TEXT("lip")), X.Lip, E);
	R.Num(TEXT("pavement_width_m"), X.PavementWidthM, true, 0.0); R.Num(TEXT("pavement_crossfall_pct"), X.PavementCrossfallPct, false, 0.0, 10.0);
	R.Num(TEXT("pavement_max_crossfall_pct"), X.PavementMaxCrossfallPct, false, 0.0, 20.0); R.Num(TEXT("tuck_depth_m"), X.TuckDepthM, false, 0.0);
	R.Num(TEXT("tuck_in_m"), X.TuckInM, false, 0.0); R.Num(TEXT("skirt_m"), X.SkirtM, false, 0.0);
	if (const FJsonObject* S = R.Obj(TEXT("materials"), true)) ReadEdgeMaterials(*S, R.P(TEXT("materials")), X.Materials, E);
	if (const FJsonObject* S = R.Obj(TEXT("split_material"), false)) ReadSplitMaterial(*S, R.P(TEXT("split_material")), X.SplitMaterial, E);
	ReadObjList(R, TEXT("drop_kerbs"), X.DropKerbs, false, [](const FJsonObject& SO, const FString& SP, FStreetDropKerb& D, TArray<FString>& SE) { ReadDropKerb(SO, SP, D, SE); });
	ReadObjList(R, TEXT("barriers"), X.Barriers, false, [](const FJsonObject& SO, const FString& SP, FStreetBarrier& D, TArray<FString>& SE) { ReadBarrier(SO, SP, D, SE, true); });
	ReadObjList(R, TEXT("embankments"), X.Embankments, false, [](const FJsonObject& SO, const FString& SP, FStreetEmbankment& D, TArray<FString>& SE) { ReadEmbankment(SO, SP, D, SE, true); });
}
TSharedRef<FJsonObject> WriteEdgeProfileImpl(const FEdgeProfileData& X)
{
	FW W(X);
	W.Num(TEXT("kerb_width_m"), X.KerbWidthM); W.Num(TEXT("kerb_height_m"), X.KerbHeightM);
	if (W.Want(TEXT("lip"))) W.Obj(TEXT("lip"), WriteLip(X.Lip));
	W.Num(TEXT("pavement_width_m"), X.PavementWidthM); W.NumD(TEXT("pavement_crossfall_pct"), X.PavementCrossfallPct, 2.5); W.NumD(TEXT("pavement_max_crossfall_pct"), X.PavementMaxCrossfallPct, 8.0);
	W.NumD(TEXT("tuck_depth_m"), X.TuckDepthM, 0.03); W.NumD(TEXT("tuck_in_m"), X.TuckInM, 0.02); W.NumD(TEXT("skirt_m"), X.SkirtM, 0.30);
	W.Obj(TEXT("materials"), WriteEdgeMaterials(X.Materials));
	if (W.Want(TEXT("split_material")) || X.SplitMaterial.bEnabled) W.Obj(TEXT("split_material"), WriteSplitMaterial(X.SplitMaterial));
	TArray<TSharedPtr<FJsonValue>> A;
	for (const FStreetDropKerb& D : X.DropKerbs) A.Add(ObjVal(WriteDropKerb(D)));
	W.ObjList(TEXT("drop_kerbs"), A, W.Want(TEXT("drop_kerbs")) || A.Num() > 0);
	A.Reset();
	for (const FStreetBarrier& D : X.Barriers) A.Add(ObjVal(WriteBarrier(D, true)));
	W.ObjList(TEXT("barriers"), A, W.Want(TEXT("barriers")) || A.Num() > 0);
	A.Reset();
	for (const FStreetEmbankment& D : X.Embankments) A.Add(ObjVal(WriteEmbankment(D, true)));
	W.ObjList(TEXT("embankments"), A, W.Want(TEXT("embankments")) || A.Num() > 0);
	return W.Finish();
}

void ReadFoliage(const FJsonObject& O, const FString& Path, FStreetFoliage& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("mode"), TEXT("density_per_m2"), TEXT("card_size_m"), TEXT("material"), TEXT("mesh_id"), TEXT("seed") });
	R.Enum(TEXT("mode"), X.Mode, true); R.Num(TEXT("density_per_m2"), X.DensityPerM2, false, 0.0); R.Num(TEXT("card_size_m"), X.CardSizeM, false, 0.0, kNaN, true);
	R.Mat(TEXT("material"), X.Material, false); R.Str(TEXT("mesh_id"), X.MeshId, false, false); R.Int(TEXT("seed"), X.Seed, false, 0);
}
TSharedRef<FJsonObject> WriteFoliage(const FStreetFoliage& X)
{
	FW W(X);
	W.Enum(TEXT("mode"), X.Mode); W.NumD(TEXT("density_per_m2"), X.DensityPerM2, 12.0); W.NumD(TEXT("card_size_m"), X.CardSizeM, 0.25);
	if (!X.Material.IsNone() || W.Want(TEXT("material"))) W.Name(TEXT("material"), X.Material);
	W.StrD(TEXT("mesh_id"), X.MeshId); W.IntD(TEXT("seed"), X.Seed, 1);
	return W.Finish();
}

void ReadHedgeSegment(const FJsonObject& O, const FString& Path, FStreetHedgeSegment& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("s0_m"), TEXT("s1_m"), TEXT("offset_m"), TEXT("height_override_m"), TEXT("width_override_m") });
	R.Num(TEXT("s0_m"), X.S0M, true, 0.0); R.OptNum(TEXT("s1_m"), X.S1M, true, true, 0.0); R.Num(TEXT("offset_m"), X.OffsetM, false);
	R.OptNum(TEXT("height_override_m"), X.HeightOverrideM, false, false, 0.0, kNaN, true); R.OptNum(TEXT("width_override_m"), X.WidthOverrideM, false, false, 0.0, kNaN, true);
}
TSharedRef<FJsonObject> WriteHedgeSegment(const FStreetHedgeSegment& X)
{
	FW W(X);
	W.Num(TEXT("s0_m"), X.S0M); W.Opt(TEXT("s1_m"), X.S1M, true); W.NumD(TEXT("offset_m"), X.OffsetM, 0.1); W.Opt(TEXT("height_override_m"), X.HeightOverrideM); W.Opt(TEXT("width_override_m"), X.WidthOverrideM);
	return W.Finish();
}

void ReadHedgeProfileImpl(const FJsonObject& O, const FString& Path, FHedgeProfileData& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("width_m"), TEXT("height_m"), TEXT("top_profile"), TEXT("corner_radius_m"), TEXT("corner_points"), TEXT("noise_amplitude_m"), TEXT("noise_scale_m"),
		TEXT("noise_seed"), TEXT("base_sink_m"), TEXT("material"), TEXT("foliage"), TEXT("segments") });
	R.Num(TEXT("width_m"), X.WidthM, true, 0.0, kNaN, true); R.Num(TEXT("height_m"), X.HeightM, true, 0.0, kNaN, true); R.Enum(TEXT("top_profile"), X.TopProfile, true);
	R.Num(TEXT("corner_radius_m"), X.CornerRadiusM, false, 0.0); R.Int(TEXT("corner_points"), X.CornerPoints, false, 1, 8);
	R.Num(TEXT("noise_amplitude_m"), X.NoiseAmplitudeM, false, 0.0); R.Num(TEXT("noise_scale_m"), X.NoiseScaleM, false, 0.0, kNaN, true); R.Int(TEXT("noise_seed"), X.NoiseSeed, false, 0);
	R.Num(TEXT("base_sink_m"), X.BaseSinkM, false, 0.0); R.Mat(TEXT("material"), X.Material, true);
	if (const FJsonObject* S = R.Obj(TEXT("foliage"), true)) ReadFoliage(*S, R.P(TEXT("foliage")), X.Foliage, E);
	ReadObjList(R, TEXT("segments"), X.Segments, true, [](const FJsonObject& SO, const FString& SP, FStreetHedgeSegment& D, TArray<FString>& SE) { ReadHedgeSegment(SO, SP, D, SE); });
}
TSharedRef<FJsonObject> WriteHedgeProfileImpl(const FHedgeProfileData& X)
{
	FW W(X);
	W.Num(TEXT("width_m"), X.WidthM); W.Num(TEXT("height_m"), X.HeightM); W.Enum(TEXT("top_profile"), X.TopProfile);
	W.NumD(TEXT("corner_radius_m"), X.CornerRadiusM, 0.15); W.IntD(TEXT("corner_points"), X.CornerPoints, 4); W.NumD(TEXT("noise_amplitude_m"), X.NoiseAmplitudeM, 0.06);
	W.NumD(TEXT("noise_scale_m"), X.NoiseScaleM, 0.6); W.IntD(TEXT("noise_seed"), X.NoiseSeed, 1); W.NumD(TEXT("base_sink_m"), X.BaseSinkM, 0.10); W.Name(TEXT("material"), X.Material);
	W.Obj(TEXT("foliage"), WriteFoliage(X.Foliage));
	TArray<TSharedPtr<FJsonValue>> A;
	for (const FStreetHedgeSegment& S : X.Segments) A.Add(ObjVal(WriteHedgeSegment(S)));
	W.ObjList(TEXT("segments"), A, true);
	return W.Finish();
}

// -- spline ------------------------------------------------------------------------------------------------------

void ReadPoint(const FJsonObject& O, const FString& Path, FStreetPoint& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("x"), TEXT("y"), TEXT("z"), TEXT("roll_deg"), TEXT("width_m"), TEXT("tags") });
	R.Num(TEXT("x"), X.X, true); R.Num(TEXT("y"), X.Y, true);
	R.OptNum(TEXT("z"), X.Z, false, true); R.OptNum(TEXT("roll_deg"), X.RollDeg, false, true, -30.0, 30.0); R.OptNum(TEXT("width_m"), X.WidthM, false, false, 0.0);
	R.StrList(TEXT("tags"), X.Tags, nullptr, false);
}
TSharedRef<FJsonObject> WritePoint(const FStreetPoint& X)
{
	FW W(X);
	W.Num(TEXT("x"), X.X); W.Num(TEXT("y"), X.Y); W.Opt(TEXT("z"), X.Z); W.Opt(TEXT("roll_deg"), X.RollDeg); W.Opt(TEXT("width_m"), X.WidthM);
	W.StrList(TEXT("tags"), X.Tags, X.Tags.Num() > 0 || W.Want(TEXT("tags")));
	return W.Finish();
}

void ReadSegmentRoad(const FJsonObject& O, const FString& Path, FStreetSegmentRoad& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("width_m"), TEXT("profile_id"), TEXT("edge_extra_left_m"), TEXT("edge_extra_right_m"), TEXT("markings"), TEXT("markings_add") });
	R.OptNum(TEXT("width_m"), X.WidthM, false, false, 0.0); R.Id(TEXT("profile_id"), X.ProfileId, false);
	R.OptNum(TEXT("edge_extra_left_m"), X.EdgeExtraLeftM, false, false); R.OptNum(TEXT("edge_extra_right_m"), X.EdgeExtraRightM, false, false);
	ReadMarkings(R, TEXT("markings"), X.Markings, &X.bHasMarkings, false);
	ReadMarkings(R, TEXT("markings_add"), X.MarkingsAdd, &X.bHasMarkingsAdd, false);
}
TSharedRef<FJsonObject> WriteSegmentRoad(const FStreetSegmentRoad& X)
{
	FW W(X);
	W.Opt(TEXT("width_m"), X.WidthM); W.StrD(TEXT("profile_id"), X.ProfileId); W.Opt(TEXT("edge_extra_left_m"), X.EdgeExtraLeftM); W.Opt(TEXT("edge_extra_right_m"), X.EdgeExtraRightM);
	W.ObjList(TEXT("markings"), WriteMarkings(X.Markings), X.bHasMarkings); W.ObjList(TEXT("markings_add"), WriteMarkings(X.MarkingsAdd), X.bHasMarkingsAdd);
	return W.Finish();
}

void ReadSegmentEdge(const FJsonObject& O, const FString& Path, FStreetSegmentEdge& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("profile_id"), TEXT("kerb_width_m"), TEXT("kerb_height_m"), TEXT("pavement_width_m"), TEXT("pavement_crossfall_pct"), TEXT("split_material"), TEXT("barrier"), TEXT("embankment") });
	R.Id(TEXT("profile_id"), X.ProfileId, false);
	R.OptNum(TEXT("kerb_width_m"), X.KerbWidthM, false, false, 0.0); R.OptNum(TEXT("kerb_height_m"), X.KerbHeightM, false, false, 0.0);
	R.OptNum(TEXT("pavement_width_m"), X.PavementWidthM, false, false, 0.0); R.OptNum(TEXT("pavement_crossfall_pct"), X.PavementCrossfallPct, false, false, 0.0, 10.0);
	if (const FJsonObject* S = R.Obj(TEXT("split_material"), false)) { X.bHasSplitMaterial = true; ReadSplitMaterial(*S, R.P(TEXT("split_material")), X.SplitMaterial, E); }
	X.bBarrierSet = R.Has(TEXT("barrier"));
	if (const FJsonObject* S = R.Obj(TEXT("barrier"), false, true)) { X.bHasBarrier = true; ReadBarrier(*S, R.P(TEXT("barrier")), X.Barrier, E, false); }
	X.bEmbankmentSet = R.Has(TEXT("embankment"));
	if (const FJsonObject* S = R.Obj(TEXT("embankment"), false, true)) { X.bHasEmbankment = true; ReadEmbankment(*S, R.P(TEXT("embankment")), X.Embankment, E, false); }
}
TSharedRef<FJsonObject> WriteSegmentEdge(const FStreetSegmentEdge& X)
{
	FW W(X);
	W.StrD(TEXT("profile_id"), X.ProfileId); W.Opt(TEXT("kerb_width_m"), X.KerbWidthM); W.Opt(TEXT("kerb_height_m"), X.KerbHeightM);
	W.Opt(TEXT("pavement_width_m"), X.PavementWidthM); W.Opt(TEXT("pavement_crossfall_pct"), X.PavementCrossfallPct);
	if (X.bHasSplitMaterial) W.Obj(TEXT("split_material"), WriteSplitMaterial(X.SplitMaterial));
	if (X.bHasBarrier) W.Obj(TEXT("barrier"), WriteBarrier(X.Barrier, false)); else if (X.bBarrierSet) W.Null(TEXT("barrier"));
	if (X.bHasEmbankment) W.Obj(TEXT("embankment"), WriteEmbankment(X.Embankment, false)); else if (X.bEmbankmentSet) W.Null(TEXT("embankment"));
	return W.Finish();
}

void ReadSegmentHedge(const FJsonObject& O, const FString& Path, FStreetSegmentHedge& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("present"), TEXT("profile_id"), TEXT("offset_m"), TEXT("height_m"), TEXT("width_m") });
	R.Bool(TEXT("present"), X.bPresent, true); R.Id(TEXT("profile_id"), X.ProfileId, false);
	R.OptNum(TEXT("offset_m"), X.OffsetM, false, false); R.OptNum(TEXT("height_m"), X.HeightM, false, false, 0.0, kNaN, true); R.OptNum(TEXT("width_m"), X.WidthM, false, false, 0.0, kNaN, true);
}
TSharedRef<FJsonObject> WriteSegmentHedge(const FStreetSegmentHedge& X)
{
	FW W(X);
	W.Bool(TEXT("present"), X.bPresent); W.StrD(TEXT("profile_id"), X.ProfileId); W.Opt(TEXT("offset_m"), X.OffsetM); W.Opt(TEXT("height_m"), X.HeightM); W.Opt(TEXT("width_m"), X.WidthM);
	return W.Finish();
}

void ReadSegment(const FJsonObject& O, const FString& Path, FStreetSegment& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("id"), TEXT("s0_m"), TEXT("s1_m"), TEXT("side"), TEXT("ramp_m"), TEXT("road"), TEXT("edge"), TEXT("hedge") });
	R.Id(TEXT("id"), X.Id, false); R.Num(TEXT("s0_m"), X.S0M, true, 0.0); R.OptNum(TEXT("s1_m"), X.S1M, true, true, 0.0); R.Enum(TEXT("side"), X.Side, true);
	R.OptNum(TEXT("ramp_m"), X.RampM, false, false, 0.0);
	if (const FJsonObject* S = R.Obj(TEXT("road"), false)) { X.bHasRoad = true; ReadSegmentRoad(*S, R.P(TEXT("road")), X.Road, E); }
	if (const FJsonObject* S = R.Obj(TEXT("edge"), false)) { X.bHasEdge = true; ReadSegmentEdge(*S, R.P(TEXT("edge")), X.Edge, E); }
	if (const FJsonObject* S = R.Obj(TEXT("hedge"), false)) { X.bHasHedge = true; ReadSegmentHedge(*S, R.P(TEXT("hedge")), X.Hedge, E); }
}
TSharedRef<FJsonObject> WriteSegment(const FStreetSegment& X)
{
	FW W(X);
	W.StrD(TEXT("id"), X.Id); W.Num(TEXT("s0_m"), X.S0M); W.Opt(TEXT("s1_m"), X.S1M, true); W.Enum(TEXT("side"), X.Side); W.Opt(TEXT("ramp_m"), X.RampM);
	if (X.bHasRoad) W.Obj(TEXT("road"), WriteSegmentRoad(X.Road));
	if (X.bHasEdge) W.Obj(TEXT("edge"), WriteSegmentEdge(X.Edge));
	if (X.bHasHedge) W.Obj(TEXT("hedge"), WriteSegmentHedge(X.Hedge));
	return W.Finish();
}

void ReadSource(const FJsonObject& O, const FString& Path, FStreetSource& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("layer"), TEXT("osm_id"), TEXT("osm_ids"), TEXT("name"), TEXT("cls"), TEXT("tags"), TEXT("tile"), TEXT("segment_index"), TEXT("segment_count") });
	R.Enum(TEXT("layer"), X.Layer, true);
	R.Str(TEXT("osm_id"), X.OsmId, false, false, true); R.StrList(TEXT("osm_ids"), X.OsmIds, &X.bHasOsmIds, false);
	R.Str(TEXT("name"), X.Name, false, false, true); R.Str(TEXT("cls"), X.Cls, false, false, true);
	if (const FJsonObject* T = R.Obj(TEXT("tags"), false))
	{
		X.bHasTags = true;
		X.Tags.Reset();
		for (const auto& KV : T->Values)
		{
			const FString KKey(*KV.Key);
			if (KKey.StartsWith(TEXT("_"))) continue;
			if (!KV.Value.IsValid() || KV.Value->Type != EJson::String) { E.Add(FString::Printf(TEXT("%s.tags.%s: expected string, got %s"), *Path, *KKey, *Compact(KV.Value))); continue; }
			X.Tags.Add(KKey, KV.Value->AsString());
		}
	}
	R.IntList(TEXT("tile"), X.Tile, &X.bHasTile, false);
	R.OptInt(TEXT("segment_index"), X.SegmentIndex, false, false, 0); R.OptInt(TEXT("segment_count"), X.SegmentCount, false, false, 1);
}
TSharedRef<FJsonObject> WriteSource(const FStreetSource& X)
{
	FW W(X);
	W.Enum(TEXT("layer"), X.Layer); W.StrD(TEXT("osm_id"), X.OsmId); W.StrList(TEXT("osm_ids"), X.OsmIds, X.bHasOsmIds); W.StrD(TEXT("name"), X.Name); W.StrD(TEXT("cls"), X.Cls);
	if (X.bHasTags)
	{
		TSharedRef<FJsonObject> T = MakeShared<FJsonObject>();
		for (const auto& KV : X.Tags) T->SetStringField(KV.Key, KV.Value);
		W.Obj(TEXT("tags"), T);
	}
	W.IntList(TEXT("tile"), X.Tile, X.bHasTile); W.OptI(TEXT("segment_index"), X.SegmentIndex); W.OptI(TEXT("segment_count"), X.SegmentCount);
	return W.Finish();
}

void ReadOverlay(const FJsonObject& O, const FString& Path, FStreetOverlay& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("kind"), TEXT("pts"), TEXT("osm_id") });
	R.Enum(TEXT("kind"), X.Kind, true);
	if (const TArray<TSharedPtr<FJsonValue>>* A = R.Arr(TEXT("pts"), true, 2))
	{
		X.Pts.Reset(); X.PtsHaveZ.Reset();
		for (int32 I = 0; I < A->Num(); ++I)
		{
			FVector3d P; bool bZ = false;
			if (R.XY(*FString::Printf(TEXT("pts[%d]"), I), (*A)[I], P, bZ, false)) { X.Pts.Add(P); X.PtsHaveZ.Add(bZ); }
		}
	}
	R.Str(TEXT("osm_id"), X.OsmId, false, false, true);
}
TSharedRef<FJsonObject> WriteOverlay(const FStreetOverlay& X)
{
	FW W(X);
	W.Enum(TEXT("kind"), X.Kind);
	TArray<TSharedPtr<FJsonValue>> A;
	for (int32 I = 0; I < X.Pts.Num(); ++I)
	{
		TArray<TSharedPtr<FJsonValue>> P;
		P.Add(MakeShared<FJsonValueNumber>(X.Pts[I].X)); P.Add(MakeShared<FJsonValueNumber>(X.Pts[I].Y));
		if (X.PtsHaveZ.IsValidIndex(I) && X.PtsHaveZ[I]) P.Add(MakeShared<FJsonValueNumber>(X.Pts[I].Z));
		A.Add(MakeShared<FJsonValueArray>(P));
	}
	W.ObjList(TEXT("pts"), A, true);
	W.StrD(TEXT("osm_id"), X.OsmId);
	return W.Finish();
}

void ReadProfileIds(const FJsonObject& O, const FString& Path, FStreetProfileIds& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("road"), TEXT("edge_left"), TEXT("edge_right"), TEXT("hedge_left"), TEXT("hedge_right") });
	R.Id(TEXT("road"), X.Road, true, true); R.Id(TEXT("edge_left"), X.EdgeLeft, true, true); R.Id(TEXT("edge_right"), X.EdgeRight, true, true);
	R.Id(TEXT("hedge_left"), X.HedgeLeft, true, true); R.Id(TEXT("hedge_right"), X.HedgeRight, true, true);
}
TSharedRef<FJsonObject> WriteProfileIds(const FStreetProfileIds& X)
{
	FW W(X);
	W.StrD(TEXT("road"), X.Road, true); W.StrD(TEXT("edge_left"), X.EdgeLeft, true); W.StrD(TEXT("edge_right"), X.EdgeRight, true);
	W.StrD(TEXT("hedge_left"), X.HedgeLeft, true); W.StrD(TEXT("hedge_right"), X.HedgeRight, true);
	return W.Finish();
}

void ReadContinuation(const FJsonObject& O, const FString& Path, FStreetContinuationKind& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("from"), TEXT("to") });
	X.From = EStreetContinuation::None; X.To = EStreetContinuation::None;
	R.Enum(TEXT("from"), X.From, true, true); R.Enum(TEXT("to"), X.To, true, true);
	if (X.From == EStreetContinuation::None && R.Has(TEXT("from")) && !R.IsNull(TEXT("from"))) E.Add(Path + TEXT(".from: 'none' is not a continuation kind (use null)"));
	if (X.To == EStreetContinuation::None && R.Has(TEXT("to")) && !R.IsNull(TEXT("to"))) E.Add(Path + TEXT(".to: 'none' is not a continuation kind (use null)"));
}
TSharedRef<FJsonObject> WriteContinuation(const FStreetContinuationKind& X)
{
	FW W(X);
	if (X.From == EStreetContinuation::None) W.Null(TEXT("from")); else W.Enum(TEXT("from"), X.From);
	if (X.To == EStreetContinuation::None) W.Null(TEXT("to")); else W.Enum(TEXT("to"), X.To);
	return W.Finish();
}

void ReadOverrun(const FJsonObject& O, const FString& Path, FStreetOverrunPoints& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("before"), TEXT("after") });
	bool bZ = false;
	if (const TSharedPtr<FJsonValue>* V = R.Get(TEXT("before"), true, true)) X.bHasBefore = R.XY(TEXT("before"), *V, X.Before, bZ, true);
	if (const TSharedPtr<FJsonValue>* V = R.Get(TEXT("after"), true, true)) X.bHasAfter = R.XY(TEXT("after"), *V, X.After, bZ, true);
}
TSharedPtr<FJsonValue> XYZVal(const FVector3d& P)
{
	TArray<TSharedPtr<FJsonValue>> A;
	A.Add(MakeShared<FJsonValueNumber>(P.X)); A.Add(MakeShared<FJsonValueNumber>(P.Y)); A.Add(MakeShared<FJsonValueNumber>(P.Z));
	return MakeShared<FJsonValueArray>(A);
}
TSharedRef<FJsonObject> WriteOverrun(const FStreetOverrunPoints& X)
{
	FW W(X);
	if (X.bHasBefore) W.O->SetField(TEXT("before"), XYZVal(X.Before)); else W.Null(TEXT("before"));
	if (X.bHasAfter) W.O->SetField(TEXT("after"), XYZVal(X.After)); else W.Null(TEXT("after"));
	return W.Finish();
}

void ReadFlags(const FJsonObject& O, const FString& Path, FStreetFlags& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("bridge"), TEXT("tunnel"), TEXT("z_gap"), TEXT("steps"), TEXT("disused"), TEXT("gauge_unmapped"), TEXT("closed_loop"), TEXT("tracks") });
	R.Bool(TEXT("bridge"), X.bBridge, false); R.Bool(TEXT("tunnel"), X.bTunnel, false); R.Bool(TEXT("z_gap"), X.bZGap, false); R.Bool(TEXT("steps"), X.bSteps, false);
	R.Bool(TEXT("disused"), X.bDisused, false); R.Bool(TEXT("gauge_unmapped"), X.bGaugeUnmapped, false); R.Bool(TEXT("closed_loop"), X.bClosedLoop, false);
	R.OptInt(TEXT("tracks"), X.Tracks, false, true, 1);
}
TSharedRef<FJsonObject> WriteFlags(const FStreetFlags& X)
{
	FW W(X);
	W.BoolD(TEXT("bridge"), X.bBridge, false); W.BoolD(TEXT("tunnel"), X.bTunnel, false); W.BoolD(TEXT("z_gap"), X.bZGap, false); W.BoolD(TEXT("steps"), X.bSteps, false);
	W.BoolD(TEXT("disused"), X.bDisused, false); W.BoolD(TEXT("gauge_unmapped"), X.bGaugeUnmapped, false); W.BoolD(TEXT("closed_loop"), X.bClosedLoop, false); W.OptI(TEXT("tracks"), X.Tracks);
	return W.Finish();
}

void ReadElevationKnot(const FJsonObject& O, const FString& Path, FStreetElevationKnot& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("s_m"), TEXT("z_m"), TEXT("bank_deg") });
	R.Num(TEXT("s_m"), X.SM, true, 0.0);
	R.Num(TEXT("z_m"), X.ZM, true);
	R.Num(TEXT("bank_deg"), X.BankDeg, true, -45.0, 45.0);
}

TSharedRef<FJsonObject> WriteElevationKnot(const FStreetElevationKnot& X)
{
	FW W(X);
	W.Num(TEXT("s_m"), X.SM); W.Num(TEXT("z_m"), X.ZM); W.Num(TEXT("bank_deg"), X.BankDeg);
	return W.Finish();
}

void ReadSplineDef(const FJsonObject& O, const FString& Path, FStreetSplineDef& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("id"), TEXT("source"), TEXT("profile_ids"), TEXT("points"), TEXT("sampling"), TEXT("segments"), TEXT("drop_kerbs"), TEXT("overlay"), TEXT("junction_start"),
		TEXT("junction_end"), TEXT("continues_from"), TEXT("continues_to"), TEXT("continuation_kind"), TEXT("overrun_points"), TEXT("flags"), TEXT("elevation_profile") });
	R.Id(TEXT("id"), X.Id, true);
	if (const FJsonObject* S = R.Obj(TEXT("source"), true)) ReadSource(*S, R.P(TEXT("source")), X.Source, E);
	if (const FJsonObject* S = R.Obj(TEXT("profile_ids"), true)) ReadProfileIds(*S, R.P(TEXT("profile_ids")), X.ProfileIds, E);
	if (const TArray<TSharedPtr<FJsonValue>>* A = R.Arr(TEXT("points"), true, 2))
	{
		X.Points.Reset();
		for (int32 I = 0; I < A->Num(); ++I)
		{
			const FString IP = FString::Printf(TEXT("%s.points[%d]"), *Path, I);
			if (!(*A)[I].IsValid() || (*A)[I]->Type != EJson::Object) { E.Add(IP + TEXT(": expected object")); continue; }
			ReadPoint(*(*A)[I]->AsObject(), IP, X.Points.AddDefaulted_GetRef(), E);
		}
	}
	if (const FJsonObject* S = R.Obj(TEXT("sampling"), false)) { X.bHasSampling = true; ReadSampling(*S, R.P(TEXT("sampling")), X.Sampling, E); }
	if (R.Arr(TEXT("elevation_profile"), false, 2))
	{
		ReadObjList(R, TEXT("elevation_profile"), X.ElevationProfile, false,
			[](const FJsonObject& SO, const FString& SP, FStreetElevationKnot& D, TArray<FString>& SE) { ReadElevationKnot(SO, SP, D, SE); });
		for (int32 I = 0; I < X.ElevationProfile.Num(); ++I)
		{
			if ((I == 0 && X.ElevationProfile[I].SM != 0.0) || (I > 0 && X.ElevationProfile[I].SM <= X.ElevationProfile[I-1].SM))
				E.Add(Path + TEXT(".elevation_profile: stations must start at 0 and strictly increase"));
		}
	}
	ReadObjList(R, TEXT("segments"), X.Segments, false, [](const FJsonObject& SO, const FString& SP, FStreetSegment& D, TArray<FString>& SE) { ReadSegment(SO, SP, D, SE); });
	ReadObjList(R, TEXT("drop_kerbs"), X.DropKerbs, false, [](const FJsonObject& SO, const FString& SP, FStreetSplineDropKerb& D, TArray<FString>& SE) { ReadSplineDropKerb(SO, SP, D, SE); });
	if (const FJsonObject* S = R.Obj(TEXT("overlay"), false)) { X.bHasOverlay = true; ReadOverlay(*S, R.P(TEXT("overlay")), X.Overlay, E); }
	R.Id(TEXT("junction_start"), X.JunctionStart, false, true); R.Id(TEXT("junction_end"), X.JunctionEnd, false, true);
	R.Id(TEXT("continues_from"), X.ContinuesFrom, false, true); R.Id(TEXT("continues_to"), X.ContinuesTo, false, true);
	if (const FJsonObject* S = R.Obj(TEXT("continuation_kind"), false)) { X.bHasContinuationKind = true; ReadContinuation(*S, R.P(TEXT("continuation_kind")), X.ContinuationKind, E); }
	if (const FJsonObject* S = R.Obj(TEXT("overrun_points"), false)) { X.bHasOverrunPoints = true; ReadOverrun(*S, R.P(TEXT("overrun_points")), X.OverrunPoints, E); }
	if (const FJsonObject* S = R.Obj(TEXT("flags"), false)) { X.bHasFlags = true; ReadFlags(*S, R.P(TEXT("flags")), X.Flags, E); }
}
TSharedRef<FJsonObject> WriteSplineDef(const FStreetSplineDef& X)
{
	FW W(X);
	W.Str(TEXT("id"), X.Id); W.Obj(TEXT("source"), WriteSource(X.Source)); W.Obj(TEXT("profile_ids"), WriteProfileIds(X.ProfileIds));
	TArray<TSharedPtr<FJsonValue>> A;
	for (const FStreetPoint& P : X.Points) A.Add(ObjVal(WritePoint(P)));
	W.ObjList(TEXT("points"), A, true);
	A.Reset();
	for (const FStreetElevationKnot& K : X.ElevationProfile) A.Add(ObjVal(WriteElevationKnot(K)));
	W.ObjList(TEXT("elevation_profile"), A, A.Num() > 0 || W.Want(TEXT("elevation_profile")));
	if (X.bHasSampling) W.Obj(TEXT("sampling"), WriteSampling(X.Sampling));
	A.Reset();
	for (const FStreetSegment& S : X.Segments) A.Add(ObjVal(WriteSegment(S)));
	W.ObjList(TEXT("segments"), A, W.Want(TEXT("segments")) || A.Num() > 0);
	A.Reset();
	for (const FStreetSplineDropKerb& D : X.DropKerbs) A.Add(ObjVal(WriteSplineDropKerb(D)));
	W.ObjList(TEXT("drop_kerbs"), A, W.Want(TEXT("drop_kerbs")) || A.Num() > 0);
	if (X.bHasOverlay) W.Obj(TEXT("overlay"), WriteOverlay(X.Overlay));
	W.StrD(TEXT("junction_start"), X.JunctionStart); W.StrD(TEXT("junction_end"), X.JunctionEnd); W.StrD(TEXT("continues_from"), X.ContinuesFrom); W.StrD(TEXT("continues_to"), X.ContinuesTo);
	if (X.bHasContinuationKind) W.Obj(TEXT("continuation_kind"), WriteContinuation(X.ContinuationKind));
	if (X.bHasOverrunPoints) W.Obj(TEXT("overrun_points"), WriteOverrun(X.OverrunPoints));
	if (X.bHasFlags) W.Obj(TEXT("flags"), WriteFlags(X.Flags));
	return W.Finish();
}

void ReadJunctionEnd(const FJsonObject& O, const FString& Path, FStreetJunctionEnd& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("spline_id"), TEXT("end") });
	R.Id(TEXT("spline_id"), X.SplineId, true); R.Enum(TEXT("end"), X.End, true);
}
void ReadJunction(const FJsonObject& O, const FString& Path, FStreetJunction& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("id"), TEXT("x"), TEXT("y"), TEXT("z"), TEXT("radius_m"), TEXT("trim_radius_m"), TEXT("kind"), TEXT("ends") });
	R.Id(TEXT("id"), X.Id, true); R.Num(TEXT("x"), X.X, true); R.Num(TEXT("y"), X.Y, true); R.OptNum(TEXT("z"), X.Z, false, true); R.OptNum(TEXT("radius_m"), X.RadiusM, false, false, 0.0);
	R.OptNum(TEXT("trim_radius_m"), X.TrimRadiusM, false, true, 0.0);
	R.Enum(TEXT("kind"), X.Kind, false);
	ReadObjList(R, TEXT("ends"), X.Ends, true, [](const FJsonObject& SO, const FString& SP, FStreetJunctionEnd& D, TArray<FString>& SE) { ReadJunctionEnd(SO, SP, D, SE); });
}
TSharedRef<FJsonObject> WriteJunction(const FStreetJunction& X)
{
	FW W(X);
	W.Str(TEXT("id"), X.Id); W.Num(TEXT("x"), X.X); W.Num(TEXT("y"), X.Y); W.Opt(TEXT("z"), X.Z); W.Opt(TEXT("radius_m"), X.RadiusM);
	W.Opt(TEXT("trim_radius_m"), X.TrimRadiusM); W.EnumD(TEXT("kind"), X.Kind, EStreetJunctionKind::Disc);
	TArray<TSharedPtr<FJsonValue>> A;
	for (const FStreetJunctionEnd& En : X.Ends)
	{
		FW WE(En);
		WE.Str(TEXT("spline_id"), En.SplineId); WE.Enum(TEXT("end"), En.End);
		A.Add(ObjVal(WE.Finish()));
	}
	W.ObjList(TEXT("ends"), A, true);
	return W.Finish();
}

void ReadOrigin(const FJsonObject& O, const FString& Path, FStreetOrigin& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("E"), TEXT("N") });
	R.Num(TEXT("E"), X.E, true); R.Num(TEXT("N"), X.N, true);
}

void ReadProfiles(const FJsonObject& O, const FString& Path, FStreetSiteProfiles& X, TArray<FString>& E)
{
	FObj R(O, Path, E, &X, { TEXT("road"), TEXT("edge"), TEXT("hedge") });
	if (const FJsonObject* M = R.Obj(TEXT("road"), true))
	{
		X.Road.Reset();
		for (const auto& KV : M->Values)
		{
			const FString KKey(*KV.Key);
			if (KKey.StartsWith(TEXT("_"))) continue;
			const FString KP = FString::Printf(TEXT("%s.road.%s"), *Path, *KKey);
			if (!KV.Value.IsValid() || KV.Value->Type != EJson::Object) { E.Add(KP + TEXT(": expected object")); continue; }
			ReadRoadProfileImpl(*KV.Value->AsObject(), KP, X.Road.Add(KKey), E);
		}
	}
	if (const FJsonObject* M = R.Obj(TEXT("edge"), true))
	{
		X.Edge.Reset();
		for (const auto& KV : M->Values)
		{
			const FString KKey(*KV.Key);
			if (KKey.StartsWith(TEXT("_"))) continue;
			const FString KP = FString::Printf(TEXT("%s.edge.%s"), *Path, *KKey);
			if (!KV.Value.IsValid() || KV.Value->Type != EJson::Object) { E.Add(KP + TEXT(": expected object")); continue; }
			ReadEdgeProfileImpl(*KV.Value->AsObject(), KP, X.Edge.Add(KKey), E);
		}
	}
	if (const FJsonObject* M = R.Obj(TEXT("hedge"), true))
	{
		X.Hedge.Reset();
		for (const auto& KV : M->Values)
		{
			const FString KKey(*KV.Key);
			if (KKey.StartsWith(TEXT("_"))) continue;
			const FString KP = FString::Printf(TEXT("%s.hedge.%s"), *Path, *KKey);
			if (!KV.Value.IsValid() || KV.Value->Type != EJson::Object) { E.Add(KP + TEXT(": expected object")); continue; }
			ReadHedgeProfileImpl(*KV.Value->AsObject(), KP, X.Hedge.Add(KKey), E);
		}
	}
}
TSharedRef<FJsonObject> WriteProfiles(const FStreetSiteProfiles& X)
{
	FW W(X);
	TSharedRef<FJsonObject> R = MakeShared<FJsonObject>();
	for (const auto& KV : X.Road) R->SetObjectField(KV.Key, WriteRoadProfileImpl(KV.Value));
	TSharedRef<FJsonObject> Ed = MakeShared<FJsonObject>();
	for (const auto& KV : X.Edge) Ed->SetObjectField(KV.Key, WriteEdgeProfileImpl(KV.Value));
	TSharedRef<FJsonObject> H = MakeShared<FJsonObject>();
	for (const auto& KV : X.Hedge) H->SetObjectField(KV.Key, WriteHedgeProfileImpl(KV.Value));
	W.Obj(TEXT("road"), R); W.Obj(TEXT("edge"), Ed); W.Obj(TEXT("hedge"), H);
	return W.Finish();
}

// -- cross checks (io_json._cross_checks) ---------------------------------------------------------------------------

void CrossChecks(const FStreetSiteDoc& D, TArray<FString>& E)
{
	TSet<FString> Seen;
	for (int32 SI = 0; SI < D.Splines.Num(); ++SI)
	{
		const FStreetSplineDef& Sp = D.Splines[SI];
		const FString Where = FString::Printf(TEXT("$.splines[%d] (%s)"), SI, *Sp.Id);
		const FStreetProfileIds& Ids = Sp.ProfileIds;
		if (!Ids.Road.IsEmpty() && !D.Profiles.Road.Contains(Ids.Road)) E.Add(FString::Printf(TEXT("%s.profile_ids.road: '%s' not in profiles.road"), *Where, *Ids.Road));
		if (!Ids.EdgeLeft.IsEmpty() && !D.Profiles.Edge.Contains(Ids.EdgeLeft)) E.Add(FString::Printf(TEXT("%s.profile_ids.edge_left: '%s' not in profiles.edge"), *Where, *Ids.EdgeLeft));
		if (!Ids.EdgeRight.IsEmpty() && !D.Profiles.Edge.Contains(Ids.EdgeRight)) E.Add(FString::Printf(TEXT("%s.profile_ids.edge_right: '%s' not in profiles.edge"), *Where, *Ids.EdgeRight));
		if (!Ids.HedgeLeft.IsEmpty() && !D.Profiles.Hedge.Contains(Ids.HedgeLeft)) E.Add(FString::Printf(TEXT("%s.profile_ids.hedge_left: '%s' not in profiles.hedge"), *Where, *Ids.HedgeLeft));
		if (!Ids.HedgeRight.IsEmpty() && !D.Profiles.Hedge.Contains(Ids.HedgeRight)) E.Add(FString::Printf(TEXT("%s.profile_ids.hedge_right: '%s' not in profiles.hedge"), *Where, *Ids.HedgeRight));
		for (int32 GI = 0; GI < Sp.Segments.Num(); ++GI)
		{
			const FStreetSegment& Seg = Sp.Segments[GI];
			const FString SW = FString::Printf(TEXT("%s.segments[%d]"), *Where, GI);
			if (Seg.S1M.IsSet() && !(Seg.S1M.GetValue() > Seg.S0M)) E.Add(FString::Printf(TEXT("%s: s1_m %s must be > s0_m %s"), *SW, *FStreetscapeJson::FormatNumber(Seg.S1M.GetValue()), *FStreetscapeJson::FormatNumber(Seg.S0M)));
			if (Seg.bHasRoad && !Seg.Road.ProfileId.IsEmpty() && !D.Profiles.Road.Contains(Seg.Road.ProfileId)) E.Add(FString::Printf(TEXT("%s.road.profile_id: '%s' not in profiles.road"), *SW, *Seg.Road.ProfileId));
			if (Seg.bHasEdge && !Seg.Edge.ProfileId.IsEmpty() && !D.Profiles.Edge.Contains(Seg.Edge.ProfileId)) E.Add(FString::Printf(TEXT("%s.edge.profile_id: '%s' not in profiles.edge"), *SW, *Seg.Edge.ProfileId));
			if (Seg.bHasHedge && !Seg.Hedge.ProfileId.IsEmpty() && !D.Profiles.Hedge.Contains(Seg.Hedge.ProfileId)) E.Add(FString::Printf(TEXT("%s.hedge.profile_id: '%s' not in profiles.hedge"), *SW, *Seg.Hedge.ProfileId));
			if (Seg.Side == EStreetSegmentSide::Centre && (Seg.bHasEdge || Seg.bHasHedge)) E.Add(SW + TEXT(": side centre reads only the road block"));
		}
		FString KindProblem;
		if (!FStreetscapeJson::RoadKindsConsistent(Sp, D.Profiles, KindProblem)) E.Add(Where + TEXT(": ") + KindProblem);
		if (const FRoadProfileData* RP = D.Profiles.Road.Find(Ids.Road))
		{
			for (const FString* EidPtr : { &Ids.EdgeLeft, &Ids.EdgeRight })
			{
				if (const FEdgeProfileData* EP = D.Profiles.Edge.Find(*EidPtr))
				{
					if (!(EP->TuckDepthM > RP->SkirtDropM))
						E.Add(FString::Printf(TEXT("%s: edge %s tuck_depth_m %s must exceed road skirt_drop_m %s"), *Where, **EidPtr, *FStreetscapeJson::FormatNumber(EP->TuckDepthM), *FStreetscapeJson::FormatNumber(RP->SkirtDropM)));
				}
			}
		}
		if (Seen.Contains(Sp.Id)) E.Add(FString::Printf(TEXT("$.splines[%d]: duplicate spline id '%s'"), SI, *Sp.Id));
		Seen.Add(Sp.Id);
	}
	for (const auto& KV : D.Profiles.Road)
	{
		for (int32 I = 0; I < KV.Value.Markings.Num(); ++I)
		{
			const FStreetMarking& M = KV.Value.Markings[I];
			if (M.S1M.IsSet() && M.S0M.IsSet() && !(M.S1M.GetValue() > M.S0M.GetValue())) E.Add(FString::Printf(TEXT("$.profiles.road.%s.markings[%d]: s1_m must be > s0_m"), *KV.Key, I));
		}
	}
	for (const auto& KV : D.Profiles.Edge)
	{
		for (int32 I = 0; I < KV.Value.Barriers.Num(); ++I)
		{
			const FStreetBarrier& B = KV.Value.Barriers[I];
			if (B.S1M.IsSet() && !(B.S1M.GetValue() > B.S0M.Get(0.0))) E.Add(FString::Printf(TEXT("$.profiles.edge.%s.barriers[%d]: s1_m must be > s0_m"), *KV.Key, I));
		}
		for (int32 I = 0; I < KV.Value.Embankments.Num(); ++I)
		{
			const FStreetEmbankment& B = KV.Value.Embankments[I];
			if (B.S1M.IsSet() && !(B.S1M.GetValue() > B.S0M.Get(0.0))) E.Add(FString::Printf(TEXT("$.profiles.edge.%s.embankments[%d]: s1_m must be > s0_m"), *KV.Key, I));
		}
	}
	for (const auto& KV : D.Profiles.Hedge)
	{
		for (int32 I = 0; I < KV.Value.Segments.Num(); ++I)
		{
			const FStreetHedgeSegment& H = KV.Value.Segments[I];
			if (H.S1M.IsSet() && !(H.S1M.GetValue() > H.S0M)) E.Add(FString::Printf(TEXT("$.profiles.hedge.%s.segments[%d]: s1_m must be > s0_m"), *KV.Key, I));
		}
	}
}
} // namespace

// =================================================================================================================
// public entry points
// =================================================================================================================

bool FStreetscapeJson::RoadKindsConsistent(const FStreetSplineDef& Spline, const FStreetSiteProfiles& Profiles, FString& OutProblem)
{
	TSet<EStreetRoadKind> Kinds;
	if (const FRoadProfileData* P = Profiles.Road.Find(Spline.ProfileIds.Road)) Kinds.Add(P->Kind);
	for (const FStreetSegment& Seg : Spline.Segments)
	{
		if (Seg.bHasRoad)
		{
			if (const FRoadProfileData* P = Profiles.Road.Find(Seg.Road.ProfileId)) Kinds.Add(P->Kind);
		}
	}
	if (Kinds.Num() > 1)
	{
		OutProblem = FString::Printf(TEXT("spline %s mixes road kinds ['rail', 'road']"), *Spline.Id);
		return false;
	}
	return true;
}

bool FStreetscapeJson::ReadSite(const TSharedRef<FJsonObject>& In, FStreetSiteDoc& Out, TArray<FString>& Problems)
{
	Out = FStreetSiteDoc();
	TArray<FString>& E = Problems;
	FObj R(*In, TEXT("$"), E, &Out, { TEXT("schema_version"), TEXT("site"), TEXT("crs"), TEXT("origin"), TEXT("vertical_datum"), TEXT("frame"), TEXT("generator"), TEXT("materials"), TEXT("profiles"), TEXT("splines"), TEXT("junctions") });
	R.Str(TEXT("schema_version"), Out.SchemaVersion, true, true); R.Str(TEXT("site"), Out.Site, true, true); R.Str(TEXT("crs"), Out.Crs, true, true);
	if (const FJsonObject* S = R.Obj(TEXT("origin"), true)) ReadOrigin(*S, TEXT("$.origin"), Out.Origin, E);
	R.Str(TEXT("vertical_datum"), Out.VerticalDatum, true, true); R.Const(TEXT("frame"), FStreetEnums::FrameConst(), Out.Frame); R.Str(TEXT("generator"), Out.Generator, true, true);
	if (const FJsonObject* M = R.Obj(TEXT("materials"), false))
	{
		for (const auto& KV : M->Values)
		{
			const FString KKey(*KV.Key);
			if (KKey.StartsWith(TEXT("_"))) continue;
			const FString KP = FString::Printf(TEXT("$.materials.%s"), *KKey);
			if (!KV.Value.IsValid() || KV.Value->Type != EJson::Object) { E.Add(KP + TEXT(": expected object")); continue; }
			ReadMaterialHint(*KV.Value->AsObject(), KP, Out.Materials.Add(KKey), E);
		}
	}
	if (const FJsonObject* S = R.Obj(TEXT("profiles"), true)) ReadProfiles(*S, TEXT("$.profiles"), Out.Profiles, E);
	ReadObjList(R, TEXT("splines"), Out.Splines, true, [](const FJsonObject& SO, const FString& SP, FStreetSplineDef& D, TArray<FString>& SE) { ReadSplineDef(SO, SP, D, SE); });
	ReadObjList(R, TEXT("junctions"), Out.Junctions, false, [](const FJsonObject& SO, const FString& SP, FStreetJunction& D, TArray<FString>& SE) { ReadJunction(SO, SP, D, SE); });
	{
		const FRegexPattern Ver(TEXT("^1\\.[0-9]+\\.[0-9]+$"));
		if (!FRegexMatcher(Ver, Out.SchemaVersion).FindNext()) E.Add(FString::Printf(TEXT("$.schema_version: '%s' is not 1.x.y"), *Out.SchemaVersion));
		const FRegexPattern CrsPat(TEXT("^EPSG:[0-9]+$"));
		if (!FRegexMatcher(CrsPat, Out.Crs).FindNext()) E.Add(FString::Printf(TEXT("$.crs: '%s' is not EPSG:<n>"), *Out.Crs));
	}
	if (E.Num() > 0) return false;
	CrossChecks(Out, E);
	return E.Num() == 0;
}

TSharedRef<FJsonObject> FStreetscapeJson::WriteSite(const FStreetSiteDoc& D)
{
	FW W(D);
	W.Str(TEXT("schema_version"), D.SchemaVersion); W.Str(TEXT("site"), D.Site); W.Str(TEXT("crs"), D.Crs);
	{
		FW WO(D.Origin);
		WO.Num(TEXT("E"), D.Origin.E); WO.Num(TEXT("N"), D.Origin.N);
		W.Obj(TEXT("origin"), WO.Finish());
	}
	W.Str(TEXT("vertical_datum"), D.VerticalDatum); W.Str(TEXT("frame"), D.Frame); W.Str(TEXT("generator"), D.Generator);
	if (D.Materials.Num() > 0 || W.Want(TEXT("materials")))
	{
		TSharedRef<FJsonObject> M = MakeShared<FJsonObject>();
		for (const auto& KV : D.Materials) M->SetObjectField(KV.Key, WriteMaterialHint(KV.Value));
		W.Obj(TEXT("materials"), M);
	}
	W.Obj(TEXT("profiles"), WriteProfiles(D.Profiles));
	TArray<TSharedPtr<FJsonValue>> A;
	for (const FStreetSplineDef& S : D.Splines) A.Add(ObjVal(WriteSplineDef(S)));
	W.ObjList(TEXT("splines"), A, true);
	A.Reset();
	for (const FStreetJunction& J : D.Junctions) A.Add(ObjVal(WriteJunction(J)));
	W.ObjList(TEXT("junctions"), A, W.Want(TEXT("junctions")) || A.Num() > 0);
	return W.Finish();
}

TSharedRef<FJsonObject> FStreetscapeJson::WriteSpline(const FStreetSplineDef& Spline) { return WriteSplineDef(Spline); }

bool FStreetscapeJson::ReadSpline(const TSharedRef<FJsonObject>& In, FStreetSplineDef& Out, TArray<FString>& Problems, const FString& Path)
{
	Out = FStreetSplineDef();
	ReadSplineDef(*In, Path, Out, Problems);
	return Problems.Num() == 0;
}

bool FStreetscapeJson::ValidateStructure(const TSharedRef<FJsonObject>& In, TArray<FString>& Problems)
{
	FStreetSiteDoc Doc;
	return ReadSite(In, Doc, Problems);
}

TArray<FString> FStreetscapeJson::ValidateWarnings(const FStreetSiteDoc& D)
{
	TArray<FString> W;
	auto Check = [&W](const FString& Path, FName Name)
	{
		if (Name.IsNone()) return;
		if (!FStreetEnums::MaterialNames().Contains(Name)) W.Add(FString::Printf(TEXT("$.%s: material '%s' is unhinted (not in SCHEMA.md 7)"), *Path, *Name.ToString()));
	};
	for (const auto& KV : D.Profiles.Road)
	{
		const FRoadProfileData& P = KV.Value;
		Check(FString::Printf(TEXT("profiles.road.%s.surface_material"), *KV.Key), P.SurfaceMaterial);
		for (int32 I = 0; I < P.Markings.Num(); ++I) Check(FString::Printf(TEXT("profiles.road.%s.markings[%d].material"), *KV.Key, I), P.Markings[I].Material);
		if (P.bHasRail)
		{
			Check(FString::Printf(TEXT("profiles.road.%s.rail.rail.material"), *KV.Key), P.Rail.Rail.Material);
			Check(FString::Printf(TEXT("profiles.road.%s.rail.sleeper.material"), *KV.Key), P.Rail.Sleeper.Material);
			Check(FString::Printf(TEXT("profiles.road.%s.rail.ballast.material"), *KV.Key), P.Rail.Ballast.Material);
		}
	}
	for (const auto& KV : D.Profiles.Edge)
	{
		const FEdgeProfileData& P = KV.Value;
		Check(FString::Printf(TEXT("profiles.edge.%s.materials.kerb"), *KV.Key), P.Materials.Kerb);
		Check(FString::Printf(TEXT("profiles.edge.%s.materials.pavement"), *KV.Key), P.Materials.Pavement);
		if (P.SplitMaterial.bEnabled)
		{
			Check(FString::Printf(TEXT("profiles.edge.%s.split_material.inner"), *KV.Key), P.SplitMaterial.Inner);
			Check(FString::Printf(TEXT("profiles.edge.%s.split_material.outer"), *KV.Key), P.SplitMaterial.Outer);
		}
		for (int32 I = 0; I < P.Barriers.Num(); ++I)
		{
			Check(FString::Printf(TEXT("profiles.edge.%s.barriers[%d].material"), *KV.Key, I), P.Barriers[I].Material);
			Check(FString::Printf(TEXT("profiles.edge.%s.barriers[%d].coping_material"), *KV.Key, I), P.Barriers[I].CopingMaterial);
			Check(FString::Printf(TEXT("profiles.edge.%s.barriers[%d].post_material"), *KV.Key, I), P.Barriers[I].PostMaterial);
		}
		for (int32 I = 0; I < P.Embankments.Num(); ++I) Check(FString::Printf(TEXT("profiles.edge.%s.embankments[%d].material"), *KV.Key, I), P.Embankments[I].Material);
	}
	for (const auto& KV : D.Profiles.Hedge)
	{
		Check(FString::Printf(TEXT("profiles.hedge.%s.material"), *KV.Key), KV.Value.Material);
		Check(FString::Printf(TEXT("profiles.hedge.%s.foliage.material"), *KV.Key), KV.Value.Foliage.Material);
	}
	for (int32 SI = 0; SI < D.Splines.Num(); ++SI)
	{
		const FStreetSplineDef& Sp = D.Splines[SI];
		for (int32 GI = 0; GI < Sp.Segments.Num(); ++GI)
		{
			const FStreetSegment& Seg = Sp.Segments[GI];
			if (Seg.bHasEdge && Seg.Edge.bHasBarrier)
			{
				Check(FString::Printf(TEXT("splines[%d].segments[%d].edge.barrier.material"), SI, GI), Seg.Edge.Barrier.Material);
				Check(FString::Printf(TEXT("splines[%d].segments[%d].edge.barrier.coping_material"), SI, GI), Seg.Edge.Barrier.CopingMaterial);
				Check(FString::Printf(TEXT("splines[%d].segments[%d].edge.barrier.post_material"), SI, GI), Seg.Edge.Barrier.PostMaterial);
			}
			if (Seg.bHasEdge && Seg.Edge.bHasEmbankment) Check(FString::Printf(TEXT("splines[%d].segments[%d].edge.embankment.material"), SI, GI), Seg.Edge.Embankment.Material);
			if (Seg.bHasRoad)
			{
				for (int32 MI = 0; MI < Seg.Road.Markings.Num(); ++MI) Check(FString::Printf(TEXT("splines[%d].segments[%d].road.markings[%d].material"), SI, GI, MI), Seg.Road.Markings[MI].Material);
				for (int32 MI = 0; MI < Seg.Road.MarkingsAdd.Num(); ++MI) Check(FString::Printf(TEXT("splines[%d].segments[%d].road.markings_add[%d].material"), SI, GI, MI), Seg.Road.MarkingsAdd[MI].Material);
			}
		}
		if (Sp.Source.Layer != EStreetSourceLayer::Authored && !Sp.bHasOverlay) W.Add(FString::Printf(TEXT("$.splines[%d]: overlay missing on a %s spline"), SI, FStreetEnums::ToString(Sp.Source.Layer)));
	}
	for (const auto& KV : D.Profiles.Road)
	{
		if (KV.Value.bHasLaneWidthsM && KV.Value.LaneWidthsM.Num() > 0)
		{
			double Sum = 0; for (double X : KV.Value.LaneWidthsM) Sum += X;
			if (Sum > KV.Value.WidthM + 1e-9) W.Add(FString::Printf(TEXT("$.profiles.road.%s: sum(lane_widths_m) %s > width_m %s"), *KV.Key, *FormatNumber(Sum), *FormatNumber(KV.Value.WidthM)));
		}
	}
	return W;
}

bool FStreetscapeJson::ReadRoadProfile(const TSharedRef<FJsonObject>& In, FRoadProfileData& Out, TArray<FString>& Problems, const FString& Path)
{
	Out = FRoadProfileData();
	ReadRoadProfileImpl(*In, Path, Out, Problems);
	return Problems.Num() == 0;
}
bool FStreetscapeJson::ReadEdgeProfile(const TSharedRef<FJsonObject>& In, FEdgeProfileData& Out, TArray<FString>& Problems, const FString& Path)
{
	Out = FEdgeProfileData();
	ReadEdgeProfileImpl(*In, Path, Out, Problems);
	return Problems.Num() == 0;
}
bool FStreetscapeJson::ReadHedgeProfile(const TSharedRef<FJsonObject>& In, FHedgeProfileData& Out, TArray<FString>& Problems, const FString& Path)
{
	Out = FHedgeProfileData();
	ReadHedgeProfileImpl(*In, Path, Out, Problems);
	return Problems.Num() == 0;
}
TSharedRef<FJsonObject> FStreetscapeJson::WriteRoadProfile(const FRoadProfileData& P) { return WriteRoadProfileImpl(P); }
TSharedRef<FJsonObject> FStreetscapeJson::WriteEdgeProfile(const FEdgeProfileData& P) { return WriteEdgeProfileImpl(P); }
TSharedRef<FJsonObject> FStreetscapeJson::WriteHedgeProfile(const FHedgeProfileData& P) { return WriteHedgeProfileImpl(P); }

bool FStreetscapeJson::ReadProfileFile(const TSharedRef<FJsonObject>& In, FStreetProfileFile& Out, TArray<FString>& Problems)
{
	Out = FStreetProfileFile();
	FObj R(*In, TEXT("$"), Problems, &Out, { TEXT("kind"), TEXT("id"), TEXT("profile") });
	R.Enum(TEXT("kind"), Out.Kind, true);
	R.Id(TEXT("id"), Out.Id, true);
	if (const FJsonObject* P = R.Obj(TEXT("profile"), true))
	{
		switch (Out.Kind)
		{
		case EStreetProfileKind::Road: ReadRoadProfileImpl(*P, TEXT("$.profile"), Out.Road, Problems); break;
		case EStreetProfileKind::Edge: ReadEdgeProfileImpl(*P, TEXT("$.profile"), Out.Edge, Problems); break;
		case EStreetProfileKind::Hedge: ReadHedgeProfileImpl(*P, TEXT("$.profile"), Out.Hedge, Problems); break;
		}
	}
	return Problems.Num() == 0;
}

TSharedRef<FJsonObject> FStreetscapeJson::WriteProfileFile(const FStreetProfileFile& F)
{
	FW W(F);
	W.Enum(TEXT("kind"), F.Kind); W.Str(TEXT("id"), F.Id);
	switch (F.Kind)
	{
	case EStreetProfileKind::Road: W.Obj(TEXT("profile"), WriteRoadProfileImpl(F.Road)); break;
	case EStreetProfileKind::Edge: W.Obj(TEXT("profile"), WriteEdgeProfileImpl(F.Edge)); break;
	case EStreetProfileKind::Hedge: W.Obj(TEXT("profile"), WriteHedgeProfileImpl(F.Hedge)); break;
	}
	return W.Finish();
}

bool FStreetscapeJson::LoadProfileLibrary(const FString& Dir, FStreetSiteProfiles& Out, TArray<FString>& Problems)
{
	TArray<FString> Files;
	IFileManager::Get().FindFiles(Files, *(Dir / TEXT("*.json")), true, false);
	Files.Sort();
	for (const FString& Name : Files)
	{
		const FString Path = Dir / Name;
		TSharedPtr<FJsonObject> Obj;
		FText Err;
		if (!LoadFile(Path, Obj, &Err)) { Problems.Add(Err.ToString()); continue; }
		FStreetProfileFile F;
		TArray<FString> P;
		if (!ReadProfileFile(Obj.ToSharedRef(), F, P))
		{
			for (const FString& S : P) Problems.Add(Name + TEXT(": ") + S);
			continue;
		}
		if (F.Id != FPaths::GetBaseFilename(Name))
		{
			Problems.Add(FString::Printf(TEXT("%s: id '%s' != file name '%s'"), *Path, *F.Id, *FPaths::GetBaseFilename(Name)));
			continue;
		}
		switch (F.Kind)
		{
		case EStreetProfileKind::Road: Out.Road.Add(F.Id, F.Road); break;
		case EStreetProfileKind::Edge: Out.Edge.Add(F.Id, F.Edge); break;
		case EStreetProfileKind::Hedge: Out.Hedge.Add(F.Id, F.Hedge); break;
		}
	}
	return Problems.Num() == 0;
}
