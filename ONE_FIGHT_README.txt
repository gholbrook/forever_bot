ONE-FIGHT CONTROL EXPERIMENT — WINDOWS

This is an experimental single-fight controller using the existing read-only viewer's pixel estimates. It does not select or approach enemies, navigate, loot, use recovery, or find additional fights. It cannot determine target hostility, range, line of sight, stance, cooldowns, adds, or cliff safety. Bright-looking icons are not proof of usability; any of the readings can be wrong. No part guarantees survival. Account enforcement for game automation is possible.

Put one_fight.py beside live_viewer.py, target_examples.py, state_reader.py, ability_states.py, priority_replay.py, your .venv, and your calibration folder. Install dependencies from the original setup. Use the same monitor, resolution, layout and UI scale used for calibration. Close the viewer or position it away from all calibrated screen regions, so it does not obstruct capture.

BEFORE EACH TEST: select one ordinary hostile enemy yourself, stand within melee range, start at full health and out of combat, and stay at the keyboard. F8 stops the test; F7 starts it when the game window is foreground. It starts auto-attack once (key 1) and only attempts Overpower (7), Victory Rush (0), or Heroic Strike (2), using the existing read-only priority logic. It stops on focus loss, uncertain combat/target readings, low estimated health, near-zero/missing target health, combat ending, no combat after eight seconds, or 30 seconds elapsed. Each input is a short press/release; it never holds movement keys. F8 is monitored by a separate listener, but OS privileges, crashes or interruption can prevent hotkeys from working. Confirm F8 works in a dry run. Do not rely on this as protection from death.

1) Dry run first; no inputs are sent. Open PowerShell in the scripts folder and run:

.\.venv\Scripts\python one_fight.py

Select the enemy, focus WoW and press F7. Press the game's keys yourself during the dry run to create combat. The console prints WOULD PRESS. Press F8 to check emergency stop, then review readings. If you cannot start, the foreground window title may not contain "Warcraft"; pass --window-title followed by a distinctive part of its actual title in quotes.

2) Only after observing a successful dry run, launch the one-fight experiment with:

.\.venv\Scripts\python one_fight.py --live

Focus WoW and press F7. Remain at the keyboard. It will stop after one fight and will not loot.

Options: --window-title "part of title", --stop-health 0.65, --min-start-health 0.95, --max-seconds 20, --rage-saturation 150. Stop-health is a threshold for a noisy pixel estimate, not verified actual health. Ability attempts default to at least 1.5 seconds apart. A game may ignore synthesized input; this script does not bypass anti-cheat, detect failed actions, or prove an ability landed. When starting F7, the current foreground window must match the title, and its exact window handle must remain in the foreground. F7/F8 are global hotkeys while running.
