from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="ARRAY", icon="MOD_ARRAY", group="GENERATE",
    defaults={
        "count": 2, "use_relative_offset": True,
        "relative_offset_displace": (1.0, 0.0, 0.0),
    },
    object_fields=("offset_object", "start_cap", "end_cap", "curve"),
    scale_props=("constant_offset_displace",),
    is_noop=lambda md: md.fit_type == "FIXED_COUNT" and md.count <= 1,
))
