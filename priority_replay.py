"""Offline appearance-based priority experiment. Never controls the game."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
import cv2
from state_reader import choose, crop
from ability_states import read, diff, frame_prompt

CAL = Path('calibration')


def calibrate(folder):
    config = json.loads((CAL / 'ability_icons.json').read_text(encoding='utf-8'))
    print('Pick examples of Overpower (key 7). Existing calibrations will be preserved.')
    bright = frame_prompt(folder, 'Choose a frame where Overpower LOOKS bright or ready.')
    dim = frame_prompt(folder, 'Choose a frame where Overpower LOOKS dim or unavailable.')
    shape = (config['height'], config['width'])
    if bright.shape[:2] != shape or dim.shape[:2] != shape:
        raise ValueError('Frame resolution differs from the existing ability calibration.')
    rect = choose(bright, 'Select the inside of the Overpower icon (key 7), avoiding the border and key text. Press Enter.')
    a, b = crop(bright, rect), crop(dim, rect)
    separation = diff(a, b)
    if separation < .015:
        raise ValueError('Overpower examples look too similar. Retry with visibly different examples.')
    # Store separately so a failed or repeated calibration leaves existing icons untouched.
    if not cv2.imwrite(str(CAL / 'overpower_bright.png'), a) or not cv2.imwrite(str(CAL / 'overpower_dim.png'), b):
        raise OSError('Could not save Overpower reference images.')
    (CAL / 'overpower_icon.json').write_text(json.dumps({'rect': rect, 'separation': separation, 'width': shape[1], 'height': shape[0]}, indent=2), encoding='utf-8')
    print(f'Overpower calibration saved; visual difference {separation:.3f}.')


def classify(img, a, b, separation):
    da, db = diff(img, a), diff(img, b)
    margin = max(.015, .15 * separation)
    result = 'unknown' if min(da, db) > .20 or abs(da-db) < margin else ('bright_like' if da < db else 'dim_like')
    return result, da, db


def priority(row):
    if row.get('combat_estimate') != 'combat' or row.get('target_presence_estimate') != 'present':
        return 'wait', 'Combat or target is absent or uncertain.'
    for name, key in [('overpower', '7'), ('victory_rush', '0'), ('heroic_strike', '2')]:
        value = row.get(name + '_appearance', '')
        if value == 'unknown' or value == '':
            return 'wait', f'{name} appearance is uncertain.'
        if value == 'bright_like':
            return name, f'First bright-looking icon in priority order; key {key}.'
        if value != 'dim_like':
            return 'wait', f'Unexpected {name} appearance.'
    return 'wait', 'All priority icons look dim.'


def analyze(folder):
    cfg = json.loads((CAL / 'overpower_icon.json').read_text(encoding='utf-8'))
    a, b = read(CAL / 'overpower_bright.png'), read(CAL / 'overpower_dim.png')
    abilities = folder / 'ability_analysis.csv'
    replay = folder / 'decision_replay_with_abilities.csv'
    if not abilities.exists() or not replay.exists():
        raise ValueError('Missing ability_analysis.csv or decision_replay_with_abilities.csv. Run the previous ability analysis first.')
    by_frame = {}
    with abilities.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if not {'frame','heroic_strike_appearance','victory_rush_appearance'} <= set(reader.fieldnames or []):
            raise ValueError('Ability analysis missing required columns.')
        for row in reader:
            by_frame[row['frame']] = row
    source_rows = []
    with replay.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        required = {'state_frame','observed_action','combat_estimate','target_presence_estimate','heroic_strike_appearance','victory_rush_appearance'}
        if not required <= set(reader.fieldnames or []):
            raise ValueError('Replay missing required columns: ' + ', '.join(sorted(required - set(reader.fieldnames or []))))
        old_fields = reader.fieldnames
        source_rows = list(reader)
    new = ['overpower_appearance','overpower_distance_bright','overpower_distance_dim','priority_recommendation','priority_reason']
    if set(old_fields) & set(new):
        raise ValueError('Input replay already contains priority columns; use the original replay.')
    output = folder / 'priority_replay.csv'
    cache = {}
    counts = Counter()
    with output.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=old_fields+new); writer.writeheader()
        for row in source_rows:
            name = row.get('state_frame','')
            if name not in cache:
                path = folder / name
                if not name or name not in by_frame or not path.is_file():
                    cache[name] = ('unknown', '', '')
                else:
                    frame = read(path)
                    if frame.shape[:2] != (cfg['height'], cfg['width']):
                        raise ValueError(f'Frame resolution mismatch: {path}')
                    status, d1, d2 = classify(crop(frame, cfg['rect']), a, b, cfg['separation'])
                    cache[name] = (status, f'{d1:.4f}', f'{d2:.4f}')
            row['overpower_appearance'], row['overpower_distance_bright'], row['overpower_distance_dim'] = cache[name]
            # Trust neither the joined replay nor file ordering for appearance; use same-frame CSV.
            for ability in ('victory_rush','heroic_strike'):
                row[ability+'_appearance'] = by_frame.get(name, {}).get(ability+'_appearance','unknown')
            row['priority_recommendation'], row['priority_reason'] = priority(row)
            counts[row['priority_recommendation']] += 1
            writer.writerow(row)
    print(f'Saved {len(source_rows)} offline rows to {output}; recommendations: {dict(counts)}')
    print('Recommendations are inferred from appearance only, not confirmed usability. No inputs were sent.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['calibrate','analyze'])
    p.add_argument('recording', type=Path)
    args = p.parse_args()
    try:
        if not args.recording.is_dir():
            raise ValueError(f'Recording folder not found: {args.recording}')
        (calibrate if args.mode == 'calibrate' else analyze)(args.recording)
    except (OSError, ValueError, KeyError) as exc:
        p.exit(1, f'Error: {exc}\n')
