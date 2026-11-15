TARGET FRAME IMPROVEMENT — READ ONLY

Put target_examples.py and the updated live_viewer.py beside your other scripts. Existing calibrations and the strict rage reader are preserved. The viewer compares the target-frame patch with multiple examples and reports present, absent, or unknown. It does not determine whether a selected target is hostile or alive.

You identified these three screenshots as having an enemy selected. From PowerShell in your scripts folder, add them as examples:

.\.venv\Scripts\python target_examples.py add present .\recording_1\frame_000096.jpg .\recording_1\frame_000115.jpg .\recording_1\frame_000211.jpg

The script saves only small crops of the already calibrated target rectangle; it leaves the original screenshots and calibration unchanged. If you later want to add examples with NO target selected, use `add absent` followed by their image paths. Be certain of each label.

Restart the viewer with:

.\.venv\Scripts\python live_viewer.py

Check it while selecting and clearing targets, including on different backgrounds. To check screenshots without adding them, run:

.\.venv\Scripts\python target_examples.py check .\recording_1\frame_000120.jpg

Replace the example filename with an existing frame you did NOT use for calibration. Testing on calibration images themselves only confirms that they match their own saved crops. A nearest-example classifier can still confidently misclassify a different scene, and a small target-border patch is not proof of hostility, target life, or range. If it is inconsistent, leave the live viewer read-only and collect different examples. Target references are loaded when the viewer starts; restart after adding any examples. No keys or clicks are sent.
