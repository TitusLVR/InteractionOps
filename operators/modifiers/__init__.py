"""iOps Modifiers panel operators. Descriptor files register themselves
into iops_mod_registry.REGISTRY on import; tool operator files are added by later
tasks. `classes` is consumed by the addon root __init__."""

from . import iops_mod_registry
from . import iops_mod_presets as presets

# Descriptor files — import order defines grid order inside each group.
from . import (
    iops_mod_bevel, iops_mod_boolean, iops_mod_mirror, iops_mod_array, iops_mod_solidify,
    iops_mod_subsurf, iops_mod_screw, iops_mod_weld, iops_mod_triangulate, iops_mod_decimate,
    iops_mod_remesh, iops_mod_wireframe,
    iops_mod_curve, iops_mod_lattice, iops_mod_simple_deform, iops_mod_displace,
    iops_mod_shrinkwrap,
    iops_mod_weighted_normal,
)

from . import iops_mod_stack

classes = (
    iops_mod_registry.IOPS_OT_ModGridClick,
    iops_mod_stack.IOPS_OT_ModStackAction,
)
