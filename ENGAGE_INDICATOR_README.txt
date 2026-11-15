ENGAGE INDICATOR — READ ONLY TEST

This is a diagnostic addon for WoW Forever. It shows a green square out of combat and a red square in combat, using PLAYER_REGEN_ENABLED and PLAYER_REGEN_DISABLED. Gray means unknown. It does not cast, target, move or control the game. Being in combat does not prove Charge succeeded or identify what engaged you.

INSTALL
1. Close WoW. Copy the entire EngageIndicator folder (containing EngageIndicator.toc and EngageIndicator.lua) into your WoW Forever installation's Interface\AddOns folder, alongside your other addons. The exact WoW Forever installation folder depends on your setup; do not assume the Retail or Classic Era folder.
2. Launch WoW and enable Engage Indicator in the character-select AddOns list. The .toc uses Forever interface number 16001; if the client reports it outdated, check your version and update the interface number.
3. In game, drag the square to a visible spot where your game UI and viewer won't cover it. Test that it turns red when you enter combat and green after you leave. Its position resets on reload; put it in the same place before using the saved screen calibration.

PYTHON READER
Copy combat_signal.py next to your existing state_reader.py and calibration folder. Run from PowerShell in your scripts folder:

.\.venv\Scripts\python combat_signal.py calibrate

After pressing Enter, switch back to WoW during the countdown. In the frozen screenshot, select only the interior of the red/green square and press Enter. Then run:

.\.venv\Scripts\python combat_signal.py run

It prints combat, out_of_combat or unknown. Select a target and enter/leave combat yourself and compare the output with the indicator. Ctrl+C stops it. This does not modify the existing live viewer or controller, and it does not send game inputs.

The overlay can be hidden, occluded or stale; pixels and addon events are not guaranteed. Recalibrate if you move it or change resolution or UI scale. Validate in your actual client before using this signal to control anything.
