"""Node-editor contextual pie: rule store, catalog and spawn operators."""
from . import catalog, store  # noqa: F401
from .ops import classes as _op_classes

classes = _op_classes


def unregister():
    """Drop everything this package holds for the session.

    Module globals outlive a disable/enable of the addon, so without this a
    reload keeps serving the rules and the probed catalog it built before the
    user's edit, and stays silent about warnings they have never seen. The
    design calls for the catalog cache to be cleared on addon reload; the
    rule cache and the warn-once set have exactly the same lifetime problem.
    Called from the repo-root `unregister()`; there is nothing to register
    here, classes are registered centrally.
    """
    catalog.clear()
    store.reset()
