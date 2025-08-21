import bpy
import bmesh
from bpy.props import FloatProperty, BoolProperty

class IOPS_OT_VertexColorAssign(bpy.types.Operator):
    """Assign Vertex color in edit mode to selected vertices"""

    bl_idname = "iops.mesh_assign_vertex_color"
    bl_label = "Assign Vertex color in edit mode to selected vertices"
    bl_options = {"REGISTER", "UNDO"}

    use_active_color: BoolProperty(
        name="Use Active Color Attribute",
        default=True
    )

    col_attr_name: bpy.props.StringProperty(
        name="Color Attribute Name",
        default="Color"
    )
    fill_color_black: BoolProperty(
        name="Fill Black",
        default=False
    )
    fill_color_white: BoolProperty(
        name="Fill White",
        default=False
    )
    fill_color_grey: BoolProperty(
        name="Fill Grey",
        default=False
    )

    domain: bpy.props.EnumProperty(
        name="Domain",
        description="Domain of the color attribute",
        items=[("POINT", "Point", "Point"), ("CORNER", "Corner", "Corner")],
        default="POINT"
    )

    attr_type: bpy.props.EnumProperty(
        name="Attribute Type",
        description="Type of the color attribute",
        items=[("FLOAT_COLOR", "Float Color", "Float Color"), ("BYTE_COLOR", "Byte Color", "Byte Color")],
        default="FLOAT_COLOR"
    )

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == "MESH"

    def execute(self, context):
        color_black = (0.0, 0.0, 0.0, 1.0)
        color_white = (1.0, 1.0, 1.0, 1.0)
        color_grey = (0.5, 0.5, 0.5, 1.0)
        color_picker = context.scene.IOPS.iops_vertex_color

        # Determine color BEFORE processing objects
        color = color_picker
        if self.fill_color_black:
            color = color_black
        elif self.fill_color_grey:
            color = color_grey
        elif self.fill_color_white:
            color = color_white
        
        # Reset the fill flags after determining color
        self.fill_color_black = False
        self.fill_color_grey = False
        self.fill_color_white = False

        sel = [obj for obj in context.selected_objects if obj.type == 'MESH']
        
        # For edit mode, we need to determine the attribute name from active object
        if context.mode == "EDIT_MESH":
            attr_name = None
            if self.use_active_color:
                try:
                    attr_name = context.object.data.color_attributes.active_color.name
                except AttributeError:
                    # Create new color attribute if none exists
                    context.object.data.color_attributes.new(
                        self.col_attr_name, self.attr_type, self.domain
                    )
                    attr_name = self.col_attr_name
                    context.object.data.color_attributes.active_color = context.object.data.color_attributes[attr_name]
            else:
                attr_name = self.col_attr_name

            # Create color attribute if not exists for all selected objects
            for obj in sel:
                if attr_name not in obj.data.color_attributes:
                    obj.data.color_attributes.new(
                        attr_name, self.attr_type, self.domain
                    )
                # Set color attribute as active
                obj.data.color_attributes.active_color = obj.data.color_attributes[attr_name]

        if sel and context.mode == "EDIT_MESH":
            # EDIT MODE
            attr_domain = context.object.data.color_attributes.active_color.domain
            attr_type = context.object.data.color_attributes.active_color.data_type
            
            if attr_domain == "POINT":
                for obj in sel:
                    bm = bmesh.from_edit_mesh(obj.data)
                    if attr_type == "FLOAT_COLOR":
                        if attr_name in bm.verts.layers.float_color:
                            col_layer = bm.verts.layers.float_color[attr_name]
                        else:
                            continue
                    elif attr_type == "BYTE_COLOR":
                        if attr_name in bm.verts.layers.color:
                            col_layer = bm.verts.layers.color[attr_name]
                        else:
                            continue
                    
                    verts = [v for v in bm.verts if v.select]
                    for vert in verts:
                        vert[col_layer] = color
                    
                    bmesh.update_edit_mesh(obj.data)
                    
            elif attr_domain == "CORNER":
                for obj in sel:
                    bm = bmesh.from_edit_mesh(obj.data)
                    if attr_type == "FLOAT_COLOR":
                        if attr_name in bm.loops.layers.float_color:
                            col_layer = bm.loops.layers.float_color[attr_name]
                        else:
                            continue
                    elif attr_type == "BYTE_COLOR":
                        if attr_name in bm.loops.layers.color:
                            col_layer = bm.loops.layers.color[attr_name]
                        else:
                            continue
                    
                    for f in bm.faces:
                        if any(v.select for v in f.verts):
                            for loop in f.loops:
                                loop[col_layer] = color
                    
                    bmesh.update_edit_mesh(obj.data)

        elif context.mode == "OBJECT":
            # OBJECT MODE - Apply color to all vertices of each selected object
            for obj in sel:
                mesh = obj.data
                
                # Determine which attribute to use for this object
                current_attr_name = None
                create_new = False
                
                if self.use_active_color:
                    # Try to use active color attribute
                    if mesh.color_attributes.active_color:
                        current_attr_name = mesh.color_attributes.active_color.name
                    else:
                        # No active color attribute, create new one
                        current_attr_name = self.col_attr_name
                        create_new = True
                else:
                    # Use specified attribute name
                    current_attr_name = self.col_attr_name
                    if current_attr_name not in mesh.color_attributes:
                        create_new = True
                
                # Create attribute if needed
                if create_new:
                    attr = mesh.color_attributes.new(
                        current_attr_name, self.attr_type, self.domain
                    )
                    mesh.color_attributes.active_color = attr
                    print(f"Created new color attribute '{current_attr_name}' for object '{obj.name}'")
                
                # Get the color attribute
                color_attr = mesh.color_attributes.get(current_attr_name)
                if not color_attr:
                    print(f"Failed to get color attribute '{current_attr_name}' for object '{obj.name}'")
                    continue
                
                # Apply color based on domain
                if color_attr.domain == "POINT":
                    # Point domain - one color per vertex
                    for i in range(len(mesh.vertices)):
                        color_attr.data[i].color = color
                        
                elif color_attr.domain == "CORNER":
                    # Corner domain - one color per loop
                    for i in range(len(mesh.loops)):
                        color_attr.data[i].color = color
                
                # Force update
                mesh.update()
                obj.update_tag()
                print(f"Applied color to object: {obj.name}")
                
        else:
            self.report({"WARNING"}, context.object.name + " is not a MESH.")

        # Force viewport update
        if context.area:
            context.area.tag_redraw()
        
        # Report success
        if context.mode == "OBJECT" and sel:
            self.report({"INFO"}, f"Applied vertex color to {len(sel)} object(s)")

        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(
            context.scene.IOPS,
            "iops_vertex_color",
            text="",
        )
        col.prop(self, "use_active_color", text="Use Active Color")
        col.prop(self, "col_attr_name", text="Color Attribute Name")
        col.prop(self, "attr_type", text="Attribute Type")
        col.prop(self, "domain", text="Domain")
        col.prop(self, "fill_color_black", text="Fill Black")
        col.prop(self, "fill_color_grey", text="Fill Grey")
        col.prop(self, "fill_color_white", text="Fill White")


class IOPS_OT_VertexColorAlphaAssign(bpy.types.Operator):
    """Assign Vertex Color Alpha to selected vertices"""

    bl_idname = "iops.mesh_assign_vertex_color_alpha"
    bl_label = "Assign Vertex Color Alpha to selected vertices"
    bl_options = {"REGISTER", "UNDO"}

    vertex_color_alpha: FloatProperty(
        name="Alpha",
        description="Alpha channel value. 0 - Transparent, 1 - Solid",
        default=1.0,
        min=0.0,
        max=1.0,
    )

    @classmethod
    def poll(cls, context):
        return (
            context.object
            and context.object.type == "MESH"
            and context.object.mode == "EDIT"
        )

    def execute(self, context):
        # Get the object and validate it exists
        obj = context.object
        if not obj:
            self.report({"ERROR"}, "No active object")
            return {"CANCELLED"}
            
        if obj.type != "MESH":
            self.report({"ERROR"}, "Active object is not a mesh")
            return {"CANCELLED"}
            
        if obj.mode != "EDIT":
            self.report({"ERROR"}, "Object must be in Edit mode")
            return {"CANCELLED"}
        
        # Get mesh data before any operations
        mesh = obj.data
        if not mesh:
            self.report({"ERROR"}, "Object has no mesh data")
            return {"CANCELLED"}
        
        try:
            # Switch to object mode to access vertex selection
            bpy.ops.object.mode_set(mode='OBJECT')
            
            # Check if we have any color attributes
            if not mesh.color_attributes:
                # Create a new color attribute if none exists
                mesh.color_attributes.new("Color", "FLOAT_COLOR", "CORNER")
            
            # Get active color attribute
            color_attr = None
            if mesh.color_attributes.active_color:
                color_attr = mesh.color_attributes.active_color
            elif len(mesh.color_attributes) > 0:
                # Fallback to first available color attribute
                color_attr = mesh.color_attributes[0]
                mesh.color_attributes.active_color = color_attr
            
            if not color_attr:
                self.report({"ERROR"}, "No color attribute found")
                return {"CANCELLED"}
            
            vertices = mesh.vertices
            modified_count = 0
            
            # Handle different domains
            if color_attr.domain == "CORNER":
                # Corner domain - one color per loop
                for loop_index, loop in enumerate(mesh.loops):
                    # If vertex is selected
                    if loop.vertex_index < len(vertices) and vertices[loop.vertex_index].select:
                        current_color = list(color_attr.data[loop_index].color)
                        current_color[3] = self.vertex_color_alpha  # Set alpha
                        color_attr.data[loop_index].color = current_color
                        modified_count += 1
                        
            elif color_attr.domain == "POINT":
                # Point domain - one color per vertex
                for vert_index, vertex in enumerate(vertices):
                    if vertex.select:
                        if vert_index < len(color_attr.data):
                            current_color = list(color_attr.data[vert_index].color)
                            current_color[3] = self.vertex_color_alpha  # Set alpha
                            color_attr.data[vert_index].color = current_color
                            modified_count += 1
            
            # Update mesh
            mesh.update()
            
            # Return to edit mode
            bpy.ops.object.mode_set(mode='EDIT')
            
            if modified_count > 0:
                self.report({"INFO"}, f"Modified alpha for {modified_count} elements")
            else:
                self.report({"WARNING"}, "No selected vertices found")
                
        except Exception as e:
            self.report({"ERROR"}, f"Error processing vertex colors: {str(e)}")
            # Try to return to edit mode if we're not there
            try:
                if context.object and context.object.mode != "EDIT":
                    bpy.ops.object.mode_set(mode='EDIT')
            except:
                pass
            return {"CANCELLED"}
            
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.prop(self, "vertex_color_alpha", slider=True, text="Alpha value")