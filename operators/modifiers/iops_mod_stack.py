import bpy

from . import iops_mod_registry, iops_mod_presets as presets

# Params-expansion state for the panel's stack list. Modifiers don't
# support IDProperties, so it lives here — session-only, everything
# collapsed by default (and again after a restart).
expanded_params = set()  # {(object session_uid, modifier name)}


def params_key(obj, md):
    return (obj.session_uid, md.name)


def copy_modifier_params(md, dst_md):
    """Copy md's writable settings onto dst_md (enums first — some enum
    setters unit-convert siblings)."""
    skip = {"name", "type"} | presets._TYPE_SKIP_PROPS.get(md.type, set())
    props = [p for p in md.bl_rna.properties
             if not p.is_readonly and p.identifier not in skip]
    for want_enum in (True, False):
        for p in props:
            if (p.type == "ENUM") is not want_enum:
                continue
            try:
                setattr(dst_md, p.identifier, getattr(md, p.identifier))
            except (AttributeError, TypeError):
                pass
    if md.type == "NODES":
        src = getattr(getattr(md, "properties", None), "inputs", None)
        dst = getattr(getattr(dst_md, "properties", None), "inputs", None)
        if src is not None and dst is not None:
            for key in src.keys():
                s = getattr(src, key, None)
                d = getattr(dst, key, None)
                if (s is not None and d is not None
                        and hasattr(s, "value") and hasattr(d, "value")):
                    try:
                        d.value = s.value
                    except (AttributeError, TypeError):
                        pass


def copy_modifier_to(md, index, obj):
    """Recreate md on obj at the same stack position with the same
    settings. Returns False if obj can't take this modifier type."""
    try:
        new_md = obj.modifiers.new(md.name, md.type)
    except TypeError:
        return False
    if new_md is None:
        return False
    copy_modifier_params(md, new_md)
    obj.modifiers.move(len(obj.modifiers) - 1,
                       min(index, len(obj.modifiers) - 1))
    return True


def sync_modifier_to(md, obj):
    """Copy md's settings into obj's matching modifier in place: same
    type + same name first, else the first modifier of the same type.
    Stack position is untouched. Returns False if nothing matches."""
    target = None
    for o_md in obj.modifiers:
        if o_md.type != md.type:
            continue
        if o_md.name == md.name:
            target = o_md
            break
        if target is None:
            target = o_md
    if target is None:
        return False
    copy_modifier_params(md, target)
    return True


class IOPS_OT_ModStackAction(bpy.types.Operator):
    """Row action in the active object's modifier stack list"""

    bl_idname = "iops.mod_stack_action"
    bl_label = "Modifier Stack Action"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(options={"SKIP_SAVE"})
    alt: bpy.props.BoolProperty(options={"SKIP_SAVE"})
    action: bpy.props.EnumProperty(
        items=[
            ("MOVE_UP", "Move Up", "Move modifier up. Alt: to top"),
            ("MOVE_DOWN", "Move Down",
             "Move modifier down. Alt: to bottom"),
            ("APPLY", "Apply",
             "Apply this modifier. Alt: apply the stack through this "
             "modifier on the whole selection, in stack order"),
            ("TOGGLE_VIS", "Toggle Visibility",
             "Toggle viewport visibility. Alt: toggle render "
             "visibility"),
            ("COPY_TO_SELECTED", "Copy To Selected",
             "Copy this modifier to the selected objects, keeping its "
             "stack position and settings. Alt: copy settings into a "
             "matching existing modifier instead"),
            ("REMOVE", "Remove", "Remove this modifier"),
            ("SAVE_PRESET", "Save As Default Preset",
             "Use this modifier's settings when adding this type "
             "from the grid"),
            ("TOGGLE_PARAMS", "Show Parameters",
             "Show/hide this modifier's parameters in the list"),
        ],
        options={"SKIP_SAVE"},
    )

    _DESCRIPTIONS = {
        "MOVE_UP": "Move the modifier up\nAlt: move to the top",
        "MOVE_DOWN": "Move the modifier down\nAlt: move to the bottom",
        "APPLY": ("Apply the modifier\n"
                  "Alt: apply the stack up to here (inclusive) on the "
                  "whole selection, in stack order"),
        "TOGGLE_VIS": ("Toggle viewport visibility\n"
                       "Alt: toggle render visibility\n"
                       "Red: viewport and render visibility differ"),
        "COPY_TO_SELECTED": ("Copy the modifier to the selected "
                             "objects, keeping its stack position and "
                             "settings\n"
                             "Alt: copy the settings into a matching "
                             "existing modifier (same name, else same "
                             "type) instead of adding a new one"),
        "REMOVE": "Remove the modifier",
        "SAVE_PRESET": ("Save these settings as the default preset "
                        "used when adding this type from the grid"),
        "TOGGLE_PARAMS": "Show/hide the modifier's parameters",
    }

    @classmethod
    def poll(cls, context):
        return (context.active_object
                and context.active_object.modifiers)

    @classmethod
    def description(cls, context, properties):
        obj = context.active_object
        md = (obj.modifiers[properties.index]
              if obj and 0 <= properties.index < len(obj.modifiers)
              else None)
        text = cls._DESCRIPTIONS.get(properties.action, "")
        return f"{md.name}\n{text}" if md else text

    def invoke(self, context, event):
        self.alt = event.alt
        return self.execute(context)

    def execute(self, context):
        obj = context.active_object
        if self.index < 0 or self.index >= len(obj.modifiers):
            self.report({"WARNING"}, "Modifier index out of range")
            return {"CANCELLED"}
        md = obj.modifiers[self.index]
        if self.action == "APPLY" and context.mode != "OBJECT":
            self.report({"ERROR"},
                        "Modifiers cannot be applied in edit mode")
            return {"CANCELLED"}

        if self.action == "MOVE_UP":
            obj.modifiers.move(self.index,
                               0 if self.alt else max(0, self.index - 1))
        elif self.action == "MOVE_DOWN":
            last = len(obj.modifiers) - 1
            obj.modifiers.move(self.index,
                               last if self.alt else min(last,
                                                         self.index + 1))
        elif self.action == "TOGGLE_VIS":
            if self.alt:
                md.show_render = not md.show_render
            else:
                md.show_viewport = not md.show_viewport
        elif self.action == "COPY_TO_SELECTED":
            copied = 0
            skipped = 0
            for o in context.selected_objects:
                if o is obj:
                    continue
                if self.alt:
                    ok = sync_modifier_to(md, o)
                else:
                    ok = copy_modifier_to(md, self.index, o)
                if ok:
                    copied += 1
                else:
                    skipped += 1
            if self.alt:
                msg = f"Updated {md.name} on {copied} object(s)"
                if skipped:
                    msg += f", {skipped} skipped (no matching modifier)"
            else:
                msg = f"Copied {md.name} to {copied} object(s)"
                if skipped:
                    msg += f", {skipped} skipped (incompatible type)"
            self.report({"INFO"} if copied else {"WARNING"}, msg)
        elif self.action == "APPLY" and not self.alt:
            name = md.name
            try:
                with context.temp_override(object=obj, active_object=obj,
                                           selected_editable_objects=[obj]):
                    bpy.ops.object.modifier_apply(modifier=name)
                self.report({"INFO"}, f"Applied {name}")
            except RuntimeError as e:
                self.report({"WARNING"}, f"Apply failed: {e}")
                return {"CANCELLED"}
        elif self.action == "APPLY":  # Alt: apply up to here
            target = (md.type, md.name)
            applied = 0
            failed = 0
            skipped = {}
            for o in context.selected_objects:
                count, reason, fail_count = iops_mod_registry.smart_apply_object(
                    context, o, up_to=target)
                applied += count
                failed += fail_count
                if reason:
                    skipped[reason] = skipped.get(reason, 0) + 1
            msg = f"Applied {applied} modifier(s) up to {md.name}"
            if failed:
                msg += f", {failed} failed (see console)"
            for reason, n in skipped.items():
                msg += f", {n} object(s) skipped ({reason})"
            self.report({"INFO"}, msg)
        elif self.action == "REMOVE":
            obj.modifiers.remove(md)
        elif self.action == "TOGGLE_PARAMS":
            key = params_key(obj, md)
            if key in expanded_params:
                expanded_params.discard(key)
            else:
                expanded_params.add(key)
        elif self.action == "SAVE_PRESET":
            if presets.save_default(md):
                self.report({"INFO"},
                            f"{md.type}: saved as default preset for the grid")
            else:
                self.report({"WARNING"}, "Could not write preset file")
        return {"FINISHED"}
