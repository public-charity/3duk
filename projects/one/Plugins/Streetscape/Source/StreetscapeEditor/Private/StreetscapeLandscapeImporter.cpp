#include "StreetscapeLandscapeImporter.h"

#include "StreetscapeEditorModule.h"
#include "StreetscapeJson.h"

#include "Editor.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "FileHelpers.h"
#include "HAL/PlatformMemory.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Materials/MaterialInterface.h"
#include "GameFramework/Actor.h"
#include "Misc/PackageName.h"
#include "AssetCompilingManager.h"
#include "UObject/GarbageCollection.h"

#include "Landscape.h"
#include "LandscapeProxy.h"
#include "LandscapeStreamingProxy.h"
#include "LandscapeInfo.h"
#include "LandscapeComponent.h"
#include "LandscapeSubsystem.h"
#include "LandscapeDataAccess.h"
#include "LandscapeEdit.h"
#include "LandscapeUtils.h"
#include "LandscapeLayerInfoObject.h"
#include "LandscapeEditLayer.h"
#include "LandscapeImportHelper.h"
#include "LandscapeEditorUtils.h"

#define LOCTEXT_NAMESPACE "StreetscapeLandscapeImporter"

// ===================================================================================================================
// The manifest (UE_PLAN.md 4.1) and the placement it implies (UE_PLAN.md 3.2-3.4)
// ===================================================================================================================

namespace
{
const TCHAR* GGroundLayers[4] = { TEXT("grass"), TEXT("sand"), TEXT("rock"), TEXT("water") };

struct FTileEntry
{
	int32 X = 0, Y = 0;
	FString Heightmap, Clip, Vis;
	FString Weights[4];
	FString ClipState;
};

struct FManifest
{
	FString Path, Dir, Site;
	double OriginE = 0, OriginN = 0;
	int32 TileM = 512, Res = 513, Nx = 0, Ny = 0, WeightRes = 256;
	double PxM = 1.0;
	int32 PadH16 = 32691;
	double PerUnit = 128.0, Offset = 32768.0, ScaleZCm = 100.0;
	TArray<FTileEntry> Tiles;
	TArray<FIntPoint> TilesClipped, TilesMissing;
	bool bHasClip = false;
	double ClipAx = 0, ClipAy = 0, ClipBx = 0, ClipBy = 0;   // survey metres
	FString ClipKeep;
	double SlopeQaMaxDeg = -1.0;
	int32 ClippedCellsTotal = 0;
	bool bHasSlopeQa = false;

	int32 W() const { return Nx * (Res - 1) + 1; }
	int32 H() const { return Ny * (Res - 1) + 1; }
};

struct FPlan
{
	int32 Qps = 127, Sections = 2, Grid = 4;
	int32 Q = 254, Cx = 0, Cy = 0, Wp = 0, Hp = 0, PadEast = 0, PadNorth = 0;
	int32 HelperQps = 0, HelperSections = 0, HelperCx = 0, HelperCy = 0;
	int32 Components() const { return Cx * Cy; }
	int32 ProxiesExpected() const { return FMath::DivideAndRoundUp(Cx, Grid) * FMath::DivideAndRoundUp(Cy, Grid); }
	FVector ActorLocation(const FManifest& M) const { return FVector(0.0, -100.0 * (double)((M.H() - 1) + PadNorth), 0.0); }
};

bool JsonNumber(const TSharedPtr<FJsonObject>& Obj, const TCHAR* Key, double& Out)
{
	return Obj.IsValid() && Obj->TryGetNumberField(Key, Out);
}

/** Read landscape_manifest.json with the UE_PLAN.md 3.6 step-2 hard fails. Returns false and fills OutProblem. */
bool ReadManifest(const FString& ManifestPath, FManifest& M, FString& OutProblem)
{
	M.Path = ManifestPath;
	M.Dir = FPaths::GetPath(ManifestPath);
	TSharedPtr<FJsonObject> Root;
	FText LoadErr;
	if (!FStreetscapeJson::LoadFile(ManifestPath, Root, &LoadErr))
	{
		OutProblem = LoadErr.ToString();
		return false;
	}

	Root->TryGetStringField(TEXT("site"), M.Site);
	const TSharedPtr<FJsonObject>* Origin = nullptr;
	if (Root->TryGetObjectField(TEXT("origin"), Origin))
	{
		(*Origin)->TryGetNumberField(TEXT("E"), M.OriginE);
		(*Origin)->TryGetNumberField(TEXT("N"), M.OriginN);
	}
	double D = 0;
	if (JsonNumber(Root, TEXT("tile_m"), D)) M.TileM = (int32)D;
	if (JsonNumber(Root, TEXT("res"), D)) M.Res = (int32)D;
	if (JsonNumber(Root, TEXT("nx"), D)) M.Nx = (int32)D;
	if (JsonNumber(Root, TEXT("ny"), D)) M.Ny = (int32)D;
	if (JsonNumber(Root, TEXT("weight_res"), D)) M.WeightRes = (int32)D;
	if (JsonNumber(Root, TEXT("px_m"), D)) M.PxM = D;
	if (JsonNumber(Root, TEXT("pad_value_h16"), D)) M.PadH16 = (int32)D;
	if (JsonNumber(Root, TEXT("clipped_cells_total"), D)) M.ClippedCellsTotal = (int32)D;

	if (M.Res != 513) { OutProblem = FString::Printf(TEXT("res %d, expected 513"), M.Res); return false; }
	if (M.Nx <= 0 || M.Ny <= 0) { OutProblem = FString::Printf(TEXT("nx %d ny %d"), M.Nx, M.Ny); return false; }
	if (M.TileM != M.Res - 1) { OutProblem = FString::Printf(TEXT("tile_m %d does not match res %d"), M.TileM, M.Res); return false; }

	const TSharedPtr<FJsonObject>* Hm = nullptr;
	if (!Root->TryGetObjectField(TEXT("heightmap"), Hm)) { OutProblem = TEXT("no heightmap block"); return false; }
	FString Row0;
	(*Hm)->TryGetStringField(TEXT("row0"), Row0);
	if (Row0 != TEXT("north")) { OutProblem = FString::Printf(TEXT("heightmap.row0 '%s', expected 'north'"), *Row0); return false; }
	bool bFlip = true;
	if (!(*Hm)->TryGetBoolField(TEXT("row_flip_for_ue"), bFlip) || bFlip)
	{
		OutProblem = TEXT("heightmap.row_flip_for_ue must be false (a north-up heightmap needs no flip for UE)");
		return false;
	}
	const TSharedPtr<FJsonObject>* Enc = nullptr;
	if (!(*Hm)->TryGetObjectField(TEXT("z_encoding"), Enc)) { OutProblem = TEXT("no heightmap.z_encoding"); return false; }
	(*Enc)->TryGetNumberField(TEXT("per_unit"), M.PerUnit);
	(*Enc)->TryGetNumberField(TEXT("offset"), M.Offset);
	(*Enc)->TryGetNumberField(TEXT("scale_z_cm"), M.ScaleZCm);
	if (M.PerUnit != 128.0) { OutProblem = FString::Printf(TEXT("z_encoding.per_unit %g, expected 128"), M.PerUnit); return false; }
	if (M.Offset != 32768.0) { OutProblem = FString::Printf(TEXT("z_encoding.offset %g, expected 32768"), M.Offset); return false; }
	if (M.ScaleZCm != 100.0) { OutProblem = FString::Printf(TEXT("z_encoding.scale_z_cm %g, expected 100"), M.ScaleZCm); return false; }

	const TSharedPtr<FJsonObject>* Wm = nullptr;
	if (Root->TryGetObjectField(TEXT("weightmaps"), Wm))
	{
		FString AlphaType;
		(*Wm)->TryGetStringField(TEXT("alphamap_type"), AlphaType);
		if (AlphaType != TEXT("Additive"))
		{
			OutProblem = FString::Printf(TEXT("weightmaps.alphamap_type '%s', expected 'Additive'"), *AlphaType);
			return false;
		}
		double WR = 0;
		if ((*Wm)->TryGetNumberField(TEXT("res"), WR)) M.WeightRes = (int32)WR;
	}

	const TSharedPtr<FJsonObject>* Slope = nullptr;
	if (Root->TryGetObjectField(TEXT("slope_qa"), Slope))
	{
		M.bHasSlopeQa = (*Slope)->TryGetNumberField(TEXT("max_deg"), M.SlopeQaMaxDeg);
	}

	const TSharedPtr<FJsonObject>* Clip = nullptr;
	if (Root->TryGetObjectField(TEXT("clip"), Clip) && Clip->IsValid())
	{
		const TArray<TSharedPtr<FJsonValue>>* Line = nullptr;
		if ((*Clip)->TryGetArrayField(TEXT("line"), Line) && Line->Num() == 2)
		{
			const TArray<TSharedPtr<FJsonValue>>* A = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* B = nullptr;
			if ((*Line)[0]->TryGetArray(A) && (*Line)[1]->TryGetArray(B) && A->Num() == 2 && B->Num() == 2)
			{
				M.ClipAx = (*A)[0]->AsNumber(); M.ClipAy = (*A)[1]->AsNumber();
				M.ClipBx = (*B)[0]->AsNumber(); M.ClipBy = (*B)[1]->AsNumber();
				(*Clip)->TryGetStringField(TEXT("keep"), M.ClipKeep);
				M.bHasClip = true;
			}
		}
	}

	auto ReadPointList = [](const TSharedPtr<FJsonObject>& Obj, const TCHAR* Key, TArray<FIntPoint>& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
		if (!Obj->TryGetArrayField(Key, Arr)) return;
		for (const TSharedPtr<FJsonValue>& V : *Arr)
		{
			const TArray<TSharedPtr<FJsonValue>>* P = nullptr;
			if (V->TryGetArray(P) && P->Num() == 2)
			{
				Out.Add(FIntPoint((int32)(*P)[0]->AsNumber(), (int32)(*P)[1]->AsNumber()));
			}
		}
	};
	ReadPointList(Root, TEXT("tiles_clipped"), M.TilesClipped);
	ReadPointList(Root, TEXT("tiles_missing"), M.TilesMissing);

	const TArray<TSharedPtr<FJsonValue>>* Tiles = nullptr;
	if (!Root->TryGetArrayField(TEXT("tiles"), Tiles)) { OutProblem = TEXT("no tiles array"); return false; }
	for (const TSharedPtr<FJsonValue>& V : *Tiles)
	{
		const TSharedPtr<FJsonObject>* T = nullptr;
		if (!V->TryGetObject(T)) continue;
		FTileEntry E;
		double TX = 0, TY = 0;
		(*T)->TryGetNumberField(TEXT("x"), TX);
		(*T)->TryGetNumberField(TEXT("y"), TY);
		E.X = (int32)TX; E.Y = (int32)TY;
		(*T)->TryGetStringField(TEXT("clip_state"), E.ClipState);
		const TSharedPtr<FJsonObject>* Files = nullptr;
		if ((*T)->TryGetObjectField(TEXT("files"), Files))
		{
			(*Files)->TryGetStringField(TEXT("heightmap"), E.Heightmap);
			(*Files)->TryGetStringField(TEXT("clip"), E.Clip);
			(*Files)->TryGetStringField(TEXT("vis"), E.Vis);
			const TSharedPtr<FJsonObject>* W = nullptr;
			if ((*Files)->TryGetObjectField(TEXT("weights"), W) && W->IsValid())
			{
				for (int32 B = 0; B < 4; ++B) (*W)->TryGetStringField(GGroundLayers[B], E.Weights[B]);
			}
		}
		if (E.Heightmap.IsEmpty())
		{
			OutProblem = FString::Printf(TEXT("tile (%d, %d) has no heightmap file"), E.X, E.Y);
			return false;
		}
		if (E.X < 0 || E.X >= M.Nx || E.Y < 0 || E.Y >= M.Ny)
		{
			OutProblem = FString::Printf(TEXT("tile (%d, %d) outside the %dx%d grid"), E.X, E.Y, M.Nx, M.Ny);
			return false;
		}
		M.Tiles.Add(E);
	}
	if (M.Tiles.Num() == 0) { OutProblem = TEXT("no tiles"); return false; }
	return true;
}

void MakePlan(const FManifest& M, int32 Qps, int32 Sections, int32 Grid, FPlan& P)
{
	P.Qps = Qps; P.Sections = Sections; P.Grid = FMath::Max(1, Grid);
	P.Q = Qps * Sections;
	P.Cx = FMath::DivideAndRoundUp(M.W() - 1, P.Q);
	P.Cy = FMath::DivideAndRoundUp(M.H() - 1, P.Q);
	P.Wp = P.Cx * P.Q + 1;
	P.Hp = P.Cy * P.Q + 1;
	P.PadEast = P.Wp - M.W();
	P.PadNorth = P.Hp - M.H();

	int32 HQps = Qps, HSec = Sections;
	FIntPoint HCount(0, 0);
	FLandscapeImportHelper::ChooseBestComponentSizeForImport(M.W(), M.H(), HQps, HSec, HCount);
	P.HelperQps = HQps; P.HelperSections = HSec; P.HelperCx = HCount.X; P.HelperCy = HCount.Y;
}

TSharedRef<FJsonObject> PlanJson(const FManifest& M, const FPlan& P)
{
	TSharedRef<FJsonObject> J = MakeShared<FJsonObject>();
	J->SetStringField(TEXT("manifest"), M.Path);
	J->SetStringField(TEXT("site"), M.Site);
	J->SetNumberField(TEXT("nx"), M.Nx);
	J->SetNumberField(TEXT("ny"), M.Ny);
	J->SetNumberField(TEXT("res"), M.Res);
	J->SetNumberField(TEXT("tiles_in_manifest"), M.Tiles.Num());
	J->SetNumberField(TEXT("tiles_clipped"), M.TilesClipped.Num());
	J->SetNumberField(TEXT("tiles_missing"), M.TilesMissing.Num());
	TArray<TSharedPtr<FJsonValue>> Unpadded;
	Unpadded.Add(MakeShared<FJsonValueNumber>(M.W()));
	Unpadded.Add(MakeShared<FJsonValueNumber>(M.H()));
	J->SetArrayField(TEXT("verts_unpadded"), Unpadded);
	TArray<TSharedPtr<FJsonValue>> Padded;
	Padded.Add(MakeShared<FJsonValueNumber>(P.Wp));
	Padded.Add(MakeShared<FJsonValueNumber>(P.Hp));
	J->SetArrayField(TEXT("verts_padded"), Padded);
	TSharedRef<FJsonObject> Size = MakeShared<FJsonObject>();
	Size->SetNumberField(TEXT("qps"), P.Qps);
	Size->SetNumberField(TEXT("sections"), P.Sections);
	Size->SetNumberField(TEXT("quads_per_component"), P.Q);
	J->SetObjectField(TEXT("component_size"), Size);
	TArray<TSharedPtr<FJsonValue>> CC;
	CC.Add(MakeShared<FJsonValueNumber>(P.Cx));
	CC.Add(MakeShared<FJsonValueNumber>(P.Cy));
	J->SetArrayField(TEXT("component_count"), CC);
	J->SetNumberField(TEXT("components_planned"), P.Components());
	J->SetNumberField(TEXT("proxies_expected"), P.ProxiesExpected());
	J->SetNumberField(TEXT("world_partition_grid"), P.Grid);
	TSharedRef<FJsonObject> Pad = MakeShared<FJsonObject>();
	Pad->SetNumberField(TEXT("east"), P.PadEast);
	Pad->SetNumberField(TEXT("north"), P.PadNorth);
	J->SetObjectField(TEXT("padding"), Pad);
	TArray<TSharedPtr<FJsonValue>> Extent;
	Extent.Add(MakeShared<FJsonValueNumber>(0));
	Extent.Add(MakeShared<FJsonValueNumber>(0));
	Extent.Add(MakeShared<FJsonValueNumber>(P.Wp - 1));
	Extent.Add(MakeShared<FJsonValueNumber>(P.Hp - 1));
	J->SetArrayField(TEXT("extent"), Extent);
	J->SetNumberField(TEXT("fill_h16"), M.PadH16);
	J->SetNumberField(TEXT("fill_z_m"), ((double)M.PadH16 - M.Offset) / M.PerUnit);
	TSharedRef<FJsonObject> Helper = MakeShared<FJsonObject>();
	Helper->SetNumberField(TEXT("qps"), P.HelperQps);
	Helper->SetNumberField(TEXT("sections"), P.HelperSections);
	TArray<TSharedPtr<FJsonValue>> HC;
	HC.Add(MakeShared<FJsonValueNumber>(P.HelperCx));
	HC.Add(MakeShared<FJsonValueNumber>(P.HelperCy));
	Helper->SetArrayField(TEXT("components"), HC);
	J->SetObjectField(TEXT("helper_suggestion"), Helper);
	const FVector Loc = P.ActorLocation(M);
	TArray<TSharedPtr<FJsonValue>> L;
	L.Add(MakeShared<FJsonValueNumber>(Loc.X));
	L.Add(MakeShared<FJsonValueNumber>(Loc.Y));
	L.Add(MakeShared<FJsonValueNumber>(Loc.Z));
	J->SetArrayField(TEXT("actor_location_cm"), L);
	TSharedRef<FJsonObject> Origin = MakeShared<FJsonObject>();
	Origin->SetNumberField(TEXT("E"), M.OriginE);
	Origin->SetNumberField(TEXT("N"), M.OriginN);
	J->SetObjectField(TEXT("origin"), Origin);
	if (M.bHasClip)
	{
		TSharedRef<FJsonObject> C = MakeShared<FJsonObject>();
		TArray<TSharedPtr<FJsonValue>> Line;
		TArray<TSharedPtr<FJsonValue>> Pa, Pb;
		Pa.Add(MakeShared<FJsonValueNumber>(M.ClipAx - M.OriginE));
		Pa.Add(MakeShared<FJsonValueNumber>(M.ClipAy - M.OriginN));
		Pb.Add(MakeShared<FJsonValueNumber>(M.ClipBx - M.OriginE));
		Pb.Add(MakeShared<FJsonValueNumber>(M.ClipBy - M.OriginN));
		Line.Add(MakeShared<FJsonValueArray>(Pa));
		Line.Add(MakeShared<FJsonValueArray>(Pb));
		C->SetArrayField(TEXT("line_local_m"), Line);
		C->SetStringField(TEXT("keep"), M.ClipKeep);
		J->SetObjectField(TEXT("clip"), C);
	}
	if (M.bHasSlopeQa) J->SetNumberField(TEXT("slope_qa_max_deg"), M.SlopeQaMaxDeg);
	J->SetNumberField(TEXT("clipped_cells_total"), M.ClippedCellsTotal);
	return J;
}

FString JsonToString(const TSharedRef<FJsonObject>& J)
{
	FString Out;
	TSharedRef<TJsonWriter<>> W = TJsonWriterFactory<>::Create(&Out);
	FJsonSerializer::Serialize(J, W);
	return Out;
}

double NowRssMb()
{
	return (double)FPlatformMemory::GetStats().UsedPhysical / (1024.0 * 1024.0);
}

// ---------------------------------------------------------------------------------------------------------------
// Array assembly (UE_PLAN.md 3.6 step 3 and 3.5)
// ---------------------------------------------------------------------------------------------------------------

struct FAssembly
{
	TArray<uint16> Heights;
	TArray<uint8> Vis;
	TArray<uint8> Weights[4];
	int32 SharedEdgeMaxDelta = 0;
	int64 SharedEdgeSamples = 0;
	int32 TilesRead = 0, VisFilesRead = 0, WeightFilesRead = 0;
	int64 HolesFromVis = 0;
	TMap<int32, int64> WeightSumHistogram;
	FString Problem;
};

bool BuildArrays(const FManifest& M, const FPlan& P, FAssembly& A)
{
	const int32 Res = M.Res;
	const int64 N2 = (int64)Res * Res;
	const int64 Total = (int64)P.Wp * (int64)P.Hp;
	if (Total > (int64)MAX_int32)
	{
		A.Problem = FString::Printf(TEXT("padded grid %d x %d exceeds a single TArray"), P.Wp, P.Hp);
		return false;
	}

	A.Heights.Init((uint16)M.PadH16, (int32)Total);
	A.Vis.Init(255, (int32)Total);                 // padding is a hole (weight 255 = hole, UE_PLAN.md 3.5)
	for (int32 B = 0; B < 3; ++B) A.Weights[B].Init(0, (int32)Total);
	A.Weights[3].Init(255, (int32)Total);          // water fills the padding

	// The step-09 weight mosaic (nx*256 x ny*256, cell centres at odd metres), assembled once and resampled once.
	const int32 MW = M.Nx * M.WeightRes;
	const int32 MH = M.Ny * M.WeightRes;
	TArray<uint8> Mosaic[4];
	bool bAnyWeights = false;

	TArray<uint8> Bytes;
	for (const FTileEntry& T : M.Tiles)
	{
		const int32 ColBase = M.TileM * T.X;
		const int32 RowBase = M.TileM * (M.Ny - 1 - T.Y);

		if (!FFileHelper::LoadFileToArray(Bytes, *(M.Dir / T.Heightmap)))
		{
			A.Problem = FString::Printf(TEXT("cannot read %s"), *T.Heightmap);
			return false;
		}
		if ((int64)Bytes.Num() != N2 * 2)
		{
			A.Problem = FString::Printf(TEXT("%s: %d bytes, expected %lld"), *T.Heightmap, Bytes.Num(), N2 * 2);
			return false;
		}
		const uint16* Src = reinterpret_cast<const uint16*>(Bytes.GetData());
		for (int32 R = 0; R < Res; ++R)
		{
			const int64 DstRow = (int64)(RowBase + R + P.PadNorth);
			uint16* Dst = A.Heights.GetData() + DstRow * P.Wp + ColBase;
			const uint16* S = Src + (int64)R * Res;
			for (int32 C = 0; C < Res; ++C)
			{
				// shared edge rows/columns are written twice: check they agree (they must, same source raster)
				if ((C == 0 && T.X > 0) || (R == 0 && T.Y < M.Ny - 1))
				{
					const int32 Prev = (int32)Dst[C];
					if (Prev != M.PadH16)
					{
						A.SharedEdgeSamples++;
						A.SharedEdgeMaxDelta = FMath::Max(A.SharedEdgeMaxDelta, FMath::Abs(Prev - (int32)S[C]));
					}
				}
				Dst[C] = S[C];
			}
		}
		A.TilesRead++;

		// visibility: the straddle tiles carry vis_*.r8; kept tiles without one are fully visible (0)
		if (!T.Vis.IsEmpty() && FFileHelper::LoadFileToArray(Bytes, *(M.Dir / T.Vis)))
		{
			if ((int64)Bytes.Num() != N2)
			{
				A.Problem = FString::Printf(TEXT("%s: %d bytes, expected %lld"), *T.Vis, Bytes.Num(), N2);
				return false;
			}
			for (int32 R = 0; R < Res; ++R)
			{
				const int64 DstRow = (int64)(RowBase + R + P.PadNorth);
				uint8* Dst = A.Vis.GetData() + DstRow * P.Wp + ColBase;
				const uint8* S = Bytes.GetData() + (int64)R * Res;
				for (int32 C = 0; C < Res; ++C)
				{
					Dst[C] = S[C];
					if (S[C] >= 170) A.HolesFromVis++;   // >= 2/3 * 255 renders as a hole
				}
			}
			A.VisFilesRead++;
		}
		else
		{
			for (int32 R = 0; R < Res; ++R)
			{
				const int64 DstRow = (int64)(RowBase + R + P.PadNorth);
				FMemory::Memset(A.Vis.GetData() + DstRow * P.Wp + ColBase, 0, Res);
			}
		}

		// weights into the mosaic
		for (int32 B = 0; B < 4; ++B)
		{
			if (T.Weights[B].IsEmpty()) continue;
			if (!FFileHelper::LoadFileToArray(Bytes, *(M.Dir / T.Weights[B]))) continue;
			if (Bytes.Num() != M.WeightRes * M.WeightRes)
			{
				A.Problem = FString::Printf(TEXT("%s: %d bytes, expected %d"), *T.Weights[B], Bytes.Num(), M.WeightRes * M.WeightRes);
				return false;
			}
			if (Mosaic[B].Num() == 0) Mosaic[B].Init(0, MW * MH);
			bAnyWeights = true;
			const int32 MCol = M.WeightRes * T.X;
			const int32 MRow = M.WeightRes * (M.Ny - 1 - T.Y);
			for (int32 R = 0; R < M.WeightRes; ++R)
			{
				FMemory::Memcpy(Mosaic[B].GetData() + (int64)(MRow + R) * MW + MCol, Bytes.GetData() + (int64)R * M.WeightRes, M.WeightRes);
			}
			A.WeightFilesRead++;
		}
	}
	Bytes.Empty();

	if (bAnyWeights)
	{
		for (int32 B = 0; B < 4; ++B)
		{
			if (Mosaic[B].Num() == 0) Mosaic[B].Init(0, MW * MH);
		}
		// one cell-centre-aware bilinear resample of the whole mosaic onto the padded vertex grid (DESIGN.md 9)
		const double CellM = (double)M.TileM / (double)M.WeightRes;
		const int32 W = M.W(), H = M.H();
		uint8 Acc[4];
		for (int32 R = 0; R < H; ++R)
		{
			const double Rv = (double)R / CellM - 0.5;
			const double Rc = FMath::Clamp(Rv, 0.0, (double)(MH - 1));
			const int32 R0 = FMath::Min((int32)FMath::FloorToDouble(Rc), MH - 2 >= 0 ? MH - 2 : 0);
			const double Ty = Rc - (double)R0;
			const int32 R1 = FMath::Min(R0 + 1, MH - 1);
			const int64 DstRow = (int64)(R + P.PadNorth) * P.Wp;
			for (int32 C = 0; C < W; ++C)
			{
				const double Cv = (double)C / CellM - 0.5;
				const double Cc = FMath::Clamp(Cv, 0.0, (double)(MW - 1));
				const int32 C0 = FMath::Min((int32)FMath::FloorToDouble(Cc), MW - 2 >= 0 ? MW - 2 : 0);
				const double Tx = Cc - (double)C0;
				const int32 C1 = FMath::Min(C0 + 1, MW - 1);
				int32 Sum = 0, Best = 0, BestV = -1;
				for (int32 B = 0; B < 4; ++B)
				{
					const uint8* Mo = Mosaic[B].GetData();
					const double V00 = (double)Mo[(int64)R0 * MW + C0];
					const double V01 = (double)Mo[(int64)R0 * MW + C1];
					const double V10 = (double)Mo[(int64)R1 * MW + C0];
					const double V11 = (double)Mo[(int64)R1 * MW + C1];
					const double V = (V00 * (1 - Tx) + V01 * Tx) * (1 - Ty) + (V10 * (1 - Tx) + V11 * Tx) * Ty;
					const int32 Iv = FMath::Clamp((int32)FMath::RoundToDouble(V), 0, 255);
					Acc[B] = (uint8)Iv;
					Sum += Iv;
					if (Iv > BestV) { BestV = Iv; Best = B; }
				}
				if (Sum > 0)
				{
					// renormalise the four to 255, residue to the largest band
					int32 New[4];
					int32 NewSum = 0;
					for (int32 B = 0; B < 4; ++B)
					{
						New[B] = (int32)FMath::RoundToDouble((double)Acc[B] * 255.0 / (double)Sum);
						NewSum += New[B];
					}
					New[Best] = FMath::Clamp(New[Best] + (255 - NewSum), 0, 255);
					for (int32 B = 0; B < 4; ++B) A.Weights[B][(int32)(DstRow + C)] = (uint8)New[B];
					A.WeightSumHistogram.FindOrAdd(255)++;
				}
				else
				{
					for (int32 B = 0; B < 4; ++B) A.Weights[B][(int32)(DstRow + C)] = 0;
					A.WeightSumHistogram.FindOrAdd(0)++;
				}
			}
		}
	}
	return true;
}

// ---------------------------------------------------------------------------------------------------------------
// Region path helpers (UE_PLAN.md 3.7) - the editor's own AddComponents, which is a private static there
// (LandscapeEditorDetailCustomization_NewLandscape.cpp:1058)
// ---------------------------------------------------------------------------------------------------------------

void AddComponentsForBlock(ULandscapeInfo* Info, ULandscapeSubsystem* Subsystem, const TArray<FIntPoint>& Coords, TArray<ALandscapeProxy*>& OutProxies)
{
	TArray<ULandscapeComponent*> NewComponents;
	Info->Modify();
	for (const FIntPoint& Coord : Coords)
	{
		if (Info->XYtoComponentMap.FindRef(Coord)) continue;
		const FIntPoint ComponentBase = Coord * Info->ComponentSizeQuads;
		ALandscapeProxy* Proxy = Subsystem->FindOrAddLandscapeProxy(Info, ComponentBase);
		if (!Proxy) continue;
		OutProxies.AddUnique(Proxy);
		ULandscapeComponent* Component = NewObject<ULandscapeComponent>(Proxy, NAME_None, RF_Transactional);
		NewComponents.Add(Component);
		Component->Init(ComponentBase.X, ComponentBase.Y, Proxy->ComponentSizeQuads, Proxy->NumSubsections, Proxy->SubsectionSizeQuads);

		TArray<FColor> HeightData;
		const int32 ComponentVerts = (Component->SubsectionSizeQuads + 1) * Component->NumSubsections;
		HeightData.Init(LandscapeDataAccess::GetDefaultPackedHeightColor(), FMath::Square(ComponentVerts));
		Component->InitHeightmapData(HeightData, true);
		Component->UpdateMaterialInstances();

		Info->XYtoComponentMap.Add(Coord, Component);
		Info->XYtoAddCollisionMap.Remove(Coord);
	}
	for (ULandscapeComponent* C : NewComponents) C->RegisterComponent();

	ALandscape* Landscape = Info->LandscapeActor.Get();
	for (ULandscapeComponent* C : NewComponents)
	{
		if (Landscape)
		{
			TArray<ULandscapeComponent*> Using;
			Using.Add(C);
			for (const ULandscapeEditLayerBase* EditLayer : Landscape->GetEditLayersConst())
			{
				TMap<UTexture2D*, UTexture2D*> Created;
				C->AddDefaultLayerData(EditLayer->GetGuid(), Using, Created);
			}
		}
		C->UpdateCachedBounds();
		C->UpdateBounds();
		C->MarkRenderStateDirty();
	}
	if (Landscape && GEngine) GEngine->BroadcastOnActorMoved(Landscape);
}

template <typename T>
void ExtractRect(const TArray<T>& Src, int32 SrcW, int32 X1, int32 Y1, int32 X2, int32 Y2, TArray<T>& Out)
{
	const int32 W = X2 - X1 + 1;
	const int32 H = Y2 - Y1 + 1;
	Out.SetNumUninitialized(W * H);
	for (int32 R = 0; R < H; ++R)
	{
		FMemory::Memcpy(Out.GetData() + (int64)R * W, Src.GetData() + (int64)(Y1 + R) * SrcW + X1, (int64)W * sizeof(T));
	}
}

ULandscapeLayerInfoObject* GetOrCreateLayerInfo(FName LayerName, const FString& PackagePath)
{
	const FString AssetName = FString::Printf(TEXT("LI_%s"), *LayerName.ToString());
	const FString ObjectPath = FString::Printf(TEXT("%s/%s.%s"), *PackagePath, *AssetName, *AssetName);
	if (ULandscapeLayerInfoObject* Existing = LoadObject<ULandscapeLayerInfoObject>(nullptr, *ObjectPath, nullptr, LOAD_NoWarn | LOAD_Quiet))
	{
		return Existing;
	}
	return UE::Landscape::CreateTargetLayerInfo(LayerName, PackagePath, AssetName);
}
}   // namespace

// ===================================================================================================================
// UFUNCTIONs
// ===================================================================================================================

FString UStreetscapeLandscapeImporter::PlanSiteJson(const FString& ManifestPath, int32 QuadsPerSection, int32 SectionsPerComponent, int32 WorldPartitionGridSize)
{
	FManifest M;
	FString Problem;
	if (!ReadManifest(ManifestPath, M, Problem))
	{
		TSharedRef<FJsonObject> J = MakeShared<FJsonObject>();
		J->SetStringField(TEXT("error"), Problem);
		J->SetStringField(TEXT("manifest"), ManifestPath);
		return JsonToString(J);
	}
	FPlan P;
	MakePlan(M, QuadsPerSection, SectionsPerComponent, WorldPartitionGridSize, P);
	return JsonToString(PlanJson(M, P));
}

ALandscape* UStreetscapeLandscapeImporter::FindLandscape()
{
	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World) return nullptr;
	for (TActorIterator<ALandscape> It(World); It; ++It)
	{
		return *It;
	}
	return nullptr;
}

int32 UStreetscapeLandscapeImporter::CountLandscapeComponents(ALandscapeProxy* Proxy)
{
	if (!Proxy) return -1;
	if (ULandscapeInfo* Info = Proxy->GetLandscapeInfo())
	{
		return Info->XYtoComponentMap.Num();
	}
	return Proxy->LandscapeComponents.Num();
}

int32 UStreetscapeLandscapeImporter::CountStreamingProxies(ALandscapeProxy* Proxy)
{
	if (!Proxy) return -1;
	ULandscapeInfo* Info = Proxy->GetLandscapeInfo();
	if (!Info) return -1;
	int32 N = 0;
	Info->ForEachLandscapeProxy([&N](ALandscapeProxy* P) -> bool
	{
		if (P && P->IsA<ALandscapeStreamingProxy>()) ++N;
		return true;
	});
	return N;
}

double UStreetscapeLandscapeImporter::ProbeHeightM(ALandscapeProxy* Proxy, double XM, double YM, bool bUseCollision)
{
	if (!Proxy) return (double)NAN;
	const FVector Loc(100.0 * XM, -100.0 * YM, 0.0);
	TOptional<float> H = Proxy->GetHeightAtLocation(Loc, bUseCollision ? EHeightfieldSource::Complex : EHeightfieldSource::Editor);
	if (!H.IsSet()) return (double)NAN;
	return (double)H.GetValue() / 100.0;
}

double UStreetscapeLandscapeImporter::TraceDownZM(double XM, double YM, double TopZM, double BottomZM)
{
	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World) return (double)NAN;
	const FVector Start(100.0 * XM, -100.0 * YM, 100.0 * TopZM);
	const FVector End(100.0 * XM, -100.0 * YM, 100.0 * BottomZM);
	FHitResult Hit;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(StreetscapeProbe), /*bTraceComplex=*/true);
	if (World->LineTraceSingleByChannel(Hit, Start, End, ECC_WorldStatic, Params))
	{
		return Hit.ImpactPoint.Z / 100.0;
	}
	return (double)NAN;
}

double UStreetscapeLandscapeImporter::RssMb()
{
	return NowRssMb();
}

FString UStreetscapeLandscapeImporter::LandscapeStateJson(ALandscapeProxy* Proxy)
{
	TSharedRef<FJsonObject> J = MakeShared<FJsonObject>();
	if (!Proxy)
	{
		J->SetStringField(TEXT("error"), TEXT("no landscape"));
		return JsonToString(J);
	}
	ULandscapeInfo* Info = Proxy->GetLandscapeInfo();
	int32 MinX = 0, MinY = 0, MaxX = 0, MaxY = 0;
	if (Info && Info->GetLandscapeExtent(MinX, MinY, MaxX, MaxY))
	{
		TArray<TSharedPtr<FJsonValue>> E;
		E.Add(MakeShared<FJsonValueNumber>(MinX));
		E.Add(MakeShared<FJsonValueNumber>(MinY));
		E.Add(MakeShared<FJsonValueNumber>(MaxX));
		E.Add(MakeShared<FJsonValueNumber>(MaxY));
		J->SetArrayField(TEXT("extent"), E);
	}
	J->SetNumberField(TEXT("components"), CountLandscapeComponents(Proxy));
	J->SetNumberField(TEXT("proxies"), CountStreamingProxies(Proxy));
	const FVector Loc = Proxy->GetActorLocation();
	const FVector Scale = Proxy->GetActorScale3D();
	TArray<TSharedPtr<FJsonValue>> L, S;
	L.Add(MakeShared<FJsonValueNumber>(Loc.X)); L.Add(MakeShared<FJsonValueNumber>(Loc.Y)); L.Add(MakeShared<FJsonValueNumber>(Loc.Z));
	S.Add(MakeShared<FJsonValueNumber>(Scale.X)); S.Add(MakeShared<FJsonValueNumber>(Scale.Y)); S.Add(MakeShared<FJsonValueNumber>(Scale.Z));
	J->SetArrayField(TEXT("location_cm"), L);
	J->SetArrayField(TEXT("scale"), S);
	J->SetStringField(TEXT("label"), Proxy->GetActorLabel());
	if (Info)
	{
		J->SetNumberField(TEXT("component_size_quads"), Info->ComponentSizeQuads);
		J->SetNumberField(TEXT("subsection_size_quads"), Info->SubsectionSizeQuads);
		J->SetNumberField(TEXT("num_subsections"), Info->ComponentNumSubsections);
	}
	if (Proxy->LandscapeMaterial) J->SetStringField(TEXT("material"), Proxy->LandscapeMaterial->GetPathName());
	return JsonToString(J);
}

FString UStreetscapeLandscapeImporter::LandscapeLayersJson(ALandscapeProxy* Proxy)
{
	TSharedRef<FJsonObject> J = MakeShared<FJsonObject>();
	if (!Proxy)
	{
		J->SetStringField(TEXT("error"), TEXT("no landscape"));
		return JsonToString(J);
	}
	const FName VisName = ALandscapeProxy::VisibilityLayer ? ALandscapeProxy::VisibilityLayer->GetLayerName() : NAME_None;
	J->SetStringField(TEXT("visibility_layer_name"), VisName.ToString());

	TArray<TSharedPtr<FJsonValue>> Target;
	bool bHasVisibility = false;
	int32 GroundFound = 0;
	for (const TPair<FName, FLandscapeTargetLayerSettings>& Pair : Proxy->GetTargetLayers())   // LandscapeProxy.h:1627
	{
		TSharedRef<FJsonObject> L = MakeShared<FJsonObject>();
		L->SetStringField(TEXT("name"), Pair.Key.ToString());
		L->SetStringField(TEXT("layer_info"), Pair.Value.LayerInfoObj ? Pair.Value.LayerInfoObj->GetPathName() : TEXT(""));
		const bool bVis = (Pair.Key == VisName);
		L->SetBoolField(TEXT("is_visibility"), bVis);
		bHasVisibility |= bVis;
		for (int32 B = 0; B < 4; ++B)
		{
			if (Pair.Key == FName(GGroundLayers[B])) ++GroundFound;
		}
		Target.Add(MakeShared<FJsonValueObject>(L));
	}
	J->SetArrayField(TEXT("target_layers"), Target);
	J->SetNumberField(TEXT("target_layer_count"), Target.Num());
	J->SetBoolField(TEXT("has_visibility_layer"), bHasVisibility);
	J->SetNumberField(TEXT("ground_layers_found"), GroundFound);

	TArray<TSharedPtr<FJsonValue>> Missing;
	for (int32 B = 0; B < 4; ++B)
	{
		if (!Proxy->HasTargetLayer(FName(GGroundLayers[B]))) Missing.Add(MakeShared<FJsonValueString>(GGroundLayers[B]));
	}
	J->SetArrayField(TEXT("ground_layers_missing"), Missing);

	if (ULandscapeInfo* Info = Proxy->GetLandscapeInfo())
	{
		TArray<TSharedPtr<FJsonValue>> Known;
		for (const FLandscapeInfoLayerSettings& S : Info->Layers)
		{
			Known.Add(MakeShared<FJsonValueString>(S.GetLayerName().ToString()));
		}
		J->SetArrayField(TEXT("info_layers"), Known);
	}
	return JsonToString(J);
}

double UStreetscapeLandscapeImporter::ProbeLayerWeight(ALandscapeProxy* Proxy, double XM, double YM, FName LayerName)
{
	if (!Proxy) return -1.0;
	ULandscapeInfo* Info = Proxy->GetLandscapeInfo();
	if (!Info || Info->ComponentSizeQuads <= 0) return -1.0;
	ULandscapeLayerInfoObject* LayerInfo = Info->GetLayerInfoByName(LayerName);          // LandscapeInfo.h:283
	if (!LayerInfo && LayerName == (ALandscapeProxy::VisibilityLayer ? ALandscapeProxy::VisibilityLayer->GetLayerName() : NAME_None))
	{
		LayerInfo = ALandscapeProxy::VisibilityLayer;
	}
	if (!LayerInfo) return -1.0;

	const FVector Loc(100.0 * XM, -100.0 * YM, 0.0);
	ALandscape* Land = Info->LandscapeActor.Get();
	if (!Land) return -1.0;
	const FVector Local = Land->LandscapeActorToWorld().InverseTransformPosition(Loc);
	const FIntPoint Key(FMath::FloorToInt(Local.X / (double)Info->ComponentSizeQuads),
		FMath::FloorToInt(Local.Y / (double)Info->ComponentSizeQuads));
	ULandscapeComponent* const* Found = Info->XYtoComponentMap.Find(Key);                // LandscapeInfo.h:189
	if (!Found || !*Found) return -1.0;
	return (double)(*Found)->GetLayerWeightAtLocation(Loc, LayerInfo);                    // LandscapeEdit.cpp:2816
}

ALandscape* UStreetscapeLandscapeImporter::ImportSite(const FString& ManifestPath, int32 QuadsPerSection, int32 SectionsPerComponent, int32 WorldPartitionGridSize,
	const FString& MaterialPath, const FString& LayerInfoPackagePath, int32 MaxComponentsPerImport, FString& OutReportJson)
{
	const double T0 = FPlatformTime::Seconds();
	TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
	TSharedRef<FJsonObject> Rss = MakeShared<FJsonObject>();
	TSharedRef<FJsonObject> Seconds = MakeShared<FJsonObject>();
	Rss->SetNumberField(TEXT("before"), NowRssMb());

	auto Finish = [&](ALandscape* L, const FString& Problem) -> ALandscape*
	{
		if (!Problem.IsEmpty()) Report->SetStringField(TEXT("error"), Problem);
		Report->SetBoolField(TEXT("ok"), Problem.IsEmpty());
		Report->SetObjectField(TEXT("rss_mb"), Rss);
		Seconds->SetNumberField(TEXT("total"), FPlatformTime::Seconds() - T0);
		Report->SetObjectField(TEXT("seconds"), Seconds);
		OutReportJson = JsonToString(Report);
		if (!Problem.IsEmpty()) UE_LOG(LogStreetscapeEditor, Error, TEXT("ImportSite: %s"), *Problem);
		return L;
	};

	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World) return Finish(nullptr, TEXT("no editor world"));
	if (!UWorld::IsPartitionedWorld(World)) return Finish(nullptr, TEXT("the editor world is not partitioned (World Partition is required, UE_PLAN.md 3.6)"));
	if (FPackageName::IsTempPackage(World->GetPackage()->GetName())) return Finish(nullptr, TEXT("the map is an unsaved temp package; save it first"));
	if (FindLandscape() != nullptr) return Finish(nullptr, TEXT("this map already holds an ALandscape - import into a fresh map"));

	FManifest M;
	FString Problem;
	if (!ReadManifest(ManifestPath, M, Problem)) return Finish(nullptr, FString::Printf(TEXT("manifest: %s"), *Problem));

	FPlan P;
	MakePlan(M, QuadsPerSection, SectionsPerComponent, WorldPartitionGridSize, P);
	TSharedRef<FJsonObject> Plan = PlanJson(M, P);
	for (const auto& KV : Plan->Values) Report->SetField(FString(*KV.Key), KV.Value);
	UE_LOG(LogStreetscapeEditor, Log, TEXT("ImportSite plan: %s"), *JsonToString(Plan));

	const double TArrays = FPlatformTime::Seconds();
	FAssembly A;
	if (!BuildArrays(M, P, A)) return Finish(nullptr, FString::Printf(TEXT("assembly: %s"), *A.Problem));
	Seconds->SetNumberField(TEXT("arrays"), FPlatformTime::Seconds() - TArrays);
	Rss->SetNumberField(TEXT("after_arrays"), NowRssMb());
	Report->SetNumberField(TEXT("tiles_read"), A.TilesRead);
	Report->SetNumberField(TEXT("vis_files_read"), A.VisFilesRead);
	Report->SetNumberField(TEXT("weight_files_read"), A.WeightFilesRead);
	Report->SetNumberField(TEXT("shared_edge_samples_checked"), (double)A.SharedEdgeSamples);
	Report->SetNumberField(TEXT("shared_edge_max_h16_delta"), A.SharedEdgeMaxDelta);
	Report->SetNumberField(TEXT("vis_hole_samples"), (double)A.HolesFromVis);
	{
		TSharedRef<FJsonObject> Hist = MakeShared<FJsonObject>();
		for (const auto& KV : A.WeightSumHistogram) Hist->SetNumberField(FString::FromInt(KV.Key), (double)KV.Value);
		Report->SetObjectField(TEXT("weight_sum_histogram"), Hist);
	}

	// --- layer infos (UE_PLAN.md 3.5)
	TArray<FLandscapeImportLayerInfo> Layers;
	TArray<ULandscapeLayerInfoObject*> GroundLayerInfos;
	for (int32 B = 0; B < 4; ++B)
	{
		const FName LayerName(GGroundLayers[B]);
		ULandscapeLayerInfoObject* LI = GetOrCreateLayerInfo(LayerName, LayerInfoPackagePath);
		if (!LI) return Finish(nullptr, FString::Printf(TEXT("could not create layer info for %s under %s"), *LayerName.ToString(), *LayerInfoPackagePath));
		GroundLayerInfos.Add(LI);
		FLandscapeImportLayerInfo Info(LayerName);
		Info.LayerInfo = LI;
		Info.LayerData = A.Weights[B];
		Layers.Add(MoveTemp(Info));
	}
	ULandscapeLayerInfoObject* VisibilityInfo = ALandscapeProxy::VisibilityLayer;
	if (!VisibilityInfo) return Finish(nullptr, TEXT("ALandscapeProxy::VisibilityLayer is null"));
	{
		FLandscapeImportLayerInfo Info(VisibilityInfo->GetLayerName());
		Info.LayerInfo = VisibilityInfo;
		Info.LayerData = A.Vis;
		Layers.Add(MoveTemp(Info));
	}
	Report->SetStringField(TEXT("visibility_layer"), VisibilityInfo->GetLayerName().ToString());

	// --- the actor
	const FVector ActorLoc = P.ActorLocation(M);
	ALandscape* Landscape = World->SpawnActor<ALandscape>(ActorLoc, FRotator::ZeroRotator);
	if (!Landscape) return Finish(nullptr, TEXT("SpawnActor<ALandscape> failed"));
	Landscape->SetActorRelativeScale3D(FVector(100.0, 100.0, 100.0));
	if (!MaterialPath.IsEmpty())
	{
		UMaterialInterface* Mat = LoadObject<UMaterialInterface>(nullptr, *MaterialPath);
		if (!Mat) UE_LOG(LogStreetscapeEditor, Warning, TEXT("ImportSite: landscape material %s not found - using the engine default"), *MaterialPath);
		Landscape->LandscapeMaterial = Mat;
		Report->SetStringField(TEXT("landscape_material"), Mat ? Mat->GetPathName() : TEXT(""));
	}
	Landscape->StaticLightingLOD = (int32)FMath::DivideAndRoundUp(FMath::CeilLogTwo(((uint32)P.Wp * (uint32)P.Hp) / (2048u * 2048u) + 1u), (uint32)2);

	// --- gate (UE_PLAN.md 3.6 step 6): one Import, or the region path of 3.7
	// UE_PLAN.md 3.7 uses 16x16-component regions (the editor's WorldPartitionRegionSize default). MaxComponents
	// doubles as the knob: its square root is the region side, clamped to [1, 16], so --max-components 64 gives
	// 8x8 regions when 16x16 still proves too big for this machine.
	const int32 RegionSize = FMath::Clamp((int32)FMath::FloorToDouble(FMath::Sqrt((double)FMath::Max(1, MaxComponentsPerImport))), 1, 16);
	const bool bRegions = (MaxComponentsPerImport > 0) && (P.Components() > MaxComponentsPerImport);
	const int32 InitCx = bRegions ? FMath::Min(RegionSize, P.Cx) : P.Cx;
	const int32 InitCy = bRegions ? FMath::Min(RegionSize, P.Cy) : P.Cy;
	const int32 InitW = InitCx * P.Q + 1;
	const int32 InitH = InitCy * P.Q + 1;
	Report->SetBoolField(TEXT("region_path"), bRegions);
	Report->SetNumberField(TEXT("max_components_per_import"), MaxComponentsPerImport);
	Report->SetNumberField(TEXT("region_size_components"), RegionSize);

	TMap<FGuid, TArray<uint16>> HeightPerLayer;
	TMap<FGuid, TArray<FLandscapeImportLayerInfo>> WeightPerLayer;
	if (bRegions)
	{
		TArray<uint16> H;
		ExtractRect(A.Heights, P.Wp, 0, 0, InitW - 1, InitH - 1, H);
		HeightPerLayer.Add(FGuid(), MoveTemp(H));
		TArray<FLandscapeImportLayerInfo> Sub;
		for (const FLandscapeImportLayerInfo& L : Layers)
		{
			FLandscapeImportLayerInfo Copy(L.LayerName);
			Copy.LayerInfo = L.LayerInfo;
			ExtractRect(L.LayerData, P.Wp, 0, 0, InitW - 1, InitH - 1, Copy.LayerData);
			Sub.Add(MoveTemp(Copy));
		}
		WeightPerLayer.Add(FGuid(), MoveTemp(Sub));
	}
	else
	{
		HeightPerLayer.Add(FGuid(), A.Heights);
		WeightPerLayer.Add(FGuid(), Layers);
	}

	const double TImport = FPlatformTime::Seconds();
	Landscape->Import(FGuid::NewGuid(), 0, 0, InitW - 1, InitH - 1, P.Sections, P.Qps, HeightPerLayer, TEXT(""), WeightPerLayer,
		ELandscapeImportAlphamapType::Additive, TArrayView<const FLandscapeLayer>());
	HeightPerLayer.Empty();
	WeightPerLayer.Empty();
	Seconds->SetNumberField(TEXT("import"), FPlatformTime::Seconds() - TImport);
	Rss->SetNumberField(TEXT("after_import"), NowRssMb());

	ULandscapeInfo* Info = Landscape->GetLandscapeInfo();
	if (!Info) return Finish(nullptr, TEXT("GetLandscapeInfo() returned null after Import"));
	Landscape->SetActorLabel(FString::Printf(TEXT("Landscape_%s"), M.Site.IsEmpty() ? TEXT("Site") : *M.Site));
	Info->UpdateLayerInfoMap(Landscape);
	for (ULandscapeLayerInfoObject* LI : GroundLayerInfos)
	{
		if (LI && !Landscape->HasTargetLayer(LI->GetLayerName()))
		{
			Landscape->AddTargetLayer(LI->GetLayerName(), FLandscapeTargetLayerSettings(LI));
		}
	}
	if (!Landscape->HasTargetLayer(VisibilityInfo->GetLayerName()))
	{
		Landscape->AddTargetLayer(VisibilityInfo->GetLayerName(), FLandscapeTargetLayerSettings(VisibilityInfo));
	}

	// --- World Partition grid (UE_PLAN.md 3.4) BEFORE the region loop.
	// ULandscapeSubsystem::ChangeGridSize asserts !ActorsToDelete.Num() (LandscapeSubsystem.cpp:1309) because it is
	// only meant to convert a not-yet-grid-based landscape. Adding the remaining regions first creates streaming
	// proxies at the OLD grid size, and re-gridding then leaves emptied proxies behind -> the assert fires (measured:
	// gate (b) crashed exactly there). The editor's own New Landscape flow calls ChangeGridSize right after the
	// initial Import and before the region loop (NewLandscape.cpp:1288 vs :1292), so we do the same and every proxy
	// the region loop creates is born at the final grid size.
	const double TGrid = FPlatformTime::Seconds();
	if (ULandscapeSubsystem* Subsystem = World->GetSubsystem<ULandscapeSubsystem>())
	{
		if (Subsystem->IsGridBased())
		{
			Subsystem->ChangeGridSize(Info, (uint32)FMath::Max(1, WorldPartitionGridSize));
		}
		else
		{
			Report->SetStringField(TEXT("grid_warning"), TEXT("ULandscapeSubsystem::IsGridBased() is false; ChangeGridSize would be a no-op"));
		}
	}
	Seconds->SetNumberField(TEXT("grid"), FPlatformTime::Seconds() - TGrid);
	Rss->SetNumberField(TEXT("after_grid"), NowRssMb());

	int32 RegionsUsed = 1;
	if (bRegions)
	{
		ULandscapeSubsystem* Subsystem = World->GetSubsystem<ULandscapeSubsystem>();
		if (!Subsystem) return Finish(nullptr, TEXT("no ULandscapeSubsystem"));
		FGuid EditLayerGuid;
		const TArray<const ULandscapeEditLayerBase*> EditLayers = Landscape->GetEditLayersConst();
		if (EditLayers.Num() > 0) EditLayerGuid = EditLayers[0]->GetGuid();

		const double TRegions = FPlatformTime::Seconds();
		const int32 Rx = FMath::DivideAndRoundUp(P.Cx, RegionSize);
		const int32 Ry = FMath::DivideAndRoundUp(P.Cy, RegionSize);
		RegionsUsed = Rx * Ry;
		for (int32 RegY = 0; RegY < Ry; ++RegY)
		{
			for (int32 RegX = 0; RegX < Rx; ++RegX)
			{
				const int32 Cx0 = RegX * RegionSize;
				const int32 Cy0 = RegY * RegionSize;
				const int32 Cx1 = FMath::Min(Cx0 + RegionSize, P.Cx);
				const int32 Cy1 = FMath::Min(Cy0 + RegionSize, P.Cy);
				TArray<FIntPoint> Coords;
				for (int32 Cy = Cy0; Cy < Cy1; ++Cy)
				{
					for (int32 Cx = Cx0; Cx < Cx1; ++Cx) Coords.Add(FIntPoint(Cx, Cy));
				}
				TArray<ALandscapeProxy*> Created;
				AddComponentsForBlock(Info, Subsystem, Coords, Created);

				const int32 X1 = Cx0 * P.Q;
				const int32 Y1 = Cy0 * P.Q;
				const int32 X2 = Cx1 * P.Q;
				const int32 Y2 = Cy1 * P.Q;
				{
					TArray<uint16> H;
					ExtractRect(A.Heights, P.Wp, X1, Y1, X2, Y2, H);
					FScopedSetLandscapeEditingLayer Scope(Landscape, EditLayerGuid, [Landscape] { Landscape->RequestLayersContentUpdate(ELandscapeLayerUpdateMode::Update_Heightmap_All); });
					FHeightmapAccessor<false> HeightAccessor(Info);
					HeightAccessor.SetData(X1, Y1, X2, Y2, H.GetData());
				}
				for (const FLandscapeImportLayerInfo& L : Layers)
				{
					TArray<uint8> Wt;
					ExtractRect(L.LayerData, P.Wp, X1, Y1, X2, Y2, Wt);
					FScopedSetLandscapeEditingLayer Scope(Landscape, EditLayerGuid, [Landscape] { Landscape->RequestLayersContentUpdate(ELandscapeLayerUpdateMode::Update_Weightmap_All); });
					TAlphamapAccessor<false> AlphaAccessor(Info, L.LayerInfo);
					AlphaAccessor.SetData(X1, Y1, X2, Y2, Wt.GetData(), ELandscapeLayerPaintingRestriction::None);
				}
				Info->ForceLayersFullUpdate();
				// Bound the peak: the single-Import attempt on the full site died because thousands of queued
				// TextureDerivedData compiles piled up (log: "AssetCompile memory estimate is greater than
				// available ... MemoryLimit = 0.000 MiB") until the D3D12 heap could not place another 256x256
				// texture and the device hung. Drain the queue and collect after every region instead.
				FAssetCompilingManager::Get().FinishAllCompilation();
				if (Created.Num() > 0) LandscapeEditorUtils::SaveObjects(MakeArrayView(Created));
				CollectGarbage(RF_NoFlags, /*bPerformFullPurge=*/true);
				UE_LOG(LogStreetscapeEditor, Log, TEXT("ImportSite: region (%d, %d) components [%d..%d]x[%d..%d], %d new proxies, %d components total, rss %.0f MB"),
					RegX, RegY, Cx0, Cx1 - 1, Cy0, Cy1 - 1, Created.Num(), Info->XYtoComponentMap.Num(), NowRssMb());
			}
		}
		Seconds->SetNumberField(TEXT("regions"), FPlatformTime::Seconds() - TRegions);
	}
	Report->SetNumberField(TEXT("regions_used"), RegionsUsed);
	Report->SetNumberField(TEXT("components_after_import"), Info->XYtoComponentMap.Num());
	Rss->SetNumberField(TEXT("after_regions"), NowRssMb());

	A.Heights.Empty();
	A.Vis.Empty();
	for (int32 B = 0; B < 4; ++B) A.Weights[B].Empty();
	Layers.Empty();

	// --- save
	const double TSave = FPlatformTime::Seconds();
	UEditorLoadingAndSavingUtils::SaveDirtyPackages(true, true);
	Seconds->SetNumberField(TEXT("save"), FPlatformTime::Seconds() - TSave);
	Rss->SetNumberField(TEXT("after_save"), NowRssMb());

	Report->SetNumberField(TEXT("components"), CountLandscapeComponents(Landscape));
	Report->SetNumberField(TEXT("proxies"), CountStreamingProxies(Landscape));
	{
		int32 MinX = 0, MinY = 0, MaxX = 0, MaxY = 0;
		if (Info->GetLandscapeExtent(MinX, MinY, MaxX, MaxY))
		{
			TArray<TSharedPtr<FJsonValue>> E;
			E.Add(MakeShared<FJsonValueNumber>(MinX));
			E.Add(MakeShared<FJsonValueNumber>(MinY));
			E.Add(MakeShared<FJsonValueNumber>(MaxX));
			E.Add(MakeShared<FJsonValueNumber>(MaxY));
			Report->SetArrayField(TEXT("extent_actual"), E);
		}
	}
	Report->SetStringField(TEXT("landscape"), Landscape->GetPathName());
	Report->SetStringField(TEXT("landscape_label"), Landscape->GetActorLabel());
	return Finish(Landscape, FString());
}

#undef LOCTEXT_NAMESPACE
