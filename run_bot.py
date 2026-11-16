from collections import deque
import json
import math
from pathlib import Path
import time

import joblib
import mss
import numpy as np
import pydirectinput
from pynput import keyboard
import torch
import torch.nn as nn

from live_viewer import configure_combat_indicator, load_calibrations, view_state
from one_fight import foreground
from signal_panel import ALL_SIGNALS, find_markers, read_panel

# --- CONFIGURATION ---
WINDOW_TITLE = 'Warcraft'
LOOP_INTERVAL = 0.20  # 5 Hz matching your training data
MAX_RADIUS = 300.5  # Map units allowed from starting spot before turning back
STUCK_SECONDS = 2.0  # Trigger unstuck if moving forward without progress
HOLD_THRESHOLD = 0.40  # Lowered slightly from 0.50 so shorter datasets trigger movement
TAP_THRESHOLD = 0.45  # Lowered slightly from 0.55 so abilities trigger reliably
TAP_COOLDOWN = 0.35  # Minimum seconds between tapping the same ability

HOLD_KEYMAP = {
    'forward': 'w',
    'backward': 's',
    'turn_left': 'a',
    'turn_right': 'd',
    'strafe_left': 'q',
    'strafe_right': 'e',
}

TAP_KEYMAP = {
    'target_tab': ('tab', False),
    'jump': ('space', False),
    'auto_attack': ('1', False),
    'heroic_strike': ('2', False),
    'charge': ('3', False),
    'thunder_clap': ('4', False),
    'rend': ('5', False),
    'hamstring': ('6', False),
    'overpower': ('7', False),
    'cleave': ('8', False),
    'slam': ('9', False),
    'victory_rush': ('0', False),
    'sunder_armor': ('-', False),
    'execute': ('=', False),
    'shadowmeld': ('1', True),
    'battle_shout': ('2', True),
    'elunes_light': ('3', True),
    'bloodrage': ('4', True),
    'demoralizing_shout': ('5', True),
    'mocking_blow': ('6', True),
    'shield_bash': ('7', True),
    'retaliation': ('8', True),
    'intimidating_shout': ('9', True),
    'shoot_gun': ('0', True),
    'recover': ('=', True),
}


class WarriorPolicyNet(nn.Module):

  def __init__(self, in_dim, out_dim):
    super().__init__()
    self.net = nn.Sequential(
        nn.Linear(in_dim, 256),
        nn.LayerNorm(256),
        nn.SiLU(),
        nn.Dropout(0.15),
        nn.Linear(256, 256),
        nn.LayerNorm(256),
        nn.SiLU(),
        nn.Dropout(0.15),
        nn.Linear(256, out_dim),
    )

  def forward(self, x):
    return self.net(x)


def encode_signal(val):
  if val == 'yes':
    return 1.0
  if val == 'no':
    return 0.0
  return -1.0


def parse_boxes(boxes):
  if not boxes:
    return 0.0, 0.5, 0.5, 0.0
  # b is (x, y, w, h) -> sort by box area (w * h)
  largest = max(boxes, key=lambda b: b[2] * b[3])
  x, y, w, h = largest
  return (
      float(len(boxes)),
      (x + w / 2.0) / 1920.0,
      (y + h / 2.0) / 1080.0,
      w / 1920.0,
  )


def press_tap(key, shift=False, act_name=''):
  label = f'Shift+{key}' if shift else key
  print(f'[KEY TAP]  {act_name} -> {label}', flush=True)
  if shift:
    pydirectinput.keyDown('shift')
    time.sleep(0.02)
  pydirectinput.press(key)
  if shift:
    time.sleep(0.02)
    pydirectinput.keyUp('shift')


def release_all_holds(currently_held):
  for key in list(currently_held):
    print(f'[KEY UP]   {key}', flush=True)
    pydirectinput.keyUp(key)
  currently_held.clear()


def run_unstuck(currently_held):
  print('[SAFETY] Obstacle detected! Running unstuck maneuver...', flush=True)
  release_all_holds(currently_held)
  pydirectinput.keyDown('s')
  time.sleep(0.35)
  pydirectinput.keyUp('s')
  pydirectinput.press('space')
  pydirectinput.keyDown('d')
  pydirectinput.keyDown('e')
  time.sleep(0.65)
  pydirectinput.keyUp('e')
  pydirectinput.keyUp('d')


def main():
  pydirectinput.PAUSE = 0.0
  meta = joblib.load('policy_meta.joblib')
  scaler = meta['scaler']
  feature_cols = meta['features']
  action_cols = [c.replace('act_', '') for c in meta['actions']]

  device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
  model = WarriorPolicyNet(len(feature_cols), len(action_cols)).to(device)
  model.load_state_dict(torch.load('warrior_policy.pt', map_location=device))
  model.eval()

  cfg = load_calibrations()
  configure_combat_indicator(cfg)
  panel = json.loads(
      Path('calibration/signal_panel.json').read_text(encoding='utf-8')
  )

  stop_flag = False

  def on_press(key):
    nonlocal stop_flag
    if key in (keyboard.Key.esc, keyboard.Key.f12):
      stop_flag = True

  listener = keyboard.Listener(on_press=on_press)
  listener.start()

  currently_held = set()
  last_tap_time = {}
  pos_history = deque(maxlen=int(STUCK_SECONDS / LOOP_INTERVAL))
  home_pos = None
  prev_x, prev_y = None, None
  tick = 0
  was_focused = False

  print(
      'Bot armed! Switch to WoW window. Press ESC or F12 at any time to stop.',
      flush=True,
  )

  try:
    with mss.mss() as capture:
      monitor = capture.monitors[cfg['base']['monitor']]
      while not stop_flag:
        loop_start = time.monotonic()
        hwnd, title = foreground()
        if not (hwnd and WINDOW_TITLE.lower() in title.lower()):
          if was_focused:
            print(
                f'[FOCUS] Lost WoW focus (active: "{title}"). Pausing...',
                flush=True,
            )
            was_focused = False
          release_all_holds(currently_held)
          time.sleep(0.25)
          continue

        if not was_focused:
          print(f'[FOCUS] Attached to "{title}". Running policy...', flush=True)
          was_focused = True

        frame = np.asarray(capture.grab(monitor))[:, :, :3].copy()
        state = view_state(frame, cfg)
        signals = read_panel(frame, panel['rect'], panel.get('cell_count', 18))

        px = signals.get('pos_x')
        py = signals.get('pos_y')
        if not isinstance(px, (int, float)):
          px = prev_x if prev_x is not None else 50.0
        if not isinstance(py, (int, float)):
          py = prev_y if prev_y is not None else 50.0

        if home_pos is None and isinstance(signals.get('pos_x'), (int, float)):
          home_pos = (px, py)
          print(
              f'[LEASH] Home anchor set to ({px:.2f}, {py:.2f}) with radius'
              f' {MAX_RADIUS}',
              flush=True,
          )

        dx = 0.0 if prev_x is None else (px - prev_x)
        dy = 0.0 if prev_y is None else (py - prev_y)
        speed = math.hypot(dx, dy)
        prev_x, prev_y = px, py

        combat_val = (
            1.0
            if str(state['combat']).lower()
            in ('in_combat', 'combat', 'true', '1')
            else 0.0
        )
        target_val = (
            1.0
            if str(state['target']).lower()
            in ('has_target', 'target', 'yes', 'true', '1')
            else 0.0
        )

        unselected_boxes = find_markers(frame, selected=False)
        selected_boxes = find_markers(frame, selected=True)
        ecount, nex, ney, new = parse_boxes(unselected_boxes + selected_boxes)
        _, sex, sey, _ = parse_boxes(selected_boxes)

        feat_dict = {
            'health_fraction': float(state['health'] or 1.0),
            'rage_fraction': float(state['rage'] or 0.0),
            'combat': combat_val,
            'target': target_val,
            'target_health_fraction': float(state['target_health'] or 0.0),
            'pos_x': px,
            'pos_y': py,
            'dx': dx,
            'dy': dy,
            'speed': speed,
            'enemy_count': ecount,
            'nearest_enemy_x': nex,
            'nearest_enemy_y': ney,
            'nearest_enemy_w': new,
            'sel_enemy_x': sex,
            'sel_enemy_y': sey,
        }
        for name in ALL_SIGNALS:
          if name not in ('pos_x', 'pos_y'):
            feat_dict[f'signal_{name}'] = encode_signal(
                signals.get(name, 'unknown')
            )

        x_vec = np.array(
            [[feat_dict.get(col, 0.0) for col in feature_cols]],
            dtype=np.float32,
        )
        x_scaled = scaler.transform(x_vec)

        with torch.no_grad():
          probs = (
              torch.sigmoid(model(torch.tensor(x_scaled, device=device)))
              .squeeze(0)
              .cpu()
              .numpy()
          )

        preds = dict(zip(action_cols, probs))
        tick += 1

        # Print top 3 model predictions once per second (every 5 ticks)
        if tick % 5 == 0:
          top3 = sorted(preds.items(), key=lambda kv: kv[1], reverse=True)[:3]
          top_str = ', '.join(f'{k}:{v:.2f}' for k, v in top3)
          print(
              f'[STATE] pos=({px:.2f},{py:.2f}) combat={int(combat_val)}'
              f' target={int(target_val)} enemies={int(ecount)} | TOP:'
              f' {top_str}',
              flush=True,
          )

          # --- SAFETY CHECK 1: STUCK DETECTION ---
          pos_history.append((px, py, 'w' in currently_held, combat_val > 0.5))
          if len(pos_history) == pos_history.maxlen:
              oldest_x, oldest_y, _, _ = pos_history[0]
              was_pushing = all(h and not c for _, _, h, c in pos_history)
              if was_pushing and math.hypot(px - oldest_x, py - oldest_y) < 0.03:
                  run_unstuck(currently_held)
                  pos_history.clear()
                  continue

          # --- SAFETY CHECK 2: GEOFENCE LEASH ---
          if home_pos is not None and combat_val < 0.5 and target_val < 0.5:
              dist_from_home = math.hypot(px - home_pos[0], py - home_pos[1])
              if dist_from_home > MAX_RADIUS:
                  print(
                      f'[LEASH] Outside radius ({dist_from_home:.2f} > {MAX_RADIUS}),'
                      ' turning around...',
                      flush=True,
                  )
                  release_all_holds(currently_held)
                  pydirectinput.keyDown('d')
                  time.sleep(0.85)
                  pydirectinput.keyUp('d')
                  pydirectinput.keyDown('w')
                  currently_held.add('w')
                  time.sleep(1.0)
                  continue

          # Use addon signals directly for reliable target detection
          has_target = (target_val > 0.5) or (signals.get('target') == 'yes')

          # --- PATROL & VISUAL HOMING WHEN NO TARGET IS LOCKED ---
          if combat_val < 0.5 and not has_target:
              if ecount > 0:
                  # Enemy spotted! Move forward and steer toward its nameplate
                  if 'w' not in currently_held:
                      pydirectinput.keyDown('w')
                      currently_held.add('w')

                  offset = nex - 0.5
                  if abs(offset) > 0.06:
                      turn_key = 'a' if offset < 0 else 'd'
                      turn_time = min(0.20, abs(offset) * 0.5)
                      pydirectinput.keyDown(turn_key)
                      time.sleep(turn_time)
                      pydirectinput.keyUp(turn_key)

                  now = time.monotonic()
                  if abs(offset) <= 0.25 and now - last_tap_time.get('target_tab', 0.0) >= 0.45:
                      press_tap('tab', False, f'homing_tab (nex={nex:.2f})')
                      last_tap_time['target_tab'] = now

                      # Fallback: if Tab didn't lock on, click the nameplate directly
                      if unselected_boxes:
                          largest = max(unselected_boxes, key=lambda b: b[2] * b[3])
                          bx, by, bw, bh = largest
                          click_x = monitor['left'] + bx + bw // 2
                          click_y = monitor['top'] + by + bh // 2
                          pydirectinput.click(x=click_x, y=click_y, button='left')
              else:
                  # No enemies on screen: stop walking forward and pivot in place to scan
                  if 'w' in currently_held:
                      pydirectinput.keyUp('w')
                      currently_held.remove('w')
                  pydirectinput.keyDown('d')
                  time.sleep(0.22)
                  pydirectinput.keyUp('d')

              elapsed = time.monotonic() - loop_start
              if elapsed < LOOP_INTERVAL:
                  time.sleep(LOOP_INTERVAL - elapsed)
              continue

          # --- INITIATE PULL WHEN HOSTILE TARGET IS LOCKED ---
          if combat_val < 0.5 and has_target and signals.get('hostile') == 'yes':

              now = time.monotonic()
              if signals.get('charge_usable') == 'yes' and signals.get('charge_range') == 'yes':
                  if now - last_tap_time.get('charge', 0.0) >= 1.0:
                      press_tap('3', False, 'auto_charge')
                      last_tap_time['charge'] = now
              else:
                  if 'w' not in currently_held:
                      pydirectinput.keyDown('w')
                      currently_held.add('w')
                  if now - last_tap_time.get('auto_attack', 0.0) >= 1.0:
                      press_tap('1', False, 'auto_pull')
                      last_tap_time['auto_attack'] = now

          # --- EXECUTE PREDICTED HOLD KEYS ---
          for act, key in HOLD_KEYMAP.items():
              if preds.get(act, 0.0) >= HOLD_THRESHOLD:
                  if key not in currently_held:
                      print(f'[KEY DOWN] {act} -> {key} ({preds[act]:.2f})', flush=True)
                      pydirectinput.keyDown(key)
                      currently_held.add(key)
              else:
                  if key in currently_held:
                      print(f'[KEY UP]   {act} -> {key}', flush=True)
                      pydirectinput.keyUp(key)
                      currently_held.remove(key)

          # --- EXECUTE PREDICTED TAP / SPELL KEYS ---
          now = time.monotonic()
          for act, (key, shift) in TAP_KEYMAP.items():
              if preds.get(act, 0.0) >= TAP_THRESHOLD:
                  if now - last_tap_time.get(act, 0.0) >= TAP_COOLDOWN:
                      press_tap(key, shift, f'{act} ({preds[act]:.2f})')
                      last_tap_time[act] = now

          elapsed = time.monotonic() - loop_start
          if elapsed < LOOP_INTERVAL:
              time.sleep(LOOP_INTERVAL - elapsed)

  finally:
    release_all_holds(currently_held)
    listener.stop()
    print('Bot stopped safely and all keys released.', flush=True)

if __name__ == '__main__':
    main()


