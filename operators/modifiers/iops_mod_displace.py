from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="DISPLACE", icon="MOD_DISPLACE", group="DEFORM",
    defaults={"strength": 0.1, "direction": "NORMAL"},
    scale_props=("strength",),
    sort_weight=50,
    is_noop=lambda md: md.strength == 0.0,
))
