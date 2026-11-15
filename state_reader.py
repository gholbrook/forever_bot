"""Calibrate simple pixel measurements and log observations; never sends input."""
import argparse
import csv
import json
import os
import time

import cv2
import mss
import numpy as np

CAL = 'calibration'


def shot(sct, monitor):
    return np.asarray(sct.grab(monitor))[:, :, :3].copy()


def crop(frame, rect):
    x, y, w, h = map(int, rect)
    return frame[y:y+h, x:x+w]


def choose(frame, prompt):
    print(prompt, flush=True)
    r = cv2.selectROI('Select region: Enter to confirm; Esc to cancel', frame, False, False)
    cv2.destroyAllWindows()
    if r[2] < 3 or r[3] < 3:
        raise SystemExit('Selection cancelled or too small.')
    return list(map(int, r))


def countdown(sct, monitor, message):
    input(message + '\nPress Enter, then switch to the game; capture starts in 5 seconds. ')
    for n in range(5, 0, -1):
        print(n, flush=True)
        time.sleep(1)
    return shot(sct, monitor)


def health(frame, rect):
    img = crop(frame, rect)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # OpenCV hue spans 0..179; tune for the user's interface if needed.
    mask = cv2.inRange(hsv, np.array([35, 75, 65], np.uint8), np.array([90, 255, 255], np.uint8))
    columns = (mask > 0).mean(axis=0) >= 0.30
    return float(columns.mean()), float(mask.mean() / 255)


def diff(a, b):
    return float(np.abs(a.astype(np.float32) - b.astype(np.float32)).mean() / 255)


def classify(current, calm, fight, margin=0.015, max_distance=0.20):
    d0, d1 = diff(current, calm), diff(current, fight)
    if min(d0, d1) > max_distance or abs(d0 - d1) < margin:
        return 'unknown', d0, d1
    return ('out_of_combat' if d0 < d1 else 'combat'), d0, d1


def calibrate(sct, mon, monitor_number):
    os.makedirs(CAL, exist_ok=True)
    frame = countdown(sct, mon, 'Stand safely OUT of combat with your normal UI visible.')
    bar = choose(frame, 'Select only the interior of your full player HEALTH bar, left to right. Exclude borders and text if possible.')
    border = choose(frame, 'Select a small section of the portrait BORDER that changes during combat. Exclude health and portrait art.')
    calm = crop(frame, border)
    fight_frame = countdown(sct, mon, 'Enter combat, keep the UI in the same location, and arrange for the border to remain visible.')
    fight = crop(fight_frame, border)
    separation = diff(calm, fight)
    if separation < 0.015:
        raise SystemExit('The selected border samples look almost identical. Retry using an area that visibly changes; no calibration saved.')
    cv2.imwrite(os.path.join(CAL, 'out_of_combat.png'), calm)
    cv2.imwrite(os.path.join(CAL, 'combat.png'), fight)
    with open(os.path.join(CAL, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump({'monitor': monitor_number, 'screen': mon, 'health_rect': bar, 'combat_rect': border}, f, indent=2)
    h, coverage = health(frame, bar)
    print(f'Saved calibration. Health estimate in calibration frame: {h:.0%}; combat reference separation: {separation:.3f}.')
    print('If the health estimate is not near full, repeat selecting only the colored portion of the entire bar.')


def run(sct):
    with open(os.path.join(CAL, 'config.json'), encoding='utf-8') as f:
        cfg = json.load(f)
    mon = sct.monitors[cfg['monitor']]
    if mon != cfg['screen']:
        raise SystemExit('Monitor geometry changed; recalibrate.')
    calm = cv2.imread(os.path.join(CAL, 'out_of_combat.png'))
    fight = cv2.imread(os.path.join(CAL, 'combat.png'))
    if calm is None or fight is None:
        raise SystemExit('Combat references are missing; recalibrate.')
    filename = time.strftime('state_%Y%m%d_%H%M%S.csv')
    print('Logging state to', filename, 'Press Ctrl+C to stop. No input is sent.')
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['unix_ns', 'health_fraction_estimate', 'combat_estimate', 'distance_calm', 'distance_combat', 'green_pixel_fraction'])
        try:
            while True:
                frame = shot(sct, mon)
                hp, green = health(frame, cfg['health_rect'])
                status, d0, d1 = classify(crop(frame, cfg['combat_rect']), calm, fight)
                w.writerow([time.time_ns(), f'{hp:.3f}', status, f'{d0:.4f}', f'{d1:.4f}', f'{green:.3f}'])
                f.flush()
                print(f'health~{hp:5.0%} | {status:13} | distances {d0:.3f}/{d1:.3f}', flush=True)
                time.sleep(0.5)
        except KeyboardInterrupt:
            print('\nStopped.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['calibrate', 'run'])
    p.add_argument('--monitor', type=int, default=2)
    args = p.parse_args()
    with mss.mss() as sct:
        if args.mode == 'calibrate':
            if args.monitor < 1 or args.monitor >= len(sct.monitors):
                raise SystemExit(f'Choose monitor 1..{len(sct.monitors)-1}')
            calibrate(sct, sct.monitors[args.monitor], args.monitor)
        else:
            run(sct)
