using System.IO;
using UnityEngine;
using UnityEditor;

/// Gives every terrain a flat TerrainLayer so it stops rendering Unity's default checkerboard.
/// Grey-box grade: one muted grass/earth tone. The real splatmap comes from OSM landcover later.
public static class MargateTerrainMaterial
{
    [MenuItem("Margate/4 - Terrain Material")]
    public static void Apply()
    {
        Directory.CreateDirectory("Assets/Generated");
        const string layerPath = "Assets/Generated/TL_Ground.terrainlayer";
        var layer = AssetDatabase.LoadAssetAtPath<TerrainLayer>(layerPath);
        if (layer == null)
        {
            var tex = new Texture2D(8, 8);
            var px = new Color[64];
            for (int i = 0; i < 64; i++) px[i] = new Color(0.50f, 0.52f, 0.44f);   // muted Kent green-grey
            tex.SetPixels(px); tex.Apply();
            File.WriteAllBytes("Assets/Generated/T_Ground.png", tex.EncodeToPNG());
            AssetDatabase.ImportAsset("Assets/Generated/T_Ground.png");
            layer = new TerrainLayer {
                diffuseTexture = AssetDatabase.LoadAssetAtPath<Texture2D>("Assets/Generated/T_Ground.png"),
                tileSize = new Vector2(8, 8)
            };
            AssetDatabase.CreateAsset(layer, layerPath);
        }
        // URP needs its own terrain shader; leaving materialTemplate null falls back to the
        // built-in pipeline's terrain shader, which URP cannot resolve -> magenta.
        const string matPath = "Assets/Generated/M_Terrain.mat";
        var mat = AssetDatabase.LoadAssetAtPath<Material>(matPath);
        if (mat == null)
        {
            var sh = Shader.Find("Universal Render Pipeline/Terrain/Lit");
            if (sh == null) { Debug.LogError("URP terrain shader not found"); return; }
            mat = new Material(sh);
            AssetDatabase.CreateAsset(mat, matPath);
        }
        int n = 0;
        foreach (var t in Object.FindObjectsByType<Terrain>(FindObjectsSortMode.None))
        {
            t.terrainData.terrainLayers = new[] { layer };
            t.materialTemplate = mat;
            n++;
        }
        AssetDatabase.SaveAssets();
        Debug.Log($"[Margate] terrain material applied to {n} tiles.");
    }
}
