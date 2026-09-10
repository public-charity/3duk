#include "StreetTerrainSource.h"
#include "StreetscapeJson.h"
#include "StreetscapeSettings.h"
#include "StreetscapeModule.h"
#include "Dom/JsonObject.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "LandscapeProxy.h"

// ---------------------------------------------------------------------------------------------------------------
// FStreetHeightfield
// ---------------------------------------------------------------------------------------------------------------

FStreetHeightfield FStreetHeightfield::FromFunction(TFunctionRef<double(double, double)> Fn, FVector2d ExtentM, double InPxM, double InTileM, FVector2d Origin, FVector2d InXY0)
{
	FStreetHeightfield H;
	H.TileM = InTileM;
	H.PxM = InPxM;
	H.Res = (int32)FMath::RoundToDouble(InTileM / InPxM) + 1;
	H.OriginE = Origin.X;
	H.OriginN = Origin.Y;
	H.XY0 = InXY0;
	H.Source = TEXT("from_function");
	const int32 Nx = (int32)FMath::CeilToDouble(ExtentM.X / InTileM);
	const int32 Ny = (int32)FMath::CeilToDouble(ExtentM.Y / InTileM);
	for (int32 I = 0; I < Nx; ++I)
	{
		for (int32 J = 0; J < Ny; ++J)
		{
			TArray<float>& T = H.Tiles.Add(FIntPoint(I, J));
			T.SetNumUninitialized(H.Res * H.Res);
			const double XBase = InXY0.X + I * InTileM;            // numpy: xy0[0] + i * tile_m + c
			const double YBase = InXY0.Y + (J + 1) * InTileM;      // numpy: xy0[1] + (j + 1) * tile_m - c  (row 0 = north)
			for (int32 R = 0; R < H.Res; ++R)
			{
				const double Y = YBase - R * InPxM;
				for (int32 C = 0; C < H.Res; ++C)
				{
					const double X = XBase + C * InPxM;
					T[R * H.Res + C] = (float)Fn(X, Y);
				}
			}
		}
	}
	return H;
}

bool FStreetHeightfield::LoadLandscapeDir(const FString& Dir, FText* Err)
{
	TSharedPtr<FJsonObject> Man;
	if (!FStreetscapeJson::LoadFile(Dir / TEXT("landscape_manifest.json"), Man, Err)) return false;
	Res = (int32)Man->GetNumberField(TEXT("res"));
	TileM = Man->GetNumberField(TEXT("tile_m"));
	PxM = Man->HasTypedField<EJson::Number>(TEXT("px_m")) ? Man->GetNumberField(TEXT("px_m")) : TileM / (Res - 1);
	double PerUnit = 128.0, Offset = 32768.0;
	const TSharedPtr<FJsonObject>* Hm = nullptr;
	if (Man->TryGetObjectField(TEXT("heightmap"), Hm))
	{
		const TSharedPtr<FJsonObject>* Enc = nullptr;
		if ((*Hm)->TryGetObjectField(TEXT("z_encoding"), Enc))
		{
			(*Enc)->TryGetNumberField(TEXT("per_unit"), PerUnit);
			(*Enc)->TryGetNumberField(TEXT("offset"), Offset);
		}
	}
	const TSharedPtr<FJsonObject>* Or = nullptr;
	if (Man->TryGetObjectField(TEXT("origin"), Or))
	{
		OriginE = (*Or)->GetNumberField(TEXT("E"));
		OriginN = (*Or)->GetNumberField(TEXT("N"));
	}
	Source = TEXT("landscape:") + FPaths::ConvertRelativePathToFull(Dir);
	auto ReadPairs = [&Man](const TCHAR* Key, TArray<FIntPoint>& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* A = nullptr;
		if (Man->TryGetArrayField(Key, A))
		{
			for (const TSharedPtr<FJsonValue>& V : *A)
			{
				const TArray<TSharedPtr<FJsonValue>>& P = V->AsArray();
				if (P.Num() == 2) Out.Add(FIntPoint((int32)P[0]->AsNumber(), (int32)P[1]->AsNumber()));
			}
		}
	};
	TilesMissing.Reset(); TilesClipped.Reset();
	ReadPairs(TEXT("tiles_missing"), TilesMissing);
	ReadPairs(TEXT("tiles_clipped"), TilesClipped);
	Tiles.Reset();
	const TArray<TSharedPtr<FJsonValue>>* TileArr = nullptr;
	if (!Man->TryGetArrayField(TEXT("tiles"), TileArr))
	{
		if (Err) *Err = FText::FromString(TEXT("landscape_manifest.json: no 'tiles'"));
		return false;
	}
	const int32 N2 = Res * Res;
	for (const TSharedPtr<FJsonValue>& V : *TileArr)
	{
		const TSharedPtr<FJsonObject>& T = V->AsObject();
		const FIntPoint Key((int32)T->GetNumberField(TEXT("x")), (int32)T->GetNumberField(TEXT("y")));
		if (TilesMissing.Contains(Key) || TilesClipped.Contains(Key)) continue;
		FString HmName = FString::Printf(TEXT("hm_x%d_y%d.r16"), Key.X, Key.Y);
		FString ClipName = FString::Printf(TEXT("clip_x%d_y%d.r8"), Key.X, Key.Y);
		const TSharedPtr<FJsonObject>* Files = nullptr;
		if (T->TryGetObjectField(TEXT("files"), Files))
		{
			FString S;
			if ((*Files)->TryGetStringField(TEXT("heightmap"), S) && !S.IsEmpty()) HmName = S;
			if ((*Files)->TryGetStringField(TEXT("clip"), S) && !S.IsEmpty()) ClipName = S;
		}
		TArray<uint8> Bytes;
		if (!FFileHelper::LoadFileToArray(Bytes, *(Dir / HmName)))
		{
			// dropping the tile is worse than failing: every spline over it would sample NaN, FillNanAlong would
			// hold the last finite height along s, and the street would be built flat and silently wrong
			if (Err) *Err = FText::FromString(FString::Printf(TEXT("cannot read %s"), *HmName));
			return false;
		}
		if (Bytes.Num() != N2 * 2)
		{
			if (Err) *Err = FText::FromString(FString::Printf(TEXT("%s: %d bytes, expected %d"), *HmName, Bytes.Num(), N2 * 2));
			return false;
		}
		TArray<float>& Z = Tiles.Add(Key);
		Z.SetNumUninitialized(N2);
		const uint16* H16 = reinterpret_cast<const uint16*>(Bytes.GetData());
		for (int32 I = 0; I < N2; ++I)
		{
			Z[I] = (float)(((double)H16[I] - Offset) / PerUnit);
		}
		TArray<uint8> Clip;
		if (FFileHelper::LoadFileToArray(Clip, *(Dir / ClipName)) && Clip.Num() == N2)
		{
			for (int32 I = 0; I < N2; ++I)
			{
				if (Clip[I] == 0) Z[I] = NAN;
			}
		}
	}
	return true;
}

bool FStreetHeightfield::Sample(double X, double Y, double& OutZ) const
{
	OutZ = NAN;
	if (!FMath::IsFinite(X) || !FMath::IsFinite(Y)) return false;
	// numpy: x + (shift - xy0)
	X = X + (ShiftXY.X - XY0.X);
	Y = Y + (ShiftXY.Y - XY0.Y);
	const int64 Ti = (int64)FMath::FloorToDouble(X / TileM);
	const int64 Tj = (int64)FMath::FloorToDouble(Y / TileM);
	const TArray<float>* T = Tiles.Find(FIntPoint((int32)Ti, (int32)Tj));
	if (!T) return false;
	const int32 R1 = Res - 1;
	double Cx = (X - (double)Ti * TileM) / PxM;
	double Ry = ((double)(Tj + 1) * TileM - Y) / PxM;
	Cx = FMath::Clamp(Cx, 0.0, (double)R1);
	Ry = FMath::Clamp(Ry, 0.0, (double)R1);
	const int32 X0 = FMath::Min((int32)FMath::FloorToDouble(Cx), R1 - 1);
	const int32 Y0 = FMath::Min((int32)FMath::FloorToDouble(Ry), R1 - 1);
	const double Tx = Cx - X0;
	const double Ty = Ry - Y0;
	// row Y0 is the NORTH edge of the cell and Ty grows southwards, which is the landscape's own +Y, so
	// A = P00 (NW), B = P10 (NE), C = P01 (SW), D = P11 (SE) in the Chaos cell of EStreetHeightSampling's comment.
	const double A = (double)(*T)[Y0 * Res + X0];
	const double B = (double)(*T)[Y0 * Res + X0 + 1];
	const double C = (double)(*T)[(Y0 + 1) * Res + X0];
	const double D = (double)(*T)[(Y0 + 1) * Res + X0 + 1];
	double V;
	if (Sampling == EStreetHeightSampling::LandscapeTriangulated)
	{
		V = (Tx < Ty) ? (A * (1.0 - Ty) + D * Tx + C * (Ty - Tx))
		              : (A * (1.0 - Tx) + B * (Tx - Ty) + D * Ty);
	}
	else
	{
		V = (A * (1 - Tx) + B * Tx) * (1 - Ty) + (C * (1 - Tx) + D * Tx) * Ty;
	}
	if (!FMath::IsFinite(V)) return false;
	OutZ = V;
	return true;
}

bool FStreetHeightfield::Bounds(double& X0, double& Y0, double& X1, double& Y1) const
{
	if (Tiles.Num() == 0) return false;
	int32 MinI = INT32_MAX, MinJ = INT32_MAX, MaxI = INT32_MIN, MaxJ = INT32_MIN;
	for (const auto& KV : Tiles)
	{
		MinI = FMath::Min(MinI, KV.Key.X); MaxI = FMath::Max(MaxI, KV.Key.X);
		MinJ = FMath::Min(MinJ, KV.Key.Y); MaxJ = FMath::Max(MaxJ, KV.Key.Y);
	}
	const double Sx = ShiftXY.X - XY0.X, Sy = ShiftXY.Y - XY0.Y;
	X0 = MinI * TileM - Sx; Y0 = MinJ * TileM - Sy; X1 = (MaxI + 1) * TileM - Sx; Y1 = (MaxJ + 1) * TileM - Sy;
	return true;
}

FString FStreetHeightfield::Describe() const
{
	return FString::Printf(TEXT("%s tile_m=%g res=%d px_m=%g n_tiles=%d origin=(%g, %g) shift=(%g, %g) xy0=(%g, %g) sampling=%s"),
		*Source, TileM, Res, PxM, Tiles.Num(), OriginE, OriginN, ShiftXY.X, ShiftXY.Y, XY0.X, XY0.Y,
		Sampling == EStreetHeightSampling::LandscapeTriangulated ? TEXT("landscape_triangulated") : TEXT("bilinear"));
}

// ---------------------------------------------------------------------------------------------------------------
// UStreetHeightfieldTerrain
// ---------------------------------------------------------------------------------------------------------------

FString UStreetHeightfieldTerrain::ResolvedDir() const
{
	if (!LandscapeDir.IsEmpty())
	{
		FString D = LandscapeDir;
		if (FPaths::IsRelative(D)) D = FPaths::ConvertRelativePathToFull(FPaths::ProjectDir(), D);
		return D;
	}
	return GetDefault<UStreetscapeSettings>()->GetResolvedDataDir() / TEXT("landscape");
}

void UStreetHeightfieldTerrain::SetSyntheticPlane(double Z0, double GX, double GY)
{
	// synthetic.flat_terrain / synthetic.graded_terrain: extent (512, 512), 1 m posts, tile 512 m, xy0 (0, -256)
	Field = FStreetHeightfield::FromFunction([Z0, GX, GY](double X, double Y) { return Z0 + GX * (X - 200.0) + GY * (Y - 100.0); },
		FVector2d(512.0, 512.0), 1.0, 512.0, FVector2d::ZeroVector, FVector2d(0.0, -256.0));
	// the frozen numbers were computed with the numpy Heightfield's own default rule
	Sampling = EStreetHeightSampling::Bilinear;
	Field.Sampling = Sampling;
	Field.Source = FString::Printf(TEXT("synthetic plane z=%g%+g(x-200)%+g(y-100)"), Z0, GX, GY);
	bLoaded = true;
	LastError.Reset();
}

bool UStreetHeightfieldTerrain::Load()
{
	FText Err;
	bLoaded = Field.LoadLandscapeDir(ResolvedDir(), &Err);
	Field.Sampling = Sampling;
	LastError = bLoaded ? FString() : Err.ToString();
	if (bLoaded)
	{
		if (bDocumentOriginSet) Field.SetDocumentOrigin(DocumentOriginEN.X, DocumentOriginEN.Y);
		UE_LOG(LogStreetscape, Log, TEXT("Heightfield loaded: %s"), *Field.Describe());
	}
	else
	{
		UE_LOG(LogStreetscape, Warning, TEXT("Heightfield load failed: %s"), *LastError);
	}
	return bLoaded;
}

bool UStreetHeightfieldTerrain::SampleHeight(double XM, double YM, double& OutZM) const
{
	if (!bLoaded)
	{
		const_cast<UStreetHeightfieldTerrain*>(this)->Load();
		if (!bLoaded) return false;
	}
	return Field.Sample(XM, YM, OutZM);
}

double UStreetHeightfieldTerrain::ProbeM(double XM, double YM) const
{
	double Z;
	return SampleHeight(XM, YM, Z) ? Z : NAN;
}

FString UStreetHeightfieldTerrain::Describe() const
{
	return bLoaded ? Field.Describe() : FString::Printf(TEXT("heightfield (not loaded) %s"), *ResolvedDir());
}

void UStreetHeightfieldTerrain::SetDocumentOrigin(double E, double N)
{
	DocumentOriginEN = FVector2D(E, N);
	bDocumentOriginSet = true;
	Field.SetDocumentOrigin(E, N);
}

// ---------------------------------------------------------------------------------------------------------------
// UStreetLandscapeTerrain
// ---------------------------------------------------------------------------------------------------------------

bool UStreetLandscapeTerrain::SampleHeight(double XM, double YM, double& OutZM) const
{
	ALandscapeProxy* L = Landscape.Get();
	if (!L) return false;
	const FVector UE = FStreetscapeJson::ToUE(FVector3d(XM, YM, 0.0));
	TOptional<float> H = L->GetHeightAtLocation(FVector(UE.X, UE.Y, 0.0), EHeightfieldSource::Complex);
	if (!H.IsSet()) return false;
	OutZM = (double)H.GetValue() / 100.0;
	return true;
}

FString UStreetLandscapeTerrain::Describe() const
{
	return FString::Printf(TEXT("landscape %s"), Landscape.IsValid() ? *Landscape->GetPathName() : TEXT("(none)"));
}
