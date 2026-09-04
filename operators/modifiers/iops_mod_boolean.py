from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="BOOLEAN", icon="MOD_BOOLEAN", group="GENERATE",
    defaults={"solver": "EXACT"},
    object_fields=("object",),
    requires_target=True,
))
