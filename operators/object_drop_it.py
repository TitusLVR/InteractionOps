import bpy
from mathutils import Vector, Matrix
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatVectorProperty,
    FloatProperty,
)
import math
from typing import Tuple, Optional, List, Dict, Any


class RaycastResult:
    """Data class for raycast results"""
    def __init__(self, success: bool, location: Vector = None, normal: Vector = None, 
                 distance: float = 0.0, error: str = ""):
        self.success = success
        self.location = location or Vector()
        self.normal = normal or Vector()
        self.distance = distance
        self.error = error


class GeometryAnalyzer:
    """Utility class for geometry analysis and validation"""
    
    @staticmethod
    def get_object_bounds(obj) -> Tuple[Vector, Vector]:
        """Get object bounding box in world space"""
        try:
            if obj.type != 'MESH' or not obj.data:
                return obj.matrix_world.translation, obj.matrix_world.translation
            
            bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            min_coord = Vector((min(c.x for c in bbox_corners),
                               min(c.y for c in bbox_corners),
                               min(c.z for c in bbox_corners)))
            max_coord = Vector((max(c.x for c in bbox_corners),
                               max(c.y for c in bbox_corners),
                               max(c.z for c in bbox_corners)))
            return min_coord, max_coord
        except:
            # Fallback to object location
            return obj.matrix_world.translation, obj.matrix_world.translation
    
    @staticmethod
    def get_lowest_face_info(obj) -> Tuple[Vector, Vector, float]:
        """Get lowest face center, normal, and Z coordinate"""
        try:
            if obj.type != 'MESH' or not obj.data or not obj.data.polygons:
                return obj.matrix_world.translation, Vector((0, 0, 1)), obj.matrix_world.translation.z
            
            mesh = obj.data
            min_z = float('inf')
            lowest_center = None
            lowest_normal = None
            
            # Simple approach without bmesh for better compatibility
            for poly in mesh.polygons:
                if len(poly.vertices) < 3:  # Skip degenerate faces
                    continue
                    
                center_local = poly.center
                center_world = obj.matrix_world @ center_local
                
                if center_world.z < min_z:
                    min_z = center_world.z
                    lowest_center = center_world
                    # Transform normal to world space
                    normal_world = obj.matrix_world.to_3x3() @ poly.normal
                    lowest_normal = normal_world.normalized()
            
            if lowest_center is None:
                return obj.matrix_world.translation, Vector((0, 0, 1)), obj.matrix_world.translation.z
            
            return lowest_center, lowest_normal, min_z
        except Exception as e:
            # Fallback to object location
            return obj.matrix_world.translation, Vector((0, 0, 1)), obj.matrix_world.translation.z


class SmartRaycaster:
    """Advanced raycast system with fallback strategies"""
    
    def __init__(self, context):
        self.context = context
        self.max_distance = 10000.0  # Much larger default distance
        self.fallback_attempts = 3
        self.offset_multiplier = 1.5
    
    def get_depsgraph(self):
        """Get depsgraph in version-agnostic way"""
        if hasattr(self.context, 'evaluated_depsgraph_get'):
            return self.context.evaluated_depsgraph_get()
        else:
            return self.context.view_layer.depsgraph
    
    def validate_direction(self, direction: Vector) -> bool:
        """Validate raycast direction vector"""
        try:
            if direction.length < 1e-6:
                return False
            return not any(math.isnan(x) or math.isinf(x) for x in direction)
        except:
            return False
    
    def calculate_smart_origin(self, obj, direction: Vector, margin_factor: float = 2.0) -> Vector:
        """Calculate optimal raycast origin with adaptive margin"""
        try:
            min_bound, max_bound = GeometryAnalyzer.get_object_bounds(obj)
            
            # Calculate margin based on object size
            size = max_bound - min_bound
            margin = max(size.length * 0.1, 1.0) * margin_factor
            
            # Start from object center, offset against direction
            direction_norm = direction.normalized()
            return obj.matrix_world.translation - (direction_norm * margin)
        except:
            # Fallback: simple offset from object location
            return obj.matrix_world.translation + Vector((0, 0, 10))
    
    def perform_raycast_with_fallback(self, origin: Vector, direction: Vector, 
                                    exclude_objects: List = None) -> RaycastResult:
        """Perform raycast with multiple fallback strategies"""
        if not self.validate_direction(direction):
            return RaycastResult(False, error="Invalid direction vector")
        
        direction_norm = direction.normalized()
        exclude_objects = exclude_objects or []
        
        # Hide excluded objects
        hidden_states = {}
        for obj in exclude_objects:
            hidden_states[obj] = obj.hide_get()
            obj.hide_set(True)
        
        try:
            # Primary raycast attempt
            result = self._single_raycast(origin, direction_norm)
            if result.success:
                return result
            
            # Fallback 1: Try from much higher position
            high_origin = Vector(origin)
            high_origin.z += 50.0
            result = self._single_raycast(high_origin, direction_norm)
            if result.success:
                return result
            
            # Fallback 2: Try pure downward direction
            if direction_norm != Vector((0, 0, -1)):
                down_direction = Vector((0, 0, -1))
                result = self._single_raycast(origin, down_direction)
                if result.success:
                    return result
                
                # Try downward from high position
                result = self._single_raycast(high_origin, down_direction)
                if result.success:
                    return result
            
            # Fallback 3: Try with origin variations
            for i in range(3):
                offset_distance = 2.0 * (i + 1)
                for offset_dir in [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((-1, 0, 0)), Vector((0, -1, 0))]:
                    offset_origin = origin + (offset_dir * offset_distance)
                    result = self._single_raycast(offset_origin, direction_norm)
                    if result.success:
                        return result
            
            return RaycastResult(False, error=f"No surface found. Origin: {origin}, Direction: {direction_norm}")
        
        finally:
            # Restore hidden states
            for obj, state in hidden_states.items():
                obj.hide_set(state)
    
    def _single_raycast(self, origin: Vector, direction: Vector) -> RaycastResult:
        """Perform single raycast attempt"""
        try:
            depsgraph = self.get_depsgraph()
            success, location, normal, *_ = bpy.context.scene.ray_cast(
                depsgraph, origin, direction, distance=self.max_distance
            )
            
            if success and location and normal:
                distance = (location - origin).length
                return RaycastResult(True, location, normal.normalized(), distance)
            else:
                return RaycastResult(False, error="No intersection found")
        
        except Exception as e:
            return RaycastResult(False, error=f"Raycast exception: {str(e)}")


class IOPS_OT_Drop_It(bpy.types.Operator):
    """Drop objects to surface"""
    
    bl_idname = "iops.object_drop_it"
    bl_label = "Drop It!"
    bl_options = {"REGISTER", "UNDO"}
    
    # Core properties
    drop_it_direction: FloatVectorProperty(
        name="Direction",
        description="Raycast direction (X, Y, Z)",
        default=(0.0, 0.0, -1.0),
        min=-1, max=1, size=3,
    )
    
    drop_it_offset: FloatVectorProperty(
        name="Offset",
        description="Position offset after drop (X, Y, Z)",
        default=(0.0, 0.0, 0.0),
        size=3,
    )
    
    # Advanced options
    use_local_z: BoolProperty(
        name="Use Local Z",
        description="Use object's local Z-axis as raycast direction",
        default=True
    )
    
    respect_lowest_face: BoolProperty(
        name="Respect Lowest Face",
        description="Position object so lowest face touches surface",
        default=False
    )
    
    max_raycast_distance: FloatProperty(
        name="Max Distance",
        description="Maximum raycast distance",
        default=10000.0,
        min=1.0, max=100000.0
    )
    
    # Alignment options
    drop_it_align_to_surf: BoolProperty(
        name="Align to Surface",
        description="Align object to surface normal",
        default=True
    )
    
    alignment_method: EnumProperty(
        name="Alignment Method",
        description="How to align object to surface",
        items=[
            ("TRACK_TO", "Track To", "Use track-to alignment"),
            ("PROJECT", "Project", "Project orientation onto surface"),
            ("NORMAL_ONLY", "Normal Only", "Align only to surface normal")
        ],
        default="NORMAL_ONLY"
    )
    
    track_axis: EnumProperty(
        name="Track Axis",
        items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", ""), 
               ("-X", "-X", ""), ("-Y", "-Y", ""), ("-Z", "-Z", "")],
        default="Z"
    )
    
    up_axis: EnumProperty(
        name="Up Axis",
        items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")],
        default="Y"
    )
    
    # Error handling
    continue_on_failure: BoolProperty(
        name="Continue on Failure",
        description="Continue processing other objects if one fails",
        default=True
    )
    
    detailed_reporting: BoolProperty(
        name="Detailed Reporting",
        description="Show detailed success/failure report",
        default=False
    )
    
    @classmethod
    def poll(cls, context):
        return context.area.type == "VIEW_3D"
    
    def execute(self, context):
        selected_objs = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({"ERROR"}, "No mesh objects selected")
            return {"CANCELLED"}
        
        raycaster = SmartRaycaster(context)
        raycaster.max_distance = self.max_raycast_distance
        
        results = {"success": [], "failed": []}
        
        for obj in selected_objs:
            try:
                result = self.process_object(obj, raycaster)
                if result["success"]:
                    results["success"].append(obj.name)
                    if self.detailed_reporting:
                        self.report({"INFO"}, f"SUCCESS: {obj.name}")
                else:
                    results["failed"].append({"name": obj.name, "error": result["error"]})
                    if self.detailed_reporting:
                        self.report({"ERROR"}, f"FAILED {obj.name}: {result['error']}")
                    if not self.continue_on_failure:
                        break
            except Exception as e:
                import traceback
                error_msg = f"Unexpected error: {str(e)}"
                if self.detailed_reporting:
                    error_msg += f"\nTraceback: {traceback.format_exc()}"
                results["failed"].append({"name": obj.name, "error": error_msg})
                if self.detailed_reporting:
                    self.report({"ERROR"}, f"EXCEPTION {obj.name}: {error_msg}")
                if not self.continue_on_failure:
                    break
        
        # Report results
        success_count = len(results["success"])
        failure_count = len(results["failed"])
        
        if failure_count == 0:
            self.report({"INFO"}, f"Drop It! SUCCESS: {success_count} objects dropped")
        elif success_count == 0:
            self.report({"ERROR"}, f"Drop It! FAILED: All {failure_count} objects failed")
            # Show first failure reason
            if results["failed"]:
                first_error = results["failed"][0]["error"]
                self.report({"ERROR"}, f"Primary error: {first_error}")
        else:
            self.report({"WARNING"}, f"Drop It! PARTIAL: {success_count} success, {failure_count} failed")
        
        return {"FINISHED"} if success_count > 0 else {"CANCELLED"}
    
    def process_object(self, obj, raycaster: SmartRaycaster) -> Dict[str, Any]:
        """Process a single object"""
        # Store original transform components
        original_matrix = obj.matrix_world.copy()
        original_location = obj.location.copy()
        original_rotation = obj.rotation_euler.copy()
        original_scale = obj.scale.copy()
        
        try:
            # Get raycast direction
            if self.use_local_z:
                local_z = Vector((0, 0, -1))
                direction = (obj.matrix_world.to_3x3() @ local_z).normalized()
            else:
                direction = Vector(tuple(self.drop_it_direction)).normalized()
            
            # Calculate raycast origin
            origin = raycaster.calculate_smart_origin(obj, direction)
            
            # Perform raycast
            raycast_result = raycaster.perform_raycast_with_fallback(
                origin, direction, exclude_objects=[obj]
            )
            
            if not raycast_result.success:
                return {"success": False, "error": raycast_result.error}
            
            # Calculate final position in world space
            hit_location = raycast_result.location
            
            if self.respect_lowest_face:
                lowest_center, lowest_normal, min_z = GeometryAnalyzer.get_lowest_face_info(obj)
                # Calculate offset from object origin to lowest face in world space
                origin_to_lowest_offset = lowest_center - obj.matrix_world.translation
                final_world_location = hit_location - origin_to_lowest_offset
            else:
                final_world_location = hit_location
            
            # Handle alignment
            if self.drop_it_align_to_surf:
                final_matrix = self.calculate_alignment_matrix(
                    final_world_location, raycast_result.normal, obj
                )
                obj.matrix_world = final_matrix
                
                # Preserve original scale after alignment
                obj.scale = original_scale
            else:
                # Keep original rotation, just change position
                # For objects with parents or constraints, we need to work in world space
                obj.matrix_world = self.create_transform_matrix(
                    final_world_location, 
                    original_matrix.to_3x3(),
                    original_scale
                )
            
            # Apply offset in world space
            offset_vec = Vector(tuple(self.drop_it_offset))
            if offset_vec.length > 0:
                offset_matrix = Matrix.Translation(offset_vec)
                obj.matrix_world @= offset_matrix
            
            return {"success": True, "error": ""}
        
        except Exception as e:
            # Restore original transform on error
            obj.matrix_world = original_matrix
            return {"success": False, "error": str(e)}
    
    def create_transform_matrix(self, location: Vector, rotation_3x3: Matrix, scale: Vector) -> Matrix:
        """Create a 4x4 transform matrix from components"""
        # Create scale matrix
        scale_matrix = Matrix.Diagonal((*scale, 1.0)).to_4x4()
        
        # Create rotation matrix
        rotation_matrix = rotation_3x3.to_4x4()
        
        # Create translation matrix
        translation_matrix = Matrix.Translation(location)
        
        # Combine: Translation * Rotation * Scale
        return translation_matrix @ rotation_matrix @ scale_matrix
    
    def calculate_alignment_matrix(self, position: Vector, normal: Vector, obj) -> Matrix:
        """Calculate object alignment matrix based on method"""
        normal = normal.normalized()
        
        if self.alignment_method == "NORMAL_ONLY":
            # Simple alignment to surface normal
            up = Vector((0, 0, 1))
            if abs(normal.dot(up)) > 0.9:  # Nearly parallel
                up = Vector((0, 1, 0))
            
            right = normal.cross(up).normalized()
            forward = right.cross(normal).normalized()
            
            rotation_matrix = Matrix((right, forward, normal)).transposed()
            return self.create_transform_matrix(position, rotation_matrix, obj.scale)
        
        elif self.alignment_method == "TRACK_TO":
            # Use track-to alignment
            if self.track_axis == self.up_axis:
                # Fallback to normal alignment
                return self.calculate_alignment_matrix(position, normal, obj)
            
            try:
                track_quat = normal.to_track_quat(self.track_axis, self.up_axis)
                rotation_matrix = track_quat.to_matrix()
                return self.create_transform_matrix(position, rotation_matrix, obj.scale)
            except:
                # Fallback to normal alignment if track-to fails
                return self.calculate_alignment_matrix(position, normal, obj)
        
        elif self.alignment_method == "PROJECT":
            # Project current orientation onto surface
            return self.calculate_projected_alignment(position, normal, obj)
        
        # Fallback: just translation
        return self.create_transform_matrix(position, Matrix.Identity(3), obj.scale)
    
    def calculate_projected_alignment(self, position: Vector, normal: Vector, obj) -> Matrix:
        """Calculate projected alignment (simplified version)"""
        try:
            # Get current forward direction from object's world matrix
            current_forward = obj.matrix_world.to_3x3() @ Vector((0, 1, 0))
            
            # Project forward vector onto surface plane
            projected_forward = current_forward - (current_forward.dot(normal) * normal)
            if projected_forward.length < 1e-6:
                projected_forward = Vector((1, 0, 0))
            projected_forward.normalize()
            
            # Calculate right vector
            right = normal.cross(projected_forward).normalized()
            
            # Build rotation matrix
            rotation_matrix = Matrix((right, projected_forward, normal)).transposed()
            return self.create_transform_matrix(position, rotation_matrix, obj.scale)
        
        except:
            # Fallback to normal alignment
            return self.calculate_alignment_matrix(position, normal, obj)
    
    def draw(self, context):
        layout = self.layout
        
        layout.prop(self, "use_local_z")
        if not self.use_local_z:
            layout.prop(self, "drop_it_direction")
        
        layout.prop(self, "respect_lowest_face")
        layout.prop(self, "drop_it_align_to_surf")
        layout.prop(self, "alignment_method")
        
        if self.alignment_method == "TRACK_TO":
            row = layout.row()
            row.prop(self, "track_axis")
            row.prop(self, "up_axis")
        
        layout.prop(self, "drop_it_offset")
        layout.prop(self, "detailed_reporting", text="Debug")