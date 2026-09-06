using System.Linq;
using UnityEngine;
using UnityEditor;

/// Turns the street-furniture source art in Assets/_Project/Art/Props into ready prefabs.
///
/// The FBX/PNG pairs are produced headlessly by tools/props/build_*.py (Blender); this
/// script does the Unity half: import settings, URP materials, LODGroup thresholds, a
/// collider, and a prefab next to the source. Re-running is safe -- it overwrites.
///
/// Litter bin: Glasdon Jubilee 110, 1.158 x 0.598 x 0.553 m, three LODs
/// (2216 / 1128 / 308 tris), one 1024x512 albedo shared by all three.
public static class MargatePropBuilder
{
    const string Dir = "Assets/_Project/Art/Props/LitterBin";
    const string Fbx = Dir + "/SM_LitterBin_Jubilee110.fbx";
    const string Tex = Dir + "/T_LitterBin_D.png";

    [MenuItem("Margate/7 - Build Props")]
    public static void BuildProps()
    {
        BuildLitterBin();
        AssetDatabase.SaveAssets();
        Debug.Log("[Margate] Props built.");
    }

    static void BuildLitterBin()
    {
        if (AssetImporter.GetAtPath(Fbx) is not ModelImporter mi) { Debug.LogError($"[Margate] Missing {Fbx} -- run tools/props/build_litterbin.py"); return; }

        // Blender exported with FBX_SCALE_ALL + baked axes, so 1 file unit = 1 m and no root rotation.
        mi.globalScale = 1f; mi.useFileScale = true; mi.useFileUnits = true; mi.bakeAxisConversion = true;
        mi.materialImportMode = ModelImporterMaterialImportMode.None;    // materials are made below
        mi.importNormals = ModelImporterNormals.Import;                   // sharp edges come from the file
        mi.importBlendShapes = false; mi.importAnimation = false; mi.animationType = ModelImporterAnimationType.None;
        mi.addCollider = false; mi.isReadable = false; mi.generateSecondaryUV = false;
        mi.SaveAndReimport();

        if (AssetImporter.GetAtPath(Tex) is TextureImporter ti)
        {
            ti.sRGBTexture = true; ti.mipmapEnabled = true; ti.maxTextureSize = 1024; ti.wrapMode = TextureWrapMode.Repeat;
            ti.SaveAndReimport();
        }
        var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(Tex);

        var outer = MakeMat(Dir + "/M_LitterBin.mat", tex, Color.white, 0.35f);
        var inner = MakeMat(Dir + "/M_LitterBin_Inner.mat", null, new Color(0.02f, 0.02f, 0.025f), 0.10f);

        var model = AssetDatabase.LoadAssetAtPath<GameObject>(Fbx);
        var go = (GameObject)PrefabUtility.InstantiatePrefab(model);
        PrefabUtility.UnpackPrefabInstance(go, PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
        go.name = "LitterBin";

        // Submesh 0 is the outside (textured), submesh 1 the shell interior, cut faces and caps.
        var renderers = go.GetComponentsInChildren<MeshRenderer>().OrderBy(r => r.name).ToArray();
        foreach (var r in renderers) r.sharedMaterials = new[] { outer, inner };

        // Unity builds the LODGroup from the _LOD0/1/2 names; just set the thresholds for a 1.16 m object.
        var lod = go.GetComponent<LODGroup>() ?? go.AddComponent<LODGroup>();
        lod.SetLODs(new[]
        {
            new LOD(0.12f, renderers.Where(r => r.name.EndsWith("_LOD0")).ToArray()),
            new LOD(0.04f, renderers.Where(r => r.name.EndsWith("_LOD1")).ToArray()),
            new LOD(0.01f, renderers.Where(r => r.name.EndsWith("_LOD2")).ToArray()),
        });
        lod.RecalculateBounds();

        var box = go.GetComponent<BoxCollider>() ?? go.AddComponent<BoxCollider>();
        box.center = new Vector3(0f, 0.579f, 0f); box.size = new Vector3(0.616f, 1.158f, 0.570f);
        GameObjectUtility.SetStaticEditorFlags(go, StaticEditorFlags.BatchingStatic | StaticEditorFlags.OccludeeStatic);

        PrefabUtility.SaveAsPrefabAsset(go, Dir + "/P_LitterBin.prefab");
        Object.DestroyImmediate(go);
        Debug.Log($"[Margate] Litter bin: {renderers.Length} LODs -> {Dir}/P_LitterBin.prefab");
    }

    static Material MakeMat(string path, Texture2D tex, Color c, float smoothness)
    {
        var m = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (m == null)
        {
            m = new Material(Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard"));
            AssetDatabase.CreateAsset(m, path);
        }
        m.SetColor("_BaseColor", c); m.color = c;
        if (tex != null) { m.SetTexture("_BaseMap", tex); m.mainTexture = tex; }
        m.SetFloat("_Smoothness", smoothness);
        EditorUtility.SetDirty(m);
        return m;
    }
}
