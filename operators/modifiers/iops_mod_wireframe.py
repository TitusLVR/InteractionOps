from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="WIREFRAME", icon="MOD_WIREFRAME", group="GENERATE",
    defaults={"thickness": 0.02, "use_replace": True},
    scale_props=("thickness",),
    sort_weight=50,
    is_noop=lambda md: md.thickness == 0.0,
))
