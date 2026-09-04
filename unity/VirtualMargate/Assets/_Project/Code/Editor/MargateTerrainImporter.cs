using System.IO;
using UnityEngine;
using UnityEditor;

/// Builds one Unity Terrain per 512 m tile from the pipeline's 16-bit RAW heightmaps.
/// The RAW is written south-row-first to match TerrainData's heights[z, x] indexing,
/// and each tile's edge row is shared with its neighbour by construction, so terrains
/// meet seamlessly with no stitching pass.
public static class MargateTerrainImporter
{
    const string RawDir = "../../data/out/terrain";
    const string TdDir  = "Assets/Generated/Terrain";

    [MenuItem("Margate/1 - Import Terrain")]
    public static void Import()
    {
        string src = Path.GetFullPath(Path.Combine(Application.dataPath, "..", RawDir));
        if (!Directory.Exists(src)) { Debug.LogError($"No heightmaps at {src}"); return; }
        Directory.CreateDirectory(TdDir);

        var root = GameObject.Find("Terrain") ?? new GameObject("Terrain");
        int res = MargateWorld.HeightmapRes, made = 0;
        var buf = new byte[res * res * 2];
        var h   = new float[res, res];

        for (int i = 0; i < MargateWorld.NX; i++)
        for (int j = 0; j < MargateWorld.NY; j++)
        {
            string raw = Path.Combine(src, $"hm_x{i}_y{j}.raw");
            if (!File.Exists(raw)) continue;
            using (var fs = File.OpenRead(raw)) { int got = 0; while (got < buf.Length) { int r = fs.Read(buf, got, buf.Length - got); if (r <= 0) break; got += r; } }

            for (int z = 0; z < res; z++)
                for (int x = 0; x < res; x++)
                {
                    int o = (z * res + x) * 2;
                    h[z, x] = (buf[o] | (buf[o + 1] << 8)) / 65535f;
                }

            var td = new TerrainData
            {
                heightmapResolution = res,
                size = new Vector3(MargateWorld.TileM, MargateWorld.YSize, MargateWorld.TileM),
                alphamapResolution = 128,
                baseMapResolution  = 128
            };
            td.SetHeights(0, 0, h);
            AssetDatabase.CreateAsset(td, $"{TdDir}/Terrain_x{i}_y{j}.asset");

            var go = Terrain.CreateTerrainGameObject(td);
            go.name = $"Terrain_x{i}_y{j}";
            go.transform.parent = root.transform;
            go.transform.position = new Vector3(i * MargateWorld.TileM,
                                                MargateWorld.YBase,
                                                j * MargateWorld.TileM);
            go.GetComponent<Terrain>().heightmapPixelError = 3f;
            made++;
        }
        AssetDatabase.SaveAssets();
        Debug.Log($"[Margate] Imported {made} terrain tiles ({made * 0.262f:F1} km2).");
    }
}
