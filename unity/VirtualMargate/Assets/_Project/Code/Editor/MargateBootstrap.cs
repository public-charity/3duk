using System.IO;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// One-shot: configure URP, build terrain, generate buildings, set up the scene, save.
/// Invoked headlessly with -executeMethod MargateBootstrap.BuildAll
public static class MargateBootstrap
{
    public static void BuildAll()
    {
        Directory.CreateDirectory("Assets/Generated");
        Directory.CreateDirectory("Assets/_Project/Settings");
        ConfigureUrp();
        AssetDatabase.SaveAssets(); AssetDatabase.Refresh();

        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        MargateTerrainImporter.Import();
        MargateBuildingGenerator.Generate();
        MargateRoadGenerator.Generate();
        MargateCoastGenerator.Generate();
        MargateSceneSetup.Setup();

        Directory.CreateDirectory("Assets/_Project/Scenes");
        EditorSceneManager.SaveScene(scene, "Assets/_Project/Scenes/Margate.unity");
        AssetDatabase.SaveAssets();
        Debug.Log("[Margate] BuildAll complete.");
    }

    static void ConfigureUrp()
    {
        const string p = "Assets/_Project/Settings/URP_Margate.asset";
        var urp = AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>(p);
        if (urp == null)
        {
            var rd = ScriptableObject.CreateInstance<UniversalRendererData>();
            AssetDatabase.CreateAsset(rd, "Assets/_Project/Settings/URP_Renderer.asset");
            urp = UniversalRenderPipelineAsset.Create(rd);
            AssetDatabase.CreateAsset(urp, p);
        }
        urp.shadowDistance = 120f;              // pedestrian scale; 500 m cascades are wasted here
        urp.shadowCascadeCount = 4;
        urp.msaaSampleCount = 4;
        GraphicsSettings.defaultRenderPipeline = urp;
        QualitySettings.renderPipeline = urp;
        Debug.Log("[Margate] URP configured.");
    }
}
