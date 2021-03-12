import bpy
# import bmesh

class IOPS_MouseoverFillSelect(bpy.types.Operator):
    """Fill select faces at mouseover"""
    bl_idname = "iops.mouseover_fill_select"
    bl_label = "IOPS Mouseover Fill Select"

    @classmethod
    def poll(cls, context):
        return (context.object is not None and
                context.object.type == 'MESH' and
                context.object.data.is_editmode)

    def invoke(self, context, event):
        # me = context.object.data
        # bm = bmesh.from_edit_mesh(me)
        # verts_sel = [v.select for v in bm.verts]
        # edges_sel = [e.select for e in bm.edges]
        # faces_sel = [f.select for f in bm.faces]

        loc = event.mouse_region_x, event.mouse_region_y

        bpy.ops.mesh.hide(unselected=False)
        ret = bpy.ops.view3d.select(extend=True, location=loc)
        if ret == {'PASS_THROUGH'}:
            self.report({'INFO'}, "No geometry under cursor!")
            return {'CANCELLED'}
        
        bpy.ops.mesh.select_linked(delimit={'NORMAL'})
        bpy.ops.mesh.reveal(select=True)

        # try:
        #     geom = bm.select_history[-1]
        # except IndexError:
        #     geom = None

        return {'FINISHED'}
