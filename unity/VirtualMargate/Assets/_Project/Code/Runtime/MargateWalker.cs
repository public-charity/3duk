using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

/// First-person walker. Currently set to 30 mph for navigating the grey-box --
/// Margate is ~6 km across and real walking pace (1.4 m/s) is slow for scouting.
/// Drop walkSpeed back to 1.4 when you want the town to read at true scale.
[RequireComponent(typeof(CharacterController))]
public class MargateWalker : MonoBehaviour
{
    // TEMPORARY navigation speed. 13.41 m/s = 30 mph, 26.82 = 60 mph.
    // Real walking pace is 1.4 -- restore that once the town is worth walking slowly.
    public float walkSpeed = 13.41f;
    public float sprintSpeed = 26.82f;
    public float mouseSensitivity = 0.12f;
    public float eyeHeight = 1.7f;
    public Transform cam;
    [Tooltip("Face this way on start, degrees clockwise from north. 0 = north (out to sea).")]
    public float startHeading = 340f;

    CharacterController cc;
    float pitch, yaw, vy;
    bool showHint = true;
    float hintT;

    void Start()
    {
        cc = GetComponent<CharacterController>();
        cc.height = 1.8f; cc.radius = 0.3f; cc.center = new Vector3(0, 0.9f, 0);
        cc.stepOffset = 0.3f; cc.slopeLimit = 55f;

        if (cam == null && Camera.main != null) cam = Camera.main.transform;
        if (cam != null) cam.localPosition = new Vector3(0, eyeHeight, 0);

        SnapToGround();
        yaw = startHeading;
        transform.rotation = Quaternion.Euler(0, yaw, 0);
        Lock(true);
    }

    /// Drop onto the terrain instead of spawning in mid-air. Ignores building roofs
    /// by preferring the lowest hit, so we always land in the street.
    void SnapToGround()
    {
        // Prefer the TerrainCollider. Building meshes include a plinth extruded below
        // ground, so "lowest hit" could otherwise drop us underneath a building.
        var from = new Vector3(transform.position.x, 500f, transform.position.z);
        var hits = Physics.RaycastAll(from, Vector3.down, 800f, ~0, QueryTriggerInteraction.Ignore);
        float best = float.NaN;
        foreach (var h in hits)
            if (h.collider is TerrainCollider) { best = h.point.y; break; }
        if (float.IsNaN(best))
            foreach (var h in hits)
                if (float.IsNaN(best) || h.point.y < best) best = h.point.y;
        if (!float.IsNaN(best))
        {
            cc.enabled = false;
            transform.position = new Vector3(transform.position.x, best + 0.15f, transform.position.z);
            cc.enabled = true;
        }
    }

    void Lock(bool on)
    {
        Cursor.lockState = on ? CursorLockMode.Locked : CursorLockMode.None;
        Cursor.visible = !on;
    }

    void Update()
    {
        Vector2 look = Vector2.zero, move = Vector2.zero;
        bool sprint = false, unlock = false, click = false;
#if ENABLE_INPUT_SYSTEM
        var k = Keyboard.current; var m = Mouse.current;
        if (m != null) { look = m.delta.ReadValue(); click = m.leftButton.wasPressedThisFrame; }
        if (k != null) {
            if (k.wKey.isPressed || k.upArrowKey.isPressed)    move.y += 1;
            if (k.sKey.isPressed || k.downArrowKey.isPressed)  move.y -= 1;
            if (k.dKey.isPressed || k.rightArrowKey.isPressed) move.x += 1;
            if (k.aKey.isPressed || k.leftArrowKey.isPressed)  move.x -= 1;
            sprint = k.leftShiftKey.isPressed;
            unlock = k.escapeKey.wasPressedThisFrame;
        }
#else
        look   = new Vector2(Input.GetAxisRaw("Mouse X"), Input.GetAxisRaw("Mouse Y")) * 8f;
        move   = new Vector2(Input.GetAxisRaw("Horizontal"), Input.GetAxisRaw("Vertical"));
        sprint = Input.GetKey(KeyCode.LeftShift);
        unlock = Input.GetKeyDown(KeyCode.Escape);
        click  = Input.GetMouseButtonDown(0);
#endif
        if (unlock) Lock(false);
        else if (click && Cursor.lockState != CursorLockMode.Locked) Lock(true);   // click to re-capture

        // Look only while captured...
        if (Cursor.lockState == CursorLockMode.Locked)
        {
            yaw += look.x * mouseSensitivity;
            pitch = Mathf.Clamp(pitch - look.y * mouseSensitivity, -85f, 85f);
            transform.rotation = Quaternion.Euler(0, yaw, 0);
            if (cam) cam.localRotation = Quaternion.Euler(pitch, 0, 0);
        }
        else move = Vector2.zero;

        // ...but ALWAYS apply gravity. Gating this behind the cursor lock left the
        // player hanging in mid-air whenever the Game view lost focus.
        Vector3 dir = transform.right * move.x + transform.forward * move.y;
        if (dir.sqrMagnitude > 1f) dir.Normalize();
        vy = cc.isGrounded ? -2f : vy + Physics.gravity.y * Time.deltaTime;
        cc.Move((dir * (sprint ? sprintSpeed : walkSpeed) + Vector3.up * vy) * Time.deltaTime);

        if (showHint) { hintT += Time.deltaTime; if (hintT > 12f) showHint = false; }
    }

    void OnGUI()
    {
        if (!showHint) return;
        var st = new GUIStyle(GUI.skin.label) { fontSize = 15, alignment = TextAnchor.UpperLeft };
        st.normal.textColor = Color.white;
        GUI.color = new Color(0, 0, 0, 0.55f);
        GUI.DrawTexture(new Rect(8, 8, 470, 74), Texture2D.whiteTexture);
        GUI.color = Color.white;
        GUI.Label(new Rect(18, 14, 460, 70),
            "WASD move (30 mph)  ·  Shift = 60 mph  ·  mouse look  ·  Esc release cursor  ·  click to re-capture\n" +
            "You are in the Old Town. Ahead/right: Droit House and the Harbour Arm.\n" +
            "Left along the front: the Clock Tower, Arlington House, Dreamland.", st);
    }
}
