ABILITY ICON EXPERIMENT (offline only)

Put ability_states.py beside state_reader.py and the calibration folder. This tool uses existing OpenCV and numpy dependencies. It does not alter or control the game.

1. Look through your recording and note two screenshot filenames for EACH of Heroic Strike (2), Charge (3) and Victory Rush (0): one where the icon looks bright/ready and one where it looks dim/unavailable. You may reuse images. If you cannot find a visibly different pair for an ability, the experiment cannot yet calibrate it; collect a short recording showing both. Keep the same monitor and UI layout. The examples are a one-time selection, not labels for every frame.

2. In PowerShell in the scripts folder, replacing recording_FOLDER with your recording's actual folder name:

.\.venv\Scripts\python ability_states.py calibrate .\recording_FOLDER

For each ability, enter the two filenames when requested. Draw a box around the actual icon in the screenshot, avoiding surrounding borders and hotkey text, and press Enter. It saves reference crops in calibration and does not overwrite the existing health/combat calibration.

3. Run:

.\.venv\Scripts\python ability_states.py analyze .\recording_FOLDER

This writes ability_analysis.csv and, if decision_replay.csv exists, a separate decision_replay_with_abilities.csv. It joins icons to the replay's PRE-INPUT state_frame, not a later frame. Existing CSVs are not overwritten except these two output filenames when rerun.

IMPORTANT: bright_like and dim_like mean visual resemblance to your two screenshots, not guaranteed ability availability. Global cooldown shading, range tint, key overlays, lack of resources, stance, proc, another target, flashing animations, or interface changes can cause mistakes. Unknown means inconclusive but confident-looking classifications may also be wrong. Compare a sample with screenshots. The tool cannot distinguish the reason an icon is dim, detect range reliably, confirm actions succeeded, or identify a cooldown from a single example. Do not use it to drive a bot without further validation.
