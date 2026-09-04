using UnityEngine;

/// Fixes Unity world space to British National Grid.
/// x = BNG_Easting - E0, z = BNG_Northing - N0, y = metres above Ordnance Datum Newlyn.
/// Because y is honest ODN, mean sea level sits at y = 0 and a tide slider is just y +/- 2.4.
public static class MargateWorld
{
    public const double E0 = 632800.0;   // BNG easting of world origin
    public const double N0 = 168200.0;   // BNG northing of world origin
    public const float  TileM = 512f;    // tile size in metres
    public const int    HeightmapRes = 513;   // 513 samples over 512 m == exactly 1 m/sample
    public const float  YBase = -5f;     // ODN metres at terrain y=0
    public const float  YSize = 60f;     // terrain vertical span (measured DTM: -2.91 .. 49.81)
    public const int    NX = 13, NY = 7;

    public static Vector3 FromBng(double e, double n, float odn) =>
        new Vector3((float)(e - E0), odn, (float)(n - N0));

    public static Vector2 TileOrigin(int i, int j) => new Vector2(i * TileM, j * TileM);
}
