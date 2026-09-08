// Streetscape.Noise.KnownAnswer (UE_PLAN.md 2.13; DESIGN.md 3.8; SCHEMA.md 9.3): the integer hash is portable bit for bit.

#include "StreetTestUtil.h"

using namespace StreetTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetNoiseKnownAnswerTest, "Streetscape.Noise.KnownAnswer", EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetNoiseKnownAnswerTest::RunTest(const FString& Parameters)
{
	const FExpected X;
	TestEqual(TEXT("lowbias32(0) = 0"), (int64)FStreetNoise::LowBias32(0u), (int64)0);
	TestEqual(TEXT("lowbias32(1) = 0x688990c0"), (int64)FStreetNoise::LowBias32(1u), (int64)X.Hex(TEXT("noise.lowbias32.1"), 0x688990c0u));
	TestEqual(TEXT("lowbias32(2) = 0xd1132181"), (int64)FStreetNoise::LowBias32(2u), (int64)X.Hex(TEXT("noise.lowbias32.2"), 0xd1132181u));
	TestEqual(TEXT("lowbias32(0xdeadbeef) = 0xe628c683"), (int64)FStreetNoise::LowBias32(0xdeadbeefu), (int64)X.Hex(TEXT("noise.lowbias32.0xdeadbeef"), 0xe628c683u));
	const double Expected[5] = { -0.33847302, 0.94551079, -0.62749659, 0.96820159, 0.64059920 };
	for (uint32 I = 0; I < 5; ++I)
	{
		const double V = FStreetNoise::UnitNoise(I, 7);
		double Exp = Expected[I];
		const TSharedPtr<FJsonValue> Arr = X.Find(TEXT("noise.unit_noise_0_4_seed7"));
		if (Arr.IsValid() && Arr->Type == EJson::Array && Arr->AsArray().IsValidIndex(I)) Exp = Arr->AsArray()[I]->AsNumber();
		TestEqual(*FString::Printf(TEXT("unit_noise(%u, 7) = %.8f"), I, Exp), V, Exp, X.Num(TEXT("noise.tol"), 1e-8));
	}
	// full-precision values measured with the numpy prototype (env python, 2026-09-08)
	TestEqual(TEXT("unit_noise(0, 7) full precision"), FStreetNoise::UnitNoise(0, 7), -0.33847302198410034, 1e-15);
	TestEqual(TEXT("unit_noise(4, 7) full precision"), FStreetNoise::UnitNoise(4, 7), 0.6405991991050541, 1e-15);
	TestEqual(TEXT("value_noise3((0.5, 0.5, 0.5), 1)"), FStreetNoise::ValueNoise3(FVector3d(0.5, 0.5, 0.5), 1), -0.16338865226134658, 1e-14);
	TestEqual(TEXT("fbm3((0.3, 0.7, 1.9), 1)"), FStreetNoise::Fbm3(FVector3d(0.3, 0.7, 1.9), 1), -0.11853411804390478, 1e-14);
	TestEqual(TEXT("fbm3((12.25, -3.5, 0.125), 5) (negative lattice coordinates wrap like numpy uint32)"), FStreetNoise::Fbm3(FVector3d(12.25, -3.5, 0.125), 5), -0.12694481121687015, 1e-14);
	// range and lattice continuity
	double Lo = 1, Hi = -1;
	for (int32 I = 0; I < 4000; ++I)
	{
		const FVector3d P(FStreetNoise::UnitNoise01((uint32)I, 11) * 40.0 - 20.0, FStreetNoise::UnitNoise01((uint32)I, 12) * 40.0 - 20.0, FStreetNoise::UnitNoise01((uint32)I, 13) * 40.0 - 20.0);
		const double V = FStreetNoise::Fbm3(P, 3);
		Lo = FMath::Min(Lo, V); Hi = FMath::Max(Hi, V);
	}
	TestTrue(FString::Printf(TEXT("fbm3 in [-1, 1] (got [%.3f, %.3f])"), Lo, Hi), Lo >= -1.0 && Hi <= 1.0);
	TestEqual(TEXT("value_noise3 at a lattice point equals the lattice value"), FStreetNoise::ValueNoise3(FVector3d(3.0, -2.0, 5.0), 9), FStreetNoise::Lattice(3, -2, 5, 9), 1e-15);
	TestEqual(TEXT("unit_noise01 = (unit_noise + 1) / 2"), FStreetNoise::UnitNoise01(17, 7), (FStreetNoise::UnitNoise(17, 7) + 1.0) * 0.5, 0.0);
	return true;
}
