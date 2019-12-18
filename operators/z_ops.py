import math

import bmesh
import bpy
import mathutils as mu
from bpy.props import FloatProperty


def get_any(someset):
    for i in someset:
        return i


def mirror(bm):
    copy_lookup = {}
    orig_faces = bm.faces[:]
    for f in orig_faces:
        if f.select:
            bmcp = bmesh.ops.duplicate(bm, geom=orig_faces)
            for fcp in bmcp['geom']:
                if type(fcp) == bmesh.types.BMFace:
                    fcp.normal_flip()
            copy_lookup[f] = bmcp
    for f in copy_lookup:
        tm = mu.Matrix.Translation(f.calc_center_median())
        sm = mu.Matrix.Scale(-1.0, 4, f.normal)
        cp = copy_lookup[f]
        bmesh.ops.transform(bm,
                            matrix=tm @ sm @ tm.inverted(),
                            verts=[v for v in cp['geom'] if type(v) == bmesh.types.BMVert])
        weld_map = {}
        for v in f.verts:
            vc = cp['vert_map'][v]
            weld_map[vc] = v
        bm.faces.remove(cp['face_map'][f])
        bm.faces.remove(f)
        bmesh.ops.weld_verts(bm, targetmap=weld_map)


def put_on(to, at, bm, turn):
    to_xyz = to.calc_center_median_weighted()
    at_xyz = at.calc_center_median_weighted()
    turn_mtx = mu.Matrix.Rotation(math.radians(turn), 4, 'Z')
    src_mtx = at.normal.to_track_quat('Z', 'Y').to_matrix().to_4x4()
    trg_mtx = to.normal.to_track_quat('-Z', 'Y').to_matrix().to_4x4()
    mtx = mu.Matrix.Translation(to_xyz) @ \
        trg_mtx @ turn_mtx @ \
        src_mtx.inverted() @ \
        mu.Matrix.Translation(-at_xyz)
    piece = extend_region(at, bm)
    bmesh.ops.transform(bm, matrix=mtx, space=mu.Matrix.Identity(4), verts=piece)
    return bm


def extend_region(f, bm):
    inside = set()
    es = set(f.edges[:])
    while es:
        e = es.pop()
        inside.add(e)
        les = set(e.verts[0].link_edges[:] + e.verts[1].link_edges[:])
        les.difference_update(inside)
        es.update(les)
    vs = set()
    for e in inside:
        vs.update(set(e.verts[:]))
    return list(vs)


def connect(bm):
    sel = set([a for a in bm.edges if a.select])
    es = set()
    for e in sel:
        e.select = False
        fs = set()
        for lf in e.link_faces:
            if len(set(lf.edges[:]).intersection(sel)) > 1:
                fs.add(lf)
        if fs:
            es.add(e)
    r1 = bmesh.ops.bisect_edges(bm, edges=list(es), cuts=1)['geom_split']
    vs = [a for a in r1 if type(a) == bmesh.types.BMVert]
    r2 = bmesh.ops.connect_verts(bm, verts=vs, check_degenerate=True)['edges']
    for e in r2:
        e.select = True
    return bm


def loop_extension(edge, vert):
    candidates = vert.link_edges[:]
    if len(vert.link_loops) == 4 and vert.is_manifold:
        cruft = [edge]
        for l in edge.link_loops:
            cruft.extend([l.link_loop_next.edge, l.link_loop_prev.edge])
        return [e for e in candidates if e not in cruft][0]
    else:
        return


def loop_end(edge):
    v1, v2 = edge.verts[:]
    return not loop_extension(edge, v1) \
        or not loop_extension(edge, v2)


def ring_extension(edge, face):
    if len(face.verts) == 4:
        target_verts = [v for v in face.verts if v not in edge.verts]
        return [e for e in face.edges if target_verts[0] in e.verts and target_verts[1] in e.verts][0]
    else:
        return


def ring_end(edge):
    faces = edge.link_faces[:]
    border = len(faces) == 1
    non_manifold = len(faces) > 2
    dead_ends = map(lambda x: len(x.verts) != 4, faces)
    return border or non_manifold or any(dead_ends)


def unselected_loop_extensions(edge):
    v1, v2 = edge.verts
    ext1, ext2 = loop_extension(edge, v1), loop_extension(edge, v2)
    return [e for e in [ext1, ext2] if e and not e.select]


def unselected_ring_extensions(edge):
    return [e for e in [ring_extension(edge, f) for f in edge.link_faces] if e and not e.select]


def entire_loop(edge):
    e = edge
    v = edge.verts[0]
    loop = [edge]
    going_forward = True
    while True:
        ext = loop_extension(e, v)
        if ext:
            if going_forward:
                if ext == edge:
                    # infinite
                    return [edge] + loop + [edge]
                else:
                    # continue forward
                    loop.append(ext)
            else:
                # continue backward
                loop.insert(0, ext)
            v = ext.other_vert(v)
            e = ext
        else:
            # finite and we've reached an end
            if going_forward:
                # the first end
                going_forward = False
                e = edge
                v = edge.verts[1]
            else:
                # the other end
                return loop


def partial_ring(edge, face):
    part_ring = []
    e, f = edge, face
    while True:
        ext = ring_extension(e, f)
        if not ext:
            break
        part_ring.append(ext)
        if ext == edge:
            break
        if ring_end(ext):
            break
        else:
            f = [x for x in ext.link_faces if x != f][0]
            e = ext
    return part_ring


def entire_ring(edge):
    fs = edge.link_faces
    ring = [edge]
    if len(fs) and len(fs) < 3:
        dirs = [ne for ne in [partial_ring(edge, f) for f in fs] if ne]
        if dirs:
            if len(dirs) == 2 and set(dirs[0]) != set(dirs[1]):
                [ring.insert(0, e) for e in dirs[1]]
            ring.extend(dirs[0])
    return ring


def complete_associated_loops(edges):
    loops = []
    for e in edges:
        if not any([e in l for l in loops]):
            loops.append(entire_loop(e))
    return loops


def complete_associated_rings(edges):
    rings = []
    for e in edges:
        if not any([e in r for r in rings]):
            rings.append(entire_ring(e))
    return rings


def grow_loop(context):
    mesh = context.active_object.data
    bm = bmesh.from_edit_mesh(mesh)
    selected_edges = [e for e in bm.edges if e.select]
    loop_exts = []
    for se in selected_edges:
        loop_exts.extend(unselected_loop_extensions(se))
    for le in loop_exts:
        le.select = True
    mesh.update()
    return {'FINISHED'}


def grow_ring(context):
    mesh = context.active_object.data
    bm = bmesh.from_edit_mesh(mesh)
    selected_edges = [e for e in bm.edges if e.select]
    ring_exts = []
    for se in selected_edges:
        ring_exts.extend(unselected_ring_extensions(se))
    for re in ring_exts:
        re.select = True
    mesh.update()
    return {'FINISHED'}


def group_selected(edges):
    chains = [[]]
    for e in edges:
        if e.select:
            chains[-1].extend([e])
        else:
            chains.append([])
    return [c for c in chains if c]


def group_unselected(edges):
    gaps = [[]]
    for e in edges:
        if not e.select:
            gaps[-1].extend([e])
        else:
            gaps.append([])
    return [g for g in gaps if g != []]


def shrink_loop(context):
    mesh = context.active_object.data
    bm = bmesh.from_edit_mesh(mesh)
    selected_edges = [e for e in bm.edges if e.select]
    loop_ends = []
    for se in selected_edges:
        for v in [se.verts[0], se.verts[1]]:
            le = loop_extension(se, v)
            if not le or not le.select:
                loop_ends.append(se)
    loop_ends_unique = list(set(loop_ends))
    if len(loop_ends_unique):
        for e in loop_ends_unique:
            e.select = False
    mesh.update()
    return {'FINISHED'}


def shrink_ring(context):
    mesh = context.active_object.data
    bm = bmesh.from_edit_mesh(mesh)
    selected_edges = [e for e in bm.edges if e.select]
    ring_ends = []
    for r in complete_associated_rings(selected_edges):
        chains = group_selected(r)
        for c in chains:
            ring_ends.append(c[0])
            ring_ends.append(c[-1])
    for e in list((set(ring_ends))):
        e.select = False
    mesh.update()
    return {'FINISHED'}


def select_bounded_loop(context):
    mesh = context.active_object.data
    bm = bmesh.from_edit_mesh(mesh)
    selected_edges = [e for e in bm.edges if e.select]
    for l in complete_associated_loops(selected_edges):
        gaps = group_unselected(l)
        new_sel = []
        if l[0] == l[-1]:
            # loop is infinite
            sg = sorted(gaps, key=lambda x: len(x), reverse=True)
            if len(sg) > 1 and len(sg[0]) > len(sg[1]):
                # single longest gap
                final_gaps = sg[1:]
            else:
                final_gaps = sg
        else:
            # loop is finite
            tails = [g for g in gaps if any(map(lambda x: loop_end(x), g))]
            nontails = [g for g in gaps if g not in tails]
            if nontails:
                final_gaps = nontails
            else:
                final_gaps = gaps
        for g in final_gaps:
            new_sel.extend(g)
        for e in new_sel:
            e.select = True
    mesh.update()
    return {'FINISHED'}


def select_bounded_ring(context):
    mesh = context.active_object.data
    bm = bmesh.from_edit_mesh(mesh)
    selected_edges = [e for e in bm.edges if e.select]
    for r in complete_associated_rings(selected_edges):
        gaps = group_unselected(r)
        new_sel = []
        if r[0] == r[-1]:
            # ring is infinite
            sg = sorted(gaps, key=lambda x: len(x), reverse=True)
            if len(sg) > 1 and len(sg[0]) > len(sg[1]):
                # single longest gap
                final_gaps = sg[1:]
            else:
                final_gaps = sg
        else:
            # ring is finite
            tails = [g for g in gaps if any(map(lambda x: ring_end(x), g))]
            nontails = [g for g in gaps if g not in tails]
            if nontails:
                final_gaps = nontails
            else:
                final_gaps = gaps
        for g in final_gaps:
            new_sel.extend(g)
        for e in new_sel:
            e.select = True
    mesh.update()
    return {'FINISHED'}


def extract_mesh_frag(es):
    frag = set()
    todo = set()
    todo.add(es.pop())
    while todo:
        e = todo.pop()
        frag.add(e)
        v1, v2 = e.verts
        more = [a for a in v1.link_edges[:] + v2.link_edges[:] if a.select]
        todo |= (set(more) - frag)
    return frag


def mesh_frags(bm):
    todo = set([e for e in bm.edges if e.select])
    frags = []
    while todo:
        frag = extract_mesh_frag(todo)
        frags.append(frag)
        todo -= frag
    return frags


def vert_chain(frag):
    fst = get_any(frag)
    e_chain = [fst]
    v_chain = fst.verts[:]
    fwd = True
    while True:
        end_e = e_chain[-1]
        end_v = v_chain[-1]
        ways = [a for a in end_v.link_edges if a in frag]
        if len(ways) > 2:
            return None, None
        elif len(ways) == 1:
            if fwd:
                e_chain.reverse()
                v_chain.reverse()
                fwd = False
            else:
                return False, v_chain
        else:
            if end_v == v_chain[0]:
                return True, v_chain
            e1, e2 = ways
            if e1 == end_e:
                nxt_e = e2
            else:
                nxt_e = e1
            e_chain.append(nxt_e)
            v_chain.append(nxt_e.other_vert(end_v))


def vert_chains(frags):
    chains = []
    for frag in frags:
        is_closed, chain = vert_chain(frag)
        if chain:
            chains.append((is_closed, chain))
    return chains


def arrange_edges(context, equalize):
    mesh = context.active_object.data
    bm = bmesh.from_edit_mesh(mesh)
    frags = mesh_frags(bm)
    for is_closed, chain in vert_chains(frags):
        if is_closed:
            circularize(chain, equalize)
        else:
            string_along(chain, equalize)
    context.active_object.data.update()
    return {'FINISHED'}


def circularize(ovs, equalize):
    n = len(ovs)
    center = mu.Vector((
        sum([v.co[0] for v in ovs]) / n,
        sum([v.co[1] for v in ovs]) / n,
        sum([v.co[2] for v in ovs]) / n))
    dists = [(v.co - center).magnitude for v in ovs]
    avg_d = (max(dists) + min(dists)) * 0.5
    crosses = []
    for v in ovs:
        pv = ovs[ovs.index(v) - 1]
        crosses.append((pv.co - center).cross(v.co - center))
    nrm = mu.Vector((
        sum([a[0] for a in crosses]) / n,
        sum([a[1] for a in crosses]) / n,
        sum([a[2] for a in crosses]) / n)).normalized()
    nrm2 = nrm.cross(ovs[0].co - center)
    offset = -nrm.cross(nrm2)
    offset.magnitude = avg_d
    doublepi = 6.283185307179586
    if equalize:
        quats = [mu.Quaternion(nrm, doublepi / (n - 1))] * n
    else:
        if not avg_d:
            quats = [mu.Quaternion((1.0, 0.0, 0.0, 0.0))] * n
        else:
            vecs = [ovs[i + 1].co - ovs[i].co for i in range(n - 1)]
            total = sum([vec.magnitude for vec in vecs])
            quats = []
            for vec in vecs:
                a = doublepi * (vec.magnitude / total)
                quats.append(mu.Quaternion(nrm, a))
    for v, quat in zip(ovs, quats):
        v.co = center + offset
        offset.rotate(quat)


def string_along(ovs, equalize):
    n = len(ovs)
    s = ovs[0].co.copy()
    d = ovs[-1].co - s
    avg = d / (n - 1)
    if equalize:
        vecs = [avg] * n
    else:
        dist = d.magnitude
        if not dist:
            vecs = [mu.Vector((0.0, 0.0, 0.0))] * (n - 1)
        else:
            vecs = []
            for i in range(n - 1):
                vecs.append(ovs[i + 1].co - ovs[i].co)
            total = sum([a.magnitude for a in vecs])
            for i in range(len(vecs)):
                vecs[i] = d * (vecs[i].magnitude / total)
    for v, vec in zip(ovs, vecs):
        v.co = s
        s += vec


class Z_OT_GrowLoop(bpy.types.Operator):
    bl_idname = "iops.z_grow_loop"
    bl_label = "Grow Loop"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH')

    def execute(self, context):
        return grow_loop(context)


class Z_OT_ShrinkLoop(bpy.types.Operator):
    bl_idname = "iops.z_shrink_loop"
    bl_label = "Shrink Loop"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH')

    def execute(self, context):
        return shrink_loop(context)


class Z_OT_GrowRing(bpy.types.Operator):
    bl_idname = "iops.z_grow_ring"
    bl_label = "Grow Ring"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH')

    def execute(self, context):
        return grow_ring(context)


class Z_OT_ShrinkRing(bpy.types.Operator):
    bl_idname = "iops.z_shrink_ring"
    bl_label = "Shrink Ring"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH')

    def execute(self, context):
        return shrink_ring(context)


class Z_OT_SelectBoundedLoop(bpy.types.Operator):
    bl_idname = "iops.z_select_bounded_loop"
    bl_label = "Select Bounded Loop"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH')

    def execute(self, context):
        return select_bounded_loop(context)


class Z_OT_SelectBoundedRing(bpy.types.Operator):
    bl_idname = "iops.z_select_bounded_ring"
    bl_label = "Select Bounded Ring"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH')

    def execute(self, context):
        return select_bounded_ring(context)


class Z_OT_ContextDelete(bpy.types.Operator):
    bl_idname = "iops.z_delete_mode"
    bl_label = "Delete Selection"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        modes = []
        for a, b in zip(['VERT', 'EDGE', 'FACE'], context.tool_settings.mesh_select_mode[:]):
            if b:
                modes.append(a)
        for m in reversed(modes):
            bpy.ops.mesh.delete(type=m)
        return {'FINISHED'}


class Z_OT_EdgeEq(bpy.types.Operator):
    '''Equalize the selected contiguous edges.'''
    bl_idname = "iops.eq_edges"
    bl_label = 'Equalize'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        sm = context.tool_settings.mesh_select_mode[:]
        return (context.mode == 'EDIT_MESH'
            and (sm == (False, True, False)))

    def execute(self, context):
        return arrange_edges(context, equalize=True)


class Z_OT_EdgeLineUp(bpy.types.Operator):
    '''Line up the selected contiguous edges.'''
    bl_idname = "iops.line_up_edges"
    bl_label = 'Line Up'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        sm = context.tool_settings.mesh_select_mode[:]
        return (context.mode == 'EDIT_MESH'
            and (sm == (False, True, False)))

    def execute(self, context):
        return arrange_edges(context, equalize=False)


class Z_OT_EdgeConnect(bpy.types.Operator):
    '''Connect the selected edges.'''
    bl_idname = "iops.z_connect"
    bl_label = 'Connect'
    bl_options = {'PRESET'}

    @classmethod
    def poll(cls, context):
        sm = context.tool_settings.mesh_select_mode[:]
        return (context.mode == 'EDIT_MESH' and (sm == (False, True, False)))

    def execute(self, context):
        mesh = context.active_object.data
        bm = bmesh.from_edit_mesh(mesh)
        connect(bm)
        bmesh.update_edit_mesh(mesh)
        return {'FINISHED'}


class Z_OT_PutOn(bpy.types.Operator):
    bl_idname = "iops.z_put_on"
    bl_label = "Put On"
    bl_options = {'REGISTER', 'UNDO'}
    turn : FloatProperty(name="Turn angle",
                         description="Turn by this angle after placing",
                         min=-180.0, max=180.0,
                         default=0.0)

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH')

    def execute(self, context):
        mesh = context.active_object.data
        bm = bmesh.from_edit_mesh(mesh)
        sel_fs = [f for f in bm.faces if f.select]
        where_to = bm.faces.active
        result = {'CANCELLED'}
        if len(sel_fs) == 2 and where_to in sel_fs:
            f1, f2 = sel_fs
            where_at = f1 if f2 == where_to else f2
            bm = put_on(where_to, where_at, bm, self.turn)
            bmesh.update_edit_mesh(mesh)
            result = {'FINISHED'}
        return result


class Z_OT_Mirror(bpy.types.Operator):
    bl_idname = "iops.z_mirror"
    bl_label = "Mirror"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH')

    def execute(self, context):
        mesh = context.active_object.data
        bm = bmesh.from_edit_mesh(mesh)
        mirror(bm)
        bmesh.update_edit_mesh(mesh)
        return {'FINISHED'}
