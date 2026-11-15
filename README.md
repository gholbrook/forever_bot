# WoW demonstration recorder: first development step

This Windows starter records a manually played combat session so a future vision and decision model can be trained and tested on your interface. It captures screenshots plus the specific movement, targeting, action-bar keys, and right clicks used in the agreed setup. It does not control the game, detect health or targets, make decisions, or loot. No model training or live bot is included yet.

## Setup

Open PowerShell in this folder. Install Python 3.10 or later from python.org if `py` is unavailable, then run:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python observe.py
```

The default records monitor 1, twice per second. To choose another monitor or higher capture frequency:

```powershell
.\.venv\Scripts\python observe.py --monitor 2 --fps 5
```

Go to a simple, safe area in-game and play normally: target, approach, fight, right-click the corpse, then use your `=` recovery macro when appropriate. Press **F8** to stop recording. The program creates a timestamped folder with JPEG frames, `events.csv` containing wall-clock nanosecond timestamps, and `metadata.json`. Screenshots cover the entire selected monitor; captured right-click coordinates are desktop coordinates. Keep other private windows off that monitor, and stop recording before entering sensitive information. Only the listed keys are recorded, but screenshots can include anything on the screen.

Timing is approximate: screenshots and key events are timestamped independently and input-to-image latency is not measured. Keys other than WASDQE, Tab, 1-0, minus, and equals are not recorded. Mouse movement and left clicks are not captured, so camera steering and left-click targeting demonstrations are incomplete. Right-click positions are recorded, but the program cannot tell loot from other right clicks. Recording is not restricted to WoW when it loses focus. No data is uploaded by this program.

## Next steps

Collect several short sessions including successful fights, low-health recovery, target failures, and corpse looting. Inspect the captures. Then label player health, target state, combat status, enemies and lootable corpses, and evaluate on separate sessions. A live controller needs reliable perception, window-focus checks, an emergency stop, and tested interaction and recovery logic; no such controller is provided here. The `=` macro is assumed to restore full health out of combat, but actual restoration must be observed, not inferred from the key press.
