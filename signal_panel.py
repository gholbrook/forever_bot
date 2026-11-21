"""Read the EngageIndicator signal cells or preview magenta markers."""

import argparse
import json
from pathlib import Path
import time
import cv2
import mss
import numpy as np
from state_reader import choose, crop

CAL = Path('calibration')
NAMES = [
    'target',
    'hostile',
    'charge_usable',
    'charge_range',
    'overpower_usable',
    'victory_rush_usable',
    'heroic_strike_usable',
]
ALL_SIGNALS = NAMES + [
    'execute_usable',
    'shoot_gun_ready',
    'rend_ready',
    'thunder_clap_ready',
    'bloodrage_ready',
    'demoralizing_shout_ready',
    'cleave_ready',
    'elunes_light_ready',
    'battle_shout_ready',
    'pos_x',
    'pos_y',
    'target_player',
]
COORD_SIGNALS = {'pos_x', 'pos_y'}


def color_state(patch):
  if patch.size == 0:
    return 'unknown'
  b, g, r = [patch[:, :, i].astype(np.int16) for i in range(3)]
  masks = {
      'yes': (r < 80) & (g > 175) & (b < 80),
      'no': (r > 175) & (g < 80) & (b < 80),
      'unknown': (r < 80) & (g < 80) & (b > 175),
  }
  scores = {k: float(v.mean()) for k, v in masks.items()}
  label = max(scores, key=scores.get)
  return label if scores[label] >= 0.70 else 'unreadable'


def decode_coord_patch(patch) -> float | str:
  if patch.size == 0:
    return 'unreadable'
  # mss captures in BGR order; take median across the center patch to avoid edge bleed
  b, g, r = np.median(patch.reshape(-1, 3), axis=0)
  if b > 128:
    return 'unknown'
  raw_16bit = (int(round(r)) << 8) | int(round(g))
  return round((raw_16bit / 65535.0) * 100.0, 3)


def read_panel(frame, rect, cell_count=7):
  if cell_count not in (7, 8, 9, 16, 18, len(ALL_SIGNALS)):
    raise ValueError('Unsupported signal panel layout; recalibrate.')
  names = ALL_SIGNALS[:cell_count]
  layout_width = 26 * cell_count - 4
  panel = crop(frame, rect)
  h, w = panel.shape[:2]
  if h < 6 or w < 60:
    raise ValueError(
        'Signal row too small; recalibrate using the colored squares.'
    )
  states = {}
  for i, name in enumerate(names):
    cx = int(w * (i * 26 + 11) / layout_width)
    cy = h // 2
    radius = max(1, min(4, h // 5, w // 50))
    patch = panel[
        max(0, cy - radius) : cy + radius + 1,
        max(0, cx - radius) : cx + radius + 1,
    ]
    if name in COORD_SIGNALS:
      states[name] = decode_coord_patch(patch)
    else:
      states[name] = color_state(patch)
  return states


def find_markers(frame, *, selected=False):
  hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
  # Pure #FF00FF is HSV(150, 255, 255).
  # Raising value >= 150 filters out the dark purple XP bar while catching faded nameplates.
  low, high = (85, 95) if selected else (138, 165)
  saturation = 210 if selected else 135
  value = 165 if selected else 150
  mask = cv2.inRange(
      hsv,
      np.array([low, saturation, value], np.uint8),
      np.array([high, 255, 255], np.uint8),
  )

  # Ignore the top 80px (signal panel/minimap) and bottom 140px (XP bar & action bars)
  mask[:80, :] = 0
  mask[-140:, :] = 0

  n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
  boxes = []
  for x, y, w, h, area in stats[1:n]:
    if 16 <= w <= 300 and 3 <= h <= 50 and w / h >= 2.5 and area >= 20:
      boxes.append((int(x), int(y), int(w), int(h)))
  return boxes


def main():
  p = argparse.ArgumentParser(description=__doc__)
  p.add_argument('mode', choices=['calibrate', 'run', 'markers'])
  p.add_argument(
      '--legacy',
      action='store_true',
      help='Calibrate the older seven-cell addon.',
  )
  p.add_argument(
      '--shoot-panel',
      action='store_true',
      help='Calibrate the nine-cell addon with Shoot Gun.',
  )
  p.add_argument(
      '--combat-panel',
      action='store_true',
      help='Calibrate the sixteen-cell combat addon.',
  )
  p.add_argument(
      '--coord-panel',
      action='store_true',
      help='Calibrate the full eighteen-cell addon with coordinates.',
  )
  p.add_argument(
      '--target-type-panel',
      action='store_true',
      help='Calibrate the nineteen-cell addon including target type.',
  )
  args = p.parse_args()
  if sum((args.legacy, args.shoot_panel, args.combat_panel, args.coord_panel, args.target_type_panel)) > 1:
    p.error('Choose only one panel layout.')
  base = json.loads((CAL / 'config.json').read_text(encoding='utf-8'))
  with mss.mss() as capture:
    monitor = capture.monitors[base['monitor']]
    if monitor != base['screen']:
      raise SystemExit(
          'Monitor geometry changed; recalibrate on the current monitor.'
      )
    if args.mode == 'calibrate':
      input(
          'Make all addon squares visible. Press Enter, then return to WoW'
          ' within 5 seconds. '
      )
      for n in range(5, 0, -1):
        print(n, flush=True)
        time.sleep(1)
      frame = np.asarray(capture.grab(monitor))[:, :, :3].copy()
      rect = choose(
          frame,
          'Select exactly the colored row, from first square left edge to last'
          ' square right edge; exclude labels. Press Enter.',
      )
      if args.target_type_panel:
        cell_count = len(ALL_SIGNALS)
      elif args.coord_panel:
        cell_count = 18
      elif args.combat_panel:
        cell_count = 16
      elif args.shoot_panel:
        cell_count = 9
      elif args.legacy:
        cell_count = 7
      else:
        cell_count = 8
      states = read_panel(frame, rect, cell_count)
      if 'unreadable' in states.values():
        raise SystemExit(
            f'Some squares could not be read: {states}. Please select only the'
            ' colored row and retry.'
        )
      (CAL / 'signal_panel.json').write_text(
          json.dumps(
              {'rect': rect, 'screen': monitor, 'cell_count': cell_count},
              indent=2,
          ),
          encoding='utf-8',
      )
      print('Saved. Current readings:', states)
    elif args.mode == 'run':
      cfg = json.loads((CAL / 'signal_panel.json').read_text(encoding='utf-8'))
      if cfg['screen'] != monitor:
        raise SystemExit('Screen changed since signal calibration.')
      print(
          'Read-only signal states; Ctrl+C exits. yes/no/unknown do not imply'
          ' safe action.'
      )
      try:
        while True:
          frame = np.asarray(capture.grab(monitor))[:, :, :3].copy()
          print(
              ' | '.join(
                  f'{k}={v}'
                  for k, v in read_panel(
                      frame, cfg['rect'], cfg.get('cell_count', 7)
                  ).items()
              ),
              flush=True,
          )
          time.sleep(0.5)
      except KeyboardInterrupt:
        print('Stopped.')
    else:
      cv2.namedWindow('Magenta markers', cv2.WINDOW_NORMAL)
      cv2.resizeWindow('Magenta markers', 1000, 400)
      print(
          'Read-only marker preview. Focus preview and press Q or Esc to quit.'
      )
      try:
        while True:
          frame = np.asarray(capture.grab(monitor))[:, :, :3].copy()
          boxes = find_markers(frame)
          for x, y, w, h in boxes:
            cv2.rectangle(
                frame, (x - 3, y - 3), (x + w + 3, y + h + 3), (0, 255, 255), 2
            )
          cv2.putText(
              frame,
              f'{len(boxes)} magenta candidates; Q quits',
              (15, 30),
              cv2.FONT_HERSHEY_SIMPLEX,
              0.7,
              (0, 255, 255),
              2,
          )
          cv2.imshow('Magenta markers', frame)
          if cv2.waitKey(1) & 0xFF in (27, ord('q')):
            break
          time.sleep(0.25)
      finally:
        cv2.destroyAllWindows()


if __name__ == '__main__':
  main()
