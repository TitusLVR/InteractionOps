from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="SOLIDIFY", icon="MOD_SOLIDIFY", group="GENERATE",
    defaults={"thickness": 0.02, "use_even_offset": True},
    scale_props=("thickness",),
    sort_weight=50,
    is_noop=lambda md: md.thickness == 0.0,
))
