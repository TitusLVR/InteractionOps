from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="SHRINKWRAP", icon="MOD_SHRINKWRAP", group="DEFORM",
    defaults={"wrap_method": "NEAREST_SURFACEPOINT"},
    object_fields=("target", "auxiliary_target"),
    requires_target=True,
))
