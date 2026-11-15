"""Add and evaluate target-frame samples for the read-only live viewer."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
from state_reader import crop

CAL = Path('calibration')


def load_examples():
    refs = {}
    for label in ('present', 'absent'):
        paths = [CAL / f'target_{label}.png'] + sorted((CAL / 'target_examples' / label).glob('*.png'))
        refs[label] = []
        for p in paths:
            img = cv2.imread(str(p))
            if img is None:
                raise ValueError(f'Cannot load target reference: {p}')
            refs[label].append(img)
    return refs


def choose_label(dp, da, max_distance=.20, margin=.015):
    if min(dp, da) > max_distance or abs(dp-da) < margin:
        return 'unknown'
    return 'present' if dp < da else 'absent'


def classify_target(img, refs):
    ds = {}
    for label in ('present', 'absent'):
        if not refs[label]:
            raise ValueError(f'No {label} target references found.')
        distances = []
        for sample in refs[label]:
            if sample.shape != img.shape:
                raise ValueError('Target reference dimensions differ; recalibrate target region and examples.')
            distances.append(float(np.abs(img.astype(np.float32) - sample.astype(np.float32)).mean() / 255))
        ds[label] = min(distances)
    return choose_label(ds['present'], ds['absent']), ds['present'], ds['absent']


def load_crop(path, cfg):
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f'Cannot open {path}')
    if image.shape[:2] != (cfg['height'], cfg['width']):
        raise ValueError(f'{path}: resolution differs from calibration.')
    patch = crop(image, cfg['target_rect'])
    if not patch.size:
        raise ValueError('Target rectangle outside screenshot; recalibrate.')
    return patch


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode', required=True)
    a = sub.add_parser('add', help='Add manually verified selected or unselected screenshots')
    a.add_argument('label', choices=['present','absent'])
    a.add_argument('images', nargs='+', type=Path)
    t = sub.add_parser('check', help='Check screenshots without adding them')
    t.add_argument('images', nargs='+', type=Path)
    args = p.parse_args()
    cfg = json.loads((CAL / 'extra.json').read_text(encoding='utf-8'))
    if args.mode == 'add':
        dest = CAL / 'target_examples' / args.label
        dest.mkdir(parents=True, exist_ok=True)
        for path in args.images:
            patch = load_crop(path, cfg)
            # Derive a stable per-source ID without overwriting files from other directories.
            import hashlib
            ident = hashlib.sha256(str(path.resolve()).encode('utf-8')).hexdigest()[:12]
            output = dest / f'{ident}_{path.stem}.png'
            if not cv2.imwrite(str(output), patch):
                raise OSError(f'Could not write {output}')
            print(f'Added {args.label}: {path.name}')
        print('Only cropped target-frame examples were saved; original calibration is unchanged.')
    else:
        refs = load_examples()
        for path in args.images:
            label, dp, da = classify_target(load_crop(path, cfg), refs)
            print(f'{path.name}: {label} (distance to present {dp:.4f}, absent {da:.4f})')
        print('Examples used for calibration are not independent tests; validate on different frames.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f'Error: {exc}')
