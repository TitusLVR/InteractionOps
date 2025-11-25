import bpy
from mathutils import Vector


class IOPS_OT_ChangeScale(bpy.types.Operator):
    """Change object scale while maintaining dimensions"""
    
    bl_idname = "iops.object_change_scale"
    bl_label = "Change Scale"
    bl_description = "Set the object's scale to a new value while retaining its dimensions"
    bl_options = {"REGISTER", "UNDO"}
    
    scale: bpy.props.FloatVectorProperty(
        name="Scale",
        description="New scale values",
        default=(1.0, 1.0, 1.0),
        min=0.0001,
        soft_max=10.0,
        subtype='XYZ',
    )
    
    @classmethod
    def poll(cls, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "OBJECT"
            and len(context.view_layer.objects.selected) > 0
        )
    
    def invoke(self, context, event):
        # Initialize scale with the active object's current scale if available
        if context.active_object:
            self.scale = context.active_object.scale.copy()
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "scale")
    
    def _scale_data(self, obj, factor):
        """Scale object data to maintain visual dimensions"""
        if obj.type == 'MESH':
            if obj.data and hasattr(obj.data, 'vertices'):
                for vertex in obj.data.vertices:
                    vertex.co.x *= factor.x
                    vertex.co.y *= factor.y
                    vertex.co.z *= factor.z
                obj.data.update()
    
    def execute(self, context):
        selected_objects = context.view_layer.objects.selected
        
        # Store original mode states
        original_active = context.active_object
        objects_in_edit_mode = []
        
        # Check which objects are in edit mode and exit temporarily
        for obj in selected_objects:
            if obj.mode == 'EDIT':
                objects_in_edit_mode.append(obj)
                with context.temp_override(object=obj):
                    bpy.ops.object.mode_set(mode='OBJECT')
        
        try:
            for obj in selected_objects:
                if obj.type != 'MESH':
                    continue
                
                # Calculate scale factor to maintain dimensions
                # current_visual = obj.scale * data
                # target_visual = new_scale * new_data
                # We want current_visual == target_visual
                # obj.scale * data = new_scale * new_data
                # new_data = data * (obj.scale / new_scale)
                
                sx = self.scale.x if self.scale.x != 0 else 1.0
                sy = self.scale.y if self.scale.y != 0 else 1.0
                sz = self.scale.z if self.scale.z != 0 else 1.0
                
                scale_factor = Vector((
                    obj.scale.x / sx,
                    obj.scale.y / sy,
                    obj.scale.z / sz,
                ))
                
                # Scale data
                self._scale_data(obj, scale_factor)
                
                # Set new scale
                obj.scale = self.scale.copy()
        
        finally:
            # Restore edit mode for objects that were in edit mode
            for obj in objects_in_edit_mode:
                if obj and obj.name in context.scene.objects:
                    if obj in context.selected_objects:
                        with context.temp_override(object=obj):
                            bpy.ops.object.mode_set(mode='EDIT')
            
            # Restore original active object if it still exists
            if original_active and original_active.name in context.scene.objects:
                context.view_layer.objects.active = original_active
        
        scale_str = f"X: {self.scale.x:.3f}, Y: {self.scale.y:.3f}, Z: {self.scale.z:.3f}"
        self.report({"INFO"}, f"Scale changed to {scale_str} while maintaining dimensions")
        return {"FINISHED"}

