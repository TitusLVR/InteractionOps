from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="SUBSURF", icon="MOD_SUBSURF", group="GENERATE",
    defaults={"levels": 2, "render_levels": 2},
    sort_weight=50,
    is_noop=lambda md: md.levels == 0 and md.render_levels == 0,
))
