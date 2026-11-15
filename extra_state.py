"""Calibrate and analyze rage, target presence, and target health from saved frames."""
import argparse
import csv
import json
from pathlib import Path
import cv2
import numpy as np
from state_reader import choose, crop, health, classify


def read(path):
    image = cv2.imread(str(path))
    if image is None:
        raise SystemExit(f'Cannot read image: {path}')
    return image


def rage(frame, rect):
    hsv = cv2.cvtColor(crop(frame, rect), cv2.COLOR_BGR2HSV)
    # Rage is red, wrapping around both ends of OpenCV's hue scale.
    a = cv2.inRange(hsv, np.array([0, 75, 55], np.uint8), np.array([10, 255, 255], np.uint8))
    b = cv2.inRange(hsv, np.array([170, 75, 55], np.uint8), np.array([179, 255, 255], np.uint8))
    columns = ((a | b) > 0).mean(axis=0) >= .30
    return float(columns.mean())


def calibrate(args):
    visible, empty = read(args.target), read(args.no_target)
    if visible.shape != empty.shape:
        raise SystemExit('Calibration images differ in resolution.')
    rage_rect = choose(visible, 'Select the WHOLE rage-bar interior, including the empty part, and press Enter.')
    target_hp_rect = choose(visible, 'Select the WHOLE target health-bar interior with a target selected, and press Enter.')
    target_rect = choose(visible, 'Select a small static target-frame border, avoiding text, portrait and bars. Press Enter.')
    yes, no = crop(visible, target_rect), crop(empty, target_rect)
    distance = float(np.abs(yes.astype(np.float32) - no.astype(np.float32)).mean() / 255)
    if distance < .015:
        raise SystemExit('Target and no-target samples are too similar. Choose a different border patch.')
    folder = Path('calibration')
    folder.mkdir(exist_ok=True)
    cv2.imwrite(str(folder / 'target_present.png'), yes)
    cv2.imwrite(str(folder / 'target_absent.png'), no)
    (folder / 'extra.json').write_text(json.dumps({'rage_rect': rage_rect, 'target_health_rect': target_hp_rect, 'target_rect': target_rect, 'width': visible.shape[1], 'height': visible.shape[0]}, indent=2), encoding='utf-8')
    print(f'Saved additional calibration. Target sample difference: {distance:.3f}.')
    print('Rage estimate on selected frame:', f'{rage(visible, rage_rect):.0%}')
    print('Target health estimate on selected frame:', f'{health(visible, target_hp_rect)[0]:.0%}')


def analyze(args):
    folder = Path('calibration')
    cfg = json.loads((folder / 'extra.json').read_text(encoding='utf-8'))
    yes, no = read(folder / 'target_present.png'), read(folder / 'target_absent.png')
    recording = Path(args.recording)
    frames = sorted(recording.glob('frame_*.jpg'))
    if not frames:
        raise SystemExit('No frame_*.jpg files found in recording folder.')
    times = {}
    events = recording / 'events.csv'
    if events.exists():
        with events.open(newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row.get('type') == 'frame':
                    times[row['value']] = row['unix_ns']
    output = recording / 'extra_state_analysis.csv'
    with output.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['frame','unix_ns','rage_fraction_estimate','target_presence_estimate','target_health_fraction_estimate','distance_absent','distance_present'])
        for path in frames:
            frame = read(path)
            if frame.shape[:2] != (cfg['height'], cfg['width']):
                raise SystemExit(f'Resolution mismatch at {path}; output incomplete.')
            state, d0, d1 = classify(crop(frame, cfg['target_rect']), no, yes)
            status = {'out_of_combat': 'absent', 'combat': 'present', 'unknown': 'unknown'}[state]
            target_hp = f'{health(frame, cfg["target_health_rect"])[0]:.3f}' if status == 'present' else ''
            writer.writerow([path.name, times.get(path.name, ''), f'{rage(frame, cfg["rage_rect"]):.3f}', status, target_hp, f'{d0:.4f}', f'{d1:.4f}'])
    print(f'Wrote {len(frames)} rows to {output}. Estimates need checking against screenshots.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest='mode', required=True)
    c = subs.add_parser('calibrate')
    c.add_argument('target', help='Screenshot with an enemy targeted')
    c.add_argument('no_target', help='Screenshot without a target')
    a = subs.add_parser('analyze')
    a.add_argument('recording', help='Folder of recorded screenshots')
    args = p.parse_args()
    (calibrate if args.mode == 'calibrate' else analyze)(args)
