from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="CURVE", icon="MOD_CURVE", group="DEFORM",
    defaults={"deform_axis": "POS_X"},
    object_fields=("object",),
    requires_target=True,
))
