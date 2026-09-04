using System.IO;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;

/// Verifies the parts of the minimap that don't need Play mode: the mask shader
/// compiles, the component is attached, and the map camera actually renders the
/// town. The OnGUI overlay can only be seen in Play mode.
public static class MargateMinimapVerify
{
    public static void Run()
    {
        EditorSceneManager.OpenScene("Assets/_Project/Scenes/Margate.unity");

        var sh = Shader.Find("Margate/MinimapMask");
        Debug.Log($"[MM] mask shader: {(sh == null ? "NOT FOUND" : sh.name)} supported={sh != null && sh.isSupported}");
        if (sh != null)
            foreach (var m in ShaderUtil.GetShaderMessages(sh))
                Debug.Log($"[MM] shader {m.severity}: {m.message.Trim()} (line {m.line})");

        var p = GameObject.Find("Player");
        Debug.Log($"[MM] player: {(p == null ? "MISSING" : "found")}  " +
                  $"minimap component: {(p != null && p.GetComponent<MargateMinimap>() != null ? "attached" : "MISSING")}");
        if (p == null) return;

        // render exactly what the minimap camera would see
        var go = new GameObject("_mmcam");
        var cam = go.AddComponent<Camera>();
        cam.orthographic = true; cam.orthographicSize = 320f;
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = new Color(0.62f, 0.70f, 0.78f);
        cam.nearClipPlane = 1f; cam.farClipPlane = 1300f;
        cam.transform.position = p.transform.position + Vector3.up * 900f;
        cam.transform.rotation = Quaternion.Euler(90, 0, 0);

        var rt = new RenderTexture(512, 512, 16);
        cam.targetTexture = rt; cam.Render();
        RenderTexture.active = rt;
        var tex = new Texture2D(512, 512, TextureFormat.RGB24, false);
        tex.ReadPixels(new Rect(0, 0, 512, 512), 0, 0); tex.Apply();
        string outp = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "..",
                                                    "salvage", "shots", "MINIMAP_VIEW.png"));
        File.WriteAllBytes(outp, tex.EncodeToPNG());
        RenderTexture.active = null; cam.targetTexture = null;
        Object.DestroyImmediate(go); Object.DestroyImmediate(rt); Object.DestroyImmediate(tex);
        Debug.Log("[MM] map-camera render -> " + outp);
    }
}
