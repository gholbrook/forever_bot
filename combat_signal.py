"""Calibrate a monitor-relative rectangle around EngageIndicator's color square."""
import argparse
import json
from pathlib import Path
import time
import cv2
import mss
import numpy as np
from state_reader import choose, crop

CAL = Path('calibration')


def classify_color(frame, rect):
    img = crop(frame, rect)
    if img.size == 0:
        return 'unknown'
    # BGR: count only clearly red or clearly green pixels.
    b, g, r = [img[:, :, i].astype(np.int16) for i in range(3)]
    red = (r >= 180) & (r-g >= 100) & (r-b >= 100)
    green = (g >= 180) & (g-r >= 100) & (g-b >= 100)
    rf, gf = red.mean(), green.mean()
    if rf >= .70 and gf < .10: return 'combat'
    if gf >= .70 and rf < .10: return 'out_of_combat'
    return 'unknown'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['calibrate', 'run'])
    args = parser.parse_args()
    cfg = json.loads((CAL/'config.json').read_text(encoding='utf-8'))
    with mss.mss() as sct:
        mon = sct.monitors[cfg['monitor']]
        if mon != cfg['screen']:
            raise SystemExit('Monitor geometry differs from the existing calibration.')
        if args.mode == 'calibrate':
            input('Show the addon square in WoW. Press Enter, then return to WoW within 5 seconds. ')
            for n in range(5, 0, -1):
                print(n, flush=True); time.sleep(1)
            frame = np.asarray(sct.grab(mon))[:, :, :3].copy()
            rect = choose(frame, 'Select ONLY the inside of the addon colored square, then press Enter.')
            status = classify_color(frame, rect)
            if status == 'unknown':
                raise SystemExit('Selection is not clearly red or green. Reposition the addon and select only the square.')
            (CAL/'combat_signal.json').write_text(json.dumps({'rect':rect, 'screen':mon}, indent=2), encoding='utf-8')
            print('Saved indicator location. Current state:', status)
        else:
            indicator = json.loads((CAL/'combat_signal.json').read_text(encoding='utf-8'))
            if indicator['screen'] != mon:
                raise SystemExit('Indicator calibration does not match the monitor.')
            print('Reading addon combat indicator. Ctrl+C stops. No inputs sent.')
            try:
                while True:
                    frame = np.asarray(sct.grab(mon))[:, :, :3].copy()
                    print(classify_color(frame, indicator['rect']), flush=True)
                    time.sleep(.5)
            except KeyboardInterrupt:
                print('Stopped.')


if __name__ == '__main__':
    main()
