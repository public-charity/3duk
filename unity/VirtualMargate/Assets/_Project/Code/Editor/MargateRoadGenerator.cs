using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;
using UnityEditor;

/// Builds road ribbons from the pipeline's draped centrelines.
///
/// Each way becomes a quad strip swept along its centreline, with the carriageway
/// inset between two raised pavements and a vertical kerb face joining them. The
/// centrelines already carry per-class height lifts, so where a service road meets
/// a trunk road the higher class wins the depth test -- far cheaper than boolean
/// merging the surfaces at every junction, and it reads correctly at street level.
/// Junctions with 3+ arms get a disc to cover the gap where the ribbons meet.
public static class MargateRoadGenerator
{
    const string SrcDir = "../../data/out/networks";
    const string OutDir = "Assets/Generated/Roads";
    const float  KerbH  = 0.12f;

    class Seg { public string cls, name; public float w, pav, r; public List<Vector3> pts = new(); }

    [MenuItem("Margate/5 - Generate Roads")]
    public static void Generate()
    {
        string src = Path.GetFullPath(Path.Combine(Application.dataPath, "..", SrcDir));
        if (!Directory.Exists(src)) { Debug.LogError($"No network data at {src}"); return; }
        Directory.CreateDirectory(OutDir);

        var roadMat = MakeMat("M_Road", new Color(0.21f, 0.21f, 0.23f));   // tarmac
        var pavMat  = MakeMat("M_Pavement", new Color(0.74f, 0.73f, 0.70f)); // paving slab

        var root = GameObject.Find("Roads");
        if (root != null) UnityEngine.Object.DestroyImmediate(root);
        root = new GameObject("Roads");

        int tiles = 0, segs = 0;
        foreach (var path in Directory.GetFiles(src, "roads_*.jsonl"))
        {
            string tile = Path.GetFileNameWithoutExtension(path).Replace("roads_", "");
            if (!InGrid(tile)) continue;      // roads spill past the terrain grid; skip those

            var rv = new List<Vector3>(); var rt = new List<int>();
            var pv = new List<Vector3>(); var pt = new List<int>();

            foreach (var line in File.ReadLines(path))
            {
                var s = Parse(line); if (s == null) continue;
                if (s.cls == "_junction") { Disc(s.pts[0], s.r, rv, rt); segs++; continue; }
                if (s.pts.Count < 2) continue;
                Ribbon(s.pts, s.w * 0.5f, 0f, rv, rt);                       // carriageway
                if (s.pav > 0.01f)
                {
                    Ribbon(s.pts, s.w * 0.5f + s.pav, KerbH, pv, pt, s.w * 0.5f);  // pavements + kerb
                }
                segs++;
            }
            if (rv.Count == 0 && pv.Count == 0) continue;

            var go = new GameObject($"Roads_{tile}");
            go.transform.parent = root.transform; go.isStatic = true;
            AddMesh(go, "Road_" + tile, rv, rt, roadMat, true);
            if (pv.Count > 0)
            {
                var pgo = new GameObject($"Pavement_{tile}");
                pgo.transform.parent = go.transform; pgo.isStatic = true;
                AddMesh(pgo, "Pav_" + tile, pv, pt, pavMat, false);
            }
            tiles++;
        }
        AssetDatabase.SaveAssets();
        Debug.Log($"[Margate] {segs} road segments across {tiles} tiles.");
    }

    static bool InGrid(string tile)
    {
        var m = System.Text.RegularExpressions.Regex.Match(tile, @"x(-?\d+)_y(-?\d+)");
        if (!m.Success) return false;
        int i = int.Parse(m.Groups[1].Value), j = int.Parse(m.Groups[2].Value);
        return i >= 0 && j >= 0 && i < MargateWorld.NX && j < MargateWorld.NY;
    }

    static Material MakeMat(string name, Color c)
    {
        string p = $"Assets/Generated/{name}.mat";
        var m = AssetDatabase.LoadAssetAtPath<Material>(p);
        if (m == null)
        {
            m = new Material(Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard"))
                { color = c };
            m.SetFloat("_Smoothness", 0.15f);
            AssetDatabase.CreateAsset(m, p);
        }
        return m;
    }

    static void AddMesh(GameObject go, string name, List<Vector3> v, List<int> t, Material mat, bool collide)
    {
        var mesh = new Mesh { name = name, indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 };
        mesh.SetVertices(v); mesh.SetTriangles(t, 0);
        mesh.RecalculateNormals(); mesh.RecalculateBounds();
        AssetDatabase.CreateAsset(mesh, $"{OutDir}/{name}.asset");
        go.AddComponent<MeshFilter>().sharedMesh = mesh;
        go.AddComponent<MeshRenderer>().sharedMaterial = mat;
        // Roads sit on the terrain collider, so they need no collider of their own.
    }

    /// Sweeps a flat strip along the polyline at half-width `hw`, raised by `lift`.
    /// If `innerHW` > 0 the strip is a pair of side bands (pavements) plus a kerb face.
    static void Ribbon(List<Vector3> p, float hw, float lift, List<Vector3> V, List<int> T, float innerHW = 0f)
    {
        int n = p.Count;
        var perp = new Vector3[n];
        for (int i = 0; i < n; i++)
        {
            Vector3 d = (i == 0) ? p[1] - p[0] : (i == n-1) ? p[n-1] - p[n-2] : p[i+1] - p[i-1];
            d.y = 0;
            if (d.sqrMagnitude < 1e-8f) d = Vector3.forward;
            d.Normalize();
            perp[i] = new Vector3(d.z, 0, -d.x);
        }
        var up = Vector3.up * lift;
        // Shared-vertex strips: one pair of vertices per cross-section rather than
        // four per quad. Cuts the road mesh roughly 4x with identical geometry.
        if (innerHW <= 0f)
        {
            int b0 = V.Count;
            for (int i = 0; i < n; i++) { V.Add(p[i] + up - perp[i]*hw); V.Add(p[i] + up + perp[i]*hw); }
            for (int i = 0; i < n - 1; i++) Strip(T, b0 + i*2);
        }
        else
        {
            int l0 = V.Count;                                     // left pavement band
            for (int i = 0; i < n; i++) { V.Add(p[i]+up-perp[i]*hw); V.Add(p[i]+up-perp[i]*innerHW); }
            for (int i = 0; i < n - 1; i++) Strip(T, l0 + i*2);

            int r0 = V.Count;                                     // right pavement band
            for (int i = 0; i < n; i++) { V.Add(p[i]+up+perp[i]*innerHW); V.Add(p[i]+up+perp[i]*hw); }
            for (int i = 0; i < n - 1; i++) Strip(T, r0 + i*2);

            var dn = Vector3.up * lift;
            int k0 = V.Count;                                     // left kerb face
            for (int i = 0; i < n; i++) { V.Add(p[i]+up-perp[i]*innerHW-dn); V.Add(p[i]+up-perp[i]*innerHW); }
            for (int i = 0; i < n - 1; i++) Strip(T, k0 + i*2);

            int k1 = V.Count;                                     // right kerb face
            for (int i = 0; i < n; i++) { V.Add(p[i]+up+perp[i]*innerHW); V.Add(p[i]+up+perp[i]*innerHW-dn); }
            for (int i = 0; i < n - 1; i++) Strip(T, k1 + i*2);
        }
    }

    /// Vertices are (left, right) per cross-section. Unity is left-handed, so the
    /// left-right-forward order winds counter-clockwise and faces DOWN -- the whole
    /// road surface gets backface-culled from above. Wind the other way.
    static void Strip(List<int> T, int i)
    {
        T.Add(i); T.Add(i+3); T.Add(i+1);
        T.Add(i); T.Add(i+2); T.Add(i+3);
    }

    static void Disc(Vector3 c, float r, List<Vector3> V, List<int> T, int seg = 14)
    {
        int c0 = V.Count; V.Add(c);
        for (int i = 0; i < seg; i++)
        {
            float a = i * Mathf.PI * 2f / seg;
            V.Add(c + new Vector3(Mathf.Cos(a) * r, 0, Mathf.Sin(a) * r));
        }
        for (int i = 0; i < seg; i++) { T.Add(c0); T.Add(c0 + 1 + (i + 1) % seg); T.Add(c0 + 1 + i); }
    }

    static void Quad(List<Vector3> V, List<int> T, Vector3 a, Vector3 b, Vector3 c, Vector3 d)
    {
        int i = V.Count; V.Add(a); V.Add(b); V.Add(c); V.Add(d);
        T.Add(i); T.Add(i+1); T.Add(i+2);
        T.Add(i); T.Add(i+2); T.Add(i+3);
    }

    static Seg Parse(string s)
    {
        try {
            var g = new Seg { cls = Str(s, "cls"), name = Str(s, "name"),
                              w = Num(s, "\"w\":"), pav = Num(s, "\"pav\":"), r = Num(s, "\"r\":") };
            int p = s.IndexOf("\"pts\":[["); if (p < 0) return null;
            int e = s.LastIndexOf("]]");     if (e < 0) return null;
            foreach (var tri in s.Substring(p + 8, e - p - 8).Split(new[]{"],["}, StringSplitOptions.None))
            {
                var xyz = tri.Trim('[', ']').Split(',');
                if (xyz.Length != 3) continue;
                if (F(xyz[0], out var x) && F(xyz[1], out var y) && F(xyz[2], out var z))
                    g.pts.Add(new Vector3(x, y, z));
            }
            return g.pts.Count > 0 ? g : null;
        } catch { return null; }
    }
    static bool F(string s, out float v) =>
        float.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out v);
    static string Str(string s, string k)
    {
        int p = s.IndexOf($"\"{k}\":\""); if (p < 0) return null;
        p += k.Length + 4; int e = s.IndexOf('"', p); return s.Substring(p, e - p);
    }
    static float Num(string s, string key)
    {
        int p = s.IndexOf(key); if (p < 0) return 0;
        p += key.Length; int e = p;
        while (e < s.Length && (char.IsDigit(s[e]) || s[e]=='-' || s[e]=='.')) e++;
        return F(s.Substring(p, e - p), out var v) ? v : 0;
    }
}
