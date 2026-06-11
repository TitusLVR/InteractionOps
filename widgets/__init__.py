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

    register_widget(EdgeDataWidget)

    def register():
        # Idempotent — re-registering replaces the live instance by name
        register_widget(EdgeDataWidget)

    def unregister():
        unregister_widget(EdgeDataWidget.name)
else:  # plain pytest / headless tooling without bpy
    def register():
        pass

    def unregister():
        pass
