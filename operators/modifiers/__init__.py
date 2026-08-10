"""iOps Modifiers panel operators. Descriptor files register themselves
into iops_mod_registry.REGISTRY on import; tool operator files are added by later
tasks. `classes` is consumed by the addon root __init__."""

from . import iops_mod_registry

classes = (
    iops_mod_registry.IOPS_OT_ModGridClick,
)
