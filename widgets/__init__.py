"""Concrete iOps widgets, registered with the ui/widgets framework registry.

Widgets are registered at import time — `register_widget` keys by name and
replaces on re-register, so addon reload is safe. The explicit register()/
unregister() hooks are provided for symmetric wiring from the root
__init__.py (alongside ui.widgets.register()/unregister()).

bpy-dependent imports are guarded (same pattern as ui/widgets/__init__.py)
so the package stays importable from plain pytest tooling.
"""
try:
    import bpy  # noqa: F401
    _HAS_BPY = True
except ModuleNotFoundError:
    _HAS_BPY = False

if _HAS_BPY:
    from ..ui.widgets import register_widget, unregister_widget
    from .edge_data import EdgeDataWidget
    from .ccp_data_ops import CCPDataOpsWidget

    # ccp_data_ops registers unconditionally even though it targets the
    # CCP Tools addon: a register-time presence probe would miss CCP Tools
    # enabling AFTER iOps (addon load order is not ours to control). The
    # widget renders disabled while scene.CCP is absent instead.
    register_widget(EdgeDataWidget)
    register_widget(CCPDataOpsWidget)

    def register():
        # Idempotent — re-registering replaces the live instance by name
        register_widget(EdgeDataWidget)
        register_widget(CCPDataOpsWidget)

    def unregister():
        # Composed (JSON) widgets first — they may not shadow built-ins,
        # so order doesn't matter, but keep teardown symmetric anyway.
        try:
            from . import composed
            composed.unregister_all()
        except Exception as e:
            print(f"IOPS widgets: composed unregister failed: {e}")
        unregister_widget(CCPDataOpsWidget.name)
        unregister_widget(EdgeDataWidget.name)
else:  # plain pytest / headless tooling without bpy
    def register():
        pass

    def unregister():
        pass
