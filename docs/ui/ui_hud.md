# HUD

Every interactive iOps tool draws the same kind of on-screen readout while it runs: a **HUD** with the tool name and its live values, and a **Help legend** listing the keys you can press. A separate **Statistics** block in the top-left corner of the 3D View shows information about the file and the active object at all times.

## HUD

- Shows the tool's name and its current parameters (count, distance, axis, mode ...) so you never have to guess what a key changed.
- Follows the mouse by default; it can be pinned to a corner or a fixed spot in *Preferences › iOps › Theme › HUD*.
- <kbd>Shift</kbd>+<kbd>Ctrl</kbd>+<kbd>Alt</kbd>+drag the HUD to move it anywhere; it then stays there.
- <kbd>/</kbd> hides the parameter list and leaves only the title (rebind in *Keymaps*).

## Help legend

- Press <kbd>H</kbd> to expand or collapse the key legend for the running tool. When collapsed it shows a one-line hint.
- Drag it with <kbd>Shift</kbd>+<kbd>Ctrl</kbd>+<kbd>Alt</kbd> to place it where you like.
- The toggle key is a normal keymap entry (*Keymaps › UI Toggles*), so you can change it.
- Expand / collapse animation styles (fade, slide, wave, shockwave or none) are chosen in the Theme tab.

## Statistics

- File name (red when unsaved), dimensions, position, material, modifiers, instances, parent and unit warnings for the active object.
- Turn individual rows on or off in *Preferences › iOps › Statistics Overlay*; turn the whole block off with the master toggle.
- Respects the viewport's *Show Overlays* switch.

## Theme

Colours, text sizes, panel background, shadow and font for all of the above are in *Preferences › iOps › Theme*. Pick a bundled preset, save your own, or click *Use Blender Theme HUD Colors* to match your Blender theme. *Theme Preview* draws a sample of every element in the viewport while you tune it.
