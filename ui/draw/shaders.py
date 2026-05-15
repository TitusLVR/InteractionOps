"""Shader cache for the unified UI draw layer.

Three shaders:
- UNIFORM_COLOR — builtin, used for filled tris and simple lines
- POLYLINE_UNIFORM_COLOR — builtin, antialiased lines independent of MSAA
- POINT_DISC — custom: antialiased filled disc with 1px contrasting ring.
  Point size is driven by `gpu.state.point_size_set(px)` from the caller —
  we do NOT write gl_PointSize from VS because that path requires
  GL_PROGRAM_POINT_SIZE which Blender does not enable by default for
  custom shaders.
"""
from __future__ import annotations
import gpu


_POINT_DISC_VS = """
void main() {
    gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
}
"""

_POINT_DISC_FS = """
void main() {
    vec2 uv = gl_PointCoord * 2.0 - 1.0;
    float d = length(uv);

    // Width of the antialias band in disc-radius units. Use the larger of
    // the screen-space derivative and a small floor so tiny points still
    // smooth visibly.
    float aa = max(fwidth(d), 0.5 / max(pointSize, 2.0));

    // Outer edge soft fade: alpha=1 inside, alpha=0 just outside radius=1.
    float outer = 1.0 - smoothstep(1.0 - aa, 1.0, d);
    if (outer <= 0.0) discard;

    // Ring thickness: ~1 px relative to point size, clamped so it never
    // collapses below the AA band.
    float ring_thickness = max(1.5 / max(pointSize, 2.0), aa);
    float ring_inner = 1.0 - ring_thickness;

    // Smooth transition between fill and ring zones.
    float in_ring = smoothstep(ring_inner - aa, ring_inner, d);
    float fill_a = (1.0 - in_ring) * outer;
    float ring_a = in_ring * outer;

    vec4 c = color * fill_a + ringColor * ring_a;
    // Premultiplied-style accumulation kept simple: rely on caller's ALPHA blend.
    c.a = color.a * fill_a + ringColor.a * ring_a;
    fragColor = c;
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


def _build_point_disc():
    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant("MAT4", "ModelViewProjectionMatrix")
    info.push_constant("FLOAT", "pointSize")
    info.push_constant("VEC4", "color")
    info.push_constant("VEC4", "ringColor")
    info.vertex_in(0, "VEC3", "pos")
    info.fragment_out(0, "VEC4", "fragColor")
    info.vertex_source(_POINT_DISC_VS)
    info.fragment_source(_POINT_DISC_FS)
    return gpu.shader.create_from_info(info)


def point_disc():
    s = _cache.get("POINT_DISC")
    if s is None:
        s = _build_point_disc()
        _cache["POINT_DISC"] = s
    return s


def reset_cache():
    _cache.clear()
