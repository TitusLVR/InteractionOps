"""Pure (bpy-free) name<->index helpers for the UV image slots widget.

The slot enum's items are [SENTINEL] + the current bpy.data.images names;
the durable store is a StringProperty holding the selected image name.
These helpers map between the stored name and the enum's integer index
WITHOUT bpy, so they are unit-testable. SENTINEL ("") is index 0 = "no
image", which keeps the enum non-empty even when the file has no images.
"""
SENTINEL = ""


def index_of_name(idents, name):
    """Index of `name` in `idents`, or 0 (the sentinel) when absent/empty."""
    try:
        return idents.index(name)
    except ValueError:
        return 0


def name_at_index(idents, index):
    """Identifier at `index`, or SENTINEL when out of range."""
    if 0 <= index < len(idents):
        return idents[index]
    return SENTINEL
