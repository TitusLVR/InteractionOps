from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="BEVEL", icon="MOD_BEVEL", group="GENERATE",
    defaults={
        "width": 0.02, "segments": 2,
        "limit_method": "ANGLE", "angle_limit": 0.5235988,  # 30 deg
        "use_clamp_overlap": True, "harden_normals": False,
    },
    scale_props=("width",),
    sort_weight=50,
    is_noop=lambda md: md.width == 0.0,
))
