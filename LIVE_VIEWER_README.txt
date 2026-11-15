LIVE SUPERVISED VIEWER — READ ONLY

This reads your monitor and displays estimates plus the Overpower > Victory Rush > Heroic Strike priority. It never presses keys, clicks, moves your character, takes control, saves screenshots, or trains a model. It does not implement enemy search, engaging, movement, recovery, death detection, or looting. Continue playing yourself.

SETUP
Put live_viewer.py in the same folder as your existing state_reader.py, extra_state.py, ability_states.py, priority_replay.py, .venv, and calibration folder. It uses the same packages already installed. Your existing calibrations must include health/combat, target/rage, ability icons, and Overpower. Use the same monitor, resolution, UI scale and positions you calibrated.

Run in PowerShell from that folder:

.\.venv\Scripts\python live_viewer.py

It updates roughly twice per second. Use WoW in windowed or borderless-windowed mode if its full-screen mode hides the viewer. Move the viewer so it does not cover ANY calibrated health, rage, target, combat-border or ability-icon region. If you have a second monitor, place it there. Anything covering those screen regions will corrupt readings. Stop by clicking Stop viewer or closing the window.

HOW TO CHECK
Compare the on-screen health, rage, combat, target and icon appearance readings against the game as you play. It says wait when combat or target is uncertain, an earlier-priority icon is unknown, or no icon resembles the bright reference. Out-of-combat engagement and recovery are not implemented. It may also wait even when a target is selected because the target classifier is imperfect. The viewer reports image appearance, not verified ability usability. If the display differs, stop and inspect calibration; do not trust or act on the recommendation blindly.

LIMITS
This is an unvalidated prototype. A bright icon may be out of range, wrong stance, unavailable, or on cooldown; the reader does not verify hostile target, cooldowns, proc, range, rage costs or threat. Health and combat can be wrong. It may show a stale value during UI/capture delays. This viewer is not a safe autonomous bot and does not interact with the game. When capture fails it stops updating and displays the error.
