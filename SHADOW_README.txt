Laya combat shadow mode

Use the existing Laya Python environment and the combat checkpoint folder:

  .\.venv-laya\Scripts\python laya_combat_pilot\shadow_combat.py --checkpoint combat_training_run\checkpoint --recorder-folder C:\Users\utahb\Downloads\wow_combat_recorder

This launches the manual recorder. Start Spellbook Observer with /sbo start
and play normally. When done, use /sbo stop and /reload in WoW, then press
Ctrl+C in PowerShell. Export as manual_spellbook_7 to pair the reported
casts with the new observation_shadow folder. The shadow runner issues
no game inputs.

Install the included EngageIndicator addon and updated recorder scripts.
After /reload, calibrate from the recorder folder with:

  .\.venv\Scripts\python signal_panel.py calibrate --combat-panel

Select the entire row of sixteen squares, from T through BS. Keep the
separate combat-indicator calibration.

The CSV includes the raw model choice and the filtered decision on each
readable combat frame with an attackable target. The filtered decision is
wait when the corresponding live readiness signal is red or unreadable.
Green is an addon readiness check. It cannot guarantee the cast will land.
The offline training run used richer SBO samples. Wait is applied by the
runner because the current model was trained on cast moments.
