// Shared helpers of the renderer Automation tests (UE_PLAN.md 2.13, phase 3): build a fixture document through the
// spline and all three renderers in one call, and the small JSON edits the numpy tests do with dict assignment
// (tests/test_edge.py doc_with, tests/test_hedge.py hedge_doc).

#pragma once

#include "StreetTestUtil.h"
#include "StreetRenderers.h"
#include "StreetTimelines.h"

namespace StreetTest
{
/** A fixture built exactly as Tools/blender/streetscape/build.build_spline does. */
struct FBuiltStreet
{
	FStreetSiteDoc Doc;
	FStreetSamples Sp;
	FStreetRenderResult Road;
	FStreetRenderResult Edge[2];    // [0] left, [1] right
	FStreetRenderResult Hedge[2];

	const FStreetMeshBuilder& RoadBuf() const { return Road.Buffer; }
	const FStreetMeshBuilder& EdgeBuf(EStreetSide S) const { return Edge[StreetSideIndex(S)].Buffer; }
	const FStreetMeshBuilder& HedgeBuf(EStreetSide S) const { return Hedge[StreetSideIndex(S)].Buffer; }

	int32 InstanceCount(FName Kind) const
	{
		int32 N = 0;
		const FStreetRenderResult* All[5] = { &Road, &Edge[0], &Edge[1], &Hedge[0], &Hedge[1] };
		for (const FStreetRenderResult* R : All)
		{
			for (const FStreetInstance& I : R->Instances) { if (I.Kind == Kind) ++N; }
		}
		return N;
	}
	TArray<FStreetInstance> InstancesOf(FName Kind) const
	{
		TArray<FStreetInstance> Out;
		const FStreetRenderResult* All[5] = { &Road, &Edge[0], &Edge[1], &Hedge[0], &Hedge[1] };
		for (const FStreetRenderResult* R : All)
		{
			for (const FStreetInstance& I : R->Instances) { if (I.Kind == Kind) Out.Add(I); }
		}
		return Out;
	}

	bool Build(FAutomationTestBase& T, const TSharedRef<FJsonObject>& DocObj, const FStreetHeightfield* Terrain)
	{
		TArray<FString> Problems;
		if (!FStreetscapeJson::ReadSite(DocObj, Doc, Problems))
		{
			T.AddError(TEXT("fixture invalid: ") + FString::Join(Problems, TEXT(" | ")));
			return false;
		}
		if (Doc.Splines.Num() == 0) { T.AddError(TEXT("fixture has no spline")); return false; }
		TUniquePtr<FStreetHeightfieldSource> Src;
		if (Terrain)
		{
			Src = MakeUnique<FStreetHeightfieldSource>(*Terrain);
			Src->SetDocumentOrigin(Doc.Origin.E, Doc.Origin.N);
		}
		FString Err;
		if (!FStreetSplineMath::Build(Doc.Splines[0], Doc.Profiles, Src.Get(), Sp, &Err))
		{
			T.AddError(TEXT("build failed: ") + Err);
			return false;
		}
		FStreetRenderBuild::BuildRoad(Sp, Road);
		for (int32 K = 0; K < 2; ++K)
		{
			const EStreetSide Side = K == 0 ? EStreetSide::Left : EStreetSide::Right;
			FStreetRenderBuild::BuildEdge(Sp, Side, Src.Get(), Edge[K]);
			FStreetRenderBuild::BuildHedge(Sp, Side, Hedge[K]);
		}
		return true;
	}
};

/** Fixture(name) as a mutable JSON object (the numpy tests deep-copy the dict before editing it). */
inline TSharedPtr<FJsonObject> FixtureCopy(FAutomationTestBase& T, const FString& Name)
{
	TSharedPtr<FJsonObject> O = Fixture(T, Name);
	if (!O.IsValid()) return nullptr;
	TSharedPtr<FJsonObject> Copy;
	FString Text;
	const TSharedRef<TJsonWriter<>> W = TJsonWriterFactory<>::Create(&Text);
	FJsonSerializer::Serialize(O.ToSharedRef(), W);
	const TSharedRef<TJsonReader<>> R = TJsonReaderFactory<>::Create(Text);
	FJsonSerializer::Deserialize(R, Copy);
	return Copy;
}

/** doc["profiles"]["edge"][id] = the library profile of that id. */
inline void AddLibraryEdgeProfile(FAutomationTestBase& T, const TSharedPtr<FJsonObject>& Doc, const FString& Id)
{
	const TSharedPtr<FJsonObject> P = LibraryProfile(T, Id);
	if (P.IsValid()) Doc->GetObjectField(TEXT("profiles"))->GetObjectField(TEXT("edge"))->SetObjectField(Id, P);
}
inline void AddLibraryHedgeProfile(FAutomationTestBase& T, const TSharedPtr<FJsonObject>& Doc, const FString& Id)
{
	const TSharedPtr<FJsonObject> P = LibraryProfile(T, Id);
	if (P.IsValid()) Doc->GetObjectField(TEXT("profiles"))->GetObjectField(TEXT("hedge"))->SetObjectField(Id, P);
}

inline TSharedPtr<FJsonObject> FirstSpline(const TSharedPtr<FJsonObject>& Doc)
{
	return Doc->GetArrayField(TEXT("splines"))[0]->AsObject();
}

/** One segment object from compact JSON text (the numpy tests write these as dict literals). */
inline TSharedPtr<FJsonValue> SegmentFromText(const FString& Text)
{
	TSharedPtr<FJsonObject> O;
	const TSharedRef<TJsonReader<>> R = TJsonReaderFactory<>::Create(Text);
	FJsonSerializer::Deserialize(R, O);
	return MakeShared<FJsonValueObject>(O);
}

inline void SetSegments(const TSharedPtr<FJsonObject>& Doc, const TArray<FString>& SegmentTexts)
{
	TArray<TSharedPtr<FJsonValue>> Segs;
	for (const FString& S : SegmentTexts) Segs.Add(SegmentFromText(S));
	FirstSpline(Doc)->SetArrayField(TEXT("segments"), Segs);
}

/** Sorted unique s values of a group's vertices (rounded to 1e-9 like the numpy tests). */
inline TArray<double> UniqueRounded(const TArray<double>& In, int32 Decimals = 9)
{
	const double Scale = FMath::Pow(10.0, (double)Decimals);
	TArray<double> Out;
	for (double X : In) Out.AddUnique(FMath::RoundToDouble(X * Scale) / Scale);
	Out.Sort();
	return Out;
}

/** Merged [s0, s1] painted runs of one marking group, from its triangles' station spans (tests/test_road_markings.dash_runs). */
inline TArray<TPair<double, double>> DashRuns(const FStreetMeshBuilder& Buf, FName Group)
{
	const TArray<bool> Mask = Buf.GroupMaskTris(FString(), &Group);
	TArray<TPair<double, double>> Spans;
	for (int32 T = 0; T < Buf.F.Num(); ++T)
	{
		if (!Mask[T]) continue;
		const UE::Geometry::FIndex3i& F = Buf.F[T];
		const double A = FMath::RoundToDouble(FMath::Min3(Buf.VS[F.A], Buf.VS[F.B], Buf.VS[F.C]) * 1e9) / 1e9;
		const double B = FMath::RoundToDouble(FMath::Max3(Buf.VS[F.A], Buf.VS[F.B], Buf.VS[F.C]) * 1e9) / 1e9;
		Spans.AddUnique(TPair<double, double>(A, B));
	}
	Spans.Sort([](const TPair<double, double>& X, const TPair<double, double>& Y) { return X.Key == Y.Key ? X.Value < Y.Value : X.Key < Y.Key; });
	TArray<TPair<double, double>> Runs;
	for (const TPair<double, double>& S : Spans)
	{
		if (Runs.Num() && FMath::Abs(S.Key - Runs.Last().Value) < 1e-9) Runs.Last().Value = S.Value;
		else Runs.Add(S);
	}
	return Runs;
}
}   // namespace StreetTest
