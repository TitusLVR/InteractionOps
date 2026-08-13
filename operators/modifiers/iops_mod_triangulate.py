from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="TRIANGULATE", icon="MOD_TRIANGULATE", group="GENERATE",
    defaults={"keep_custom_normals": True, "min_vertices": 5},
    sort_weight=90,
))
