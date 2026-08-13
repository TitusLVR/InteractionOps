from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="WEIGHTED_NORMAL", icon="MOD_NORMALEDIT", group="UTILITY",
    defaults={"keep_sharp": True, "weight": 50},
    sort_weight=85,
))
