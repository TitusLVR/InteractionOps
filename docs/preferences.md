# Preferences

InteractionOps provides extensive customization options through Blender's addon preferences panel and external preset files.

## Accessing Preferences

**In Blender:**
1. Go to `Edit > Preferences > Add-ons`
2. Search for "InteractionOps" 
3. Expand the addon preferences panel

**Preset Files Location:**
`C:\Users\<USER NAME>\AppData\Roaming\Blender Foundation\Blender\2.xx\scripts\presets\IOPS`

## Preference Categories

### General Settings

**Panel Category**
- **Tab Name**: Customize the name of the iOps panel tab in the 3D viewport
- **Default**: "iOps"

**Debug Mode**
- **Query Debug**: Enable debugging output for troubleshooting
- **Default**: Off

### UI Text & Display

**Modal Operator Text**
- **Text Color**: Color for main modal operator text
- **Key Color**: Color for keyboard shortcut hints
- **Text Size**: Size of modal text display (1-100)
- **Position X/Y**: Screen position for modal text

**Text Shadow**
- **Shadow Toggle**: Enable/disable text shadows
- **Shadow Color**: Shadow color and opacity
- **Shadow Blur**: None, Mid (3), or High (5)
- **Shadow Position**: X/Y offset for shadow

**Statistics Display**
- **Statistics**: Show UV maps and non-uniform scale info
- **Stat Colors**: Colors for normal, key, and error statistics
- **Stat Position**: Screen position for statistics display

### Hotkeys & Keymaps

**Functional Keys (F1-F5)**
- Context-sensitive operations mapped to function keys
- Modifier key combinations (Ctrl, Alt, Shift)
- ESC key for canceling operations

**Default Hotkeys:**
- **F1-F5**: Main functional buttons
- **Alt+F1-F3**: Mesh selection mode switching
- **Alt+F5**: Align origin to normal
- **↑**: Mesh to grid / Object normalize
- **Ctrl+Alt+Shift+S**: Drag snap operations

### Snap Combinations

**8 Configurable Snap Presets**
- **Snap Elements**: Vertex, Edge, Face, Volume, etc.
- **Snap Target**: Active, Closest, Center, Median
- **Tool Settings**: Self-snapping, rotation alignment, etc.
- **Transformation**: Global, Local, Normal orientations

### Split Area Pies

**9 Customizable Area Splits**
- **Split Factor**: Ratio for area division (0.0-1.0)
- **Position**: Top, Bottom, Left, Right
- **Area Type**: Choose target editor type
- **Presets**: Save and recall viewport layouts

### Script Executor

**Executor Settings**
- **Scripts Folder**: Path to custom scripts directory
- **Column Count**: Number of columns in executor UI
- **Name Length**: Maximum displayed name length
- **Use Script Path**: Use Blender's default script directory
- **Subfolder**: Custom subfolder name ("iops_exec")

### Object Operations

**Align to Edge**
- **Edge Color**: Highlight color for alignment guides
- **Visual Feedback**: Real-time alignment indicators

**Rotation Settings**
- **Rotation Angle**: Default rotation increment (degrees)
- **Multi-axis Support**: X, Y, Z axis rotations

### Import/Export

**Preset Management**
- Save current preferences as presets
- Load preset configurations
- Share presets between installations
- Reset to default settings

## Advanced Configuration

### Custom Scripts Integration
- Place Python scripts in the executor folder
- Scripts appear in the executor interface
- Batch operation support
- Error handling and reporting

### Workflow Presets
- Create custom operator combinations
- Save frequently used settings
- Quick workspace switching
- Context-sensitive configurations

## Troubleshooting

**Common Issues:**
- **Hotkeys not working**: Check for conflicts in Blender keymap
- **Text not visible**: Adjust text position and color settings
- **Scripts not loading**: Verify executor folder path
- **Preferences not saving**: Check Blender user preferences directory

**Debug Mode:**
Enable "Query Debug" to see detailed operation information in the console.

## Tips & Best Practices

- **Backup Preferences**: Export settings before major changes
- **Custom Hotkeys**: Avoid conflicts with Blender defaults
- **Screen Position**: Adjust text positions for different monitor sizes
- **Color Schemes**: Match text colors to your Blender theme
- **Script Organization**: Use subfolders for better script management