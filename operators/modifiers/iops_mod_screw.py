from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="SCREW", icon="MOD_SCREW", group="GENERATE",
    defaults={"axis": "Z", "steps": 16, "render_steps": 16},
    object_fields=("object",),
    scale_props=("screw_offset",),
))
