using System.IO;
using UnityEngine;
using UnityEditor;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// Sea surface + beach/cliff terrain layers.
///
/// The sea is a tessellated grid only on tiles whose terrain dips below the water
/// line, plus one coarse skirt out to the horizon. It needs no clipping to the
/// coastline: the terrain occludes it wherever the ground is above the water, which
/// is exactly the real waterline and costs nothing.
public static class MargateCoastGenerator
{
    const string SrcDir  = "../../data/out/coast";
    const string OutDir  = "Assets/Generated/Coast";
    const int    Div     = 96;      // 512/96 = 5.3 m -- enough for 14-44 m swell
    const float  SkirtM  = 18000f;  // open sea to the horizon

    [MenuItem("Margate/6 - Generate Sea and Beach")]
    public static void Generate()
    {
        string src = Path.GetFullPath(Path.Combine(Application.dataPath, "..", SrcDir));
        string manifestPath = Path.Combine(src, "coast_manifest.json");
        if (!File.Exists(manifestPath)) { Debug.LogError($"No coast data at {src}"); return; }
        Directory.CreateDirectory(OutDir);

        var man = JsonUtility.FromJson<Manifest>(File.ReadAllText(manifestPath));
        float waterY = man.water_level;

        EnableOpaqueAndDepth();
        int painted = PaintTerrain(src, man.splat_res);

        var old = GameObject.Find("Sea"); if (old) Object.DestroyImmediate(old);
        var root = GameObject.Find("Water"); if (root) Object.DestroyImmediate(root);
        root = new GameObject("Water");
        root.transform.position = Vector3.zero;

        var mat = WaterMaterial();
        var terrains = Object.FindObjectsByType<Terrain>(FindObjectsSortMode.None);

        int n = 0;
        for (int w = 0; w + 1 < man.water_tiles_flat.Length; w += 2)
        {
            int i = man.water_tiles_flat[w], j = man.water_tiles_flat[w + 1];
            var mesh = Grid($"Sea_x{i}_y{j}", MargateWorld.TileM, Div,
                            new Vector2(i * MargateWorld.TileM, j * MargateWorld.TileM), waterY, terrains);
            AddPiece(root.transform, $"Sea_x{i}_y{j}", mesh, mat, waterY);
            n++;
        }
        // open sea beyond the surveyed area, so the horizon isn't an empty edge
        float cx = MargateWorld.NX * MargateWorld.TileM * 0.5f;
        float cz = MargateWorld.NY * MargateWorld.TileM * 0.5f;
        var skirt = Grid("Sea_Open", SkirtM, 80, new Vector2(cx - SkirtM * 0.5f, cz - SkirtM * 0.5f));
        AddPiece(root.transform, "Sea_Open", skirt, mat, waterY - 0.02f);

        AssetDatabase.SaveAssets();
        Debug.Log($"[Margate] sea: {n} tiles + horizon skirt at y={waterY} m ODN; "
                + $"terrain splat painted on {painted} tiles.");
    }

    [System.Serializable] class Manifest {
        public float water_level; public int splat_res; public int tile_m;
        public int[] water_tiles_flat; public string[] layers;
    }

    static void AddPiece(Transform parent, string name, Mesh m, Material mat, float y)
    {
        var go = new GameObject(name);
        go.transform.parent = parent;
        go.transform.position = new Vector3(0, y, 0);
        go.AddComponent<MeshFilter>().sharedMesh = m;
        var r = go.AddComponent<MeshRenderer>();
        r.sharedMaterial = mat;
        r.shadowCastingMode = ShadowCastingMode.Off;   // water casting shadows looks wrong
        r.receiveShadows = false;
    }

    /// Flat XZ grid. Winding is (a,c,b)/(b,c,d) so the normal points UP -- getting
    /// this backwards silently backface-culls the whole surface.
    static Mesh Grid(string name, float size, int div, Vector2 origin, float waterY = 0f, Terrain[] terr = null)
    {
        var v = new Vector3[(div + 1) * (div + 1)];
        var uv = new Vector2[v.Length];
        var col = new Color32[v.Length];
        var t = new int[div * div * 6];
        float s = size / div;
        for (int z = 0; z <= div; z++)
            for (int x = 0; x <= div; x++)
            {
                int k = z * (div + 1) + x;
                var p = new Vector3(origin.x + x * s, 0, origin.y + z * s);
                v[k]  = p;
                uv[k] = new Vector2(x / (float)div, z / (float)div);
                // Shore factor: how deep the water is here, normalised over 2.5 m.
                // The shader multiplies wave displacement by this, so swell flattens
                // as it shoals instead of washing over the sand.
                float g = SampleGround(terr, p);
                col[k] = (Color32)new Color(Mathf.Clamp01((waterY - g) / 2.5f), 0, 0, 1);
            }
        int o = 0;
        for (int z = 0; z < div; z++)
            for (int x = 0; x < div; x++)
            {
                int a = z * (div + 1) + x, b = a + 1, c = a + div + 1, d = c + 1;
                t[o++] = a; t[o++] = c; t[o++] = b;
                t[o++] = b; t[o++] = c; t[o++] = d;
            }
        var m = new Mesh { name = name, indexFormat = IndexFormat.UInt32 };
        m.vertices = v; m.uv = uv; m.colors32 = col; m.triangles = t;
        m.RecalculateNormals(); m.RecalculateBounds();
        // waves displace in the vertex shader, so give the bounds headroom or the
        // mesh gets frustum-culled early at grazing angles
        var bb = m.bounds; bb.Expand(new Vector3(0, 12f, 0)); m.bounds = bb;
        AssetDatabase.CreateAsset(m, $"{OutDir}/{name}.asset");
        return m;
    }

    static float SampleGround(Terrain[] terr, Vector3 p)
    {
        if (terr == null) return -9999f;      // open-sea skirt: always full depth
        foreach (var t in terr)
        {
            var lp = p - t.transform.position;
            if (lp.x < 0 || lp.z < 0 || lp.x > t.terrainData.size.x || lp.z > t.terrainData.size.z) continue;
            return t.SampleHeight(p) + t.transform.position.y;
        }
        return -9999f;
    }

    static Material WaterMaterial()
    {
        const string p = "Assets/Generated/M_Water.mat";
        var sh = Shader.Find("Margate/Water");
        if (sh == null) { Debug.LogError("Margate/Water shader not found -- did it compile?"); return null; }
        var m = AssetDatabase.LoadAssetAtPath<Material>(p);
        if (m == null) { m = new Material(sh); AssetDatabase.CreateAsset(m, p); }
        else m.shader = sh;
        m.renderQueue = 3000;
        return m;
    }

    /// URP does not render _CameraOpaqueTexture or _CameraDepthTexture unless asked;
    /// without them the water has no refraction and no shoreline foam.
    static void EnableOpaqueAndDepth()
    {
        var urp = GraphicsSettings.defaultRenderPipeline as UniversalRenderPipelineAsset;
        if (urp == null) { Debug.LogWarning("URP asset not found"); return; }
        var so = new SerializedObject(urp);
        so.FindProperty("m_RequireOpaqueTexture").boolValue = true;
        so.FindProperty("m_RequireDepthTexture").boolValue = true;
        so.ApplyModifiedProperties();
        EditorUtility.SetDirty(urp);

        // Depth must be copied AFTER OPAQUES. The default here was AfterTransparents,
        // which leaves _CameraDepthTexture unwritten while the water samples it --
        // water depth reads as 0, the foam term saturates, and the whole sea renders
        // as flat white foam.
        foreach (var g in AssetDatabase.FindAssets("t:UniversalRendererData"))
        {
            var rd = AssetDatabase.LoadAssetAtPath<ScriptableRendererData>(AssetDatabase.GUIDToAssetPath(g));
            var rs = new SerializedObject(rd);
            var cd = rs.FindProperty("m_CopyDepthMode");
            if (cd != null && cd.enumValueIndex != 0) { cd.enumValueIndex = 0; rs.ApplyModifiedProperties(); EditorUtility.SetDirty(rd); }
        }
    }

    static int PaintTerrain(string src, int res)
    {
        var layers = new[] {
            MakeLayer("TL_Grass", new Color(0.46f, 0.50f, 0.38f), 0.05f, 9f),
            MakeLayer("TL_Sand",  new Color(0.80f, 0.75f, 0.62f), 0.03f, 6f),
            MakeLayer("TL_Rock",  new Color(0.52f, 0.49f, 0.45f), 0.09f, 12f),
        };
        int n = 0;
        foreach (var terr in Object.FindObjectsByType<Terrain>(FindObjectsSortMode.None))
        {
            var m = System.Text.RegularExpressions.Regex.Match(terr.name, @"x(\d+)_y(\d+)");
            if (!m.Success) continue;
            string png = Path.Combine(src, $"splat_x{m.Groups[1].Value}_y{m.Groups[2].Value}.png");
            if (!File.Exists(png)) continue;

            var tex = new Texture2D(2, 2, TextureFormat.RGB24, false);
            tex.LoadImage(File.ReadAllBytes(png));
            var px = tex.GetPixels();
            int w = tex.width;

            var td = terr.terrainData;
            td.terrainLayers = layers;
            td.alphamapResolution = res;
            var a = new float[res, res, 3];
            for (int y = 0; y < res; y++)
                for (int x = 0; x < res; x++)
                {
                    var c = px[Mathf.Clamp(y, 0, w - 1) * w + Mathf.Clamp(x, 0, w - 1)];
                    float sum = Mathf.Max(c.r + c.g + c.b, 1e-4f);
                    a[y, x, 0] = c.r / sum; a[y, x, 1] = c.g / sum; a[y, x, 2] = c.b / sum;
                }
            td.SetAlphamaps(0, 0, a);
            Object.DestroyImmediate(tex);
            n++;
        }
        return n;
    }

    static TerrainLayer MakeLayer(string name, Color c, float noise, float tile)
    {
        string lp = $"Assets/Generated/{name}.terrainlayer";
        var l = AssetDatabase.LoadAssetAtPath<TerrainLayer>(lp);
        if (l != null) return l;
        string tp = $"Assets/Generated/T_{name}.png";
        const int S = 64;
        var t = new Texture2D(S, S, TextureFormat.RGB24, false);
        var px = new Color[S * S];
        var rnd = new System.Random(name.GetHashCode());
        for (int i = 0; i < px.Length; i++)
        {
            float d = ((float)rnd.NextDouble() - 0.5f) * 2f * noise;
            px[i] = new Color(c.r + d, c.g + d, c.b + d * 0.8f);
        }
        t.SetPixels(px); t.Apply();
        File.WriteAllBytes(tp, t.EncodeToPNG());
        AssetDatabase.ImportAsset(tp);
        Object.DestroyImmediate(t);
        l = new TerrainLayer {
            diffuseTexture = AssetDatabase.LoadAssetAtPath<Texture2D>(tp),
            tileSize = new Vector2(tile, tile)
        };
        AssetDatabase.CreateAsset(l, lp);
        return l;
    }
}
