"""Shader cache for the unified UI draw layer.

Three shaders:
- UNIFORM_COLOR — builtin, used for filled tris and simple lines
- POLYLINE_UNIFORM_COLOR — builtin, antialiased lines independent of MSAA
- POINT_DISC — custom: antialiased filled disc with 1px contrasting ring
"""
from __future__ import annotations
import gpu


_POINT_DISC_VS = """
in vec2 pos;
uniform mat4 ModelViewProjectionMatrix;
uniform float pointSize;
void main() {
    gl_Position = ModelViewProjectionMatrix * vec4(pos, 0.0, 1.0);
    gl_PointSize = pointSize;
}
"""

_POINT_DISC_FS = """
out vec4 fragColor;
uniform vec4 color;
uniform vec4 ringColor;
uniform float pointSize;
void main() {
    vec2 uv = gl_PointCoord * 2.0 - 1.0;
    float d = length(uv);
    float radius = 1.0;
    float ring_inner = 1.0 - (2.0 / max(pointSize, 2.0));
    float aa = fwidth(d) * 1.5;
    if (d > radius) discard;
    float fill_a = 1.0 - smoothstep(ring_inner - aa, ring_inner, d);
    float ring_a = smoothstep(ring_inner - aa, ring_inner, d) *
                   (1.0 - smoothstep(radius - aa, radius, d));
    fragColor = color * fill_a + ringColor * ring_a;
}
"""


_cache: dict[str, object] = {}


def uniform_color():
    s = _cache.get("UNIFORM_COLOR")
    if s is None:
        s = gpu.shader.from_builtin("UNIFORM_COLOR")
        _cache["UNIFORM_COLOR"] = s
    return s


def polyline_uniform_color():
    s = _cache.get("POLYLINE_UNIFORM_COLOR")
    if s is None:
        s = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        _cache["POLYLINE_UNIFORM_COLOR"] = s
    return s


def point_disc():
    s = _cache.get("POINT_DISC")
    if s is None:
        s = gpu.types.GPUShader(_POINT_DISC_VS, _POINT_DISC_FS)
        _cache["POINT_DISC"] = s
    return s


def reset_cache():
    _cache.clear()
