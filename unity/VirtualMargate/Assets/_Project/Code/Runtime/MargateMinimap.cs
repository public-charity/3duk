using System.Collections.Generic;
using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

/// Circular north-up minimap, top-left, with Margate's real landmarks on it.
///
/// North-up rather than rotate-with-player: for finding your way around a real
/// town you already half-know, a stable map you can read against the actual
/// street layout beats one that spins.
[DefaultExecutionOrder(100)]
public class MargateMinimap : MonoBehaviour
{
    [Header("Layout")]
    public int   sizePx   = 240;
    public int   marginPx = 18;
    public int   rtRes    = 512;

    [Header("View")]
    public float zoom      = 320f;   // metres from centre to rim
    public float minZoom   = 90f;
    public float maxZoom   = 1400f;
    public float camHeight = 900f;

    struct LM { public string name; public Vector2 p;
                public LM(string n, float x, float z) { name = n; p = new Vector2(x, z); } }

    // Real OSM centroids in local metres (x = BNG_E - 632800, z = BNG_N - 168200)
    static readonly LM[] Landmarks = {
        new LM("Harbour Arm",        2450f, 3015f),
        new LM("Droit House",        2535f, 3022f),
        new LM("Turner Contemporary",2589f, 3031f),
        new LM("Tudor House",        2747f, 2855f),
        new LM("Winter Gardens",     2885f, 3145f),
        new LM("Shell Grotto",       3119f, 2663f),
        new LM("Cliftonville Lido",  3170f, 3162f),
        new LM("Walpole Bay Pool",   4119f, 3310f),
        new LM("Theatre Royal",      2798f, 2566f),
        new LM("Jubilee Clock Tower",2374f, 2555f),
        new LM("Dreamland",          2300f, 2292f),
        new LM("Arlington House",    2106f, 2426f),
        new LM("Nayland Rock Hotel", 1815f, 2469f),
        new LM("Railway Station",    1928f, 2349f),
        new LM("Hartsdown Leisure",  1845f, 1963f),
    };

    Camera mapCam;
    RenderTexture rt;
    Material maskMat;
    Texture2D dot, arrow;
    int target = 0;
    GUIStyle label, sub;

    void Start()
    {
        var go = new GameObject("MinimapCamera");
        go.transform.SetParent(transform, false);
        mapCam = go.AddComponent<Camera>();
        mapCam.orthographic = true;
        mapCam.clearFlags = CameraClearFlags.SolidColor;
        mapCam.backgroundColor = new Color(0.62f, 0.70f, 0.78f);   // sea, for off-map edges
        mapCam.cullingMask = ~0;
        mapCam.nearClipPlane = 1f;
        mapCam.farClipPlane = camHeight + 400f;
        mapCam.transform.rotation = Quaternion.Euler(90f, 0f, 0f);  // straight down, north up
        mapCam.enabled = false;                                      // rendered manually

        rt = new RenderTexture(rtRes, rtRes, 16) { name = "MinimapRT" };
        mapCam.targetTexture = rt;

        var sh = Shader.Find("Margate/MinimapMask");
        if (sh != null) { maskMat = new Material(sh); maskMat.SetTexture("_MainTex", rt); }

        dot   = Solid(new Color(1f, 1f, 1f, 1f));
        arrow = Solid(new Color(1f, 0.85f, 0.25f, 1f));
    }

    static Texture2D Solid(Color c)
    {
        var t = new Texture2D(1, 1); t.SetPixel(0, 0, c); t.Apply(); return t;
    }

    void LateUpdate()
    {
        Cycle();
        Zoom();
        var p = transform.position;
        mapCam.transform.position = new Vector3(p.x, p.y + camHeight, p.z);
        mapCam.orthographicSize = zoom;
        mapCam.Render();
    }

    void Cycle()
    {
        bool next = false, prev = false;
#if ENABLE_INPUT_SYSTEM
        var k = Keyboard.current;
        if (k != null) { next = k.tabKey.wasPressedThisFrame; prev = k.qKey.wasPressedThisFrame; }
#else
        next = Input.GetKeyDown(KeyCode.Tab); prev = Input.GetKeyDown(KeyCode.Q);
#endif
        if (next) target = (target + 1) % Landmarks.Length;
        if (prev) target = (target + Landmarks.Length - 1) % Landmarks.Length;
    }

    void Zoom()
    {
        float s = 0f;
#if ENABLE_INPUT_SYSTEM
        var m = Mouse.current; var k = Keyboard.current;
        if (m != null) s = m.scroll.ReadValue().y * 0.01f;
        if (k != null) { if (k.minusKey.isPressed) s -= 0.6f; if (k.equalsKey.isPressed) s += 0.6f; }
#else
        s = Input.GetAxisRaw("Mouse ScrollWheel") * 10f;
        if (Input.GetKey(KeyCode.Minus)) s -= 0.6f; if (Input.GetKey(KeyCode.Equals)) s += 0.6f;
#endif
        if (Mathf.Abs(s) > 0.001f)
            zoom = Mathf.Clamp(zoom * Mathf.Exp(-s * 0.06f), minZoom, maxZoom);
    }

    void OnGUI()
    {
        if (maskMat == null || rt == null) return;
        if (label == null)
        {
            label = new GUIStyle(GUI.skin.label) { fontSize = 13, alignment = TextAnchor.UpperLeft };
            label.normal.textColor = Color.white;
            sub = new GUIStyle(label) { fontSize = 11 };
            sub.normal.textColor = new Color(0.85f, 0.88f, 0.92f);
        }

        var r = new Rect(marginPx, marginPx, sizePx, sizePx);
        Vector2 c = r.center;
        float radius = sizePx * 0.5f;

        if (Event.current.type == EventType.Repaint)
            Graphics.DrawTexture(r, rt, maskMat);

        // world -> minimap pixels (north up, so +z is up the screen)
        Vector3 me = transform.position;
        Vector2 ToMap(Vector2 world)
        {
            Vector2 d = world - new Vector2(me.x, me.z);
            return c + new Vector2(d.x / zoom * radius, -d.y / zoom * radius);
        }

        // landmarks
        for (int i = 0; i < Landmarks.Length; i++)
        {
            Vector2 sp = ToMap(Landmarks[i].p);
            bool isTarget = i == target;
            if ((sp - c).magnitude > radius - 6f)
            {
                if (!isTarget) continue;                       // only the target gets a rim marker
                Vector2 dir = (sp - c).normalized;
                sp = c + dir * (radius - 12f);
                Blip(sp, 9f, new Color(1f, 0.82f, 0.2f, 1f));
            }
            else Blip(sp, isTarget ? 8f : 4.5f,
                      isTarget ? new Color(1f, 0.82f, 0.2f, 1f) : new Color(1f, 1f, 1f, 0.75f));
        }

        // player, pointing where the camera is looking
        DrawArrow(c, transform.eulerAngles.y, 11f, new Color(0.25f, 0.85f, 1f, 1f));

        // north tick on the rim
        Blip(c + new Vector2(0, -(radius - 9f)), 3.5f, new Color(0.95f, 0.35f, 0.35f, 1f));
        GUI.Label(new Rect(c.x - 6, r.y - 2, 20, 18), "N", sub);

        // target readout
        var t = Landmarks[target];
        float dist = Vector2.Distance(new Vector2(me.x, me.z), t.p);
        var bar = new Rect(marginPx, marginPx + sizePx + 4, sizePx + 60, 34);
        GUI.color = new Color(0, 0, 0, 0.45f);
        GUI.DrawTexture(bar, Texture2D.whiteTexture);
        GUI.color = Color.white;
        GUI.Label(new Rect(bar.x + 8, bar.y + 2, bar.width - 10, 18), $"► {t.name}", label);
        GUI.Label(new Rect(bar.x + 8, bar.y + 17, bar.width - 10, 16),
                  $"{dist:0} m   ·   Tab / Q to cycle   ·   scroll to zoom ({zoom:0} m)", sub);
    }

    void Blip(Vector2 p, float s, Color col)
    {
        GUI.color = new Color(0, 0, 0, 0.55f);
        GUI.DrawTexture(new Rect(p.x - s * 0.5f - 1, p.y - s * 0.5f - 1, s + 2, s + 2), dot);
        GUI.color = col;
        GUI.DrawTexture(new Rect(p.x - s * 0.5f, p.y - s * 0.5f, s, s), dot);
        GUI.color = Color.white;
    }

    void DrawArrow(Vector2 p, float headingDeg, float s, Color col)
    {
        var m = GUI.matrix;
        GUIUtility.RotateAroundPivot(headingDeg, p);
        GUI.color = new Color(0, 0, 0, 0.6f);
        GUI.DrawTexture(new Rect(p.x - s * 0.32f, p.y - s * 0.7f, s * 0.64f, s * 1.4f), arrow);
        GUI.color = col;
        GUI.DrawTexture(new Rect(p.x - s * 0.22f, p.y - s * 0.6f, s * 0.44f, s * 1.2f), arrow);
        GUI.color = Color.white;
        GUI.matrix = m;
    }

    void OnDestroy()
    {
        if (rt != null) rt.Release();
    }
}
