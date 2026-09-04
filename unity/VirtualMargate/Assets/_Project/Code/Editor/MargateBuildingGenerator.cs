using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;
using UnityEditor;

/// Reads the pipeline's semantic JSONL and builds one combined mesh per tile.
/// Every building gets a plinth extruded down to the lowest ground pixel beneath it:
/// 36% of Margate's footprints span >0.5 m of ground and 6% span >2 m, so a single
/// flat base would visibly float or sink. The plinth is invisible when buried and
/// becomes a stone base course on the steep streets -- which is what real Margate has.
public static class MargateBuildingGenerator
{
    const string SrcDir = "../../data/out/massing";
    const string OutDir = "Assets/Generated/Massing";

    class B {
        public string id, name, type, roof;
        public float h, ridge, baseY, skirt;
        public uint seed;
        public List<List<Vector2>> rings = new();
        public List<bool> hole = new();
    }

    [MenuItem("Margate/2 - Generate Buildings")]
    public static void Generate()
    {
        string src = Path.GetFullPath(Path.Combine(Application.dataPath, "..", SrcDir));
        if (!Directory.Exists(src)) { Debug.LogError($"No massing at {src}"); return; }
        Directory.CreateDirectory(OutDir);

        var mat = AssetDatabase.LoadAssetAtPath<Material>("Assets/Generated/M_Greybox.mat");
        if (mat == null)
        {
            var sh = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            mat = new Material(sh) { color = new Color(0.72f, 0.70f, 0.66f) };
            AssetDatabase.CreateAsset(mat, "Assets/Generated/M_Greybox.mat");
        }

        var root = GameObject.Find("Buildings") ?? new GameObject("Buildings");
        int tiles = 0, total = 0;

        foreach (var path in Directory.GetFiles(src, "buildings_*.jsonl"))
        {
            string tile = Path.GetFileNameWithoutExtension(path).Replace("buildings_", "");
            var verts = new List<Vector3>(); var tris = new List<int>(); var cols = new List<Color32>();

            foreach (var line in File.ReadLines(path))
            {
                var b = Parse(line); if (b == null) continue;
                EmitBuilding(b, verts, tris, cols); total++;
            }
            if (verts.Count == 0) continue;

            var mesh = new Mesh { name = $"Massing_{tile}", indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 };
            mesh.SetVertices(verts); mesh.SetTriangles(tris, 0); mesh.SetColors(cols);
            mesh.RecalculateNormals(); mesh.RecalculateBounds();
            AssetDatabase.CreateAsset(mesh, $"{OutDir}/{mesh.name}.asset");

            var go = new GameObject($"Massing_{tile}");
            go.transform.parent = root.transform;
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            go.AddComponent<MeshRenderer>().sharedMaterial = mat;
            go.AddComponent<MeshCollider>().sharedMesh = mesh;   // one collider per tile, not per building
            go.isStatic = true;
            tiles++;
        }
        AssetDatabase.SaveAssets();
        Debug.Log($"[Margate] {total} buildings across {tiles} tiles.");
    }

    static void EmitBuilding(B b, List<Vector3> V, List<int> T, List<Color32> C)
    {
        float top = b.baseY + b.h;
        var col = PaletteFor(b);
        foreach (var (ring, isHole) in Zip(b.rings, b.hole))
        {
            if (ring.Count < 4) continue;
            var r = Dedup(ring);
            if (r.Count < 3) continue;
            if (SignedArea(r) < 0) r.Reverse();          // normalise to CCW
            if (isHole) r.Reverse();

            // walls: skirt -> top
            for (int k = 0; k < r.Count; k++)
            {
                Vector2 p = r[k], q = r[(k + 1) % r.Count];
                int v0 = V.Count;
                V.Add(new Vector3(p.x, b.skirt, p.y)); V.Add(new Vector3(q.x, b.skirt, q.y));
                V.Add(new Vector3(q.x, top,     q.y)); V.Add(new Vector3(p.x, top,     p.y));
                for (int n = 0; n < 4; n++) C.Add(col);
                T.Add(v0); T.Add(v0 + 2); T.Add(v0 + 1);
                T.Add(v0); T.Add(v0 + 3); T.Add(v0 + 2);
            }
            if (isHole) continue;
            // flat roof cap (ear clipping)
            int baseIdx = V.Count;
            foreach (var p in r) { V.Add(new Vector3(p.x, top, p.y)); C.Add(col); }
            foreach (var t in EarClip(r)) { T.Add(baseIdx + t.x); T.Add(baseIdx + t.z); T.Add(baseIdx + t.y); }
        }
    }

    /// Per-building colour seeded from the OSM id, written to vertex colour.
    /// GPU Resident Drawer forbids MaterialPropertyBlock, so per-instance variation
    /// has to live in the mesh -- which costs nothing when the mesh is generated anyway.
    static Color32 PaletteFor(B b)
    {
        var rnd = new System.Random((int)(b.seed & 0x7fffffff));
        float g = 0.55f + 0.28f * (float)rnd.NextDouble();
        float warm = 0.03f * (float)rnd.NextDouble();
        return new Color(g + warm, g, g - warm * 0.5f);
    }

    static IEnumerable<(List<Vector2>, bool)> Zip(List<List<Vector2>> a, List<bool> b)
    { for (int i = 0; i < a.Count; i++) yield return (a[i], i < b.Count && b[i]); }

    static List<Vector2> Dedup(List<Vector2> r)
    {
        var o = new List<Vector2>();
        foreach (var p in r) if (o.Count == 0 || (p - o[^1]).sqrMagnitude > 1e-6f) o.Add(p);
        if (o.Count > 1 && (o[0] - o[^1]).sqrMagnitude < 1e-6f) o.RemoveAt(o.Count - 1);
        return o;
    }

    static float SignedArea(List<Vector2> r)
    {
        float a = 0; for (int i = 0; i < r.Count; i++)
        { var p = r[i]; var q = r[(i + 1) % r.Count]; a += p.x * q.y - q.x * p.y; }
        return a * 0.5f;
    }

    static List<Vector3Int> EarClip(List<Vector2> poly)
    {
        var res = new List<Vector3Int>();
        var idx = new List<int>(); for (int i = 0; i < poly.Count; i++) idx.Add(i);
        int guard = 0;
        while (idx.Count > 3 && guard++ < 4000)
        {
            bool clipped = false;
            for (int i = 0; i < idx.Count; i++)
            {
                int ia = idx[(i + idx.Count - 1) % idx.Count], ib = idx[i], ic = idx[(i + 1) % idx.Count];
                Vector2 a = poly[ia], bb = poly[ib], c = poly[ic];
                if ((bb.x - a.x) * (c.y - a.y) - (bb.y - a.y) * (c.x - a.x) <= 0) continue; // reflex
                bool bad = false;
                foreach (int k in idx)
                {
                    if (k == ia || k == ib || k == ic) continue;
                    if (InTri(poly[k], a, bb, c)) { bad = true; break; }
                }
                if (bad) continue;
                res.Add(new Vector3Int(ia, ib, ic)); idx.RemoveAt(i); clipped = true; break;
            }
            if (!clipped) break;   // self-intersecting ring: keep what we have
        }
        if (idx.Count == 3) res.Add(new Vector3Int(idx[0], idx[1], idx[2]));
        return res;
    }

    static bool InTri(Vector2 p, Vector2 a, Vector2 b, Vector2 c)
    {
        float d1 = (p.x-b.x)*(a.y-b.y)-(a.x-b.x)*(p.y-b.y);
        float d2 = (p.x-c.x)*(b.y-c.y)-(b.x-c.x)*(p.y-c.y);
        float d3 = (p.x-a.x)*(c.y-a.y)-(c.x-a.x)*(p.y-a.y);
        bool neg = (d1<0)||(d2<0)||(d3<0), pos = (d1>0)||(d2>0)||(d3>0);
        return !(neg && pos);
    }

    // Minimal JSONL reader -- the records are machine-written and flat.
    static B Parse(string s)
    {
        try {
            var b = new B {
                id = Str(s,"id"), name = Str(s,"name"), type = Str(s,"type"), roof = Str(s,"roof"),
                h = Num(s,"h"), ridge = Num(s,"ridge"), baseY = Num(s,"base_y"), skirt = Num(s,"skirt"),
                seed = (uint)Num(s,"seed")
            };
            int p = s.IndexOf("\"rings\":[");
            if (p < 0) return null;
            foreach (var (ring, isHole) in ReadRings(s, p)) { b.rings.Add(ring); b.hole.Add(isHole); }
            return b.rings.Count > 0 ? b : null;
        } catch { return null; }
    }

    static IEnumerable<(List<Vector2>,bool)> ReadRings(string s, int from)
    {
        int i = from;
        while (true)
        {
            int hp = s.IndexOf("\"hole\":", i); if (hp < 0) yield break;
            bool isHole = s.Substring(hp + 7, 4).StartsWith("true");
            int pp = s.IndexOf("\"pts\":[[", hp); if (pp < 0) yield break;
            int end = s.IndexOf("]]", pp); if (end < 0) yield break;
            var pts = new List<Vector2>();
            foreach (var pair in s.Substring(pp + 8, end - pp - 8).Split(new[]{"],["}, StringSplitOptions.None))
            {
                var xy = pair.Trim('[', ']').Split(',');
                if (xy.Length == 2 &&
                    float.TryParse(xy[0], NumberStyles.Float, CultureInfo.InvariantCulture, out float x) &&
                    float.TryParse(xy[1], NumberStyles.Float, CultureInfo.InvariantCulture, out float y))
                    pts.Add(new Vector2(x, y));
            }
            if (pts.Count >= 3) yield return (pts, isHole);
            i = end + 2;
            if (i >= s.Length || s[i] == ']') yield break;
        }
    }

    static string Str(string s, string k)
    {
        int p = s.IndexOf($"\"{k}\":\""); if (p < 0) return null;
        p += k.Length + 4; int e = s.IndexOf('"', p); return s.Substring(p, e - p);
    }
    static float Num(string s, string k)
    {
        int p = s.IndexOf($"\"{k}\":"); if (p < 0) return 0;
        p += k.Length + 3; int e = p;
        while (e < s.Length && (char.IsDigit(s[e]) || s[e]=='-' || s[e]=='.' || s[e]=='e')) e++;
        return float.TryParse(s.Substring(p, e - p), NumberStyles.Float, CultureInfo.InvariantCulture, out float v) ? v : 0;
    }
}
