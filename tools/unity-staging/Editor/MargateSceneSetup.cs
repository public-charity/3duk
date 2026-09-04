using UnityEngine;
using UnityEditor;

/// Drops in the player, a sea plane at true mean sea level, sun and sea haze.
/// Because world y is honest metres above Ordnance Datum Newlyn, the sea plane
/// sits at exactly y = 0 -- and Margate's ~4.5 m tidal range becomes a single slider.
public static class MargateSceneSetup
{
    [MenuItem("Margate/3 - Setup Scene and Player")]
    public static void Setup()
    {
        // Sun
        var sunGo = GameObject.Find("Sun");
        if (sunGo == null)
        {
            var old = Object.FindFirstObjectByType<Light>();
            if (old && old.type == LightType.Directional) sunGo = old.gameObject;
            else sunGo = new GameObject("Sun", typeof(Light));
        }
        sunGo.name = "Sun";
        var sun = sunGo.GetComponent<Light>();
        sun.type = LightType.Directional; sun.intensity = 1.15f;
        sun.color = new Color(1f, 0.96f, 0.88f);
        sunGo.transform.rotation = Quaternion.Euler(38f, -55f, 0f);   // late-afternoon, NW

        // Sea haze
        RenderSettings.fog = true;
        RenderSettings.fogMode = FogMode.ExponentialSquared;
        RenderSettings.fogDensity = 0.0016f;
        RenderSettings.fogColor = new Color(0.74f, 0.80f, 0.85f);
        RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Trilight;
        RenderSettings.ambientSkyColor    = new Color(0.62f, 0.70f, 0.82f);
        RenderSettings.ambientEquatorColor= new Color(0.52f, 0.54f, 0.55f);
        RenderSettings.ambientGroundColor = new Color(0.36f, 0.34f, 0.30f);

        // Sea at y=0 ODN
        if (GameObject.Find("Sea") == null)
        {
            var sea = GameObject.CreatePrimitive(PrimitiveType.Plane);
            sea.name = "Sea";
            sea.transform.position = new Vector3(MargateWorld.NX * MargateWorld.TileM * 0.5f, 0f,
                                                 MargateWorld.NY * MargateWorld.TileM * 0.5f);
            sea.transform.localScale = new Vector3(900, 1, 900);
            Object.DestroyImmediate(sea.GetComponent<MeshCollider>());
            var m = new Material(Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard"));
            m.color = new Color(0.22f, 0.36f, 0.42f);
            m.SetFloat("_Smoothness", 0.85f);
            AssetDatabase.CreateAsset(m, "Assets/Generated/M_Sea.mat");
            sea.GetComponent<MeshRenderer>().sharedMaterial = m;
        }

        // Player, dropped on the Harbour Arm end of the Old Town
        var p = GameObject.Find("Player");
        if (p == null)
        {
            p = new GameObject("Player", typeof(CharacterController), typeof(MargateWalker));
            var camGo = new GameObject("Camera", typeof(Camera), typeof(AudioListener));
            camGo.transform.SetParent(p.transform);
            camGo.transform.localPosition = new Vector3(0, 1.7f, 0);
            camGo.tag = "MainCamera";
            camGo.GetComponent<Camera>().fieldOfView = 68f;
            camGo.GetComponent<Camera>().farClipPlane = 3000f;
            p.GetComponent<MargateWalker>().cam = camGo.transform;
        }
        // BNG 635480, 170560 -- the Old Town, just inland of the harbour
        p.transform.position = new Vector3(635480f - (float)MargateWorld.E0, 40f,
                                           170560f - (float)MargateWorld.N0);
        Debug.Log("[Margate] Scene ready. Press Play. WASD to walk, Shift to sprint, Esc to release the cursor.");
    }
}
