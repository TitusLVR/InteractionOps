import os
import bpy

from ..ui.draw.theme import get_theme, Role
from ..ui.hud import text as hud_text
from ..ui.hud.text import draw as hud_text_draw, measure as hud_text_measure

# Object types whose data block carries material slots — gates the material
# stat line so empties/lights/cameras don't show a useless "No material".
_MATERIAL_OBJECT_TYPES = frozenset(
    {"MESH", "CURVE", "SURFACE", "META", "FONT",
     "GREASEPENCIL", "GPENCIL", "VOLUME", "POINTCLOUD"}
)


def draw_iops_statistics():
    context = bpy.context
    if not context.area or context.area.type != "VIEW_3D":
        return
    if not context.region or context.region.type != "WINDOW":
        return

    try:
        prefs = context.preferences.addons["InteractionOps"].preferences
    except KeyError:
        return
    if not prefs.iops_stat:
        return

    area_3d = context.area
    space_3d = context.space_data
    show_overlays = space_3d.overlay.show_overlays if space_3d else True

    theme = get_theme(context)

    # Stat overlay sits in the top-left of the 3D view, offset from the
    # toolbar (TOOLS region). Position uses the unified HUD padding.
    t_offset = 0
    for region in area_3d.regions:
        if region.type == "TOOLS":
            t_offset = region.width
            break

    offset_x = t_offset + theme.stats_offset_x
    line_h = theme.text_size("stats")
    offset_y = area_3d.height - theme.stats_offset_y - line_h
    row_step = int(line_h * float(getattr(theme, "stats_row_spacing", 1.5)))

    base_column_x = offset_x + int(line_h
                                   * float(getattr(theme, "stats_column_spacing", 9.0)))

    def _t(text, *, role=None, color=None, x=offset_x, y=None):
        if y is None:
            y = offset_y
        eff_color = color
        if eff_color is None and role is not None:
            r, g, b, a = theme.color_for(role)
            eff_color = (r, g, b, a * (1.0 if show_overlays else 0.0))
        hud_text_draw(text, int(x), int(y), theme=theme,
                      color=eff_color, role=role, size_token="stats",
                      alpha_mul=(1.0 if show_overlays else 0.0))

    def _dim(text):
        return hud_text_measure(text, theme=theme, size_token="stats")

    active_object = context.active_object

    try:
        if prefs.show_filename_stat:
            file_saved = bpy.data.is_saved
            file_dirty = bpy.data.is_dirty
            if file_saved and bpy.data.filepath:
                filename = os.path.basename(bpy.data.filepath)
                file_status = filename + "*" if file_dirty else filename
            else:
                file_status = "Unsaved"

            _t("File:", role=Role.HUD_LABEL)
            value_role = Role.HUD_LABEL_ACTIVE if (file_saved and not file_dirty) else Role.HUD_STATS_ERROR
            _t(file_status, role=value_role, x=base_column_x)
            offset_y -= row_step

        unit_settings = context.scene.unit_settings

        def _fmt_len(value):
            if unit_settings.system != "NONE":
                return bpy.utils.units.to_string(
                    unit_settings.system, "LENGTH",
                    value * unit_settings.scale_length, precision=2)
            return f"{value:.2f}"

        if active_object:
            if prefs.show_dimensions_stat:
                dims = active_object.dimensions
                if dims.x or dims.y or dims.z:
                    _t("Dims:", role=Role.HUD_LABEL)
                    _t(" x ".join(_fmt_len(d) for d in dims),
                       role=Role.HUD_LABEL_ACTIVE, x=base_column_x)
                    offset_y -= row_step

            if prefs.show_view_position_stat:
                loc = active_object.matrix_world.translation
                value = f"{loc.x:.2f}, {loc.y:.2f}, {loc.z:.2f}"
                rv3d = space_3d.region_3d if space_3d else None
                if rv3d:
                    dist = (rv3d.view_matrix @ loc).length
                    value += f"   Dist: {_fmt_len(dist)}"
                _t("Pos:", role=Role.HUD_LABEL)
                _t(value, role=Role.HUD_LABEL_ACTIVE, x=base_column_x)
                offset_y -= row_step

            if (prefs.show_material_stat
                    and active_object.type in _MATERIAL_OBJECT_TYPES):
                slots = active_object.material_slots
                filled = sum(1 for slot in slots if slot.material)
                mat = active_object.active_material
                segments = []
                if mat:
                    name = mat.name
                    if prefs.show_material_users_stat and mat.users > 1:
                        name += f" ({mat.users} users)"
                    segments.append((f"{name} [{filled}/{len(slots)}]",
                                     Role.HUD_LABEL_ACTIVE))
                else:
                    segments.append(("No material", Role.HUD_STATS_ERROR))
                if slots and filled < len(slots):
                    segments.append(("Empty slots", Role.HUD_STATS_ERROR))
                _t("Mat:", role=Role.HUD_LABEL)
                col_x = base_column_x
                for seg_text, seg_role in segments:
                    _t(seg_text, role=seg_role, x=col_x)
                    w, _h = _dim(seg_text)
                    col_x += w + 6
                offset_y -= row_step

            if prefs.show_modifiers_stat and active_object.modifiers:
                mods = active_object.modifiers
                count = str(len(mods))
                _t("Mods:", role=Role.HUD_LABEL)
                _t(count, role=Role.HUD_LABEL_ACTIVE, x=base_column_x)
                if any(m.show_viewport != m.show_render for m in mods):
                    w, _h = _dim(count)
                    _t("viewport ≠ render", role=Role.HUD_STATS_ERROR,
                       x=base_column_x + w + 6)
                offset_y -= row_step

            if prefs.show_instances_stat:
                obj_data = getattr(active_object, "data", None)
                if obj_data is not None:
                    users = obj_data.users - (1 if obj_data.use_fake_user else 0)
                    if users > 1:
                        _t("Instances:", role=Role.HUD_LABEL)
                        _t(str(users), role=Role.HUD_STATS_ERROR,
                           x=base_column_x)
                        offset_y -= row_step

            if prefs.show_parent_stat and (active_object.parent
                                           or active_object.constraints):
                _t("Parent:", role=Role.HUD_LABEL)
                col_x = base_column_x
                if active_object.parent:
                    parent_name = active_object.parent.name
                    _t(parent_name, role=Role.HUD_LABEL_ACTIVE, x=col_x)
                    w, _h = _dim(parent_name)
                    col_x += w + 6
                constraint_count = len(active_object.constraints)
                if constraint_count:
                    _t(f"+{constraint_count} constraints",
                       role=Role.HUD_LABEL_ACTIVE, x=col_x)
                offset_y -= row_step

        if prefs.show_units_stat and unit_settings.scale_length != 1.0:
            _t("Units:", role=Role.HUD_LABEL)
            _t(f"scale {unit_settings.scale_length:g}",
               role=Role.HUD_STATS_ERROR, x=base_column_x)
            offset_y -= row_step

        if active_object and active_object.type == "MESH":
            scale_stat = []
            scale = active_object.scale
            if scale[0] != 1 and scale[1] != 1 and scale[2] != 1:
                scale_stat.append("≠ 1")
            if scale[0] != scale[1] or scale[1] != scale[2] or scale[0] != scale[2]:
                scale_stat.append("Non-uniform")
            if scale[0] < 0 or scale[1] < 0 or scale[2] < 0:
                scale_stat.append("Negative")

            all_uvmap_names = []
            active_uvmaps = set()
            render_uvmaps = set()
            seen = set()
            selected_meshes = [
                obj for obj in context.selected_objects if obj.type == "MESH"
            ]
            if active_object not in selected_meshes:
                selected_meshes.insert(0, active_object)
            for obj in selected_meshes:
                obj_data = obj.data
                if not obj_data.uv_layers:
                    continue
                if obj_data.uv_layers.active:
                    active_uvmaps.add(obj_data.uv_layers.active.name)
                for uv in obj_data.uv_layers:
                    if uv.name not in seen:
                        seen.add(uv.name)
                        all_uvmap_names.append(uv.name)
                    if uv.active_render:
                        render_uvmaps.add(uv.name)

            _t("UVMaps:", role=Role.HUD_LABEL)
            col_x = base_column_x
            if all_uvmap_names:
                for uvmap in all_uvmap_names:
                    is_render = uvmap in render_uvmaps
                    display = "[ " + uvmap + " ]" if is_render else uvmap
                    role = Role.HUD_LABEL_ACTIVE if uvmap in active_uvmaps else Role.HUD_LABEL
                    _t(display, role=role, x=col_x)
                    w, _h = _dim(display)
                    col_x += w + 6
                offset_y -= row_step
            else:
                _t("No UVMaps", role=Role.HUD_STATS_ERROR, x=base_column_x)
                offset_y -= row_step

            if scale_stat:
                _t("Scale:", role=Role.HUD_LABEL)
                col_x = base_column_x
                for s in scale_stat:
                    _t(s, role=Role.HUD_STATS_ERROR, x=col_x)
                    w, _h = _dim(s)
                    col_x += w + 6
                offset_y -= row_step
        else:
            _t("- - -", role=Role.HUD_LABEL)

        if context.selected_objects:
            scaled_objects = []
            for obj in context.selected_objects:
                if obj.type != "MESH":
                    continue
                if obj is active_object:
                    continue
                s = obj.scale
                if s[0] != 1 or s[1] != 1 or s[2] != 1:
                    scaled_objects.append(obj)
            if scaled_objects:
                _t("Selection:", role=Role.HUD_LABEL)
                _t("There are scaled objects", role=Role.HUD_STATS_ERROR, x=base_column_x)
                offset_y -= row_step

    except Exception:
        pass
    finally:
        # blf shadow is a *global* state bit on the shared UI font (id 0 when
        # no custom font_path) — the same font the outliner draws its rows
        # with. `configure()` enables SHADOW and leaves it on; on the next
        # same-pass redraw that bleeds into the outliner's text, which the
        # user sees as row flicker on click (only when shadow is enabled).
        # Hard-disable it after our draw so our HUD state never escapes into
        # Blender's own UI rendering.
        import blf
        try:
            blf.disable(hud_text._resolve_font(theme), blf.SHADOW)
        except Exception:
            pass
