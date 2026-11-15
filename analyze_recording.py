"""Apply a saved state_reader calibration to frames captured by observe.py."""
import argparse
import csv
import json
import os
from pathlib import Path

import cv2
from state_reader import health, classify, crop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path, help='Directory containing frame_*.jpg and events.csv')
    parser.add_argument('--calibration', type=Path, default=Path('calibration'))
    parser.add_argument('--output', type=Path, default=None)
    args = parser.parse_args()
    with (args.calibration / 'config.json').open(encoding='utf-8') as f:
        cfg = json.load(f)
    calm = cv2.imread(str(args.calibration / 'out_of_combat.png'))
    fight = cv2.imread(str(args.calibration / 'combat.png'))
    if calm is None or fight is None:
        raise SystemExit('Missing combat reference images; check --calibration.')
    events = args.recording / 'events.csv'
    timestamps = {}
    if events.exists():
        with events.open(newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row.get('type') == 'frame':
                    timestamps[row['value']] = row['unix_ns']
    frames = sorted(args.recording.glob('frame_*.jpg'))
    if not frames:
        raise SystemExit(f'No frame_*.jpg files in {args.recording}')
    output = args.output or args.recording / 'state_analysis.csv'
    screen = cfg['screen']
    expected = (screen['width'], screen['height'])
    with output.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['frame', 'unix_ns', 'health_fraction_estimate', 'combat_estimate', 'distance_calm', 'distance_combat', 'green_pixel_fraction'])
        for path in frames:
            frame = cv2.imread(str(path))
            if frame is None:
                raise SystemExit(f'Could not read {path}; output is incomplete.')
            if (frame.shape[1], frame.shape[0]) != expected:
                raise SystemExit(f'Frame {path.name} is {frame.shape[1]}x{frame.shape[0]}, calibration expects {expected[0]}x{expected[1]}; output is incomplete.')
            hp, green = health(frame, cfg['health_rect'])
            current = crop(frame, cfg['combat_rect'])
            if current.shape != calm.shape or fight.shape != calm.shape:
                raise SystemExit('Combat crop size mismatch. Check the calibration and original recording.')
            state, d0, d1 = classify(current, calm, fight)
            writer.writerow([path.name, timestamps.get(path.name, ''), f'{hp:.3f}', state, f'{d0:.4f}', f'{d1:.4f}', f'{green:.3f}'])
    print(f'Analyzed {len(frames)} frames. Saved {output}')
    print('Results are unverified estimates. Blank timestamps mean no matching frame entry in events.csv.')


if __name__ == '__main__':
    main()
