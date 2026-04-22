use pyo3::prelude::*;
use std::collections::{BinaryHeap, HashSet};
use std::cmp::Ordering;

/// Fixed-point priority queue entry (we invert for min-heap via BinaryHeap which is max-heap).
#[derive(Copy, Clone, Debug)]
struct HeapEntry {
    f: f64,
    g: f64,
    vi: u32,
}
impl PartialEq for HeapEntry {
    fn eq(&self, other: &Self) -> bool { self.f == other.f }
}
impl Eq for HeapEntry {}
impl Ord for HeapEntry {
    fn cmp(&self, other: &Self) -> Ordering {
        // Min-heap via reversed comparison on f, NaN treated as greater
        other.f.partial_cmp(&self.f).unwrap_or(Ordering::Equal)
    }
}
impl PartialOrd for HeapEntry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> { Some(self.cmp(other)) }
}

#[pyclass]
pub struct Graph {
    nv: usize,
    ne: usize,
    // CSR adjacency
    starts: Vec<u32>,          // len nv+1
    adj_other: Vec<u32>,       // len 2E
    adj_edge: Vec<u32>,        // len 2E
    adj_dir: Vec<[f64; 3]>,    // len 2E, zero vector => degenerate (skip flow)
    adj_dir_valid: Vec<bool>,  // len 2E
    // Per-edge
    edge_len: Vec<f64>,        // len E
    has_angle: Vec<bool>,      // len E
    angle_bias: Vec<f64>,      // len E
    edge_barrier: Vec<bool>,   // len E (mutable)
    // Per-vertex
    vert_co: Vec<[f64; 3]>,    // len V
}

fn vsub(a: [f64; 3], b: [f64; 3]) -> [f64; 3] { [a[0]-b[0], a[1]-b[1], a[2]-b[2]] }
fn vlen(v: [f64; 3]) -> f64 { (v[0]*v[0] + v[1]*v[1] + v[2]*v[2]).sqrt() }
fn vdot(a: [f64; 3], b: [f64; 3]) -> f64 { a[0]*b[0] + a[1]*b[1] + a[2]*b[2] }

#[pymethods]
impl Graph {
    /// Build graph from flat arrays.
    ///
    /// edge_verts: flat [v0a, v0b, v1a, v1b, ...], length 2*E.
    /// edge_len / has_angle / angle_bias / edge_barrier: length E.
    /// vert_co: flat [x, y, z, ...], length 3*V.
    #[new]
    fn new(
        nv: usize,
        edge_verts: Vec<u32>,
        edge_len: Vec<f64>,
        has_angle: Vec<u8>,
        angle_bias: Vec<f64>,
        edge_barrier: Vec<u8>,
        vert_co: Vec<f64>,
    ) -> PyResult<Self> {
        let ne = edge_len.len();
        if edge_verts.len() != ne * 2 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "edge_verts len must equal 2 * edge_len len"));
        }
        if has_angle.len() != ne || angle_bias.len() != ne || edge_barrier.len() != ne {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "per-edge arrays must all have length E"));
        }
        if vert_co.len() != nv * 3 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "vert_co len must equal 3 * nv"));
        }

        // Per-vertex coords
        let mut co = Vec::with_capacity(nv);
        for i in 0..nv {
            co.push([vert_co[i*3], vert_co[i*3+1], vert_co[i*3+2]]);
        }

        // Count degrees
        let mut degree = vec![0u32; nv];
        for i in 0..ne {
            let a = edge_verts[i*2] as usize;
            let b = edge_verts[i*2+1] as usize;
            degree[a] += 1;
            degree[b] += 1;
        }
        // Prefix sum -> starts
        let mut starts = vec![0u32; nv + 1];
        for i in 0..nv {
            starts[i+1] = starts[i] + degree[i];
        }
        let total = starts[nv] as usize;
        let mut adj_other = vec![0u32; total];
        let mut adj_edge = vec![0u32; total];
        let mut adj_dir = vec![[0.0f64; 3]; total];
        let mut adj_dir_valid = vec![false; total];
        let mut pos = starts[..nv].to_vec();
        for i in 0..ne {
            let a = edge_verts[i*2] as usize;
            let b = edge_verts[i*2+1] as usize;
            // a -> b
            {
                let p = pos[a] as usize;
                pos[a] += 1;
                adj_other[p] = b as u32;
                adj_edge[p] = i as u32;
                let d = vsub(co[b], co[a]);
                let l = vlen(d);
                if l > 1e-8 {
                    adj_dir[p] = [d[0]/l, d[1]/l, d[2]/l];
                    adj_dir_valid[p] = true;
                }
            }
            // b -> a
            {
                let p = pos[b] as usize;
                pos[b] += 1;
                adj_other[p] = a as u32;
                adj_edge[p] = i as u32;
                let d = vsub(co[a], co[b]);
                let l = vlen(d);
                if l > 1e-8 {
                    adj_dir[p] = [d[0]/l, d[1]/l, d[2]/l];
                    adj_dir_valid[p] = true;
                }
            }
        }

        Ok(Graph {
            nv, ne,
            starts, adj_other, adj_edge, adj_dir, adj_dir_valid,
            edge_len,
            has_angle: has_angle.into_iter().map(|b| b != 0).collect(),
            angle_bias,
            edge_barrier: edge_barrier.into_iter().map(|b| b != 0).collect(),
            vert_co: co,
        })
    }

    fn set_barrier(&mut self, mask: Vec<u8>) -> PyResult<()> {
        if mask.len() != self.ne {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "barrier mask length must equal E"));
        }
        for (i, b) in mask.iter().enumerate() {
            self.edge_barrier[i] = *b != 0;
        }
        Ok(())
    }

    #[getter] fn nv(&self) -> usize { self.nv }
    #[getter] fn ne(&self) -> usize { self.ne }

    /// Index of the vertex with minimum squared distance to `point`.
    fn nearest_vertex(&self, point: [f64; 3]) -> u32 {
        let mut best = 0u32;
        let mut best_d = f64::INFINITY;
        for (i, co) in self.vert_co.iter().enumerate() {
            let dx = co[0] - point[0];
            let dy = co[1] - point[1];
            let dz = co[2] - point[2];
            let d = dx*dx + dy*dy + dz*dz;
            if d < best_d {
                best_d = d;
                best = i as u32;
            }
        }
        best
    }

    /// Weighted A* from start to end.
    /// Returns Vec<u32> of edge indices in order start->end.
    /// excluded_edge: -1 for none.
    /// flow_cos: -2.0 (or any <=-1) disables the flow filter.
    /// curvature_c: 0.0 disables curvature weighting.
    /// h_weight: 1.0 == admissible; >1.0 == faster but ε-suboptimal.
    #[pyo3(signature = (start, end, excluded_edge, flow_cos, curvature_c, h_weight, max_visited, initial_dir, forbidden=None))]
    fn astar(
        &self,
        start: u32,
        end: u32,
        excluded_edge: i64,
        flow_cos: f64,
        curvature_c: f64,
        h_weight: f64,
        max_visited: usize,
        initial_dir: [f64; 3],
        forbidden: Option<Vec<u32>>,
    ) -> Vec<u32> {
        let forbidden_set: Option<HashSet<u32>> = forbidden.and_then(|v| {
            if v.is_empty() { None } else { Some(v.into_iter().collect()) }
        });
        let nv = self.nv;
        let start_us = start as usize;
        let end_us = end as usize;
        if start_us >= nv || end_us >= nv { return Vec::new(); }

        let flow_active = flow_cos > -1.0;
        let curv_active = curvature_c != 0.0;
        const CURVATURE_SCALE: f64 = 0.8;

        let inf = f64::INFINITY;
        let mut dist = vec![inf; nv];
        let mut prev_v = vec![-1i32; nv];
        let mut prev_e = vec![-1i32; nv];
        let mut incoming: Vec<[f64; 3]> = vec![[0.0; 3]; nv];
        let mut incoming_valid = vec![false; nv];
        let mut visited = vec![false; nv];

        dist[start_us] = 0.0;
        incoming[start_us] = initial_dir;
        incoming_valid[start_us] = vlen(initial_dir) > 1e-8;

        let target_co = self.vert_co[end_us];
        let start_co = self.vert_co[start_us];
        let h0 = vlen(vsub(start_co, target_co)) * h_weight;

        let mut heap: BinaryHeap<HeapEntry> = BinaryHeap::new();
        heap.push(HeapEntry { f: h0, g: 0.0, vi: start });

        let mut visited_count = 0usize;
        let mut reached = false;

        while let Some(HeapEntry { f: _, g, vi }) = heap.pop() {
            let vi_us = vi as usize;
            if visited[vi_us] { continue; }
            visited[vi_us] = true;
            visited_count += 1;
            if visited_count > max_visited { break; }
            if vi_us == end_us { reached = true; break; }

            let inc_dir = if incoming_valid[vi_us] { incoming[vi_us] } else { initial_dir };
            let s = self.starts[vi_us] as usize;
            let e = self.starts[vi_us + 1] as usize;
            for k in s..e {
                let ei = self.adj_edge[k] as usize;
                if excluded_edge >= 0 && ei as i64 == excluded_edge { continue; }
                if self.edge_barrier[ei] { continue; }
                let ovi = self.adj_other[k] as usize;
                if visited[ovi] { continue; }
                if let Some(fs) = &forbidden_set {
                    if fs.contains(&(ovi as u32)) { continue; }
                }
                let dir_valid = self.adj_dir_valid[k];
                if flow_active && dir_valid {
                    let dv = self.adj_dir[k];
                    if vdot(inc_dir, dv) < flow_cos { continue; }
                }
                let w = if curv_active && self.has_angle[ei] {
                    let mut m = 1.0 - CURVATURE_SCALE * curvature_c * self.angle_bias[ei];
                    if m < 0.1 { m = 0.1; }
                    self.edge_len[ei] * m
                } else {
                    self.edge_len[ei]
                };
                let ng = g + w;
                if ng < dist[ovi] {
                    dist[ovi] = ng;
                    prev_v[ovi] = vi_us as i32;
                    prev_e[ovi] = ei as i32;
                    if dir_valid {
                        incoming[ovi] = self.adj_dir[k];
                        incoming_valid[ovi] = true;
                    } else {
                        incoming[ovi] = inc_dir;
                        incoming_valid[ovi] = incoming_valid[vi_us];
                    }
                    let h = vlen(vsub(self.vert_co[ovi], target_co)) * h_weight;
                    heap.push(HeapEntry { f: ng + h, g: ng, vi: ovi as u32 });
                }
            }
        }

        if !reached { return Vec::new(); }
        reconstruct(&prev_v, &prev_e, end_us)
    }

    /// Dijkstra. If end < 0, expand until a barrier-touching vert is reached (Direction mode)
    /// or until max_visited is exceeded — returns path to furthest reached vertex.
    #[pyo3(signature = (start, end, excluded_edge, flow_cos, curvature_c, max_visited, initial_dir, forbidden=None))]
    fn dijkstra(
        &self,
        start: u32,
        end: i64,
        excluded_edge: i64,
        flow_cos: f64,
        curvature_c: f64,
        max_visited: usize,
        initial_dir: [f64; 3],
        forbidden: Option<Vec<u32>>,
    ) -> Vec<u32> {
        let forbidden_set: Option<HashSet<u32>> = forbidden.and_then(|v| {
            if v.is_empty() { None } else { Some(v.into_iter().collect()) }
        });
        let nv = self.nv;
        let start_us = start as usize;
        if start_us >= nv { return Vec::new(); }

        let flow_active = flow_cos > -1.0;
        let curv_active = curvature_c != 0.0;
        const CURVATURE_SCALE: f64 = 0.8;

        let inf = f64::INFINITY;
        let mut dist = vec![inf; nv];
        let mut prev_v = vec![-1i32; nv];
        let mut prev_e = vec![-1i32; nv];
        let mut incoming: Vec<[f64; 3]> = vec![[0.0; 3]; nv];
        let mut incoming_valid = vec![false; nv];
        let mut visited = vec![false; nv];

        dist[start_us] = 0.0;
        incoming[start_us] = initial_dir;
        incoming_valid[start_us] = vlen(initial_dir) > 1e-8;

        let mut heap: BinaryHeap<HeapEntry> = BinaryHeap::new();
        heap.push(HeapEntry { f: 0.0, g: 0.0, vi: start });

        let mut visited_count = 0usize;
        let mut target: i64 = -1;

        while let Some(HeapEntry { f: _, g, vi }) = heap.pop() {
            let vi_us = vi as usize;
            if visited[vi_us] { continue; }
            visited[vi_us] = true;
            visited_count += 1;
            if visited_count > max_visited { break; }

            if vi_us != start_us {
                if end >= 0 {
                    if vi_us as i64 == end { target = end; break; }
                } else {
                    // Direction mode: stop on any barrier-touching neighbor
                    let s = self.starts[vi_us] as usize;
                    let e = self.starts[vi_us + 1] as usize;
                    let mut touched = false;
                    for k in s..e {
                        let ei = self.adj_edge[k] as usize;
                        if excluded_edge >= 0 && ei as i64 == excluded_edge { continue; }
                        if self.edge_barrier[ei] { touched = true; break; }
                    }
                    if touched { target = vi_us as i64; break; }
                }
            }

            let inc_dir = if incoming_valid[vi_us] { incoming[vi_us] } else { initial_dir };
            let s = self.starts[vi_us] as usize;
            let e = self.starts[vi_us + 1] as usize;
            for k in s..e {
                let ei = self.adj_edge[k] as usize;
                if excluded_edge >= 0 && ei as i64 == excluded_edge { continue; }
                if self.edge_barrier[ei] { continue; }
                let ovi = self.adj_other[k] as usize;
                if visited[ovi] { continue; }
                if let Some(fs) = &forbidden_set {
                    if fs.contains(&(ovi as u32)) { continue; }
                }
                let dir_valid = self.adj_dir_valid[k];
                if flow_active && dir_valid {
                    let dv = self.adj_dir[k];
                    if vdot(inc_dir, dv) < flow_cos { continue; }
                }
                let w = if curv_active && self.has_angle[ei] {
                    let mut m = 1.0 - CURVATURE_SCALE * curvature_c * self.angle_bias[ei];
                    if m < 0.1 { m = 0.1; }
                    self.edge_len[ei] * m
                } else {
                    self.edge_len[ei]
                };
                let ng = g + w;
                if ng < dist[ovi] {
                    dist[ovi] = ng;
                    prev_v[ovi] = vi_us as i32;
                    prev_e[ovi] = ei as i32;
                    if dir_valid {
                        incoming[ovi] = self.adj_dir[k];
                        incoming_valid[ovi] = true;
                    } else {
                        incoming[ovi] = inc_dir;
                        incoming_valid[ovi] = incoming_valid[vi_us];
                    }
                    heap.push(HeapEntry { f: ng, g: ng, vi: ovi as u32 });
                }
            }
        }

        if target < 0 && end < 0 {
            // Fallback: furthest reached
            let mut best = -1.0f64;
            for i in 0..nv {
                if dist[i] < inf && dist[i] > best {
                    best = dist[i];
                    target = i as i64;
                }
            }
        }
        if target < 0 { return Vec::new(); }
        reconstruct(&prev_v, &prev_e, target as usize)
    }
}

fn reconstruct(prev_v: &[i32], prev_e: &[i32], target: usize) -> Vec<u32> {
    let mut out = Vec::new();
    let mut cur = target as i32;
    while prev_v[cur as usize] != -1 {
        out.push(prev_e[cur as usize] as u32);
        cur = prev_v[cur as usize];
    }
    out.reverse();
    out
}

#[pymodule]
fn mesh_uv_shortest_mark_lib(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Graph>()?;
    Ok(())
}
