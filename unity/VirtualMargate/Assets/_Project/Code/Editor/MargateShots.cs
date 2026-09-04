using System.IO;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;

public static class MargateShots
{
    struct Shot { public string name; public Vector3 pos; public Vector3 look; public float fov; public bool ortho; public float orthoSize; public bool ground; }

    public static void Capture()
    {
        EditorSceneManager.OpenScene("Assets/_Project/Scenes/Margate.unity");
        string dir = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "..", "salvage", "shots"));
        Directory.CreateDirectory(dir);

        // BNG -> local helper: x = E-632800, z = N-168200
        Vector3 L(double e, double n, float y) => new Vector3((float)(e - 632800), y, (float)(n - 168200));

        var shots = new[] {
            // All coordinates are real OSM landmark centroids in British National Grid.
            new Shot { name="01_overhead",       pos = L(635400, 168900, 1350), look = L(635400, 171100, 0),  fov = 55 },
            new Shot { name="08_plan_80m",       pos = L(635175, 170742, 80),   look = L(635175, 170743, 0),  fov = 60 },
            new Shot { name="07_streets_close",  pos = L(635500, 170750, 150),  look = L(635420, 171150, 6),  fov = 62 },
            new Shot { name="02_harbour_air",    pos = L(635150, 170300, 190),  look = L(635360, 171230, 8),  fov = 60 },
            new Shot { name="03_oldtown_street", pos = L(635547, 171055, 0),    look = L(635420, 171200, 4),  fov = 70, ground = true },
            new Shot { name="04_harbour_quay",   pos = L(635300, 171180, 0),    look = L(635389, 171231, 10), fov = 65, ground = true },
            new Shot { name="05_arlington",      pos = L(635060, 170700, 0),    look = L(634906, 170626, 40), fov = 72, ground = true },
            new Shot { name="06_clocktower",     pos = L(635240, 170830, 0),    look = L(635174, 170755, 12), fov = 68, ground = true },
        };

        var go = new GameObject("ShotCam"); var cam = go.AddComponent<Camera>();
        cam.farClipPlane = 6000; cam.nearClipPlane = 0.2f;
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = new Color(0.70f, 0.79f, 0.86f);

        foreach (var s in shots)
        {
            var p = s.pos;
            if (s.ground)   // drop eye height onto the terrain
            {
                // Sample the TERRAIN, not the first collider -- a downward ray inside a
                // footprint lands on the building roof, which is where the earlier shots ended up.
                float g = float.NaN;
                foreach (var t in Object.FindObjectsByType<Terrain>(FindObjectsSortMode.None))
                {
                    var lp = p - t.transform.position;
                    if (lp.x < 0 || lp.z < 0 || lp.x > t.terrainData.size.x || lp.z > t.terrainData.size.z) continue;
                    g = t.SampleHeight(p) + t.transform.position.y; break;
                }
                p.y = (float.IsNaN(g) ? 10f : g) + 1.7f;
            }
            cam.transform.position = p;
            cam.orthographic = s.ortho;
            if (s.ortho) { cam.orthographicSize = s.orthoSize; cam.transform.rotation = Quaternion.Euler(90, 0, 0); }
            else { cam.fieldOfView = s.fov; cam.transform.LookAt(s.look); }

            var rt = new RenderTexture(1920, 1080, 24, RenderTextureFormat.ARGB32) { antiAliasing = 4 };
            cam.targetTexture = rt; cam.Render();
            RenderTexture.active = rt;
            var tex = new Texture2D(1920, 1080, TextureFormat.RGB24, false);
            tex.ReadPixels(new Rect(0, 0, 1920, 1080), 0, 0); tex.Apply();
            File.WriteAllBytes(Path.Combine(dir, s.name + ".png"), tex.EncodeToPNG());
            RenderTexture.active = null; cam.targetTexture = null;
            Object.DestroyImmediate(rt); Object.DestroyImmediate(tex);
            Debug.Log($"[Margate] shot {s.name} at {p}");
        }
        Debug.Log("[Margate] shots written to " + dir);
    }
}
