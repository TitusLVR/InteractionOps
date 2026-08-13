from .iops_mod_registry import ModDescriptor, register_descriptor

register_descriptor(ModDescriptor(
    mod_type="REMESH", icon="MOD_REMESH", group="GENERATE",
    defaults={"mode": "VOXEL", "voxel_size": 0.05},
    scale_props=("voxel_size",),
    sort_weight=50,
))
