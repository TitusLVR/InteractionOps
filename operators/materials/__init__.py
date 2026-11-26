"""iOps Materials: assignment, deduplication and material functions behind
the Materials panel (ui/iops_materials_panel.py). Decision logic without
bpy lives in utils/materials_core.py."""
from .assets import (
    IOPS_OT_MaterialAssetSelectUsers,
    IOPS_OT_MaterialAssignAsset,
    IOPS_OT_MaterialsClearAsset,
    IOPS_OT_MaterialsLibraryAdd,
    IOPS_OT_MaterialsMarkAsset,
)
from .assign import (
    IOPS_OT_MaterialAssign,
    IOPS_OT_MaterialAssignDrop,
    IOPS_OT_MaterialNew,
)
from .dedup import IOPS_OT_MaterialsMergeDuplicates
from .functions import (
    IOPS_OT_MaterialsClear,
    IOPS_OT_MaterialsCopyFromActive,
    IOPS_OT_MaterialsDeleteUnused,
    IOPS_OT_MaterialsRemoveEmptySlots,
    IOPS_OT_MaterialsRemoveUnusedSlots,
    IOPS_OT_MaterialsSelectUsers,
)
from .remap import IOPS_OT_MaterialsRemap
from .state import (
    IOPS_MaterialsRemapRow,
    IOPS_MaterialsState,
    register_props,
    unregister_props,
)

CLASSES = (
    IOPS_MaterialsRemapRow,   # before IOPS_MaterialsState (its collection)
    IOPS_MaterialsState,
    IOPS_OT_MaterialAssign,
    IOPS_OT_MaterialNew,
    IOPS_OT_MaterialAssignDrop,
    IOPS_OT_MaterialsMergeDuplicates,
    IOPS_OT_MaterialsRemap,
    IOPS_OT_MaterialsCopyFromActive,
    IOPS_OT_MaterialsSelectUsers,
    IOPS_OT_MaterialsRemoveUnusedSlots,
    IOPS_OT_MaterialsRemoveEmptySlots,
    IOPS_OT_MaterialsClear,
    IOPS_OT_MaterialsDeleteUnused,
    IOPS_OT_MaterialAssignAsset,
    IOPS_OT_MaterialAssetSelectUsers,
    IOPS_OT_MaterialsMarkAsset,
    IOPS_OT_MaterialsClearAsset,
    IOPS_OT_MaterialsLibraryAdd,
)

__all__ = ("CLASSES", "register_props", "unregister_props")
