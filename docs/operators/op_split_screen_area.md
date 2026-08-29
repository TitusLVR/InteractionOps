# Split Screen Area

The tool behind the Split pie. It opens a new editor (UV Editor, Outliner, Timeline, ...) next to the current area on the side you choose, and closes it again when you call it a second time — one shortcut toggles a paired editor on and off. A companion *Switch Screen Area* action converts the current area in place instead of splitting.

**Hotkey:** Not bound directly — use the Split pie, <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd>. Each pie slot remembers its own editor type, side and split ratio (set in *Preferences › iOps › Split Pie Layout*).

## Options
- **Which area to create** and **which UI to enable** — the editor the new area becomes.
- **Position** — Left, Right, Top or Bottom of the current area.
- **Area split factor** — how much of the current area the new editor takes.

## Tips
- If you are in a maximised (fullscreen) area, the first call just exits fullscreen.
- Editor settings (hidden header, Outliner columns, ...) are restored when the area reopens — see [Save/Load Space Data](op_save_load_space_data.md).
