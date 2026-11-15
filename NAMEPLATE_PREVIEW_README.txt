READ-ONLY NAMEPLATE PREVIEW

Copy nameplate_preview.py next to the existing scripts and calibration folder. This is a candidate detector, not a targeting or navigation system; it does not click or move the cursor.

To check an existing screenshot:
.\.venv\Scripts\python nameplate_preview.py --image .\recording_1\frame_000096.jpg

The program opens an annotated image. Press any key while its window is focused to close it. To check the live calibrated monitor:
.\.venv\Scripts\python nameplate_preview.py

Move the preview to another monitor, or keep it clear of the area being captured. Focus the preview and press Q or Escape to quit. The preview can itself obscure the game and can introduce red/yellow artifacts. The selected monitor must match your existing calibration.

Yellow rectangles identify red horizontal pixel regions. They can include interface elements or other objects and can miss real enemies: no model understands the scene, no hostility/level/distance/line-of-sight verification is done, and the bar position is not a safe click-to-move destination. The screen margins and fixed size thresholds are tuned for a broad landscape display and may need changes for your resolution, nameplate style, scaling, or lighting. Do not send clicks based on these rectangles without further validation.
