using UnityEngine;
using UnityEditor;
public static class MargateWaterDebug
{
    public static void D1() => Set(1);   // scene eye depth
    public static void D2() => Set(2);   // computed water depth
    public static void D3() => Set(3);   // raw depth buffer sample
    public static void Off() => Set(0);
    static void Set(float v)
    {
        var m = AssetDatabase.LoadAssetAtPath<Material>("Assets/Generated/M_Water.mat");
        m.SetFloat("_Debug", v); EditorUtility.SetDirty(m); AssetDatabase.SaveAssets();
        Debug.Log($"[Margate] water debug = {v}");
    }
}
