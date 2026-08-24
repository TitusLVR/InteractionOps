"""Sidebar panel for the ported library addon.

Ported from the source addon's ``FLT_KB_PT_sidebar`` (SRC 1784-1880) as
``IOPS_PT_Library``: master-file prop, find/refresh/clean-unlinked
operators, active-object/hierarchy info, publish buttons (object /
collection / material / shader group) and the library popup launcher.
"""

import bpy

from ..operators.library.common import get_catalog, get_prefs, object_hierarchy
from ..operators.library.library_publish import IOPS_OT_LibraryPublish
from ..operators.library.library_refresh import (
    IOPS_OT_LibraryFindMaster,
    IOPS_OT_LibraryRefresh,
)
from ..operators.library.library_remove import IOPS_OT_LibraryRemoveAsset
from ..operators.library.library_popup import IOPS_OT_LibraryPopup


class IOPS_PT_Library(bpy.types.Panel):
    bl_label = "IOPS Library"
    bl_idname = "IOPS_PT_Library"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "iOps"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        preferences = get_prefs(context)
        if preferences is None:
            layout.label(text="Add-on preferences unavailable.", icon="ERROR")
            return

        layout.prop(preferences, "library_master_file", text="Master")
        layout.operator(
            IOPS_OT_LibraryFindMaster.bl_idname,
            text="Find Master",
            icon="VIEWZOOM",
        )
        layout.operator(
            IOPS_OT_LibraryRefresh.bl_idname,
            text="Refresh Library",
            icon="FILE_REFRESH",
        )
        operator = layout.operator(
            IOPS_OT_LibraryRemoveAsset.bl_idname,
            text="Clean Unlinked Assets",
            icon="TRASH",
        )
        operator.mode = "CLEAN_UNLINKED"

        layout.separator()
        obj = context.active_object
        if obj is None:
            layout.label(text="No active object.", icon="INFO")
        else:
            hierarchy_count = len(object_hierarchy(obj))
            layout.label(text=obj.name, icon="OBJECT_DATA")
            if hierarchy_count > 1:
                layout.label(
                    text="%d objects in hierarchy" % hierarchy_count,
                    icon="OUTLINER_COLLECTION",
                )

        column = layout.column()
        column.enabled = not context.window_manager.iops_library_busy
        operator = column.operator(
            IOPS_OT_LibraryPublish.bl_idname,
            text="Publish Active Object",
            icon="OBJECT_DATA",
        )
        operator.publish_kind = "OBJECT"
        operator = column.operator(
            IOPS_OT_LibraryPublish.bl_idname,
            text="Publish Active Collection",
            icon="OUTLINER_COLLECTION",
        )
        operator.publish_kind = "COLLECTION"
        operator = column.operator(
            IOPS_OT_LibraryPublish.bl_idname,
            text="Publish Active Material",
            icon="MATERIAL",
        )
        operator.publish_kind = "MATERIAL"

        column.separator()
        column.prop_search(
            preferences,
            "library_shader_group",
            bpy.data,
            "node_groups",
            text="Shader Group",
        )
        operator = column.operator(
            IOPS_OT_LibraryPublish.bl_idname,
            text="Publish Shader Group",
            icon="NODETREE",
        )
        operator.publish_kind = "SHADER_GROUP"

        layout.separator()
        layout.operator(
            IOPS_OT_LibraryPopup.bl_idname,
            text="Open Library Popup",
            icon="ASSET_MANAGER",
        )
        layout.prop(preferences, "library_preview_size", slider=True)
        layout.label(
            text="%d synced asset(s)" % len(get_catalog(context)),
        )

        status = context.window_manager.iops_library_status
        if status:
            layout.separator()
            layout.label(text=status, icon="INFO")
