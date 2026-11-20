"""Group tables for the IOPS Pie (no bpy: imported by the pytest suite).

PIE_GROUPS[mode][slot] = (title, rows). A row is a list of entries drawn side
by side; an entry is (idname, text, props). VERTEX_COLOR in place of rows
means the custom Vertex Color box. A slot missing from a table is empty.
"""

# Blender pie fill order.
SLOTS = ("LEFT", "RIGHT", "BOTTOM", "TOP",
         "TOP_LEFT", "TOP_RIGHT", "BOTTOM_LEFT", "BOTTOM_RIGHT")

# Group keys that are not pie slots of their own: extra columns of the top
# panel, drawn to the right of TOP_RIGHT.
EXTRA_COLUMNS = ("TOP_FAR_RIGHT",)

VERTEX_COLOR = "VERTEX_COLOR"


def _col(*entries):
    """One entry per row: (idname, text) or (idname, text, props)."""
    return [[(e[0], e[1], e[2] if len(e) > 2 else {})] for e in entries]


PIE_GROUPS = {
    "OBJECT": {
        "LEFT": ("Transform & Align", _col(
            ("iops.object_aligner", "Object Aligner"),
            ("iops.object_align_between_two", "Align Between Two"),
            ("iops.object_modal_three_point_rotation", "3 Point Rotation"),
            ("iops.object_mirror_rotate", "Mirror Rotate"),
            ("iops.object_match_transform_active", "Match Dimensions"),
            ("iops.object_normalize", "Normalize"),
            ("iops.object_change_scale", "Change Scale"),
            ("iops.object_visual_origin", "Visual Origin"),
            ("iops.object_drop_it", "Drop It!"),
        )),
        "RIGHT": ("Arrange", [
            [("iops.object_replace", "Object Replace", {})],
            [("iops.object_radial_array", "Radial Array", {})],
            [("iops.object_kitbash_grid", "Grid", {}),
             ("iops.object_kitbash_grid", "Grid to Center", {"arrange_mode": "CENTER"})],
            [("iops.object_to_grid_from_active", "To Grid From Active", {})],
        ]),
        "BOTTOM": ("Vertex Color", VERTEX_COLOR),
        "TOP": ("Select & Name", _col(
            ("iops.object_select_similar_name", "Select Similar Name"),
            ("iops.object_name_from_active", "Name From Active"),
            ("iops.object_search_rename", "Search & Replace"),
            ("iops.object_select_boolean_operands", "Select Boolean Operands"),
            ("iops.object_select_boolean_targets", "Select Boolean Targets"),
            ("iops.object_select_mirror_objects", "Select Mirror Objects"),
        )),
        "TOP_FAR_RIGHT": ("Overlays", _col(
            ("iops.object_negative_scale_overlay", "Negative Scale Overlay"),
            ("iops.mesh_zfight_overlay", "Z-Fight Overlay"),
            ("iops.mesh_hidden_faces_overlay", "Hidden Faces Overlay"),
        )),
        "TOP_LEFT": ("Modifiers", _col(
            ("iops.modifier_easy_array_caps", "Easy Array Caps"),
            ("iops.modifier_easy_array_curve", "Easy Array Curve"),
            ("iops.modifier_easy_curve", "Easy Curve"),
            ("iops.modifier_easy_shwarp", "Easy SHWARP"),
        )),
        "TOP_RIGHT": ("Assets & Files", _col(
            ("iops.materials_from_textures", "Materials from Textures"),
            ("iops.call_panel_material_override", "Material Override"),
            ("iops.assets_render_asset_thumbnail", "Render Asset Thumbnail"),
            ("iops.reload_libraries", "Reload Libraries"),
            ("iops.reload_images", "Reload Images"),
        )),
    },
    "EDIT_MESH": {
        "BOTTOM": ("Vertex Color", VERTEX_COLOR),
        "LEFT": ("Mesh", _col(
            ("iops.mesh_inset", "Inset"),
            ("iops.mesh_edge_slide", "Edge Slide"),
            ("iops.mesh_straight_bevel", "Straight Bevel"),
            ("iops.mesh_shear", "Shear"),
            ("iops.mesh_hinge", "Hinge"),
            ("iops.mesh_converge", "Converge"),
            ("iops.mesh_vert_fuse", "Vert Fuse"),
            ("iops.mesh_quick_connect", "Quick Connect"),
            ("iops.mesh_quick_snap", "Quick Snap"),
            ("iops.mesh_to_tris_to_quads", "Tris to Quads"),
            ("iops.mesh_cursor_bisect", "Cursor Bisect"),
            ("iops.mesh_to_grid", "To Grid"),
            ("iops.mesh_snapshot", "Mesh Snapshot"),
        )),
        "RIGHT": ("UV", _col(
            ("iops.mesh_uv_stripe", "UV Stripe"),
            ("iops.mesh_uv_stripe_interactive", "UV Stripe (Interactive)"),
            ("iops.mesh_uv_pipe", "UV Pipe"),
            ("iops.mesh_uv_shortest_mark", "UV Shortest Path Mark"),
            ("iops.mesh_uv_channel_hop", "UV Channel Hop"),
            ("iops.mesh_visual_uv", "Visual UV"),
        )),
        "TOP": ("Measure & Align", _col(
            ("iops.mesh_copy_edge_length", "Copy Edge Length"),
            ("iops.mesh_copy_edges_angle", "Copy Edges Angle"),
            ("iops.mesh_align_origin_to_normal", "Align Origin to Normal"),
            ("iops.mesh_align_object_to_face", "Align Object to Face"),
        )),
        "TOP_FAR_RIGHT": ("Overlays", _col(
            ("iops.mesh_nonplanar_overlay", "Non-Planar Overlay"),
            ("iops.mesh_zfight_overlay", "Z-Fight Overlay"),
            ("iops.mesh_hidden_faces_overlay", "Hidden Faces Overlay"),
        )),
        "TOP_LEFT": ("Bevel", _col(
            ("iops.pin_unwrap_bevel", "Pin & Unwrap Bevel"),
            ("iops.bevel_edge_data_fix", "Bevel Edge Data Fix"),
        )),
    },
}


# Fixed number of button columns for a group; other groups are split in two
# when they are too long. Mesh stays one column: the pie moves the top and
# bottom panels away from it instead.
GROUP_COLUMNS = {"Mesh": 1}


def groups_for_mode(mode):
    """Edit Mesh gets its own set; every other mode falls back to Object."""
    if mode == "EDIT_MESH":
        return PIE_GROUPS["EDIT_MESH"]
    return PIE_GROUPS["OBJECT"]
