// Streetscape.Terrain.Bilinear (UE_PLAN.md 2.5.5, 2.13): the heightfield sampler is the numpy Heightfield.sample
// transcription - bilinear between pixel centres, inward clamp at the last row/column, NaN on clip and off coverage,
// document-origin rebasing. The numpy fixture of 10 000 hashed points arrives with the geometry track's
// fixtures/; until then the same 10 000 hashed points are checked against the analytic field they sample.

#include "StreetTestUtil.h"

using namespace StreetTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetTerrainBilinearTest, "Streetscape.Terrain.Bilinear", EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetTerrainBilinearTest::RunTest(const FString& Parameters)
{
	// a linear field is reproduced exactly by bilinear interpolation (its float32 samples are exact multiples of 1/4)
	FStreetHeightfield H = FStreetHeightfield::FromFunction([](double X, double Y) { return 0.5 * X + 0.25 * Y + 3.0; }, FVector2d(1024.0, 1024.0), 1.0, 512.0, FVector2d::ZeroVector, FVector2d(0.0, -256.0));
	TestEqual(TEXT("2 x 2 tiles"), H.Tiles.Num(), 4);
	TestEqual(TEXT("res 513"), H.Res, 513);
	double MaxDiff = 0; int32 Inside = 0, Outside = 0;
	for (int32 I = 0; I < 10000; ++I)
	{
		const double X = FStreetNoise::UnitNoise01((uint32)I, 101) * 1100.0 - 40.0;   // spills off coverage on both sides
		const double Y = FStreetNoise::UnitNoise01((uint32)I, 102) * 1100.0 - 300.0;
		double Z;
		const bool bIn = X >= 0.0 && X < 1024.0 && Y >= -256.0 && Y < 768.0;
		const bool bGot = H.Sample(X, Y, Z);
		if (bGot != bIn) { AddError(FString::Printf(TEXT("coverage mismatch at (%.3f, %.3f): got %d expected %d"), X, Y, bGot, bIn)); return false; }
		if (bGot) { MaxDiff = FMath::Max(MaxDiff, FMath::Abs(Z - (0.5 * X + 0.25 * Y + 3.0))); ++Inside; } else ++Outside;
	}
	AddInfo(FString::Printf(TEXT("10000 hashed points: %d inside, %d outside, max |diff| %.3g"), Inside, Outside, MaxDiff));
	TestTrue(TEXT("bilinear of a linear field is exact (< 1e-9)"), MaxDiff < 1e-9);
	TestTrue(TEXT("both inside and outside points were hit"), Inside > 5000 && Outside > 500);
	// tile borders: x = 512 belongs to tile 1 (cx = 0), x = 511.9 to tile 0 with the inward clamp of the last column
	double Z;
	TestTrue(TEXT("sample at the shared column x = 512"), H.Sample(512.0, 10.0, Z) && FMath::Abs(Z - (256.0 + 2.5 + 3.0)) < 1e-9);
	TestTrue(TEXT("sample just before the shared column"), H.Sample(511.9, 10.0, Z) && FMath::Abs(Z - (255.95 + 2.5 + 3.0)) < 1e-9);
	TestTrue(TEXT("sample at the north edge row y = 255.999 of tile row 0"), H.Sample(10.0, 255.999, Z) && FMath::Abs(Z - (5.0 + 63.99975 + 3.0)) < 1e-9);
	TestTrue(TEXT("sample at the south edge y = -256"), H.Sample(10.0, -256.0, Z) && FMath::Abs(Z - (5.0 - 64.0 + 3.0)) < 1e-9);
	TestFalse(TEXT("off coverage north (y = 768)"), H.Sample(10.0, 768.0, Z));
	TestFalse(TEXT("off coverage west (x = -0.001)"), H.Sample(-0.001, 10.0, Z));
	TestFalse(TEXT("non-finite query"), H.Sample(NAN, 10.0, Z));
	// clip: a NaN cell poisons the four samples around it and nothing else
	{
		TArray<float>& T0 = H.Tiles[FIntPoint(0, 0)];
		const int32 Row = 256 - 100, Col = 200;   // pixel centre at x = 200, y = 100 (row 0 = north = y 256)
		T0[Row * H.Res + Col] = NAN;
		TestFalse(TEXT("clip: sample on the NaN cell"), H.Sample(200.0, 100.0, Z));
		TestFalse(TEXT("clip: sample 0.5 m east"), H.Sample(200.5, 100.0, Z));
		TestFalse(TEXT("clip: sample 0.5 m south-west"), H.Sample(199.5, 99.5, Z));
		TestTrue(TEXT("clip: sample 1.5 m away is fine"), H.Sample(201.5, 100.0, Z));
		TestTrue(TEXT("clip: sample exactly at the next centre"), H.Sample(201.0, 100.0, Z) && FMath::Abs(Z - (100.5 + 25.0 + 3.0)) < 1e-9);
	}
	// document origin: a document authored in (E, N) = (5120, 5120) on a heightfield whose origin is (0, 0)
	{
		FStreetHeightfield G = FStreetHeightfield::FromFunction([](double X, double Y) { return 0.5 * X + 0.25 * Y + 3.0; }, FVector2d(512.0, 512.0), 1.0, 512.0, FVector2d(632800.0, 168200.0), FVector2d::ZeroVector);
		G.SetDocumentOrigin(627680.0, 163080.0);   // Thanet document on Margate tiles: +5120 shift (BRIEF 4.1)
		double Zg;
		TestTrue(TEXT("rebased sample lands 5120 m off"), G.Sample(5120.0 + 10.0, 5120.0 + 20.0, Zg) && FMath::Abs(Zg - (5.0 + 5.0 + 3.0)) < 1e-9);
		TestFalse(TEXT("rebased: document (10, 20) is off the Margate tiles"), G.Sample(10.0, 20.0, Zg));
		double X0, Y0, X1, Y1;
		TestTrue(TEXT("bounds in the document frame"), G.Bounds(X0, Y0, X1, Y1) && FMath::Abs(X0 - 5120.0) < 1e-9 && FMath::Abs(X1 - 5632.0) < 1e-9);
	}
	// the adapter product, when it exists on this machine
	{
		const FString Dir = ProjectDir() / TEXT("../../data/thanet/out/unreal/landscape");
		if (FPaths::FileExists(Dir / TEXT("landscape_manifest.json")))
		{
			FStreetHeightfield L;
			FText Err;
			const bool bOk = L.LoadLandscapeDir(Dir, &Err);
			TestTrue(TEXT("landscape dir loads: ") + Err.ToString(), bOk);
			if (bOk) AddInfo(TEXT("adapter heightfield: ") + L.Describe());
		}
		else
		{
			AddInfo(TEXT("no adapter landscape output at ") + FPaths::ConvertRelativePathToFull(Dir) + TEXT(" - loader not exercised"));
		}
	}
	return true;
}

// Streetscape.Terrain.Triangulated: EStreetHeightSampling::LandscapeTriangulated reproduces the rule the engine's
// own heightfield uses, so a street draped through the terrain source sits on the ground the pawn collides with.
// Rule and citation: Chaos::FHeightField::GetHeightAt -> GetHeightNormalAt, HeightField.cpp:921-968, reached from
// ALandscapeProxy::GetHeightAtLocation (LandscapeCollision.cpp:2703 -> :2548). Every cell splits on its
// (0,0)-(1,1) diagonal; the fractions are measured with +Y southwards, which is our row direction.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetTerrainTriangulatedTest, "Streetscape.Terrain.Triangulated", EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetTerrainTriangulatedTest::RunTest(const FString& Parameters)
{
	// A field that is planar over each triangle but NOT bilinear: a 45-degree ridge along the SW-NE diagonal.
	// f(x, y) = min(x_frac, 1 - y_frac) style content is awkward to build from a function, so use the measured
	// Ramsgate harbour-wall cell instead: the four DTM corners the georegistration audit read out of the raster,
	// where the two rules disagree by 0.518 m.
	//   SW -2.182   SE -0.435   NW -1.781   NE 2.240   at local (10595.636, 1232.358)
	const double NW = -1.781, NE = 2.240, SW = -2.182, SE = -0.435;
	auto Cell = [&](double X, double Y) -> double
	{
		// one 1 m cell with its NW post at (0, 1): x in [0, 1], y in [0, 1] with y = 1 north
		const double Fx = X;
		const double Fy = 1.0 - Y;                 // fraction measured southwards, as the engine's grid +Y is
		return (Fx < Fy) ? (NW * (1.0 - Fy) + SE * Fx + SW * (Fy - Fx))
		                 : (NW * (1.0 - Fx) + NE * (Fx - Fy) + SE * Fy);
	};
	const double Fx = 0.636, Fy = 0.642;           // the audit's point, to the millimetre
	const double Expect = NW * (1.0 - Fy) + SE * Fx + SW * (Fy - Fx);
	TestTrue(TEXT("the closed form matches the measured engine height -0.92735"), FMath::Abs(Expect - (-0.92735)) < 5e-5);
	TestTrue(TEXT("the helper agrees with the closed form"), FMath::Abs(Cell(Fx, 1.0 - Fy) - Expect) < 1e-12);

	// The same four posts through FStreetHeightfield, both ways.
	auto Field = [&](double X, double Y) -> double
	{
		// posts at integer metres: (0,0) SW, (1,0) SE, (0,1) NW, (1,1) NE, repeated so every cell is the same
		const int32 Ix = (int32)FMath::FloorToDouble(X), Iy = (int32)FMath::FloorToDouble(Y);
		const bool bEast = (Ix & 1) != 0, bNorth = (Iy & 1) != 0;
		return bNorth ? (bEast ? NE : NW) : (bEast ? SE : SW);
	};
	FStreetHeightfield H = FStreetHeightfield::FromFunction(Field, FVector2d(512.0, 512.0), 1.0, 512.0);
	double Zb = 0, Zt = 0;
	const double X = 10.0 + Fx, Y = 100.0 + (1.0 - Fy);   // an even cell: SW at (10, 100)
	H.Sampling = EStreetHeightSampling::Bilinear;
	TestTrue(TEXT("bilinear sample"), H.Sample(X, Y, Zb));
	H.Sampling = EStreetHeightSampling::LandscapeTriangulated;
	TestTrue(TEXT("triangulated sample"), H.Sample(X, Y, Zt));
	const double Bilin = (SW * (1 - Fx) + SE * Fx) * (1 - (1.0 - Fy)) + (NW * (1 - Fx) + NE * Fx) * (1.0 - Fy);
	AddInfo(FString::Printf(TEXT("bilinear %.5f, triangulated %.5f, |difference| %.5f m"), Zb, Zt, FMath::Abs(Zb - Zt)));
	TestTrue(TEXT("bilinear is the untouched rule"), FMath::Abs(Zb - Bilin) < 1e-6);
	TestTrue(TEXT("triangulated is the Chaos rule"), FMath::Abs(Zt - Expect) < 1e-6);
	TestTrue(TEXT("the two rules disagree by more than the 0.125 m kerb on this cell"), FMath::Abs(Zb - Zt) > 0.125);

	// on a planar patch the two rules must agree exactly - a triangulation of a plane is that plane
	FStreetHeightfield P = FStreetHeightfield::FromFunction([](double Xx, double Yy) { return 0.5 * Xx - 0.25 * Yy + 1.0; }, FVector2d(512.0, 512.0), 1.0, 512.0);
	double MaxDiff = 0.0;
	for (int32 I = 0; I < 2000; ++I)
	{
		const double Px = FStreetNoise::UnitNoise01((uint32)I, 211) * 500.0;
		const double Py = FStreetNoise::UnitNoise01((uint32)I, 212) * 500.0;
		double Z1 = 0, Z2 = 0;
		P.Sampling = EStreetHeightSampling::Bilinear;
		P.Sample(Px, Py, Z1);
		P.Sampling = EStreetHeightSampling::LandscapeTriangulated;
		P.Sample(Px, Py, Z2);
		MaxDiff = FMath::Max(MaxDiff, FMath::Abs(Z1 - Z2));
	}
	AddInfo(FString::Printf(TEXT("planar patch, 2000 points: max |bilinear - triangulated| = %.3g"), MaxDiff));
	TestTrue(TEXT("the two rules agree exactly on a plane"), MaxDiff < 1e-9);
	// at grid posts the rules are identical by construction
	double Za = 0, Zc = 0;
	P.Sampling = EStreetHeightSampling::Bilinear;      P.Sample(37.0, 91.0, Za);
	P.Sampling = EStreetHeightSampling::LandscapeTriangulated; P.Sample(37.0, 91.0, Zc);
	TestTrue(TEXT("identical at a grid post"), FMath::Abs(Za - Zc) < 1e-12);
	return true;
}

// Streetscape.Terrain.SamplerAgreement: the plugin, the numpy core and the engine have to mean the SAME surface by
// "the ground". This pins the three things that could drift apart:
//
//   1. the DIAGONAL. Both branches of the triangulated rule share P00 (NW) and P11 (SE), i.e. the quad splits on the
//      NW-SE diagonal. The opposite split is a different surface by the full |twist|/4 at the quad centre, so the
//      choice is asserted here against a cell with a large twist rather than left to a comment.
//   2. the EXPRESSION. It is checked against a literal transcription of Tools/blender/streetscape/terrain.py:_interp
//      over hashed points on a twisted field, to 0 (not to a tolerance).
//   3. the DEFAULTS. UStreetHeightfieldTerrain - what a real street is draped from - must ask for the landscape's own
//      rule, and the pure FStreetHeightfield must keep the numpy contract's bilinear so no frozen number moves. The
//      two are only allowed to differ where the surface itself does not: on a plane, and at every grid post.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetTerrainSamplerAgreementTest, "Streetscape.Terrain.SamplerAgreement", EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter)
bool FStreetTerrainSamplerAgreementTest::RunTest(const FString& Parameters)
{
	// -- 1 + 2: a field with a big twist in every cell, so the two diagonals and the two rules all disagree --------
	auto Twisted = [](double X, double Y) -> double
	{
		const int32 Ix = (int32)FMath::FloorToDouble(X), Iy = (int32)FMath::FloorToDouble(Y);
		return 3.0 * (double)((Ix & 1) ^ (Iy & 1)) + 0.05 * (double)Ix - 0.03 * (double)Iy;
	};
	FStreetHeightfield H = FStreetHeightfield::FromFunction(Twisted, FVector2d(512.0, 512.0), 1.0, 512.0);
	H.Sampling = EStreetHeightSampling::LandscapeTriangulated;

	// the numpy rule, transcribed here so that two expressions are compared and not one expression called twice
	auto Post = [&](int32 Col, int32 Row) -> double
	{
		// tile (0, 0) covers x in [0, 512], y in [0, 512]; row 0 is the NORTH edge, so post (col, row) is at
		// (x, y) = (col, 512 - row) and Twisted is evaluated on the integer lattice there. The cast through float
		// is not cosmetic: the heightfield stores float32 samples on BOTH sides (numpy's tiles are float32 too),
		// so comparing against the double-precision function instead of the stored value would leave a 1e-6
		// residual that has nothing to do with the interpolation rule.
		return (double)(float)Twisted((double)Col, (double)(512 - Row));
	};
	auto NumpyTriangulated = [&](double X, double Y) -> double
	{
		const double Cx = X;
		const double Ry = 512.0 - Y;
		const int32 X0 = FMath::Min((int32)FMath::FloorToDouble(Cx), 511);
		const int32 Y0 = FMath::Min((int32)FMath::FloorToDouble(Ry), 511);
		const double Tx = Cx - X0, Ty = Ry - Y0;
		const double A = Post(X0, Y0);              // NW
		const double B = Post(X0 + 1, Y0);          // NE
		const double C = Post(X0, Y0 + 1);          // SW
		const double D = Post(X0 + 1, Y0 + 1);      // SE
		return (Tx < Ty) ? (A * (1.0 - Ty) + D * Tx + C * (Ty - Tx))
		                 : (A * (1.0 - Tx) + B * (Tx - Ty) + D * Ty);
	};
	double MaxDiff = 0.0, MaxFlipped = 0.0;
	int32 N = 0;
	for (int32 I = 0; I < 5000; ++I)
	{
		const double X = FStreetNoise::UnitNoise01((uint32)I, 401) * 500.0 + 5.0;
		const double Y = FStreetNoise::UnitNoise01((uint32)I, 402) * 500.0 + 5.0;
		double Z = 0;
		if (!H.Sample(X, Y, Z)) continue;
		++N;
		MaxDiff = FMath::Max(MaxDiff, FMath::Abs(Z - NumpyTriangulated(X, Y)));
		// the SW-NE split of the same cell: the answer a mirrored diagonal convention would give
		const double Cx = X, Ry = 512.0 - Y;
		const int32 X0 = FMath::Min((int32)FMath::FloorToDouble(Cx), 511);
		const int32 Y0 = FMath::Min((int32)FMath::FloorToDouble(Ry), 511);
		const double Tx = Cx - X0, Ty = Ry - Y0;
		const double A = Post(X0, Y0), Bq = Post(X0 + 1, Y0), Cq = Post(X0, Y0 + 1), Dq = Post(X0 + 1, Y0 + 1);
		const double Flipped = (Tx + Ty < 1.0) ? (A + (Bq - A) * Tx + (Cq - A) * Ty)
		                                       : (Dq + (Cq - Dq) * (1.0 - Tx) + (Bq - Dq) * (1.0 - Ty));
		MaxFlipped = FMath::Max(MaxFlipped, FMath::Abs(Z - Flipped));
	}
	AddInfo(FString::Printf(TEXT("%d hashed points on a twisted field: max |plugin - numpy rule| = %.3g, max |plugin - flipped diagonal| = %.3g"), N, MaxDiff, MaxFlipped));
	TestTrue(TEXT("at least 4000 points landed on coverage"), N > 4000);
	TestTrue(TEXT("the plugin's triangulated rule IS terrain.py:_interp's, bit for bit"), MaxDiff == 0.0);
	TestTrue(TEXT("and it is NOT the mirrored diagonal (the twist is 3 m, so the split is visible)"), MaxFlipped > 0.5);

	// -- 3: the defaults, and the only places they are allowed to differ -----------------------------------------
	{
		FStreetHeightfield Fresh;
		TestTrue(TEXT("FStreetHeightfield keeps the numpy contract's bilinear default"), Fresh.Sampling == EStreetHeightSampling::Bilinear);
		const UStreetHeightfieldTerrain* Cdo = GetDefault<UStreetHeightfieldTerrain>();
		TestTrue(TEXT("UStreetHeightfieldTerrain - what a real street is draped from - asks for the landscape's own rule"),
			Cdo->Sampling == EStreetHeightSampling::LandscapeTriangulated);
	}
	{
		// a plane: the two rules ARE one surface there, which is why no frozen fixture number moves
		FStreetHeightfield P = FStreetHeightfield::FromFunction([](double X, double Y) { return -0.375 * X + 0.125 * Y - 7.0; }, FVector2d(512.0, 512.0), 1.0, 512.0);
		double Worst = 0.0, WorstPost = 0.0;
		for (int32 I = 0; I < 4000; ++I)
		{
			const double X = FStreetNoise::UnitNoise01((uint32)I, 411) * 500.0;
			const double Y = FStreetNoise::UnitNoise01((uint32)I, 412) * 500.0;
			double Z1 = 0, Z2 = 0;
			P.Sampling = EStreetHeightSampling::Bilinear;               P.Sample(X, Y, Z1);
			P.Sampling = EStreetHeightSampling::LandscapeTriangulated;  P.Sample(X, Y, Z2);
			Worst = FMath::Max(Worst, FMath::Abs(Z1 - Z2));
		}
		FStreetHeightfield T = FStreetHeightfield::FromFunction(Twisted, FVector2d(512.0, 512.0), 1.0, 512.0);
		for (int32 I = 0; I < 500; ++I)
		{
			const double X = FMath::FloorToDouble(FStreetNoise::UnitNoise01((uint32)I, 421) * 500.0);
			const double Y = FMath::FloorToDouble(FStreetNoise::UnitNoise01((uint32)I, 422) * 500.0);
			double Z1 = 0, Z2 = 0;
			T.Sampling = EStreetHeightSampling::Bilinear;               T.Sample(X, Y, Z1);
			T.Sampling = EStreetHeightSampling::LandscapeTriangulated;  T.Sample(X, Y, Z2);
			WorstPost = FMath::Max(WorstPost, FMath::Abs(Z1 - Z2));
		}
		AddInfo(FString::Printf(TEXT("plane: max |bilinear - triangulated| = %.3g; grid posts on a twisted field: %.3g"), Worst, WorstPost));
		TestTrue(TEXT("the two rules are one surface on a plane"), Worst == 0.0);
		TestTrue(TEXT("and one value at every grid post"), WorstPost == 0.0);
	}

	// -- and the coupling to the numpy core, read out of terrain.py rather than asserted from memory --------------
	{
		const FString Py = ProjectDir() / TEXT("Tools/blender/streetscape/terrain.py");
		FString Text;
		if (FFileHelper::LoadFileToString(Text, *Py))
		{
			const FString Needle = TEXT("sampling: str = ");
			const int32 At = Text.Find(Needle, ESearchCase::CaseSensitive);
			if (At != INDEX_NONE)
			{
				const int32 Q0 = Text.Find(TEXT("\""), ESearchCase::CaseSensitive, ESearchDir::FromStart, At) + 1;
				const int32 Q1 = Text.Find(TEXT("\""), ESearchCase::CaseSensitive, ESearchDir::FromStart, Q0);
				const FString Declared = (Q0 > 0 && Q1 > Q0) ? Text.Mid(Q0, Q1 - Q0) : FString();
				AddInfo(TEXT("terrain.py Heightfield.sampling default = ") + Declared);
				TestTrue(TEXT("terrain.py declares a rule this plugin implements"),
					Declared == TEXT("bilinear") || Declared == TEXT("landscape_triangulated"));
				if (Declared == TEXT("landscape_triangulated"))
				{
					AddWarning(TEXT("terrain.py's Heightfield now defaults to landscape_triangulated: FStreetHeightfield::Sampling should follow it, ")
						TEXT("and fixtures/expected.json's frozen numbers move with it (see EStreetHeightSampling in StreetTerrainSource.h)."));
				}
			}
			else
			{
				AddWarning(TEXT("could not find Heightfield.sampling's default in ") + Py);
			}
		}
		else
		{
			AddInfo(TEXT("terrain.py not readable from here - the numpy-side default was not cross-checked"));
		}
	}
	return true;
}
