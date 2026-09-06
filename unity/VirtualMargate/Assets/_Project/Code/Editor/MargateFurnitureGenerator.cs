using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;
using UnityEditor;

/// Places street furniture from the pipeline's per-tile placement records (step 10).
///
/// Each record names a prop, a local-metre position, a yaw, and usually a height taken
/// from the draped road centreline plus the kerb. Records with "y":null were not near a
/// road; those are dropped onto the terrain here. Prefabs are the ones Margate/7 builds.
public static class MargateFurnitureGenerator
{
    const string SrcDir = "../../data/out/furniture";
    static readonly Dictionary<string, string> Prefabs = new()
    {
        { "LitterBin", "Assets/_Project/Art/Props/LitterBin/P_LitterBin.prefab" },
    };

    [MenuItem("Margate/8 - Scatter Street Furniture")]
    public static void Generate()
    {
        string src = Path.GetFullPath(Path.Combine(Application.dataPath, "..", SrcDir));
        if (!Directory.Exists(src)) { Debug.LogError($"[Margate] No furniture data at {src} -- run ./run.sh --only 10"); return; }

        var prefabs = new Dictionary<string, GameObject>();
        foreach (var kv in Prefabs)
        {
            var p = AssetDatabase.LoadAssetAtPath<GameObject>(kv.Value);
            if (p == null) Debug.LogError($"[Margate] Missing {kv.Value} -- run Margate/7 - Build Props first");
            else prefabs[kv.Key] = p;
        }
        if (prefabs.Count == 0) return;

        var root = GameObject.Find("Furniture");
        if (root != null) Object.DestroyImmediate(root);
        root = new GameObject("Furniture");

        int placed = 0, onTerrain = 0, skipped = 0, tiles = 0;
        foreach (var path in Directory.GetFiles(src, "furniture_*.jsonl"))
        {
            var tile = new GameObject(Path.GetFileNameWithoutExtension(path).Replace("furniture_", "Furniture_"));
            tile.transform.parent = root.transform;
            foreach (var line in File.ReadLines(path))
            {
                string prop = Str(line, "prop");
                if (prop == null || !prefabs.TryGetValue(prop, out var prefab)) { skipped++; continue; }
                float x = Num(line, "\"x\":"), z = Num(line, "\"z\":"), yaw = Num(line, "\"yaw\":");
                if (!TryNum(line, "\"y\":", out float y)) { y = GroundY(x, z); onTerrain++; }   // "y":null
                var go = (GameObject)PrefabUtility.InstantiatePrefab(prefab, tile.transform);
                go.name = $"{prop}_{Str(line, "id")}";
                go.transform.SetPositionAndRotation(new Vector3(x, y, z), Quaternion.Euler(0f, yaw, 0f));
                go.isStatic = true;
                placed++;
            }
            tiles++;
        }
        Debug.Log($"[Margate] {placed} furniture items across {tiles} tiles ({onTerrain} dropped onto terrain, {skipped} skipped: unknown prop).");
    }

    /// Terrain height under (x, z). The world is 91 separate Terrain tiles, so find the one containing the point.
    static float GroundY(float x, float z)
    {
        foreach (var t in Terrain.activeTerrains)
        {
            var p = t.transform.position; var s = t.terrainData.size;
            if (x >= p.x && x < p.x + s.x && z >= p.z && z < p.z + s.z)
                return t.SampleHeight(new Vector3(x, 0f, z)) + p.y;
        }
        Debug.LogWarning($"[Margate] No terrain under ({x:0.#}, {z:0.#}); placing at y=0");
        return 0f;
    }

    // Same minimal JSONL readers as MargateRoadGenerator -- the records are flat, one per line.
    static string Str(string s, string k)
    {
        int p = s.IndexOf($"\"{k}\":\""); if (p < 0) return null;
        p += k.Length + 4; int e = s.IndexOf('"', p); return s.Substring(p, e - p);
    }
    static float Num(string s, string key) => TryNum(s, key, out var v) ? v : 0f;
    static bool TryNum(string s, string key, out float v)
    {
        v = 0f;
        int p = s.IndexOf(key); if (p < 0) return false;
        p += key.Length; int e = p;
        while (e < s.Length && (char.IsDigit(s[e]) || s[e] == '-' || s[e] == '.')) e++;
        return e > p && float.TryParse(s.Substring(p, e - p), NumberStyles.Float, CultureInfo.InvariantCulture, out v);
    }
}
