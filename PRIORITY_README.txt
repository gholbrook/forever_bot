OFFLINE PRIORITY REPLAY

Put priority_replay.py next to your existing state_reader.py, ability_states.py, and calibration folder. This preserves your existing calibrations. The recording folder should already contain ability_analysis.csv and decision_replay_with_abilities.csv.

Choose two frames from the recording: one where Overpower (key 7) looks bright, and one where it looks dim. From PowerShell in your scripts folder, replacing the folder name below:

.\.venv\Scripts\python priority_replay.py calibrate .\recording_FOLDER

Enter the two frame filenames when prompted. Select only the interior of the Overpower icon and press Enter. Then run:

.\.venv\Scripts\python priority_replay.py analyze .\recording_FOLDER

It creates priority_replay.csv in that folder. Compare priority_recommendation to observed_action. It chooses the first bright-looking icon in this order: Overpower, Victory Rush, Heroic Strike. It waits if combat/target is not confidently detected, a higher-priority icon is unknown, or all icons are dim. No action is sent to the game.

LIMITS: These are icon-appearance comparisons, not true ability-availability checks. Bright may be out of range, in the wrong stance, on cooldown or unusable; dim may be global cooldown or another transient effect. Player health, target hostility, rage, range, threat, movement and death are not sufficiently verified. It must not be used to control the game without additional safeguards and validation. Screenshots and input times have latency. A recommendation is not proof an action succeeded.
