# Automatic UI state reader

This is an experimental observation tool. It estimates player health and combat status using the interface, records values to CSV and sends no input. It does not fight, loot, train a model, or control WoW. It captures monitor frames in memory but does not save full screenshots. Calibration stores two small images of the selected combat-border region.

Install dependencies following README.md, then from the extracted folder:

```powershell
.\.venv\Scripts\python state_reader.py calibrate
.\.venv\Scripts\python state_reader.py run
```

For another monitor, use `calibrate --monitor 2`. The tool waits five seconds after Enter before each capture. Start with a full health bar; select its entire interior (including the space where health empties), keeping the selection clear of the border, text, and other UI elements. Then select a small part of the portrait border that changes color in combat. Enter a fight and capture a combat example. Recalibrate after resolution, UI scale, interface placement, or monitor changes.

Health is estimated from the percentage of columns containing enough green pixels. It may be wrong if the bar changes color, has text or highlights, is obscured, or uses a different fill effect. Combat is classified by comparing the selected patch with the two examples, and may return `unknown`; animation, overlays, lighting and other border states can lead to incorrect results, including confident errors. Not all interfaces show combat through a stable border. Test against the actual game display over many state changes before trusting either value. Never use these estimates as the sole safety control.

The CSV contains estimated values, not verified labels. A recording of your actions is separate (`observe.py`). They have wall-clock timestamps but should not be assumed perfectly synchronized. Additional perception is needed for target identity, range, positioning, threat, cooldowns, death and loot; screen pixels for health/combat alone do not establish those facts.
