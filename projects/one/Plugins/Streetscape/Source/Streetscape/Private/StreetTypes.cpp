#include "StreetTypes.h"

// ---------------------------------------------------------------------------------------------------------------
// enum tables: one array per enum, index = enumerator value, string = schema value
// ---------------------------------------------------------------------------------------------------------------

namespace
{
template <typename TEnum>
struct TStreetEnumTable
{
	const TCHAR* const* Names;
	int32 Count;
	const TCHAR* ToString(TEnum V) const
	{
		const int32 I = static_cast<int32>(V);
		return (I >= 0 && I < Count) ? Names[I] : TEXT("");
	}
	bool Parse(const FString& S, TEnum& Out) const
	{
		for (int32 I = 0; I < Count; ++I)
		{
			if (S.Equals(Names[I], ESearchCase::CaseSensitive))
			{
				Out = static_cast<TEnum>(I);
				return true;
			}
		}
		return false;
	}
};

const TCHAR* const GRoadKind[] = { TEXT("road"), TEXT("rail") };
const TCHAR* const GCamberKind[] = { TEXT("parabolic"), TEXT("planar"), TEXT("none") };
const TCHAR* const GMarkingAnchor[] = { TEXT("centre"), TEXT("edge_left"), TEXT("edge_right") };
const TCHAR* const GMarkingPattern[] = { TEXT("solid"), TEXT("dashed"), TEXT("double"), TEXT("none") };
const TCHAR* const GLipKind[] = { TEXT("radius"), TEXT("chamfer"), TEXT("none") };
const TCHAR* const GBarrierType[] = { TEXT("brick_wall"), TEXT("stone_wall"), TEXT("concrete_wall"), TEXT("retaining_wall"), TEXT("chain_link"), TEXT("wood_fence"), TEXT("railing"), TEXT("guard_rail"), TEXT("none") };
const TCHAR* const GEmbankmentSide[] = { TEXT("left"), TEXT("right"), TEXT("both"), TEXT("downhill"), TEXT("uphill"), TEXT("auto") };
const TCHAR* const GEmbankmentKind[] = { TEXT("batter"), TEXT("retaining_wall"), TEXT("auto") };
const TCHAR* const GSide[] = { TEXT("left"), TEXT("right") };
const TCHAR* const GSegmentSide[] = { TEXT("left"), TEXT("right"), TEXT("both"), TEXT("centre") };
const TCHAR* const GSideOrBoth[] = { TEXT("left"), TEXT("right"), TEXT("both") };
const TCHAR* const GTopProfile[] = { TEXT("flat"), TEXT("rounded"), TEXT("domed") };
const TCHAR* const GFoliageMode[] = { TEXT("none"), TEXT("cards"), TEXT("instances") };
const TCHAR* const GSleeperMode[] = { TEXT("instances"), TEXT("merged") };
const TCHAR* const GSourceLayer[] = { TEXT("roads"), TEXT("rail"), TEXT("barriers"), TEXT("authored") };
const TCHAR* const GOverlayKind[] = { TEXT("osm_way"), TEXT("step06_smoothed"), TEXT("other") };
const TCHAR* const GContinuation[] = { TEXT("seam"), TEXT("way"), TEXT("gap"), TEXT("none") };
const TCHAR* const GSplineEnd[] = { TEXT("start"), TEXT("end") };
const TCHAR* const GJunctionKind[] = { TEXT("disc"), TEXT("none"), TEXT("connector"), TEXT("bend") };
const TCHAR* const GProfileKind[] = { TEXT("road"), TEXT("edge"), TEXT("hedge") };

#define STREET_ENUM_TABLE(Type, Arr) \
	const TCHAR* FStreetEnums::ToString(Type V) { return TStreetEnumTable<Type>{ Arr, UE_ARRAY_COUNT(Arr) }.ToString(V); } \
	bool FStreetEnums::Parse(const FString& S, Type& Out) { return TStreetEnumTable<Type>{ Arr, UE_ARRAY_COUNT(Arr) }.Parse(S, Out); }
}

STREET_ENUM_TABLE(EStreetRoadKind, GRoadKind)
STREET_ENUM_TABLE(EStreetCamberKind, GCamberKind)
STREET_ENUM_TABLE(EStreetMarkingAnchor, GMarkingAnchor)
STREET_ENUM_TABLE(EStreetMarkingPattern, GMarkingPattern)
STREET_ENUM_TABLE(EStreetLipKind, GLipKind)
STREET_ENUM_TABLE(EStreetBarrierType, GBarrierType)
STREET_ENUM_TABLE(EStreetEmbankmentSide, GEmbankmentSide)
STREET_ENUM_TABLE(EStreetEmbankmentKind, GEmbankmentKind)
STREET_ENUM_TABLE(EStreetSide, GSide)
STREET_ENUM_TABLE(EStreetSegmentSide, GSegmentSide)
STREET_ENUM_TABLE(EStreetSideOrBoth, GSideOrBoth)
STREET_ENUM_TABLE(EStreetTopProfile, GTopProfile)
STREET_ENUM_TABLE(EStreetFoliageMode, GFoliageMode)
STREET_ENUM_TABLE(EStreetSleeperMode, GSleeperMode)
STREET_ENUM_TABLE(EStreetSourceLayer, GSourceLayer)
STREET_ENUM_TABLE(EStreetOverlayKind, GOverlayKind)
STREET_ENUM_TABLE(EStreetContinuation, GContinuation)
STREET_ENUM_TABLE(EStreetSplineEnd, GSplineEnd)
STREET_ENUM_TABLE(EStreetJunctionKind, GJunctionKind)
STREET_ENUM_TABLE(EStreetProfileKind, GProfileKind)

#undef STREET_ENUM_TABLE

const TArray<FName>& FStreetEnums::MaterialNames()
{
	static const TArray<FName> Names = {
		TEXT("tarmac"), TEXT("white_paint"), TEXT("yellow_paint"), TEXT("concrete_kerb"), TEXT("paving_slab"), TEXT("grass"), TEXT("gravel"),
		TEXT("brick_red"), TEXT("coping_concrete"), TEXT("chain_link"), TEXT("post_steel"), TEXT("steel_painted_black"), TEXT("wood_fence"),
		TEXT("privet_leaf"), TEXT("ballast"), TEXT("sleeper_concrete"), TEXT("rail_steel"), TEXT("stone_flint"), TEXT("concrete_wall"),
		TEXT("massing_grey")
	};
	return Names;
}

// ---------------------------------------------------------------------------------------------------------------
// sampling resolution (schema.resolve_sampling)
// ---------------------------------------------------------------------------------------------------------------

FStreetSamplingResolved FStreetSamplingResolved::Defaults(EStreetRoadKind Kind)
{
	FStreetSamplingResolved R;
	if (Kind == EStreetRoadKind::Rail)
	{
		R.StepM = 1.0;
		R.CurvatureGain = 60.0;
		R.SmoothingWindowM = 40.0;
		R.SmoothingPasses = 2;
		R.BankMaxDeg = 6.0;
	}
	return R;
}

void FStreetSamplingResolved::Apply(const FStreetSampling& S)
{
	if (S.StepM.IsSet()) StepM = S.StepM.GetValue();
	if (S.MinStepM.IsSet()) MinStepM = S.MinStepM.GetValue();
	if (S.CurvatureGain.IsSet()) CurvatureGain = S.CurvatureGain.GetValue();
	if (S.SmoothingWindowM.IsSet()) SmoothingWindowM = S.SmoothingWindowM.GetValue();
	if (S.SmoothingPasses.IsSet()) SmoothingPasses = S.SmoothingPasses.GetValue();
	if (S.WidthRampM.IsSet()) WidthRampM = S.WidthRampM.GetValue();
	if (S.BankMaxDeg.IsSet()) BankMaxDeg = S.BankMaxDeg.GetValue();
	if (S.BankProbeMinHalfWidthM.IsSet()) BankProbeMinHalfWidthM = S.BankProbeMinHalfWidthM.GetValue();
	if (S.BankRateMaxDegPerM.IsSet()) BankRateMaxDegPerM = S.BankRateMaxDegPerM.GetValue();
	if (S.PinBlendM.IsSet()) PinBlendM = S.PinBlendM.GetValue();
	if (S.bHasExtraStationsM) ExtraStationsM = S.ExtraStationsM;
}

FStreetSamplingResolved FStreetSamplingResolved::Resolve(EStreetRoadKind Kind, const FStreetSampling* ProfileDefaults, const FStreetSampling* SplineSampling)
{
	FStreetSamplingResolved R = Defaults(Kind);
	if (ProfileDefaults) R.Apply(*ProfileDefaults);
	if (SplineSampling) R.Apply(*SplineSampling);
	return R;
}

// ---------------------------------------------------------------------------------------------------------------

FStreetDropKerb FStreetSplineDropKerb::AsDropKerb() const
{
	FStreetDropKerb D;
	D.SM = SM;
	D.LengthM = LengthM.Get(1.83);
	D.RampM = RampM.Get(0.915);
	D.TargetHeightM = TargetHeightM.Get(0.006);
	return D;
}

TArray<double> FStreetBarrier::EffectiveRails() const
{
	if (bHasRailsM)
	{
		return RailsM;
	}
	if (Type == EStreetBarrierType::GuardRail)
	{
		return { 0.75, 0.55 };
	}
	const double H = HeightM.Get(0.0);
	return { H - 0.02, 0.5 * H, 0.10 };
}
