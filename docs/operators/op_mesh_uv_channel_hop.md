# UV Channel Hop

Switches the active UV map of the active mesh to the next one, so you can cycle channels with a key instead of visiting the Data properties. Optionally makes the new channel the render channel and rebuilds seams from its islands so the seam overlay matches what you see. Edit Mesh mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: iOps Data panel › UV maps.

## Options
- **Hop to Previous** — step backwards instead.
- **Mark Seams** — clear seams and re-mark them from the new channel's islands. Turn this off if you author seams by hand.
- **Set Render** — make the new channel the render channel.
