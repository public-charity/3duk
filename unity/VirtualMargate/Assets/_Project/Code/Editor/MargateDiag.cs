using System.IO;
using System.Text;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine.Rendering;

public static class MargateDiag
{
    public static void Run()
    {
        EditorSceneManager.OpenScene("Assets/_Project/Scenes/Margate.unity");
        var sb = new StringBuilder();
        sb.AppendLine("=== RENDER PIPELINE ===");
        sb.AppendLine("  defaultRenderPipeline : " + (GraphicsSettings.defaultRenderPipeline ? GraphicsSettings.defaultRenderPipeline.name : "NULL (built-in!)"));
        sb.AppendLine("  QualitySettings.rp    : " + (QualitySettings.renderPipeline ? QualitySettings.renderPipeline.name : "null"));
        sb.AppendLine("  current               : " + (GraphicsSettings.currentRenderPipeline ? GraphicsSettings.currentRenderPipeline.name : "NULL"));
        sb.AppendLine("  skybox material       : " + (RenderSettings.skybox ? RenderSettings.skybox.name + " / shader " + RenderSettings.skybox.shader.name : "NULL"));
        sb.AppendLine("  skybox shader ok      : " + (RenderSettings.skybox && RenderSettings.skybox.shader && RenderSettings.skybox.shader.isSupported));

        sb.AppendLine("\n=== LIGHTS ===");
        foreach (var l in Object.FindObjectsByType<Light>(FindObjectsSortMode.None))
            sb.AppendLine($"  {l.name}: {l.type} intensity={l.intensity} enabled={l.enabled} rot={l.transform.eulerAngles}");

        sb.AppendLine("\n=== CAMERAS ===");
        foreach (var c in Object.FindObjectsByType<Camera>(FindObjectsSortMode.None))
            sb.AppendLine($"  {c.name}: tag={c.tag} enabled={c.enabled} activeGO={c.gameObject.activeInHierarchy} " +
                          $"clear={c.clearFlags} near={c.nearClipPlane} far={c.farClipPlane} fov={c.fieldOfView} " +
                          $"cullingMask={c.cullingMask} depth={c.depth} pos={c.transform.position}");

        sb.AppendLine("\n=== PLAYER ===");
        var p = GameObject.Find("Player");
        if (p == null) sb.AppendLine("  *** NO PLAYER ***");
        else {
            var cc = p.GetComponent<CharacterController>();
            sb.AppendLine($"  pos={p.transform.position} active={p.activeInHierarchy}");
            sb.AppendLine($"  CharacterController: h={cc.height} r={cc.radius} center={cc.center} enabled={cc.enabled}");
            var w = p.GetComponent<MargateWalker>();
            sb.AppendLine($"  MargateWalker: {(w ? "present, enabled=" + w.enabled + ", cam=" + (w.cam ? w.cam.name : "NULL") : "MISSING")}");
        }

        sb.AppendLine("\n=== GROUND UNDER PLAYER ===");
        if (p) {
            var hit = Physics.Raycast(p.transform.position + Vector3.up * 5, Vector3.down, out var h, 200f);
            sb.AppendLine(hit ? $"  hits '{h.collider.name}' at y={h.point.y:F2} (dist {h.distance:F1})"
                              : "  *** NOTHING BELOW PLAYER -- would fall forever ***");
        }
        sb.AppendLine($"  terrain colliders in scene: {Object.FindObjectsByType<TerrainCollider>(FindObjectsSortMode.None).Length}");
        sb.AppendLine($"  mesh colliders in scene   : {Object.FindObjectsByType<MeshCollider>(FindObjectsSortMode.None).Length}");
        sb.AppendLine($"  renderers in scene        : {Object.FindObjectsByType<MeshRenderer>(FindObjectsSortMode.None).Length}");
        sb.AppendLine($"  terrains in scene         : {Object.FindObjectsByType<Terrain>(FindObjectsSortMode.None).Length}");

        // Render through the ACTUAL player camera, settling it on the ground first
        var pc = Camera.main;
        if (pc && p) {
            if (Physics.Raycast(p.transform.position + Vector3.up * 5, Vector3.down, out var h2, 200f))
                p.transform.position = new Vector3(p.transform.position.x, h2.point.y + 1.0f, p.transform.position.z);
            pc.transform.localRotation = Quaternion.identity;
            var rt = new RenderTexture(1280, 720, 24);
            pc.targetTexture = rt; pc.Render(); RenderTexture.active = rt;
            var tex = new Texture2D(1280, 720, TextureFormat.RGB24, false);
            tex.ReadPixels(new Rect(0,0,1280,720),0,0); tex.Apply();
            string outp = Path.GetFullPath(Path.Combine(Application.dataPath,"..","..","..","salvage","shots","PLAYER_VIEW.png"));
            File.WriteAllBytes(outp, tex.EncodeToPNG());
            RenderTexture.active = null; pc.targetTexture = null;
            sb.AppendLine("\n  player-camera render -> " + outp);
        }
        Debug.Log(sb.ToString());
    }
}
