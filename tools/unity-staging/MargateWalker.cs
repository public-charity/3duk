using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

/// First-person walker. Deliberately walks at 1.4 m/s -- real human pace.
/// Game-standard 5 m/s makes a real town feel like a diorama; at true walking
/// speed Margate reads at the size it actually is.
[RequireComponent(typeof(CharacterController))]
public class MargateWalker : MonoBehaviour
{
    public float walkSpeed = 1.4f;
    public float sprintSpeed = 6.0f;
    public float mouseSensitivity = 0.12f;
    public float eyeHeight = 1.7f;
    public Transform cam;

    CharacterController cc;
    float pitch, yaw;
    float vy;

    void Start()
    {
        cc = GetComponent<CharacterController>();
        cc.height = eyeHeight + 0.1f; cc.radius = 0.3f; cc.stepOffset = 0.3f; cc.slopeLimit = 55f;
        if (cam == null && Camera.main != null) cam = Camera.main.transform;
        yaw = transform.eulerAngles.y;
        Cursor.lockState = CursorLockMode.Locked; Cursor.visible = false;
    }

    void Update()
    {
        Vector2 look = Vector2.zero, move = Vector2.zero;
        bool sprint = false, unlock = false;
#if ENABLE_INPUT_SYSTEM
        var k = Keyboard.current; var m = Mouse.current;
        if (m != null) look = m.delta.ReadValue();
        if (k != null) {
            if (k.wKey.isPressed) move.y += 1; if (k.sKey.isPressed) move.y -= 1;
            if (k.dKey.isPressed) move.x += 1; if (k.aKey.isPressed) move.x -= 1;
            sprint = k.leftShiftKey.isPressed; unlock = k.escapeKey.wasPressedThisFrame;
        }
#else
        look = new Vector2(Input.GetAxisRaw("Mouse X"), Input.GetAxisRaw("Mouse Y")) * 8f;
        move = new Vector2(Input.GetAxisRaw("Horizontal"), Input.GetAxisRaw("Vertical"));
        sprint = Input.GetKey(KeyCode.LeftShift); unlock = Input.GetKeyDown(KeyCode.Escape);
#endif
        if (unlock) { Cursor.lockState = CursorLockMode.None; Cursor.visible = true; }
        if (Cursor.lockState != CursorLockMode.Locked) return;

        yaw += look.x * mouseSensitivity;
        pitch = Mathf.Clamp(pitch - look.y * mouseSensitivity, -85f, 85f);
        transform.rotation = Quaternion.Euler(0, yaw, 0);
        if (cam) cam.localRotation = Quaternion.Euler(pitch, 0, 0);

        Vector3 dir = (transform.right * move.x + transform.forward * move.y);
        if (dir.sqrMagnitude > 1f) dir.Normalize();
        vy = cc.isGrounded ? -1f : vy + Physics.gravity.y * Time.deltaTime;
        cc.Move((dir * (sprint ? sprintSpeed : walkSpeed) + Vector3.up * vy) * Time.deltaTime);
    }
}
