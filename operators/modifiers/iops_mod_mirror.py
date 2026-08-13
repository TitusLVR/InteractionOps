from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="MIRROR", icon="MOD_MIRROR", group="GENERATE",
    defaults={"use_axis": (True, False, False), "use_clip": True},
    object_fields=("mirror_object",),
    sort_weight=10,
))
