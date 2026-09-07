from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="WELD", icon="AUTOMERGE_OFF", group="GENERATE",
    defaults={"merge_threshold": 0.001},
    scale_props=("merge_threshold",),
))
