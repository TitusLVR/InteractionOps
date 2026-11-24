"""Headless check of every modal HUD against the More Options (Tab) rules. Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_hud_more_options.py

The cases live in ``tests/blender/hud_cases_*.py`` (a list ``CASES`` of ``HudCase`` each). For every case the
operator's overlay-building method runs on a stand-in instance (the RNA defaults of the operator's properties plus
``state``), then:

* a "More Options (Tab)" row exists exactly when the case has a Tab section;
* with More Options off and the default state the HUD shows exactly ``always``; with it on, ``always | tab_rows``;
* each ``also`` change shows its Tab row while More Options is off;
* the help starts collapsed, lists every key in ``keys`` and has no line for H or ``/``;
* every event type the operator's module compares ``event.type`` with is named in the help (``hud_keys``).

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import glob
import importlib
import inspect
import os
import sys
import traceback
from types import SimpleNamespace
import bpy

ADDON = "InteractionOps"
HERE = os.path.dirname(os.path.abspath(__file__))
MORE = "More Options (Tab)"


def op_rna(cls):
    """The registered operator's RNA type with its own properties (``cls.bl_rna`` has only the base ones)."""
    prefix, name = cls.bl_idname.split(".", 1)
    return getattr(getattr(bpy.ops, prefix), name).get_rna_type()


class StandIn:
    """Stands in for an operator instance: its RNA property defaults, the case's state, the class's methods."""

    def __init__(self, cls, state):
        object.__setattr__(self, "_cls", cls)
        rna = op_rna(cls)
        # like a real instance: its own property type at .properties.bl_rna (MoreOptions.changed reads it)
        self.__dict__["properties"] = SimpleNamespace(bl_rna=rna)
        for prop in rna.properties:
            ident = prop.identifier
            if ident == "rna_type" or prop.type in {"POINTER", "COLLECTION"}:
                continue
            if prop.type == "ENUM" and prop.is_enum_flag:
                value = set(prop.default_flag)
            elif getattr(prop, "is_array", False) and prop.array_length > 0:
                value = tuple(prop.default_array)
            else:
                value = prop.default
            self.__dict__[ident] = value
        self.__dict__.update(state)
        self.__dict__["reports"] = []

    def report(self, _kinds, message):
        self.reports.append(message)

    def __getattr__(self, name):
        try:
            attr = inspect.getattr_static(self._cls, name)
        except AttributeError:
            raise AttributeError(name) from None
        if hasattr(attr, "__get__"):
            return attr.__get__(self, self._cls)
        return attr


def _cases():
    out = []
    for path in sorted(glob.glob(os.path.join(HERE, "hud_cases_*.py"))):
        mod = importlib.import_module(os.path.splitext(os.path.basename(path))[0])
        out.extend(mod.CASES)
    return out


def _params(hud):
    return [p for section in hud.param_sections for p in section.params]


def _shown(hud):
    return {p.name for p in _params(hud) if p.is_visible()}


def _key_parts(helpo):
    parts = set()
    for section in helpo.sections:
        for it in section.items:
            parts.add(it.key.strip())
            parts.update(part.strip() for part in it.key.split(" / "))
    return parts


def check(case):
    module = importlib.import_module(f"{ADDON}.{case.module}")
    cls = getattr(module, case.cls)
    op = StandIn(cls, dict(case.state))
    tab = case.tab_rows is not None
    if tab:
        op.show_options = False
    (case.build or (lambda o: o._build_overlays(None)))(op)
    hud, helpo = getattr(op, case.hud), getattr(op, case.help)
    names = [p.name for p in _params(hud)]
    assert len(names) == len(set(names)), f"duplicate rows: {names}"
    assert (MORE in names) == tab, f"More Options row present: {MORE in names}, Tab section: {tab}"
    shown = _shown(hud)
    assert shown == set(case.always), (
        f"More Options off: shown {sorted(shown)}; expected {sorted(case.always)}")
    if tab:
        assert MORE in case.always, "the More Options row is always shown"
        assert not (set(case.tab_rows) & set(case.always)), "a row is both always shown and a Tab row"
        op.show_options = True
        shown = _shown(hud)
        assert shown == set(case.always) | set(case.tab_rows), (
            f"More Options on: shown {sorted(shown)}; expected {sorted(set(case.always) | set(case.tab_rows))}")
        op.show_options = False
    for changes, row in case.also:
        before = {k: getattr(op, k) for k in changes}
        for k, v in changes.items():
            setattr(op, k, v)
        assert row in _shown(hud), f"{row} hidden after {changes} with More Options off"
        for k, v in before.items():
            setattr(op, k, v)
    assert helpo.expanded is False, "the help starts collapsed"
    parts = _key_parts(helpo)
    missing = [k for k in case.keys if k not in parts]
    assert not missing, f"keys missing from the help: {missing}; help keys: {sorted(parts)}"
    assert "H" not in parts and "/" not in parts, "the help lists H or / itself"
    if tab:
        assert "Tab" in parts, "the help lists Tab"
    import hud_keys          # every key the module compares event.type with is named in the help
    texts = [it.key for section in helpo.sections for it in section.items]
    # the operator's module, and the bodies of its addon base classes from other modules (a shared modal mixin)
    sources = [module.__file__]
    sources += [(sys.modules[c.__module__].__file__, c.__name__) for c in cls.__mro__[1:]
                if c.__module__.startswith(ADDON + ".") and c.__module__ != module.__name__]
    unnamed = hud_keys.missing_keys(sources, texts, case.ignore_events)
    assert not unnamed, f"handled in {sources} but not in the help: {unnamed}; help keys: {texts}"
    for p in _params(hud):     # every getter works on the stand-in
        assert p.value_text() != "?", f"row {p.name} cannot read its value"


def enable_addon():
    repo_root = os.path.dirname(os.path.dirname(HERE))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), f"addon loaded from {loaded}"


# --- the same rows on a REAL operator instance --------------------------------------------------------------------
# A stand-in can hide a difference from a real instance (an instance's own ``bl_rna`` lists only the base Operator
# fields, for one). For these cases the operator's ``execute`` is swapped for a probe (Blender looks it up on the
# class at call time) and the operator is called through bpy.ops: the probe builds the overlays on the real
# instance and checks them there. (In the background INVOKE_DEFAULT runs ``execute`` too.)
REAL_CASES = {"UV Stripe", "UV Pipe"}


def _edit_mesh():
    """A 4 x 1 strip of quads, active and in Edit Mode with every face selected (enough for the operators' poll)."""
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    verts = [(x, y, 0.0) for y in (0, 1) for x in range(5)]
    faces = [(i, i + 1, i + 6, i + 5) for i in range(4)]
    me = bpy.data.meshes.new("hud_real")
    me.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new("hud_real", me)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")


def check_real(case):
    """On the real instance, Tab off: the default rows are ``always`` and every ``also`` change shows its row."""
    module = importlib.import_module(f"{ADDON}.{case.module}")
    cls = getattr(module, case.cls)
    original = cls.__dict__["execute"]
    out = {}

    def probe(self, _context):
        try:
            out["real"] = type(self) is cls and isinstance(self, bpy.types.Operator)
            for k, v in case.state.items():
                setattr(self, k, v)
            self.show_options = False
            (case.build or (lambda o: o._build_overlays(None)))(self)
            hud = getattr(self, case.hud)
            out["base"] = _shown(hud)
            out["also"] = []
            for changes, row in case.also:
                before = {k: getattr(self, k) for k in changes}
                for k, v in changes.items():
                    setattr(self, k, v)
                out["also"].append((changes, row, row in _shown(hud)))
                for k, v in before.items():
                    setattr(self, k, v)
        except Exception:
            out["error"] = traceback.format_exc()
        return {"CANCELLED"}

    _edit_mesh()
    cls.execute = probe
    try:
        prefix, name = cls.bl_idname.split(".", 1)
        getattr(getattr(bpy.ops, prefix), name)("EXEC_DEFAULT")
    finally:
        cls.execute = original
    assert "error" not in out, out.get("error")
    assert out.get("real"), "the probe did not run on a real operator instance"
    assert out["base"] == set(case.always), f"real instance, Tab off: shown {sorted(out['base'])}"
    hidden = [(changes, row) for changes, row, shown in out["also"] if not shown]
    assert not hidden, f"real instance: rows hidden after their option changed: {hidden}"


def main():
    enable_addon()
    cases = _cases()
    runs = [(case.name, check, case) for case in cases]
    runs += [(case.name + " (real instance)", check_real, case) for case in cases if case.name in REAL_CASES]
    assert {case.name for case in cases} >= REAL_CASES, "a real-instance case has no HudCase"
    failed = 0
    for label, fn, case in runs:
        try:
            fn(case)
            print("PASS", label)
        except Exception:
            failed += 1
            print("FAIL", label)
            traceback.print_exc()
    print(f"{len(runs) - failed}/{len(runs)} passed")
    if failed or not cases:
        sys.exit(1)


if __name__ == "__main__":
    main()
