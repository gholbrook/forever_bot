1. Put replay.py in the same folder as state_reader.py.
2. Check your recording folder contains events.csv, state_analysis.csv and extra_state_analysis.csv, produced by the previous steps.
3. In PowerShell, replace the example folder with your actual recording folder:

.\.venv\Scripts\python replay.py .\recording_FOLDER

Open recording_FOLDER\decision_replay.csv in Excel or a text editor. Each row is a recorded key-down or right-click, joined to the latest previously captured frame, not a later frame. It includes the age of that frame in milliseconds, your observed input, estimated state, and a simple rule-based recommendation. Right-click may not be loot. Repeated key-down events may reflect key repeat, and inputs may have failed in the game. Actions before the first frame and observations over one second old are preserved with an abstention. Unknown states are not filled in.

The only concrete baseline recommendation is recovery when out of combat and below 90% health. This is an arbitrary initial threshold to inspect, not trained Laya or proof that recovery was possible. In combat and most other cases the tool deliberately abstains because it cannot see range, cooldowns, enemies, loot, or threats. It does not replay inputs, play video, control the game, or produce a trained model. Input timestamps and screenshots have capture latency, and frame capture is not exact, so inspect examples before using this data for training.
