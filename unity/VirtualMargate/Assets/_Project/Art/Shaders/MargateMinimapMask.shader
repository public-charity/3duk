// Masks the minimap render texture to a circle and draws its rim.
// Plain unlit so it works through Graphics.DrawTexture in OnGUI, which needs no
// uGUI canvas -- fewer moving parts than a Canvas + RawImage + mask material.
Shader "Margate/MinimapMask"
{
    Properties
    {
        _MainTex   ("Texture", 2D) = "white" {}
        _RimColor  ("Rim colour", Color) = (0.93, 0.94, 0.95, 1)
        _RimWidth  ("Rim width", Range(0,0.2)) = 0.035
        _Vignette  ("Edge darkening", Range(0,1)) = 0.35
    }
    SubShader
    {
        Tags { "Queue"="Overlay" "RenderType"="Transparent" "IgnoreProjector"="True" }
        Blend SrcAlpha OneMinusSrcAlpha
        ZTest Always ZWrite Off Cull Off Lighting Off

        Pass
        {
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            TEXTURE2D(_MainTex); SAMPLER(sampler_MainTex);
            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST; float4 _RimColor; float _RimWidth; float _Vignette;
            CBUFFER_END

            struct A { float4 pos : POSITION; float2 uv : TEXCOORD0; };
            struct V { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };

            V vert(A i) { V o; o.pos = TransformObjectToHClip(i.pos.xyz); o.uv = i.uv; return o; }

            half4 frag(V i) : SV_Target
            {
                float2 p = i.uv * 2.0 - 1.0;
                float  d = length(p);
                float  aa = fwidth(d) * 1.5;
                if (d > 1.0 + aa) discard;

                half3 col = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, i.uv).rgb;
                col *= lerp(1.0, 1.0 - _Vignette, smoothstep(0.55, 1.0, d));   // settle the eye centrally

                float inner = 1.0 - _RimWidth;
                float rim   = smoothstep(inner - aa, inner + aa, d);
                col = lerp(col, _RimColor.rgb, rim);

                float alpha = 1.0 - smoothstep(1.0 - aa, 1.0 + aa, d);
                return half4(col, alpha);
            }
            ENDHLSL
        }
    }
}
