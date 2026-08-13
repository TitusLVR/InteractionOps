from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="DECIMATE", icon="MOD_DECIM", group="GENERATE",
    defaults={"decimate_type": "COLLAPSE", "ratio": 0.5},
    sort_weight=50,
    is_noop=lambda md: md.decimate_type == "COLLAPSE" and md.ratio >= 1.0,
))
