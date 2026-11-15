This extension analyzes your existing recording; it does not control the game.

1. Put extra_state.py next to state_reader.py in the folder you already use.
2. Find two saved frames in one recording: one with an enemy selected and one with no target. Note their filenames. Same layout and resolution required.
3. From PowerShell in that folder, replace folder and filenames below with your actual names:

.\.venv\Scripts\python extra_state.py calibrate .\recording_FOLDER\frame_000020.jpg .\recording_FOLDER\frame_000010.jpg

4. Three screenshot selections appear one after another. Draw a rectangle and press Enter for each:
   - The full rage-bar interior, including unfilled space.
   - The full target health-bar interior, including any unfilled space.
   - A small unmoving piece of the target frame border, excluding bars, portrait and text. The second reference frame must show what is behind that exact area when no target is selected.

5. Run:

.\.venv\Scripts\python extra_state.py analyze .\recording_FOLDER

Results are in recording_FOLDER\extra_state_analysis.csv. Your previous state_analysis.csv is unchanged. Timestamps can be matched to join results by frame or unix_ns. Blank timestamps indicate missing events.csv entries.

Readings are estimates. A red resource bar is assumed; other UI colors, highlights, text, and low rage can cause wrong values. A no-target reference captures a changing 3D background, so especially treat absent or unknown as uncertain; comparing a few frames is essential, and even confident answers can be wrong. Target health is blank unless presence was classified as present; health color variations may break the green detector. Recalibrate for layout/resolution changes. This does not detect cooldowns, range, loot or death, and does not guarantee combat safety.
