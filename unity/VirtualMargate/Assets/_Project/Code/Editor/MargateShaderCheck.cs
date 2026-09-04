using UnityEngine;
using UnityEditor;
public static class MargateShaderCheck
{
    public static void Run()
    {
        var sh = Shader.Find("Margate/Water");
        Debug.Log($"[CHK] Shader.Find -> {(sh == null ? "NULL" : sh.name)}");
        if (sh != null)
        {
            Debug.Log($"[CHK] isSupported={sh.isSupported}  passCount={sh.passCount}");
            int n = ShaderUtil.GetShaderMessageCount(sh);
            Debug.Log($"[CHK] messages={n}");
            foreach (var m in ShaderUtil.GetShaderMessages(sh))
                Debug.Log($"[CHK] {m.severity}: {m.message.Trim()} | {m.messageDetails.Trim()} (line {m.line})");
        }
        var mat = AssetDatabase.LoadAssetAtPath<Material>("Assets/Generated/M_Water.mat");
        Debug.Log($"[CHK] material shader = {(mat == null ? "no material" : mat.shader.name)}");
    }
}
