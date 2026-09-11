// Shared helpers of the Streetscape Automation tests (UE_PLAN.md 2.13).
//
// Fixtures: the synthetic documents of Tools/blender/tests/synthetic.py are rebuilt here the same way (library
// profiles from schema/profiles, road_test_marked from schema/examples/synthetic_straight.json) unless the geometry
// track has written Tools/blender/tests/fixtures/<name>.json, which is then loaded verbatim. Expected numbers come
// from fixtures/expected.json when it exists (keys documented at FExpected) and from SCHEMA.md 9.3 / DESIGN.md 3.7-3.8
// otherwise, so both toolchains assert one set of numbers.

#pragma once

#include "CoreMinimal.h"
#include "Misc/AutomationTest.h"
#include "Misc/Paths.h"
#include "Misc/FileHelper.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "StreetscapeJson.h"
#include "StreetSplineMath.h"
#include "StreetTerrainSource.h"
#include "StreetGeometry.h"
#include "StreetJunctions.h"
#include "StreetRenderers.h"
#include <cmath>

namespace StreetTest
{
inline FString ProjectDir() { return FPaths::ConvertRelativePathToFull(FPaths::ProjectDir()); }
inline FString SchemaDir() { return ProjectDir() / TEXT("schema"); }
inline FString ExamplesDir() { return SchemaDir() / TEXT("examples"); }
inline FString ProfilesDir() { return SchemaDir() / TEXT("profiles"); }
inline FString FixturesDir() { return ProjectDir() / TEXT("Tools/blender/tests/fixtures"); }
inline FString ExpectedPath() { return FixturesDir() / TEXT("expected.json"); }

inline bool LoadJson(FAutomationTestBase& T, const FString& Path, TSharedPtr<FJsonObject>& Out)
{
	FText Err;
	if (!FStreetscapeJson::LoadFile(Path, Out, &Err))
	{
		T.AddError(FString::Printf(TEXT("cannot load %s: %s"), *Path, *Err.ToString()));
		return false;
	}
	return true;
}

inline bool LoadDoc(FAutomationTestBase& T, const FString& Path, FStreetSiteDoc& Out)
{
	TSharedPtr<FJsonObject> Obj;
	if (!LoadJson(T, Path, Obj)) return false;
	TArray<FString> Problems;
	if (!FStreetscapeJson::ReadSite(Obj.ToSharedRef(), Out, Problems))
	{
		T.AddError(FString::Printf(TEXT("%s: %s"), *Path, *FString::Join(Problems, TEXT(" | "))));
		return false;
	}
	return true;
}

/** fixtures/expected.json when present. Keys are looked up as dotted paths, e.g. "straight_100.n_stations". */
struct FExpected
{
	TSharedPtr<FJsonObject> Root;
	bool bPresent = false;
	FExpected()
	{
		FText Err;
		bPresent = FPaths::FileExists(ExpectedPath()) && FStreetscapeJson::LoadFile(ExpectedPath(), Root, &Err);
	}
	TSharedPtr<FJsonValue> Find(const FString& Dotted) const
	{
		if (!bPresent) return nullptr;
		TArray<FString> Parts;
		Dotted.ParseIntoArray(Parts, TEXT("."));
		TSharedPtr<FJsonObject> O = Root;
		for (int32 I = 0; I < Parts.Num(); ++I)
		{
			const TSharedPtr<FJsonValue>* V = O->Values.Find(*Parts[I]);
			if (!V || !V->IsValid()) return nullptr;
			if (I == Parts.Num() - 1) return *V;
			if ((*V)->Type != EJson::Object) return nullptr;
			O = (*V)->AsObject();
		}
		return nullptr;
	}
	bool Has(const FString& Dotted) const { return Find(Dotted).IsValid(); }
	/** A number written as a hex string ("0x688990c0") or a number; the fallback when absent. */
	uint32 Hex(const FString& Dotted, uint32 Fallback) const
	{
		const TSharedPtr<FJsonValue> V = Find(Dotted);
		if (V.IsValid() && V->Type == EJson::Number) return (uint32)V->AsNumber();
		if (V.IsValid() && V->Type == EJson::String) return (uint32)FCString::Strtoui64(*V->AsString(), nullptr, 16);
		return Fallback;
	}
	/** The number at Dotted, or the fallback (SCHEMA.md / DESIGN.md value) when absent. */
	double Num(const FString& Dotted, double Fallback) const
	{
		const TSharedPtr<FJsonValue> V = Find(Dotted);
		return (V.IsValid() && V->Type == EJson::Number) ? V->AsNumber() : Fallback;
	}
};

// -- synthetic terrains (tests/synthetic.py) --------------------------------------------------------------------

inline FStreetHeightfield FlatTerrain(double Z = 10.0, FVector2d Extent = FVector2d(512.0, 512.0))
{
	return FStreetHeightfield::FromFunction([Z](double, double) { return Z; }, Extent, 1.0, 512.0, FVector2d::ZeroVector, FVector2d(0.0, -256.0));
}
inline FStreetHeightfield CrossSlopeTerrain(double Slope = 0.1, FVector2d Extent = FVector2d(512.0, 512.0))
{
	return FStreetHeightfield::FromFunction([Slope](double, double Y) { return Slope * Y; }, Extent, 1.0, 512.0, FVector2d::ZeroVector, FVector2d(0.0, -256.0));
}
/** 2 % grade along x with hash noise of sigma 0.1 on the integer lattice. */
inline FStreetHeightfield GradeNoiseTerrain(FVector2d Extent = FVector2d(512.0, 512.0))
{
	return FStreetHeightfield::FromFunction([](double X, double Y)
	{
		const int64 I = (int64)FMath::RoundToDouble(X) * 7919 + (int64)FMath::RoundToDouble(Y);
		return 0.02 * X + 0.1 * std::sqrt(3.0) * FStreetNoise::UnitNoise((uint32)I, 7);
	}, Extent, 1.0, 512.0, FVector2d::ZeroVector, FVector2d(0.0, -256.0));
}
inline FStreetHeightfield StepTerrain(double StepAtY = 6.0, double Drop = 1.5, FVector2d Extent = FVector2d(512.0, 512.0))
{
	return FStreetHeightfield::FromFunction([StepAtY, Drop](double, double Y) { return Y < StepAtY ? 10.0 : 10.0 - Drop; }, Extent, 1.0, 512.0, FVector2d::ZeroVector, FVector2d(0.0, -256.0));
}

// -- fixture documents (tests/synthetic.py) ---------------------------------------------------------------------

inline double Round6(double V) { return FMath::RoundToDouble(V * 1e6) / 1e6; }

inline TSharedPtr<FJsonObject> LibraryProfile(FAutomationTestBase& T, const FString& Id)
{
	TSharedPtr<FJsonObject> F;
	if (!LoadJson(T, ProfilesDir() / (Id + TEXT(".json")), F)) return nullptr;
	return F->GetObjectField(TEXT("profile"));
}

inline TSharedPtr<FJsonValue> PointVal(double X, double Y, TOptional<double> W = TOptional<double>())
{
	TSharedRef<FJsonObject> P = MakeShared<FJsonObject>();
	P->SetNumberField(TEXT("x"), X);
	P->SetNumberField(TEXT("y"), Y);
	if (W.IsSet()) P->SetNumberField(TEXT("width_m"), W.GetValue());
	return MakeShared<FJsonValueObject>(P);
}

inline TSharedRef<FJsonObject> RoadSampling()
{
	TSharedRef<FJsonObject> S = MakeShared<FJsonObject>();
	S->SetNumberField(TEXT("step_m"), 2.0); S->SetNumberField(TEXT("min_step_m"), 0.25); S->SetNumberField(TEXT("curvature_gain"), 20.0);
	S->SetNumberField(TEXT("smoothing_window_m"), 20.0); S->SetNumberField(TEXT("smoothing_passes"), 1); S->SetNumberField(TEXT("width_ramp_m"), 5.0);
	S->SetNumberField(TEXT("bank_max_deg"), 4.0); S->SetNumberField(TEXT("bank_probe_min_half_width_m"), 1.5); S->SetNumberField(TEXT("pin_blend_m"), 10.0);
	S->SetNumberField(TEXT("bank_rate_max_deg_per_m"), 0.25);
	return S;
}

/** synthetic._doc */
inline TSharedRef<FJsonObject> MakeDoc(FAutomationTestBase& T, const FString& Site, const FString& SplineId, const TArray<TSharedPtr<FJsonValue>>& Points,
	TSharedRef<FJsonObject> RoadProfiles, TSharedRef<FJsonObject> EdgeProfiles, TSharedRef<FJsonObject> ProfileIds, bool bRoadSampling,
	TSharedPtr<FJsonObject> Source = nullptr, TArray<TSharedPtr<FJsonValue>>* OverlayPts = nullptr, const FString& OverlayOsmId = FString())
{
	TSharedPtr<FJsonObject> Straight;
	LoadJson(T, ExamplesDir() / TEXT("synthetic_straight.json"), Straight);
	TSharedRef<FJsonObject> D = MakeShared<FJsonObject>();
	D->SetStringField(TEXT("schema_version"), TEXT("1.0.0"));
	D->SetStringField(TEXT("site"), Site);
	D->SetStringField(TEXT("crs"), TEXT("EPSG:27700"));
	TSharedRef<FJsonObject> Or = MakeShared<FJsonObject>();
	Or->SetNumberField(TEXT("E"), 0); Or->SetNumberField(TEXT("N"), 0);
	D->SetObjectField(TEXT("origin"), Or);
	D->SetStringField(TEXT("vertical_datum"), TEXT("ODN"));
	D->SetStringField(TEXT("frame"), FStreetEnums::FrameConst());
	D->SetStringField(TEXT("generator"), TEXT("hand-authored (Tools/blender/tests/synthetic.py)"));
	if (Straight.IsValid()) D->SetObjectField(TEXT("materials"), Straight->GetObjectField(TEXT("materials")));
	TSharedRef<FJsonObject> Profiles = MakeShared<FJsonObject>();
	Profiles->SetObjectField(TEXT("road"), RoadProfiles);
	Profiles->SetObjectField(TEXT("edge"), EdgeProfiles);
	Profiles->SetObjectField(TEXT("hedge"), MakeShared<FJsonObject>());
	D->SetObjectField(TEXT("profiles"), Profiles);
	TSharedRef<FJsonObject> Sp = MakeShared<FJsonObject>();
	Sp->SetStringField(TEXT("id"), SplineId);
	if (Source.IsValid()) Sp->SetObjectField(TEXT("source"), Source);
	else
	{
		TSharedRef<FJsonObject> Src = MakeShared<FJsonObject>();
		Src->SetStringField(TEXT("layer"), TEXT("authored"));
		Src->SetField(TEXT("osm_id"), MakeShared<FJsonValueNull>());
		Src->SetStringField(TEXT("name"), SplineId);
		Src->SetField(TEXT("cls"), MakeShared<FJsonValueNull>());
		Sp->SetObjectField(TEXT("source"), Src);
	}
	Sp->SetObjectField(TEXT("profile_ids"), ProfileIds);
	Sp->SetArrayField(TEXT("points"), Points);
	Sp->SetArrayField(TEXT("segments"), {});
	Sp->SetArrayField(TEXT("drop_kerbs"), {});
	Sp->SetField(TEXT("junction_start"), MakeShared<FJsonValueNull>());
	Sp->SetField(TEXT("junction_end"), MakeShared<FJsonValueNull>());
	if (bRoadSampling) Sp->SetObjectField(TEXT("sampling"), RoadSampling());
	if (OverlayPts)
	{
		TSharedRef<FJsonObject> Ov = MakeShared<FJsonObject>();
		Ov->SetStringField(TEXT("kind"), TEXT("other"));
		Ov->SetArrayField(TEXT("pts"), *OverlayPts);
		if (OverlayOsmId.IsEmpty()) Ov->SetField(TEXT("osm_id"), MakeShared<FJsonValueNull>()); else Ov->SetStringField(TEXT("osm_id"), OverlayOsmId);
		Sp->SetObjectField(TEXT("overlay"), Ov);
	}
	D->SetArrayField(TEXT("splines"), { MakeShared<FJsonValueObject>(Sp) });
	D->SetArrayField(TEXT("junctions"), {});
	return D;
}

inline TSharedRef<FJsonObject> ProfileIdsObj(const FString& Road, const FString& Edge)
{
	TSharedRef<FJsonObject> P = MakeShared<FJsonObject>();
	P->SetStringField(TEXT("road"), Road);
	if (Edge.IsEmpty()) { P->SetField(TEXT("edge_left"), MakeShared<FJsonValueNull>()); P->SetField(TEXT("edge_right"), MakeShared<FJsonValueNull>()); }
	else { P->SetStringField(TEXT("edge_left"), Edge); P->SetStringField(TEXT("edge_right"), Edge); }
	P->SetField(TEXT("hedge_left"), MakeShared<FJsonValueNull>());
	P->SetField(TEXT("hedge_right"), MakeShared<FJsonValueNull>());
	return P;
}

inline TSharedPtr<FJsonValue> XYVal(double X, double Y)
{
	TArray<TSharedPtr<FJsonValue>> A;
	A.Add(MakeShared<FJsonValueNumber>(X)); A.Add(MakeShared<FJsonValueNumber>(Y));
	return MakeShared<FJsonValueArray>(A);
}

/** synthetic.load_fixture: fixtures/<name>.json when the geometry track wrote it, else the builder. */
inline TSharedPtr<FJsonObject> Fixture(FAutomationTestBase& T, const FString& Name)
{
	const FString Path = FixturesDir() / (Name + TEXT(".json"));
	if (FPaths::FileExists(Path))
	{
		TSharedPtr<FJsonObject> O;
		if (LoadJson(T, Path, O)) return O;
	}
	if (Name == TEXT("straight_100"))
	{
		TSharedPtr<FJsonObject> O;
		LoadJson(T, ExamplesDir() / TEXT("synthetic_straight.json"), O);
		return O;
	}
	TSharedPtr<FJsonObject> Straight;
	if (!LoadJson(T, ExamplesDir() / TEXT("synthetic_straight.json"), Straight)) return nullptr;
	TSharedRef<FJsonObject> RoadMarked = MakeShared<FJsonObject>();
	RoadMarked->SetObjectField(TEXT("road_test_marked"), Straight->GetObjectField(TEXT("profiles"))->GetObjectField(TEXT("road"))->GetObjectField(TEXT("road_test_marked")));
	TSharedRef<FJsonObject> EdgeKerb = MakeShared<FJsonObject>();
	if (Name != TEXT("rail_R300_600")) EdgeKerb->SetObjectField(TEXT("edge_uk_kerb"), LibraryProfile(T, TEXT("edge_uk_kerb")));
	TArray<TSharedPtr<FJsonValue>> Pts, Ov;
	if (Name == TEXT("sine_5_50"))
	{
		for (int32 X = 0; X <= 100; X += 5)
		{
			const double Y = Round6(5.0 * std::sin(2.0 * UE_DOUBLE_PI * (double)X / 50.0));
			Pts.Add(PointVal((double)X, Y, 6.0));
			Ov.Add(XYVal((double)X, Y));
		}
		return MakeDoc(T, TEXT("synthetic_sine"), TEXT("authored:sine_5_50"), Pts, RoadMarked, EdgeKerb, ProfileIdsObj(TEXT("road_test_marked"), TEXT("edge_uk_kerb")), true, nullptr, &Ov);
	}
	if (Name == TEXT("curve_R20_200"))
	{
		Pts.Add(PointVal(0.0, 0.0, 6.0)); Ov.Add(XYVal(0.0, 0.0));
		Pts.Add(PointVal(60.0, 0.0, 6.0)); Ov.Add(XYVal(60.0, 0.0));
		const double R = 20.0;
		for (int32 K = 1; K <= 8; ++K)
		{
			const double Th = 90.0 * K / 8 * (UE_DOUBLE_PI / 180.0);
			const double X = Round6(60.0 + R * std::sin(Th)), Y = Round6(R - R * std::cos(Th));
			Pts.Add(PointVal(X, Y, 6.0)); Ov.Add(XYVal(X, Y));
		}
		const double Arc = UE_DOUBLE_PI / 2 * R;
		const double Yend = Round6(20.0 + (200.0 - 60.0 - Arc));
		Pts.Add(PointVal(80.0, Yend, 6.0)); Ov.Add(XYVal(80.0, Yend));
		return MakeDoc(T, TEXT("synthetic_curve"), TEXT("authored:curve_R20_200"), Pts, RoadMarked, EdgeKerb, ProfileIdsObj(TEXT("road_test_marked"), TEXT("edge_uk_kerb")), true, nullptr, &Ov);
	}
	if (Name == TEXT("rail_R300_600"))
	{
		const double X0 = 100.0, Y0 = 100.0;
		for (double X : { 0.0, 50.0, 100.0, 150.0, 200.0 }) { Pts.Add(PointVal(X0 + X, Y0)); Ov.Add(XYVal(X0 + X, Y0)); }
		const double R = 300.0, ArcLen = 200.0;
		const int32 NArc = 10;
		for (int32 K = 1; K <= NArc; ++K)
		{
			const double Th = (ArcLen / R) * K / NArc;
			const double X = Round6(X0 + 200.0 + R * std::sin(Th)), Y = Round6(Y0 + R - R * std::cos(Th));
			Pts.Add(PointVal(X, Y)); Ov.Add(XYVal(X, Y));
		}
		const double ThEnd = ArcLen / R;
		const double Ex = X0 + 200.0 + R * std::sin(ThEnd), Ey = Y0 + R - R * std::cos(ThEnd);
		const double Tx = std::cos(ThEnd), Ty = std::sin(ThEnd);
		for (double Dd : { 50.0, 100.0, 150.0, 200.0 })
		{
			const double X = Round6(Ex + Tx * Dd), Y = Round6(Ey + Ty * Dd);
			Pts.Add(PointVal(X, Y)); Ov.Add(XYVal(X, Y));
		}
		TSharedRef<FJsonObject> RailProf = MakeShared<FJsonObject>();
		RailProf->SetObjectField(TEXT("rail_standard"), LibraryProfile(T, TEXT("rail_standard")));
		TSharedRef<FJsonObject> Src = MakeShared<FJsonObject>();
		Src->SetStringField(TEXT("layer"), TEXT("rail")); Src->SetStringField(TEXT("osm_id"), TEXT("0")); Src->SetStringField(TEXT("name"), TEXT("rail_R300_600")); Src->SetStringField(TEXT("cls"), TEXT("rail"));
		TSharedRef<FJsonObject> Tags = MakeShared<FJsonObject>();
		Tags->SetStringField(TEXT("gauge"), TEXT("1435")); Tags->SetStringField(TEXT("electrified"), TEXT("rail"));
		Src->SetObjectField(TEXT("tags"), Tags);
		return MakeDoc(T, TEXT("synthetic_rail"), TEXT("authored:rail_R300_600"), Pts, RailProf, MakeShared<FJsonObject>(), ProfileIdsObj(TEXT("rail_standard"), FString()), false, Src, &Ov, TEXT("0"));
	}
	T.AddError(TEXT("unknown fixture ") + Name);
	return nullptr;
}

inline FStreetHeightfield TerrainFor(const FString& Name)
{
	return FlatTerrain(10.0, Name == TEXT("rail_R300_600") ? FVector2d(1024.0, 1024.0) : FVector2d(512.0, 512.0));
}

/** Build the first spline of a document on a terrain. */
inline bool BuildDoc(FAutomationTestBase& T, const TSharedRef<FJsonObject>& DocObj, const FStreetHeightfield* Terrain, FStreetSiteDoc& Doc, FStreetSamples& Out)
{
	TArray<FString> Problems;
	if (!FStreetscapeJson::ReadSite(DocObj, Doc, Problems))
	{
		T.AddError(TEXT("fixture invalid: ") + FString::Join(Problems, TEXT(" | ")));
		return false;
	}
	if (Doc.Splines.Num() == 0) { T.AddError(TEXT("fixture has no spline")); return false; }
	FString Err;
	TUniquePtr<FStreetHeightfieldSource> Src;
	if (Terrain)
	{
		Src = MakeUnique<FStreetHeightfieldSource>(*Terrain);
		Src->SetDocumentOrigin(Doc.Origin.E, Doc.Origin.N);
	}
	if (!FStreetSplineMath::Build(Doc.Splines[0], Doc.Profiles, Src.Get(), Out, &Err))
	{
		T.AddError(TEXT("build failed: ") + Err);
		return false;
	}
	return true;
}

inline bool BuildFixture(FAutomationTestBase& T, const FString& Name, const FStreetHeightfield* Terrain, FStreetSiteDoc& Doc, FStreetSamples& Out)
{
	TSharedPtr<FJsonObject> O = Fixture(T, Name);
	if (!O.IsValid()) return false;
	return BuildDoc(T, O.ToSharedRef(), Terrain, Doc, Out);
}

inline FString Fmt(double V) { return FStreetscapeJson::FormatNumber(V); }

// -- junction fixtures (tests/synthetic.py "junction fixtures", SCHEMA.md 4.18) ----------------------------------
//
// Six shapes, each of which breaks a different naive implementation: the symmetric crossroads (the control), a T (an
// odd arm count and two collinear arms whose corner is a straight kerb), a five-arm (more arms than a quad patch could
// hold), a 30/150 skew (where a notch appears if the trim ignores width), the crossroads on a 6 % grade (where a flat
// disc would float or bury), and a 12 m trunk crossing 4 m lanes (where the wide arm must be pushed back further).
//
// Every arm is a STRAIGHT spline running OUT of the node, so End == Start for all of them and the trim distance along
// the spline is exactly the trim radius - which is what makes the assertions exact rather than approximate.

inline const FVector2d& JunctionNode() { static const FVector2d N(200.0, 100.0); return N; }

/** synthetic.junction_doc */
inline TSharedPtr<FJsonObject> JunctionDoc(FAutomationTestBase& T, const FString& Name, const TArray<double>& BearingsDeg,
	const TArray<double>& Widths, double Length = 60.0, double RadiusM = 4.0)
{
	TSharedPtr<FJsonObject> Straight;
	if (!LoadJson(T, ExamplesDir() / TEXT("synthetic_straight.json"), Straight)) return nullptr;
	TSharedPtr<FJsonObject> EdgeProf = LibraryProfile(T, TEXT("edge_uk_kerb"));
	if (!EdgeProf.IsValid()) return nullptr;
	TSharedRef<FJsonObject> D = MakeShared<FJsonObject>();
	D->SetStringField(TEXT("schema_version"), TEXT("1.0.0"));
	D->SetStringField(TEXT("site"), Name);
	D->SetStringField(TEXT("crs"), TEXT("EPSG:27700"));
	TSharedRef<FJsonObject> Or = MakeShared<FJsonObject>();
	Or->SetNumberField(TEXT("E"), 0); Or->SetNumberField(TEXT("N"), 0);
	D->SetObjectField(TEXT("origin"), Or);
	D->SetStringField(TEXT("vertical_datum"), TEXT("ODN"));
	D->SetStringField(TEXT("frame"), FStreetEnums::FrameConst());
	D->SetStringField(TEXT("generator"), TEXT("hand-authored (Tools/blender/tests/synthetic.py)"));
	D->SetObjectField(TEXT("materials"), Straight->GetObjectField(TEXT("materials")));
	TSharedRef<FJsonObject> RoadProfiles = MakeShared<FJsonObject>();
	RoadProfiles->SetObjectField(TEXT("road_test_marked"), Straight->GetObjectField(TEXT("profiles"))->GetObjectField(TEXT("road"))->GetObjectField(TEXT("road_test_marked")));
	TSharedRef<FJsonObject> EdgeProfiles = MakeShared<FJsonObject>();
	EdgeProfiles->SetObjectField(TEXT("edge_uk_kerb"), EdgeProf);
	TSharedRef<FJsonObject> Profiles = MakeShared<FJsonObject>();
	Profiles->SetObjectField(TEXT("road"), RoadProfiles);
	Profiles->SetObjectField(TEXT("edge"), EdgeProfiles);
	Profiles->SetObjectField(TEXT("hedge"), MakeShared<FJsonObject>());
	D->SetObjectField(TEXT("profiles"), Profiles);

	const FVector2d Node = JunctionNode();
	TArray<TSharedPtr<FJsonValue>> Splines, Ends;
	for (int32 K = 0; K < BearingsDeg.Num(); ++K)
	{
		const double Th = BearingsDeg[K] * (UE_DOUBLE_PI / 180.0);
		const double W = Widths.IsValidIndex(K) ? Widths[K] : 6.0;
		const FString Sid = FString::Printf(TEXT("authored:arm%d"), K);
		TArray<TSharedPtr<FJsonValue>> Pts, Ov;
		const double Ts[3] = { 0.0, Length * 0.5, Length };
		for (int32 Q = 0; Q < 3; ++Q)
		{
			const double X = Round6(Node.X + std::cos(Th) * Ts[Q]);
			const double Y = Round6(Node.Y + std::sin(Th) * Ts[Q]);
			Pts.Add(PointVal(X, Y, W));
			Ov.Add(XYVal(X, Y));
		}
		TSharedRef<FJsonObject> Sp = MakeShared<FJsonObject>();
		Sp->SetStringField(TEXT("id"), Sid);
		TSharedRef<FJsonObject> Src = MakeShared<FJsonObject>();
		Src->SetStringField(TEXT("layer"), TEXT("authored"));
		Src->SetField(TEXT("osm_id"), MakeShared<FJsonValueNull>());
		Src->SetStringField(TEXT("name"), Sid);
		Src->SetField(TEXT("cls"), MakeShared<FJsonValueNull>());
		Sp->SetObjectField(TEXT("source"), Src);
		Sp->SetObjectField(TEXT("profile_ids"), ProfileIdsObj(TEXT("road_test_marked"), TEXT("edge_uk_kerb")));
		Sp->SetArrayField(TEXT("points"), Pts);
		Sp->SetObjectField(TEXT("sampling"), RoadSampling());
		Sp->SetArrayField(TEXT("segments"), {});
		Sp->SetArrayField(TEXT("drop_kerbs"), {});
		Sp->SetStringField(TEXT("junction_start"), TEXT("j0"));
		Sp->SetField(TEXT("junction_end"), MakeShared<FJsonValueNull>());
		TSharedRef<FJsonObject> Ovl = MakeShared<FJsonObject>();
		Ovl->SetStringField(TEXT("kind"), TEXT("other"));
		Ovl->SetArrayField(TEXT("pts"), Ov);
		Ovl->SetField(TEXT("osm_id"), MakeShared<FJsonValueNull>());
		Sp->SetObjectField(TEXT("overlay"), Ovl);
		Splines.Add(MakeShared<FJsonValueObject>(Sp));
		TSharedRef<FJsonObject> En = MakeShared<FJsonObject>();
		En->SetStringField(TEXT("spline_id"), Sid);
		En->SetStringField(TEXT("end"), TEXT("start"));
		Ends.Add(MakeShared<FJsonValueObject>(En));
	}
	D->SetArrayField(TEXT("splines"), Splines);
	TSharedRef<FJsonObject> J = MakeShared<FJsonObject>();
	J->SetStringField(TEXT("id"), TEXT("j0"));
	J->SetNumberField(TEXT("x"), Node.X);
	J->SetNumberField(TEXT("y"), Node.Y);
	J->SetField(TEXT("z"), MakeShared<FJsonValueNull>());
	J->SetNumberField(TEXT("radius_m"), RadiusM);
	J->SetStringField(TEXT("kind"), TEXT("disc"));
	J->SetArrayField(TEXT("ends"), Ends);
	D->SetArrayField(TEXT("junctions"), { MakeShared<FJsonValueObject>(J) });
	return D;
}

/** synthetic.JUNCTION_BUILDERS - the six names, in the order fixtures/expected.json lists them. */
inline const TArray<FString>& JunctionFixtureNames()
{
	static const TArray<FString> Names = { TEXT("junction_crossroads"), TEXT("junction_tee"), TEXT("junction_five_arm"),
		TEXT("junction_skew"), TEXT("junction_slope"), TEXT("junction_widths") };
	return Names;
}

inline TSharedPtr<FJsonObject> JunctionFixture(FAutomationTestBase& T, const FString& Name)
{
	const FString Path = FixturesDir() / (Name + TEXT(".json"));
	if (FPaths::FileExists(Path))
	{
		TSharedPtr<FJsonObject> O;
		if (LoadJson(T, Path, O)) return O;
	}
	if (Name == TEXT("junction_crossroads")) return JunctionDoc(T, Name, { 0, 90, 180, 270 }, { 6, 6, 6, 6 });
	if (Name == TEXT("junction_tee")) return JunctionDoc(T, Name, { 0, 90, 180 }, { 6, 6, 6 });
	if (Name == TEXT("junction_five_arm")) return JunctionDoc(T, Name, { 0, 72, 144, 216, 288 }, { 6, 6, 6, 6, 6 });
	if (Name == TEXT("junction_skew")) return JunctionDoc(T, Name, { 0, 30, 180, 210 }, { 6, 6, 6, 6 });
	if (Name == TEXT("junction_slope")) return JunctionDoc(T, Name, { 0, 90, 180, 270 }, { 6, 6, 6, 6 });
	if (Name == TEXT("junction_widths")) return JunctionDoc(T, Name, { 0, 90, 180, 270 }, { 12, 4, 12, 6 });
	T.AddError(TEXT("unknown junction fixture ") + Name);
	return nullptr;
}

/** synthetic.junction_terrain_for: the slope fixture stands on a 6 % east / 3 % north grade, the rest on flat 10 m. */
inline FStreetHeightfield JunctionTerrainFor(const FString& Name)
{
	if (Name == TEXT("junction_slope"))
	{
		return FStreetHeightfield::FromFunction([](double X, double Y) { return 10.0 + 0.06 * (X - 200.0) + 0.03 * (Y - 100.0); },
			FVector2d(512.0, 512.0), 1.0, 512.0, FVector2d::ZeroVector, FVector2d(0.0, -256.0));
	}
	return FlatTerrain(10.0);
}

/** One spline's five buffers, as build.BuildResult.buffers() keys them. */
struct FJunctionSplineBuild
{
	FStreetRenderResult Road, EdgeL, EdgeR, HedgeL, HedgeR;
};

/**
 * build.build_all for one junction document: solve the plan first (in plan geometry only), build every spline exactly
 * once with its trim already known, then merge each junction's patch into its OWNING spline's ROAD buffer and its
 * corners into that spline's LEFT EDGE buffer - no fourth renderer, no fourth buffer, no new material.
 */
struct FJunctionSiteBuild
{
	FStreetJunctionPlan Plan;
	TMap<FString, FStreetSamples> Samples;
	TMap<FString, const FStreetSamples*> SamplePtrs;
	TMap<FString, FJunctionSplineBuild> Builds;
	TMap<FString, FStreetJunctionInfo> Junctions;   // by junction id
	TMap<FString, FString> Owner;                   // junction id -> owning spline id

	int32 TotalVerts() const
	{
		int32 N = 0;
		for (const TPair<FString, FJunctionSplineBuild>& KV : Builds)
		{
			for (const FStreetRenderResult* B : { &KV.Value.Road, &KV.Value.EdgeL, &KV.Value.EdgeR, &KV.Value.HedgeL, &KV.Value.HedgeR }) N += B->Buffer.V.Num();
		}
		return N;
	}
	int32 TotalTris() const
	{
		int32 N = 0;
		for (const TPair<FString, FJunctionSplineBuild>& KV : Builds)
		{
			for (const FStreetRenderResult* B : { &KV.Value.Road, &KV.Value.EdgeL, &KV.Value.EdgeR, &KV.Value.HedgeL, &KV.Value.HedgeR }) N += B->Buffer.F.Num();
		}
		return N;
	}
};

inline bool BuildJunctionSite(FAutomationTestBase& T, const FString& Name, FStreetSiteDoc& Doc, FJunctionSiteBuild& Out)
{
	TSharedPtr<FJsonObject> O = JunctionFixture(T, Name);
	if (!O.IsValid()) return false;
	TArray<FString> Problems;
	if (!FStreetscapeJson::ReadSite(O.ToSharedRef(), Doc, Problems))
	{
		T.AddError(Name + TEXT(": ") + FString::Join(Problems, TEXT(" | ")));
		return false;
	}
	const FStreetHeightfield Field = JunctionTerrainFor(Name);
	FStreetHeightfieldSource Src(Field);
	Src.SetDocumentOrigin(Doc.Origin.E, Doc.Origin.N);
	if (!Out.Plan.Build(Doc)) { T.AddError(Out.Plan.Error); return false; }
	for (const FStreetSplineDef& Def : Doc.Splines)
	{
		double Trim[2] = { 0.0, 0.0 };
		Out.Plan.TrimFor(Def.Id, Trim);
		FStreetSamples Sp;
		FString Err;
		if (!FStreetSplineMath::Build(Def, Doc.Profiles, &Src, Sp, &Err, Trim, Out.Plan.InteriorBendsFor(Def.Id)))
		{
			T.AddError(Name + TEXT(": build ") + Def.Id + TEXT(": ") + Err);
			return false;
		}
		Out.Samples.Add(Def.Id, MoveTemp(Sp));
	}
	for (TPair<FString, FStreetSamples>& KV : Out.Samples) Out.SamplePtrs.Add(KV.Key, &KV.Value);
	for (const FStreetSplineDef& Def : Doc.Splines)
	{
		FJunctionSplineBuild B;
		const FStreetSamples& Sp = Out.Samples[Def.Id];
		FStreetRenderBuild::BuildRoad(Sp, B.Road);
		FStreetRenderBuild::BuildEdge(Sp, EStreetSide::Left, &Src, B.EdgeL);
		FStreetRenderBuild::BuildEdge(Sp, EStreetSide::Right, &Src, B.EdgeR);
		FStreetRenderBuild::BuildHedge(Sp, EStreetSide::Left, B.HedgeL);
		FStreetRenderBuild::BuildHedge(Sp, EStreetSide::Right, B.HedgeR);
		Out.Builds.Add(Def.Id, MoveTemp(B));
	}
	for (const FString& Jid : Out.Plan.BuiltJunctionIds())
	{
		const FString OwnerId = Out.Plan.Owner(Jid);
		FJunctionSplineBuild* Ob = Out.Builds.Find(OwnerId);
		if (!Ob) continue;
		const FStreetJunctionSpec Spec = Out.Plan.SpecFor(Jid);
		FStreetJunctionInfo Info = FStreetRenderBuild::BuildJunctionPatch(Spec, Out.SamplePtrs, Ob->Road.Buffer);
		const FStreetJunctionInfo Corner = FStreetRenderBuild::BuildJunctionCorners(Spec, Out.SamplePtrs, Ob->EdgeL.Buffer);
		Info.Corners = Corner.Corners;
		Info.CornersSkippedNoKerb = Corner.CornersSkippedNoKerb;
		Info.CornersSkippedIncompatible = Corner.CornersSkippedIncompatible;
		Info.CornerVerts = Corner.CornerVerts;
		Info.CornerTris = Corner.CornerTris;
		Out.Junctions.Add(Jid, Info);
		Out.Owner.Add(Jid, OwnerId);
	}
	return true;
}
}
