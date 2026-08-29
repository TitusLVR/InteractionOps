# iOps Dispatcher

The dispatcher is the engine behind the F1–F5 keys. It looks at where your mouse is (3D Viewport, UV Editor, Outliner…), what kind of object is active, which mode you are in and which selection mode is on, then runs the iOps action that fits that situation. You never run it directly — you just press an F-key and get the right tool for the context.

**Hotkey:** none of its own. Press <kbd>F1</kbd>–<kbd>F5</kbd> or <kbd>Esc</kbd>; see [Modes (F1–F5)](op_modes.md) for what each key does where.

## Tips

- Keep the mouse over the editor you want to act on. If nothing is under the cursor, iOps asks you to focus a window.
- Hold <kbd>Alt</kbd>, <kbd>Ctrl</kbd> or <kbd>Shift</kbd> with an F-key to reach the alternate action for that context (for example <kbd>Alt</kbd>+<kbd>F1</kbd>–<kbd>F3</kbd> converts the selection instead of switching mode).
- If a key does nothing in some context you get a short "No operation defined" message — that context simply has no action assigned.
