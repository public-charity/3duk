using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;

public static class MargateWaterTune
{
    public static void Diagnose()
    {
        EditorSceneManager.OpenScene("Assets/_Project/Scenes/Margate.unity");
        var m = AssetDatabase.LoadAssetAtPath<Material>("Assets/Generated/M_Water.mat");
        if (m == null) { Debug.LogError("no water material"); return; }
        // strip everything except the depth-driven body colour
        m.SetFloat("_ReflStrength", 0f);
        m.SetFloat("_SpecInt", 0f);
        m.SetFloat("_FoamDepth", 0.001f);
        m.SetFloat("_Turbidity", 1f);
        m.SetFloat("_Refract", 0f);
        EditorUtility.SetDirty(m); AssetDatabase.SaveAssets();
        Debug.Log("[Margate] water stripped to body colour only");
    }
    /// Tuned to Margate's ACTUAL depths: the LIDAR sea bed sits at -2.1 to -2.9 m ODN
    /// and the water line is -0.6, so there is only 1.3-2.4 m of water near shore.
    /// The stock defaults assumed open ocean and made everything read as shallow foam.
    public static void Restore()
    {
        var m = AssetDatabase.LoadAssetAtPath<Material>("Assets/Generated/M_Water.mat");
        m.SetFloat("_Debug", 0f);
        m.SetColor("_ShallowColor", new Color(0.20f, 0.52f, 0.52f));
        m.SetColor("_DeepColor",    new Color(0.02f, 0.13f, 0.22f));
        m.SetFloat("_DepthFade",  2.6f);     // full deep colour by ~2.6 m
        m.SetFloat("_Turbidity",  0.45f);
        m.SetFloat("_FoamDepth",  0.40f);    // foam only in the last 40 cm at the waterline
        m.SetFloat("_FoamEdge",   0.18f);
        m.SetFloat("_ReflStrength", 0.62f);
        m.SetFloat("_SpecInt",    3.0f);
        m.SetFloat("_SpecPower",  480f);
        m.SetFloat("_Refract",    0.30f);
        m.SetFloat("_Smooth",     0.94f);
        m.SetVector("_WaveA", new Vector4( 1.00f, 0.32f, 0.10f, 68f));
        m.SetVector("_WaveB", new Vector4( 0.72f, 1.00f, 0.07f, 41f));
        m.SetVector("_WaveC", new Vector4(-0.55f, 0.86f, 0.04f, 24f));
        m.SetFloat("_WaveSpeed", 0.85f);
        m.SetFloat("_RippleStr", 0.22f);
        EditorUtility.SetDirty(m); AssetDatabase.SaveAssets();
        Debug.Log("[Margate] water tuned for Margate depths");
    }
}
