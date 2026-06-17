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
    def register():
        # Composed (JSON) widgets are loaded from the library folder by
        # the root __init__ (composed.load_all + sync_from_files). Nothing
        # to register here anymore — kept for symmetric wiring.
        pass

    def unregister():
        try:
            from . import composed
            composed.unregister_all()
        except Exception as e:
            print(f"IOPS widgets: composed unregister failed: {e}")
else:  # plain pytest / headless tooling without bpy
    def register():
        pass

    def unregister():
        pass
