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
            // over the bay, looking down at the water so fresnel isn't grazing
            new Shot { name="20_bay_down",   pos = L(635150, 170450, 230), look = L(635150, 171550, -1), fov = 60 },
            // standing on Main Sands at the waterline
            new Shot { name="21_waterline",  pos = L(635120, 171150, 0),   look = L(635000, 171700, 2),  fov = 68, ground = true },
            // from the Harbour Arm looking west across the bay
            new Shot { name="22_from_arm",   pos = L(635300, 171330, 0),   look = L(634800, 171450, 3),  fov = 72, ground = true },
            // straight down on the waterline: beach -> shallow -> deep
            new Shot { name="23_plan_shore", pos = L(635120, 171250, 110), look = L(635120, 171251, 0),  fov = 62 },
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
