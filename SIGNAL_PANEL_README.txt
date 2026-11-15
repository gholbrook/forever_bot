ENGAGE INDICATOR: SIGNAL PANEL AND NAMEPLATE MARKERS

INSTALL
1. Close WoW. Replace the EngageIndicator addon folder in your Forever Interface\AddOns directory with the included EngageIndicator folder. This updates the addon you already installed. Keep the exact folder structure.
2. Put signal_panel.py next to your existing state_reader.py and calibration folder. Start the game with enemy nameplates enabled.
3. The original green/red combat square remains. The seven smaller squares below it, left to right, mean: T target exists; H target attackable; CU Charge usable; CR Charge in range; OP Overpower usable; VR Victory Rush usable; HS Heroic Strike usable. Green #00FF00 means yes; red #FF0000 means no; blue #0000FF means unknown/not accessible. 'Usable' does not prove range, cooldown, proc, line of sight, or success. Unknown must not be treated as yes.
4. Drag the addon by its original top row to a stable position. The addon does not save its position; after reloading it returns to the default. If that changes the original combat square's location, recalibrate your existing combat_signal.py reader. The addon is read-only.

SIGNAL READER
In PowerShell in your scripts folder:
.\.venv\Scripts\python signal_panel.py calibrate

After Enter return to WoW within five seconds. In the frozen screenshot draw exactly one rectangle around the seven colored squares, from the first square's left edge to the last square's right edge; exclude the labels underneath. Press Enter. The calibration is saved separately as calibration/signal_panel.json.

.\.venv\Scripts\python signal_panel.py run

The console prints yes/no/unknown/unreadable for each signal. Ctrl+C stops. It does not control the bot or update one_fight.py. Recalibrate after moving the panel or changing display/UI scaling.

MAGENTA MARKERS
The addon attempts to attach vivid #FF00FF markers above visible attackable nameplates. The Forever client may block or restrict nameplate modification and unit data, especially during combat or in some locations. If there are no markers, do not assume the addon is seeing no enemies. Verify in the actual game.

.\.venv\Scripts\python signal_panel.py markers

This read-only preview draws boxes around visible magenta candidates. Move the preview to another monitor if possible; otherwise it can obscure what it is analyzing. Press Q or Escape in its window to stop. Magenta pixels can match unrelated UI/objects; no guarantee of hostility, enemy location, safe ground, range, or loot location. It does not click or navigate.

The signals use addon API access where available. API functions may return restricted/secret/unknown values, and marker attachment may be rejected; there is no attempt to bypass the client. Test in and out of combat on your Forever client. Red/green/blue pixels can be obscured or stale and should never be treated as infallible evidence for autonomous actions.
