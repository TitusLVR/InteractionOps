import bpy
from bpy.types import Menu

# Slot numbers follow numpad positions, same as the Split pie (5 unused).
SHADING_PIE_SLOTS = (1, 2, 3, 4, 6, 7, 8, 9)

shading_type_list = [
    ("SOLID", "Solid", "Solid shading"),
    ("MATERIAL", "Material", "Material preview"),
    ("RENDERED", "Rendered", "Rendered preview"),
]

shading_light_list = [
    ("STUDIO", "Studio", "Studio lighting"),
    ("MATCAP", "MatCap", "MatCap lighting"),
    ("FLAT", "Flat", "Flat lighting"),
]

shading_color_type_list = [
    ("MATERIAL", "Material", "Material color"),
    ("OBJECT", "Object", "Object color"),
    ("VERTEX", "Attribute", "Color attribute"),
    ("SINGLE", "Single", "Single color"),
    ("RANDOM", "Random", "Random color per object"),
    ("TEXTURE", "Texture", "Texture color"),
]

_CRYPTO_PASSES = {"CryptoObject", "CryptoAsset", "CryptoMaterial"}

shading_render_pass_list = [
    ("COMBINED", "Combined", ""),
    ("EMISSION", "Emission", ""),
    ("ENVIRONMENT", "Environment", ""),
    ("AO", "AO", ""),
    ("SHADOW", "Shadow", ""),
    ("TRANSPARENT", "Transparent", ""),
    ("DIFFUSE_LIGHT", "Diffuse Light", ""),
    ("DIFFUSE_COLOR", "Diffuse Color", ""),
    ("SPECULAR_LIGHT", "Specular Light", ""),
    ("SPECULAR_COLOR", "Specular Color", ""),
    ("VOLUME_LIGHT", "Volume Light", ""),
    ("CryptoObject", "Crypto Object", "EEVEE only"),
    ("CryptoAsset", "Crypto Asset", "EEVEE only"),
    ("CryptoMaterial", "Crypto Material", "EEVEE only"),
]

_TYPE_ICONS = {
    "SOLID": "SHADING_SOLID",
    "MATERIAL": "MATERIAL",
    "RENDERED": "SHADING_RENDERED",
}


def _enum_label(items, key):
    for identifier, label, *_ in items:
        if identifier == key:
            return label
    return key


def get_shading_pie_prefs():
    return bpy.context.preferences.addons["InteractionOps"].preferences


def shading_slot_label(prefs, slot):
    """Slot button text: custom name, or an auto label from the stored state."""
    name = getattr(prefs, f"shading_pie_{slot}_name")
    if name:
        return name
    s_type = getattr(prefs, f"shading_pie_{slot}_type")
    if s_type == "SOLID":
        light = _enum_label(shading_light_list, getattr(prefs, f"shading_pie_{slot}_light"))
        color = _enum_label(shading_color_type_list, getattr(prefs, f"shading_pie_{slot}_color_type"))
        return f"{light} / {color}"
    base = "Material Preview" if s_type == "MATERIAL" else "Rendered"
    render_pass = getattr(prefs, f"shading_pie_{slot}_render_pass")
    if render_pass != "COMBINED":
        base = f"{base} / {_enum_label(shading_render_pass_list, render_pass)}"
    return base


class IOPS_OT_Apply_Shading_Preset(bpy.types.Operator):
    """Apply a shading preset stored in the addon preferences"""

    bl_idname = "iops.apply_shading_preset"
    bl_label = "Apply Shading Preset"

    slot: bpy.props.IntProperty(name="Slot", default=1, min=1, max=9)

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and context.space_data is not None
        )

    def execute(self, context):
        prefs = get_shading_pie_prefs()
        n = self.slot
        shading = context.space_data.shading

        s_type = getattr(prefs, f"shading_pie_{n}_type")
        shading.type = s_type

        if s_type == "SOLID":
            shading.light = getattr(prefs, f"shading_pie_{n}_light")
            color_type = getattr(prefs, f"shading_pie_{n}_color_type")
            shading.color_type = color_type
            if color_type == "SINGLE":
                shading.single_color = getattr(prefs, f"shading_pie_{n}_single_color")
        else:
            render_pass = getattr(prefs, f"shading_pie_{n}_render_pass")
            if (render_pass in _CRYPTO_PASSES
                    and not context.scene.render.engine.startswith("BLENDER_EEVEE")):
                render_pass = "COMBINED"
            try:
                shading.render_pass = render_pass
            except TypeError:
                # Pass not available for the current engine/shading combo
                self.report({"WARNING"}, f"Render pass '{render_pass}' not available")
            scene_world = getattr(prefs, f"shading_pie_{n}_scene_world")
            if s_type == "MATERIAL":
                shading.use_scene_world = scene_world
            else:
                shading.use_scene_world_render = scene_world

        return {"FINISHED"}


class IOPS_MT_Pie_Shading(Menu):
    bl_label = "IOPS Shading"

    def draw(self, context):
        prefs = get_shading_pie_prefs()
        layout = self.layout
        pie = layout.menu_pie()
        # Blender pie fill order: W, E, S, N, NW, NE, SW, SE
        for n in (4, 6, 2, 8, 7, 9, 1, 3):
            if getattr(prefs, f"shading_pie_{n}_enable"):
                op = pie.operator(
                    "iops.apply_shading_preset",
                    text=shading_slot_label(prefs, n),
                    icon=_TYPE_ICONS[getattr(prefs, f"shading_pie_{n}_type")],
                )
                op.slot = n
            else:
                pie.separator()


class IOPS_OT_Call_Pie_Shading(bpy.types.Operator):
    """IOPS Shading Pie"""

    bl_idname = "iops.call_pie_shading"
    is_bindable = True
    bl_label = "IOPS Pie Shading"

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Shading")
        return {"FINISHED"}
