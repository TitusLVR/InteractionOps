"""Generate iops_mod_layouts.py from Blender's MOD_*.cc panel code.

Parses panel_register() for the panel tree and each *_draw function for
the ordered prop calls. Output: LAYOUTS = {RNA type enum: [panel, ...]}.
"""
import re, sys, glob, os, pprint

SRC = os.path.join(os.path.dirname(__file__), "modsrc")
OUT = sys.argv[1] if len(sys.argv) > 1 else None

# eModifierType_<Name> -> RNA enum identifier (only where the naive
# normalisation (strip '_' + lower) does not match)
OVERRIDES = {
    "WeightVGEdit": "VERTEX_WEIGHT_EDIT",
    "WeightVGMix": "VERTEX_WEIGHT_MIX",
    "WeightVGProximity": "VERTEX_WEIGHT_PROXIMITY",
    "Softbody": "SOFT_BODY",
    "GreasePencilLineart": "LINEART",
}
RNA_TYPES = """GREASE_PENCIL_VERTEX_WEIGHT_PROXIMITY DATA_TRANSFER MESH_CACHE MESH_SEQUENCE_CACHE NORMAL_EDIT WEIGHTED_NORMAL UV_PROJECT UV_WARP VERTEX_WEIGHT_EDIT VERTEX_WEIGHT_MIX VERTEX_WEIGHT_PROXIMITY ARRAY BEVEL BOOLEAN BUILD DECIMATE EDGE_SPLIT NODES MASK MIRROR MESH_TO_VOLUME MULTIRES REMESH SCREW SKIN SOLIDIFY SUBSURF TRIANGULATE VOLUME_TO_MESH WELD WIREFRAME LINEART ARMATURE CAST CURVE DISPLACE HOOK LAPLACIANDEFORM LATTICE MESH_DEFORM SHRINKWRAP SIMPLE_DEFORM SMOOTH CORRECTIVE_SMOOTH LAPLACIANSMOOTH SURFACE_DEFORM WARP WAVE VOLUME_DISPLACE CLOTH COLLISION DYNAMIC_PAINT EXPLODE FLUID OCEAN PARTICLE_INSTANCE PARTICLE_SYSTEM SOFT_BODY SURFACE""".split()
NORM = {t.replace("_", "").lower(): t for t in RNA_TYPES}


def strip_comments(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"//[^\n]*", "", s)
    return s


def find_functions(src):
    """name -> body text for `static void name(...)` / `void name(...)`."""
    out = {}
    for m in re.finditer(r"(?:static\s+)?void\s+(\w+)\s*\([^;{]*?\)\s*\{", src):
        name = m.group(1)
        i = m.end()
        depth = 1
        while depth and i < len(src):
            c = src[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        out[name] = src[m.end():i - 1]
    return out


STR = r'"([A-Za-z0-9_]+)"'
IFACE = r'(?:IFACE_|N_|CTX_IFACE_\([^,]+,)\s*\(?\s*"([^"]*)"\s*\)?'


def parse_items(body, funcs, depth=0):
    """Ordered UI items from a draw-function body."""
    items = []
    # dynamic names: const char *x = cond ? "a" : "b";
    dyn = {}
    for m in re.finditer(r'const char \*(\w+)\s*=\s*[^;]*?"([a-z_]+)"[^;]*?"([a-z_]+)"', body):
        dyn[m.group(1)] = [m.group(2), m.group(3)]

    token_re = re.compile(
        r'(?P<prop>\bprop(?:_search)?\s*\(\s*(?P<pptr>&?\w+)\s*,\s*(?P<pname>"[A-Za-z0-9_]+"|\w+)\s*(?P<prest>(?:[^;])*?)\)\s*;)'
        r'|(?P<vg>\bmodifier_vgroup_ui\s*\((?P<vgargs>[^;]*)\)\s*;)'
        r'|(?P<wvg>\bweightvg_ui_common\s*\()'
        r'|(?P<sep>\bseparator\s*\()'
        r'|(?P<head>\b(?:column|row)\s*\(\s*(?:true|false)\s*,\s*' + IFACE + r')'
        r'|(?P<tmpl>\btemplate_\w+\s*\([^;]*?"(?P<tname>[A-Za-z0-9_]+)"[^;]*\)\s*;)'
        r'|(?P<fp>\bRNA_struct_find_property\s*\(\s*ptr\s*,\s*"(?P<fpname>[A-Za-z0-9_]+)"\s*\))',
        re.S)
    for m in token_re.finditer(body):
        if m.group("prop"):
            ptr = m.group("pptr").lstrip("&")
            if ptr not in ("ptr", "md_ptr", "modifier_ptr"):
                continue      # props of the object / other IDs
            raw = m.group("pname")
            names = [raw.strip('"')] if raw.startswith('"') else dyn.get(raw, [])
            rest = m.group("prest")
            expand = "ITEM_R_EXPAND" in rest
            slider = "ITEM_R_SLIDER" in rest
            tm = re.search(IFACE, rest)
            text = tm.group(1) if tm else None
            for n in names:
                it = {"prop": n}
                if expand:
                    it["expand"] = True
                if slider:
                    it["slider"] = True
                if text:
                    it["text"] = text
                items.append(it)
        elif m.group("vg"):
            strs = re.findall(STR, m.group("vgargs"))
            if strs:
                it = {"vgroup": strs[0]}
                if len(strs) > 1:
                    it["invert"] = strs[1]
                items.append(it)
        elif m.group("wvg"):
            if "weightvg_ui_common" in funcs and depth < 2:
                items.extend(parse_items(funcs["weightvg_ui_common"], funcs, depth + 1))
        elif m.group("sep"):
            items.append({"sep": True})
        elif m.group("head"):
            text = re.search(IFACE, m.group("head")).group(1)
            # `prop = RNA_struct_find_property(ptr, "x"); row(true, IFACE_("Axis"))`
            # + per-index toggles: the heading labels that prop's row
            if items and items[-1].get("_fp"):
                items[-1]["text"] = text
                continue
            items.append({"heading": text})
        elif m.group("tmpl"):
            items.append({"prop": m.group("tname")})
        elif m.group("fp"):
            items.append({"prop": m.group("fpname"), "_fp": True})
    # dedupe props (conditional branches repeat them), keep first
    seen, out = set(), []
    for it in items:
        it.pop("_fp", None)
        key = it.get("prop") or it.get("vgroup")
        if key:
            if key in seen:
                continue
            seen.add(key)
        # collapse duplicate separators
        if "sep" in it and out and "sep" in out[-1]:
            continue
        out.append(it)
    while out and ("sep" in out[-1] or "heading" in out[-1]):
        out.pop()
    while out and "sep" in out[0]:
        out.pop(0)
    return out


def parse_file(path, extra_funcs):
    src = strip_comments(open(path, encoding="utf-8").read())
    funcs = find_functions(src)
    funcs.update({k: v for k, v in extra_funcs.items() if k not in funcs})
    reg = funcs.get("panel_register")
    if reg is None:
        return None
    m = re.search(r"modifier_panel_register\s*\(\s*region_type\s*,\s*eModifierType_(\w+)\s*,\s*(\w+)\s*\)", reg)
    if not m:
        return None
    ctype, root_fn = m.group(1), m.group(2)
    rna = OVERRIDES.get(ctype) or NORM.get(ctype.lower())
    if rna is None:
        print("!! no RNA type for", ctype, file=sys.stderr)
        return None
    var_to_id = {}
    rootvar = re.search(r"PanelType \*(\w+)\s*=\s*modifier_panel_register", reg)
    if rootvar:
        var_to_id[rootvar.group(1)] = None
    panels = [{"id": "", "label": "", "parent": None,
               "items": parse_items(funcs.get(root_fn, ""), funcs)}]
    for sm in re.finditer(
            r"(?:PanelType \*(\w+)\s*=\s*)?modifier_subpanel_register\s*\(\s*region_type\s*,\s*"
            r'"([A-Za-z0-9_]+)"\s*,\s*"([^"]*)"\s*,\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*\)', reg):
        var, pid, label, hdr, draw, parent = sm.groups()
        if var:
            var_to_id[var] = pid
        panel = {"id": pid, "label": label, "parent": var_to_id.get(parent),
                 "items": parse_items(funcs.get(draw, ""), funcs)}
        if hdr != "nullptr":
            hitems = [i for i in parse_items(funcs.get(hdr, ""), funcs) if "prop" in i]
            if hitems:
                panel["header"] = [i["prop"] for i in hitems]
        panels.append(panel)
    return rna, panels


def main():
    util = strip_comments(open(os.path.join(SRC, "MOD_weightvg_util.cc"), encoding="utf-8").read())
    extra = find_functions(util)
    layouts = {}
    for path in sorted(glob.glob(os.path.join(SRC, "MOD_*.cc"))):
        base = os.path.basename(path)
        if base in ("MOD_ui_common.cc", "MOD_util.cc", "MOD_weightvg_util.cc", "MOD_none.cc"):
            continue
        r = parse_file(path, extra)
        if r is None:
            print("-- skip", base, file=sys.stderr)
            continue
        rna, panels = r
        layouts[rna] = panels
    body = pprint.pformat(layouts, width=78, sort_dicts=False)
    text = ('"""Native modifier panel layouts, GENERATED from Blender\'s\n'
            'source/blender/modifiers/intern/MOD_*.cc (branch blender-v5.2-release)\n'
            'by the gen_layouts.py scratch script - do not hand-edit; regenerate.\n\n'
            'LAYOUTS[md.type] = [panel, ...] in native order. panel = {\n'
            '    "id": subpanel idname ("" = the root body), "label", "parent": id | None,\n'
            '    "header": [prop, ...]     # checkbox props drawn in the subpanel header\n'
            '    "items": [{"prop": name, "expand"?, "slider"?, "text"?}\n'
            '              | {"vgroup": name, "invert"?: name}\n'
            '              | {"sep": True} | {"heading": text}, ...]\n'
            '}\nProps are listed unconditionally (the C code hides some behind\n'
            'enum checks); the reader draws only those that exist on the modifier.\n"""\n\n'
            f"LAYOUTS = {body}\n")
    if OUT:
        open(OUT, "w", encoding="utf-8", newline="\n").write(text)
        print("wrote", OUT, len(layouts), "types")
    else:
        print(text)


main()
