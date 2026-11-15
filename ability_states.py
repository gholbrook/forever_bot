"""Compare ability-icon appearances in saved screenshots, not game ability usability."""
import argparse
import csv
import json
from pathlib import Path
import cv2
import numpy as np
from state_reader import choose, crop

ABILITY = [('heroic_strike','2'), ('charge','3'), ('victory_rush','0')]
CAL = Path('calibration')


def read(path):
    im = cv2.imread(str(path))
    if im is None:
        raise ValueError(f'Cannot read image: {path}')
    return im


def diff(a, b):
    if a.shape != b.shape:
        raise ValueError('Icon crop dimensions differ; use recordings from the same resolution and layout.')
    return float(np.abs(a.astype(np.float32) - b.astype(np.float32)).mean() / 255)


def frame_prompt(folder, prompt):
    while True:
        name = input(prompt + '\nFilename (for example frame_000025.jpg): ').strip().strip('"')
        path = Path(name)
        if not path.is_absolute():
            path = folder / path
        if path.is_file():
            return read(path)
        print('File not found:', path)


def calibrate(folder):
    CAL.mkdir(exist_ok=True)
    configs = {}
    expected = None
    for name, key in ABILITY:
        print(f'\n--- {name} (key {key}) ---')
        yes = frame_prompt(folder, 'Pick a screenshot where this icon LOOKS ready or bright.')
        no = frame_prompt(folder, 'Pick a screenshot where the icon LOOKS unavailable or dim.')
        if yes.shape != no.shape or (expected is not None and yes.shape != expected):
            raise ValueError('The screenshots differ in resolution; choose frames with the same layout.')
        expected = yes.shape
        rect = choose(yes, f'Select only the {name} icon interior, avoiding borders and hotkey text; press Enter.')
        a, b = crop(yes, rect), crop(no, rect)
        separation = diff(a, b)
        if separation < .015:
            raise ValueError(f'{name}: examples are too similar ({separation:.3f}). Choose visibly different screenshots and retry.')
        cv2.imwrite(str(CAL / f'{name}_bright.png'), a)
        cv2.imwrite(str(CAL / f'{name}_dim.png'), b)
        configs[name] = {'rect': rect, 'separation': separation}
        print(f'Saved {name} examples; visual difference {separation:.3f}.')
    configs['width'], configs['height'] = expected[1], expected[0]
    (CAL / 'ability_icons.json').write_text(json.dumps(configs, indent=2), encoding='utf-8')
    print('\nCalibration saved. Bright/dim is appearance, not proof an ability can be used.')


def analyze(folder):
    cfg = json.loads((CAL / 'ability_icons.json').read_text(encoding='utf-8'))
    refs = {name: (read(CAL / f'{name}_bright.png'), read(CAL / f'{name}_dim.png')) for name, _ in ABILITY}
    frames = sorted(folder.glob('frame_*.jpg'))
    if not frames:
        raise ValueError('No frame_*.jpg files found in recording folder.')
    results = {}
    for path in frames:
        frame = read(path)
        if frame.shape[:2] != (cfg['height'], cfg['width']):
            raise ValueError(f'Resolution mismatch: {path}')
        row = {'frame': path.name}
        for name, _ in ABILITY:
            img = crop(frame, cfg[name]['rect'])
            dbright, ddim = diff(img, refs[name][0]), diff(img, refs[name][1])
            # Reject both distant images and weak separations; neither is a calibrated probability.
            margin = max(.015, .15 * cfg[name]['separation'])
            appearance = 'unknown' if min(dbright, ddim) > .20 or abs(dbright-ddim) < margin else ('bright_like' if dbright < ddim else 'dim_like')
            row[f'{name}_appearance'] = appearance
            row[f'{name}_distance_bright'] = f'{dbright:.4f}'
            row[f'{name}_distance_dim'] = f'{ddim:.4f}'
        results[path.name] = row
    fields = ['frame'] + [f'{name}_{suffix}' for name, _ in ABILITY for suffix in ('appearance','distance_bright','distance_dim')]
    output = folder / 'ability_analysis.csv'
    with output.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(results.values())
    print(f'Wrote {len(results)} frames to {output}')
    replay = folder / 'decision_replay.csv'
    if replay.exists():
        output_replay = folder / 'decision_replay_with_abilities.csv'
        with replay.open(newline='', encoding='utf-8-sig') as src, output_replay.open('w', newline='', encoding='utf-8') as dst:
            reader = csv.DictReader(src)
            if not reader.fieldnames or 'state_frame' not in reader.fieldnames:
                raise ValueError('Replay missing state_frame column.')
            added = fields[1:]
            if set(added) & set(reader.fieldnames):
                raise ValueError('Replay already contains ability columns.')
            writer = csv.DictWriter(dst, fieldnames=reader.fieldnames + added)
            writer.writeheader()
            for row in reader:
                ability_row = results.get(row['state_frame'], {})
                row.update({field: ability_row.get(field, '') for field in added})
                writer.writerow(row)
        print(f'Wrote joined replay to {output_replay}')
    else:
        print('No decision_replay.csv found; ability_analysis.csv was saved without a replay join.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['calibrate','analyze'])
    parser.add_argument('recording', type=Path)
    args = parser.parse_args()
    try:
        if not args.recording.is_dir():
            raise ValueError(f'Recording folder not found: {args.recording}')
        (calibrate if args.mode == 'calibrate' else analyze)(args.recording)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'Error: {exc}\n')
