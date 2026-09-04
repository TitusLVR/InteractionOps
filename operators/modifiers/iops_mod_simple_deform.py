from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="SIMPLE_DEFORM", icon="MOD_SIMPLEDEFORM", group="DEFORM",
    defaults={"deform_method": "BEND", "angle": 0.7853982},  # 45 deg
    object_fields=("origin",),
    is_noop=lambda md: md.deform_method in {"BEND", "TWIST"} and md.angle == 0.0,
))
