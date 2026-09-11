#include "StreetMeshCacheLibrary.h"
#include "DynamicMeshActor.h"
#include "DynamicMesh/DynamicMesh3.h"
#include "DynamicMesh/DynamicMeshAttributeSet.h"
#include "DynamicMesh/MeshNormals.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Misc/FileHelper.h"
#include "Materials/MaterialInterface.h"
#include "Engine/CollisionProfile.h"

// UE 5.8: DynamicMeshActor.h:26, DynamicMeshComponent.h:210/722,
// GeometryCore/Public/DynamicMesh/MeshNormals.h:188. Coordinates are local metres,
// north positive. Match FStreetGeometry::ToDynamicMesh: KEEP indices when reflecting Y;
// GeometryCore's left-handed front-face normal already reverses the cross-product order.
FString UStreetMeshCacheLibrary::ApplyMeshCache(ADynamicMeshActor* Actor, const FString& JsonPath)
{
    using namespace UE::Geometry;
    auto Fail=[](const TCHAR* Why){ return FString::Printf(TEXT("{\"ok\":false,\"error\":\"%s\"}"),Why); };
    if (!Actor) return Fail(TEXT("Missing target"));
    FString Text; TSharedPtr<FJsonObject> J;
    if (!FFileHelper::LoadFileToString(Text,*JsonPath) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),J) || !J)
        return Fail(TEXT("Invalid JSON"));
    FString Frame;
    const TArray<TSharedPtr<FJsonValue>> *Verts=nullptr,*Tris=nullptr,*Mats=nullptr;
    if (!J->TryGetStringField(TEXT("frame"),Frame) || Frame!=TEXT("local-metres, X east, Y north, Z up") ||
        !J->TryGetArrayField(TEXT("vertices"),Verts) || !J->TryGetArrayField(TEXT("triangles"),Tris) || !J->TryGetArrayField(TEXT("materials"),Mats))
        return Fail(TEXT("Missing cache fields or wrong frame"));
    if (Verts->Num()<3 || Verts->Num()>2000000 || Tris->Num()<1 || Tris->Num()>4000000)
        return Fail(TEXT("Invalid mesh size"));
    TArray<UMaterialInterface*> Materials;
    for (const auto& V:*Mats) {
        FString Path; if (!V->TryGetString(Path) || !Path.StartsWith(TEXT("/Game/Thanet/"))) return Fail(TEXT("Invalid material path"));
        auto* M=LoadObject<UMaterialInterface>(nullptr,*Path); if (!M) return Fail(TEXT("Missing material")); Materials.Add(M);
    }
    FDynamicMesh3 Mesh(true,false,true,false); Mesh.EnableAttributes(); Mesh.Attributes()->EnableMaterialID();
    for (const auto& V:*Verts) {
        const TArray<TSharedPtr<FJsonValue>>* A=nullptr; double X,Y,Z;
        if (!V->TryGetArray(A)||A->Num()!=3||!(*A)[0]->TryGetNumber(X)||!(*A)[1]->TryGetNumber(Y)||!(*A)[2]->TryGetNumber(Z)||
            !FMath::IsFinite(X)||!FMath::IsFinite(Y)||!FMath::IsFinite(Z)||FMath::Abs(X)>20000||FMath::Abs(Y)>20000||FMath::Abs(Z)>2000)
            return Fail(TEXT("Invalid vertex"));
        Mesh.AppendVertex(FVector3d(100*X,-100*Y,100*Z));
    }
    for (const auto& V:*Tris) {
        const TArray<TSharedPtr<FJsonValue>>* A=nullptr;
        if (!V->TryGetArray(A)||A->Num()!=4) return Fail(TEXT("Invalid face"));
        int32 Q[4]; for(int K=0;K<4;++K) {double D;
            if (!(*A)[K]->TryGetNumber(D)||!FMath::IsFinite(D)||D!=FMath::FloorToDouble(D)||D<0||D>4000000) return Fail(TEXT("Invalid index")); Q[K]=int32(D);}
        if (Q[0]>=Verts->Num()||Q[1]>=Verts->Num()||Q[2]>=Verts->Num()||Q[3]>=Materials.Num()) return Fail(TEXT("Out of range index"));
        if (FVector3d::CrossProduct(Mesh.GetVertex(Q[1])-Mesh.GetVertex(Q[0]),Mesh.GetVertex(Q[2])-Mesh.GetVertex(Q[0])).SquaredLength()<1e-8)
            return Fail(TEXT("Degenerate triangle"));
        int32 T=Mesh.AppendTriangle(Q[0],Q[1],Q[2]); if(T<0) return Fail(TEXT("Nonmanifold or duplicate triangle"));
        Mesh.Attributes()->GetMaterialID()->SetValue(T,Q[3]);
        auto* UV=Mesh.Attributes()->PrimaryUV();
        FIndex3i U;
        for(int K=0;K<3;++K) {const auto P=Mesh.GetVertex(Q[K]);U[K]=UV->AppendElement(FVector2f(float(P.X/400.),float(-P.Y/400.)));}
        UV->SetTriangle(T,U);
    }
    FMeshNormals::InitializeOverlayToPerVertexNormals(Mesh.Attributes()->PrimaryNormals(),false);
    // All parsing, materials and mesh topology have passed before altering the supplied actor.
    Actor->Modify(); auto* C=Actor->GetDynamicMeshComponent(); C->Modify();
    C->SetMesh(MoveTemp(Mesh));
    C->SetTangentsType(EDynamicMeshComponentTangentsMode::AutoCalculated);
    for(int32 I=0;I<Materials.Num();++I) C->SetMaterial(I,Materials[I]);
    C->SetCollisionProfileName(UCollisionProfile::BlockAll_ProfileName);
    C->SetComplexAsSimpleCollisionEnabled(true,true);
    Actor->MarkPackageDirty();
    return FString::Printf(TEXT("{\"ok\":true,\"vertices\":%d,\"triangles\":%d}"),Verts->Num(),Tris->Num());
}
