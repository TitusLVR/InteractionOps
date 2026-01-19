import bpy
import os


class IOPS_OT_Scan_Source_Collections(bpy.types.Operator):
    """Scan selected linked instance for available collections in source file"""
    
    bl_idname = "iops.scan_source_collections"
    bl_label = "Scan Source Collections"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return (
            context.selected_objects and 
            context.mode == 'OBJECT' and
            context.active_object and
            context.active_object.instance_collection
        )
    
    def execute(self, context):
        wm = context.window_manager
        props = wm.IOPS_AddonProperties
        obj = context.active_object
        
        # Clear existing collection list
        props.iops_source_collections.clear()
        
        # Check if object is a linked asset by instance_collection
        if not obj.instance_collection:
            self.report({'WARNING'}, "Active object is not a collection instance")
            return {'CANCELLED'}
        
        instance_coll = obj.instance_collection
        
        # Check if it's linked
        if not instance_coll.library:
            self.report({'WARNING'}, "Active object's collection is not linked")
            return {'CANCELLED'}
        
        source_library = instance_coll.library
        source_filepath = bpy.path.abspath(source_library.filepath)
        
        if not os.path.exists(source_filepath):
            self.report({'ERROR'}, f"Source file not found: {source_filepath}")
            return {'CANCELLED'}
        
        # Scan collections from the source file
        try:
            with bpy.data.libraries.load(source_filepath) as (data_from, data_to):
                collection_names = data_from.collections
                
                if not collection_names:
                    self.report({'INFO'}, "No collections found in source file")
                    return {'CANCELLED'}
                
                # Add collections to the list
                for coll_name in collection_names:
                    item = props.iops_source_collections.add()
                    item.name = coll_name
                    item.is_selected = False
                
                self.report({'INFO'}, f"Found {len(collection_names)} collection(s) in source file")
                
        except Exception as e:
            self.report({'ERROR'}, f"Failed to scan source file: {str(e)}")
            return {'CANCELLED'}
        
        return {'FINISHED'}


class IOPS_OT_Instance_Collection_Append(bpy.types.Operator):
    """Append a collection from a linked asset's source library"""
    
    bl_idname = "iops.instance_collection_append"
    bl_label = "Append Collection from Linked Asset"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return (
            context.selected_objects and 
            context.mode == 'OBJECT'
        )
    
    def execute(self, context):
        wm = context.window_manager
        props = wm.IOPS_AddonProperties
        
        # Get selected collections from the list
        selected_collections = [item.name for item in props.iops_source_collections if item.is_selected]
        
        if not selected_collections:
            self.report({'WARNING'}, "Please select at least one collection from the list")
            return {'CANCELLED'}
        
        appended_count = 0
        skipped_count = 0
        error_count = 0
        
        for obj in context.selected_objects:
            # Step 1: Check if object is a linked asset by instance_collection
            if not obj.instance_collection:
                skipped_count += 1
                continue
            
            instance_coll = obj.instance_collection
            
            # Step 2: Try to get the source library and filepath
            if not instance_coll.library:
                self.report({'WARNING'}, f"Object '{obj.name}' has instance collection but it's not linked")
                skipped_count += 1
                continue
            
            source_library = instance_coll.library
            source_filepath = bpy.path.abspath(source_library.filepath)
            
            if not os.path.exists(source_filepath):
                self.report({'ERROR'}, f"Source file not found: {source_filepath}")
                error_count += 1
                continue
            
            # Step 3: Append each selected collection
            for target_collection_name in selected_collections:
                try:
                    # Load collections from the source file
                    with bpy.data.libraries.load(source_filepath, link=False) as (data_from, data_to):
                        if target_collection_name in data_from.collections:
                            data_to.collections = [target_collection_name]
                        else:
                            self.report({'WARNING'}, 
                                f"Collection '{target_collection_name}' not found in {os.path.basename(source_filepath)}")
                            error_count += 1
                            continue
                    
                    # Step 4: Append the collection and preserve location/rotation
                    if data_to.collections:
                        appended_coll = data_to.collections[0]
                        
                        # Link the collection to the current scene
                        if appended_coll.name not in context.scene.collection.children:
                            context.scene.collection.children.link(appended_coll)
                        
                        # Get the instance object's world matrix
                        instance_matrix = obj.matrix_world.copy()
                        
                        # Apply the transform to all objects in the appended collection
                        for coll_obj in appended_coll.objects:
                            # Store the object's original matrix basis (local transform)
                            original_matrix = coll_obj.matrix_basis.copy()
                            
                            # Apply the instance transform to the object
                            # This transforms the object as if it was instanced at the original location
                            coll_obj.matrix_world = instance_matrix @ original_matrix
                        
                        appended_count += 1
                        self.report({'INFO'}, 
                            f"Appended collection '{target_collection_name}' from '{obj.name}' at its location")
                    
                except Exception as e:
                    self.report({'ERROR'}, f"Failed to append collection '{target_collection_name}' for '{obj.name}': {str(e)}")
                    error_count += 1
                    continue
        
        # Final report
        if appended_count > 0:
            self.report({'INFO'}, 
                f"Successfully appended {appended_count} collection(s). Skipped: {skipped_count}, Errors: {error_count}")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, 
                f"No collections were appended. Skipped: {skipped_count}, Errors: {error_count}")
            return {'CANCELLED'}


class IOPS_UL_SourceCollectionsList(bpy.types.UIList):
    """UIList for displaying source collections"""
    
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "is_selected", text="")
            row.label(text=item.name, icon='OUTLINER_COLLECTION')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.prop(item, "is_selected", text="")
            layout.label(text=item.name)


class IOPS_OT_Select_All_Collections(bpy.types.Operator):
    """Select or deselect all collections"""
    
    bl_idname = "iops.select_all_collections"
    bl_label = "Select All Collections"
    
    action: bpy.props.EnumProperty(
        items=[
            ('SELECT', "Select", "Select all collections"),
            ('DESELECT', "Deselect", "Deselect all collections"),
            ('TOGGLE', "Toggle", "Toggle selection"),
        ],
        default='TOGGLE'
    )
    
    def execute(self, context):
        wm = context.window_manager
        props = wm.IOPS_AddonProperties
        
        if self.action == 'SELECT':
            for item in props.iops_source_collections:
                item.is_selected = True
        elif self.action == 'DESELECT':
            for item in props.iops_source_collections:
                item.is_selected = False
        elif self.action == 'TOGGLE':
            # Check if any are selected
            any_selected = any(item.is_selected for item in props.iops_source_collections)
            # If any are selected, deselect all; otherwise select all
            for item in props.iops_source_collections:
                item.is_selected = not any_selected
        
        return {'FINISHED'}
