OBSERVATION-ONLY RECORDING

This records screen-derived state and your bound action-key attempts. It sends
no keyboard or mouse input and does not save screenshots. It uses your existing
monitor, health, rage, target, combat-indicator and signal-panel calibrations.
Keep the game and addon indicators visible. It records only while the Warcraft
window is focused. Keys typed in game chat may be recorded as action attempts;
a key attempt does not prove that an ability was cast or hit.

1. Copy record_observations.py into your wow_combat_recorder folder.
2. Open PowerShell in that folder and run:

   .\.venv\Scripts\python record_observations.py

3. In WoW, while out of combat, type /sbo start. This replaces the addon’s
   previous in-memory observation session; export that session first if needed.
4. Play normally, including whichever abilities you normally use. The existing
   Spellbook Observer records spellbook availability and cast events, including
   spells outside the main bar, once per second where the client exposes them.
5. Type /sbo stop and then /reload to write the addon data to SavedVariables.
6. Return to PowerShell and press Ctrl+C to stop the screen recorder. Note the
   observation folder name it prints. Then run:

   .\.venv\Scripts\python convert_spellbook_observer.py --find --output spellbook_session_1

Choose a different --output folder for each session to avoid overwriting.
The observation folder contains states.csv, key_attempts.csv and metadata.json.
The spellbook_session_1 folder contains the addon’s CSV files.

The addon uses a coarse absolute clock (whole seconds); the screen recorder uses
nanoseconds. These are separate files and are not automatically synchronized.
Do not treat a nearest-time match as proof of a successful cast. Availability,
range and cast events may be unknown, delayed or absent, and success does not
guarantee a hit. This is data collection, not model training or live control.
