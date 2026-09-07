from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="LATTICE", icon="MOD_LATTICE", group="DEFORM",
    defaults={},
    object_fields=("object",),
    requires_target=True,
))
