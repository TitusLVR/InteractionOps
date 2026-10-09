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
    """Raycast system with a couple of fallback strategies.

    Excluded objects are skipped by stepping past their hits instead of
    toggling their visibility: hide_set() dirties the depsgraph, which made
    every cast re-evaluate the scene (very slow on Adjust Last Operation)."""

    # Max excluded-object hits to step through before giving up on one cast
    MAX_SKIP_HITS = 64
    SKIP_EPSILON = 1e-4

    def __init__(self, context):
        self.context = context
        self.max_distance = 10000.0  # Much larger default distance
        # Evaluate once per operator run, not once per cast
        self.depsgraph = context.evaluated_depsgraph_get()
        self.exclude = set()

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
        self.exclude = {o.name for o in (exclude_objects or [])}

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
        down_direction = Vector((0, 0, -1))
        if (direction_norm - down_direction).length > 1e-6:
            result = self._single_raycast(origin, down_direction)
            if result.success:
                return result
            result = self._single_raycast(high_origin, down_direction)
            if result.success:
                return result

        return RaycastResult(False, error="No surface found")

    def _single_raycast(self, origin: Vector, direction: Vector) -> RaycastResult:
        """Cast once, stepping past hits on excluded objects"""
        scene = self.context.scene
        start = Vector(origin)
        remaining = self.max_distance
        try:
            for _ in range(self.MAX_SKIP_HITS):
                success, location, normal, _index, hit_obj, _matrix = scene.ray_cast(
                    self.depsgraph, start, direction, distance=remaining
                )
                if not success:
                    return RaycastResult(False, error="No intersection found")

                hit_name = getattr(getattr(hit_obj, "original", hit_obj), "name", None)
                if hit_name in self.exclude:
                    travelled = (location - start).length + self.SKIP_EPSILON
                    remaining -= travelled
                    if remaining <= 0.0:
                        return RaycastResult(False, error="No intersection found")
                    start = location + direction * self.SKIP_EPSILON
                    continue

                if normal.length < 1e-6:
                    # Degenerate face: fall back to facing against the cast
                    normal = -direction
                distance = (location - origin).length
                return RaycastResult(True, location, normal.normalized(), distance)

            return RaycastResult(False, error="No intersection found")

        except Exception as e:
            return RaycastResult(False, error=f"Raycast exception: {e}")


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
        return context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        # Adjust Last Operation re-runs execute on every tweak; a CANCELLED
        # there drops the redo panel, so stay FINISHED and let the user fix
        # the parameters (failed objects are left untouched anyway).
        is_repeat = self.options.is_repeat

        selected_objs = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({"WARNING"}, "Drop It!: no mesh objects selected")
            return {"FINISHED"} if is_repeat else {"CANCELLED"}

        if not self.use_local_z and Vector(self.drop_it_direction).length < 1e-6:
            self.report({"WARNING"}, "Drop It!: direction is zero")
            return {"FINISHED"} if is_repeat else {"CANCELLED"}

        raycaster = SmartRaycaster(context)
        raycaster.max_distance = self.max_raycast_distance

        dropped = 0
        failed = []

        for obj in selected_objs:
            try:
                result = self.process_object(obj, raycaster)
                error = None if result["success"] else result["error"]
            except Exception as e:
                error = f"Unexpected error: {e}"
                if self.detailed_reporting:
                    import traceback
                    traceback.print_exc()

            if error is None:
                dropped += 1
                continue

            failed.append(obj.name)
            if self.detailed_reporting:
                print(f"IOPS Drop It!: {obj.name}: {error}")
            if not self.continue_on_failure:
                break

        # One summary line per run: redo can fire execute many times a second
        if not failed:
            self.report({"INFO"}, f"Drop It!: {dropped} dropped")
        elif dropped == 0:
            names = ", ".join(failed[:3]) + ("…" if len(failed) > 3 else "")
            self.report({"WARNING"}, f"Drop It!: no surface found for {names}")
        else:
            self.report({"WARNING"}, f"Drop It!: {dropped} dropped, {len(failed)} found no surface")

        if dropped == 0 and not is_repeat:
            return {"CANCELLED"}
        return {"FINISHED"}
    
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
        layout.prop(self, "max_raycast_distance")
        layout.prop(self, "detailed_reporting", text="Debug (console)")