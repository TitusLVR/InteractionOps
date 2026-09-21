# Outliner Collection Ops

Four extra entries in the Outliner's collection right-click menu for working on a whole branch at once.

**Hotkey:** Not bound by default — right-click a collection in the Outliner.

## Menu entries

| Entry | What it does |
| --- | --- |
| Include All | Enable the collection and all its children in the view layer |
| Exclude All | Disable the collection and all its children in the view layer |
| Group Duplicates by Name | Move same-named object copies (`box`, `box.000`, `box.001`, ...) from each selected collection into a child collection named `<collection>_<name>`; singletons and nested collections are untouched, other memberships preserved |
| Remove (Keep Objects) | Delete the selected collections and their sub-collections, keeping objects in any other collections they belong to; objects left without a home go to the scene root |
