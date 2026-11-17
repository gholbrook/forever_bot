from collections import deque
import json
import math
from pathlib import Path
import time
import random

import joblib
import mss
import numpy as np
import pydirectinput
from pynput import keyboard, mouse
import torch
import torch.nn as nn

from live_viewer import configure_combat_indicator, load_calibrations, view_state
from one_fight import foreground
from signal_panel import ALL_SIGNALS, find_markers, read_panel

mouse_controller = mouse.Controller()

# --- CONFIGURATION ---
WINDOW_TITLE = 'Warcraft'
LOOP_INTERVAL = 0.20  # 5 Hz matching your training data
MAX_RADIUS = 30.5  # Map units allowed from starting spot before turning back
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
      (x + w / 2.0) / 1920.0, # 5120
      (y + h / 2.0) / 1080.0, # 1440
      w / 1920.0,
  )


def press_tap(key, shift=False, act_name=''):
  if isinstance(key, tuple):
    key, shift = key

  label = f'Shift+{key}' if shift else key
  # print(f'[KEY TAP]  {act_name} -> {label}', flush=True)
  if shift:
    pydirectinput.keyDown('shift')
    time.sleep(0.02)
  pydirectinput.press(key)
  if shift:
    time.sleep(0.02)
    pydirectinput.keyUp('shift')


# copied from one_fight.py
def marker_click_point(frame, offset):
    from signal_panel import find_markers
    height, width = frame.shape[:2]
    candidates = []
    for x, y, bw, bh in find_markers(frame):
        px, py = x + bw//2, y + bh + offset
        if .08*width <= px <= .88*width and .12*height <= py <= .80*height:
            candidates.append((px, py))
    if not candidates:
        return None
    return min(candidates, key=lambda pt: abs(pt[0]-width/2))


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


def right_click(coords, hold=0.06):
  mouse_controller.position = coords
  time.sleep(0.03)  # Let cursor settle at target coordinates
  mouse_controller.press(mouse.Button.right)
  try:
    time.sleep(hold)  # Hold long enough for WoW to register the frame
  finally:
    mouse_controller.release(mouse.Button.right)


def approach_enemy(coords):
  right_click(coords)


def walk_backwards(held_keys, seconds):
    release_all_holds(held_keys)
    time.sleep(0.05)
    pydirectinput.keyDown('s')
    time.sleep(random.randint(seconds, seconds*2))
    pydirectinput.keyUp('s')


def face_enemy(enemy_position):
    # face target
    x, y = enemy_position
    if x > 2650:
        pydirectinput.keyDown('d')
        time.sleep(random.uniform(0.1, 0.4))
        pydirectinput.keyUp('d')
    elif x < 2450:
        pydirectinput.keyDown('a')
        time.sleep(random.uniform(0.1, 0.4))
        pydirectinput.keyUp('a')


def combat_loop(enemy_position, health, ability_status, enemy_count, combat_ticks):
    # print(f'FIGHTING {enemy_count} enemies...', flush=True)
    time.sleep(0.5)
    face_enemy(enemy_position)
    if health < 0.3:
        press_tap(TAP_KEYMAP['recover'])
    if ability_status.get('elunes_light_ready') == 'yes':
        press_tap(TAP_KEYMAP['elunes_light'])
    if ability_status.get('victory_rush_usable') == 'yes':
        press_tap(TAP_KEYMAP['victory_rush'])
    if ability_status.get('overpower_usable') == 'yes':
        press_tap(TAP_KEYMAP['overpower'])
    if ability_status.get('execute_usable') == 'yes':
        press_tap(TAP_KEYMAP['execute'])
    if combat_ticks < 10 and combat_ticks > 0 and ability_status.get('thunder_clap_ready') == 'yes':
        press_tap(TAP_KEYMAP['thunder_clap'])
    if combat_ticks < 10 and combat_ticks > 0 and ability_status.get('demoralizing_shout_ready') == 'yes':
        press_tap(TAP_KEYMAP['demoralizing_shout'])
    if ability_status.get('heroic_strike_usable') == 'yes':
        press_tap(TAP_KEYMAP['heroic_strike'])
    if random.randint(1, 10) == 5:
        pydirectinput.keyDown('s')
        time.sleep(0.33)
        pydirectinput.keyUp('s')
    # update this to somehow determine if they are actually attacking me vs just nearby
    # if enemy_count > 1:
    #     if ability_status.get('retaliation_ready'):
    #         press_tap(TAP_KEYMAP['retaliation'])
    #     if ability_status.get('cleave_ready'):
    #         press_tap(TAP_KEYMAP['cleave'])


def loot_once():
  print('looting once...', flush=True)
  time.sleep(random.uniform(0.4, 0.9))  # Wait for corpse death animation / loot sparkles
  right_click((2552, 761))
  time.sleep(random.uniform(0.8, 1.4))  # Wait for auto-loot window to finish collecting


def clear_target():
    pydirectinput.keyDown('esc')
    time.sleep(random.uniform(0.2, 0.4))
    pydirectinput.keyUp('esc')


def main():
  pydirectinput.PAUSE = 0.0
  meta = joblib.load('policy_meta.joblib')
  scaler = meta['scaler']
  feature_cols = meta['features']
  action_cols = [c.replace('act_', '') for c in meta['actions']]

  cfg = load_calibrations()
  configure_combat_indicator(cfg)
  panel = json.loads(
      Path('calibration/signal_panel.json').read_text(encoding='utf-8')
  )

  stop_flag = False

  def on_press(key):
    nonlocal stop_flag
    if key in (keyboard.KeyCode.from_char('['), keyboard.Key.f12):
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
  recovering = False
  prev_combat_val = 0
  combat_ticks = 0
  out_of_combat_ticks = 0
  battle_shout_timer = time.monotonic() - 180

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

        tick += 1

        # Print top 3 model predictions once per second (every 5 ticks)
        if tick % 5 == 0:
          pass

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
          target_health = feat_dict['target_health_fraction']

          # --- PATROL ---
          health = feat_dict['health_fraction']
          if combat_val < 0.5 and not has_target:
              if 'w' not in currently_held and recovering == False:
                  pydirectinput.keyDown('w')
                  currently_held.add('w')
          # middle_x is 2550, greater than is to the right, less than is to the left
          # middle_y is around 733, greater than is lower, less than is higher
          nearest_enemy = (feat_dict['nearest_enemy_x'] * 1920, (feat_dict['nearest_enemy_y'] * 1080) + 120)
          enemy_count = feat_dict['enemy_count']
          if (loop_start - battle_shout_timer) > 179 and signals.get('battle_shout_ready') == 'yes':
              press_tap(TAP_KEYMAP['battle_shout'])
              battle_shout_timer = loop_start
          if enemy_count > 0 and combat_val < 0.5:
              if 'w' in currently_held:
                  pydirectinput.keyUp('w')
                  currently_held.remove('w')
              approach_enemy(nearest_enemy)
          if has_target and combat_val < 0.5:
              if enemy_count > 2:
                  print(f'Shooting because enemy count: {enemy_count}')
                  release_all_holds(currently_held)
                  if 'w' in currently_held:
                      pydirectinput.keyUp('w')
                      currently_held.remove('w')
                  # time.sleep(random.uniform(0.1, 0.25))
                  # press_tap(TAP_KEYMAP['shoot_gun'])
                  # time.sleep(random.uniform(0.5, 1.1))
              elif signals.get('charge_usable') == 'yes' and signals.get('charge_range') == 'yes':
                  press_tap(TAP_KEYMAP['charge'])
              elif enemy_count > 0:
                  time.sleep(random.uniform(0.5, 1.0))
                  approach_enemy(nearest_enemy)
              if target_health < 0.01:
                  clear_target()
          if has_target and combat_val > 0.5:
              if target_health <= 0.01 and out_of_combat_ticks > 0:
                  print('Target is dead but still in combat. Walking backwards to see if I can bring a new target in front of me.')
                  walk_backwards(currently_held, 1)
                  press_tap(TAP_KEYMAP['target_tab'])
                  press_tap(TAP_KEYMAP['heroic_strike'])
              combat_loop(nearest_enemy, health, signals, enemy_count, combat_ticks)
          # elif not has_target and combat_val > 0.5:
          #     print('search for whats attacking me and target it')
          #     press_tap(TAP_KEYMAP['target_tab'])
          #     press_tap(TAP_KEYMAP['heroic_strike'])
          if prev_combat_val > 0.5 and combat_val < 0.5:
              release_all_holds(currently_held)
              loot_once()
              if has_target:
                  clear_target()
                  has_target = False
          if recovering and health < 0.95 and combat_val < 0.5:
              continue
          else:
              recovering = False
          if health < 0.5:
              release_all_holds(currently_held)
              print('RECOVERING...')
              recovering = True
              press_tap(TAP_KEYMAP['recover'])
              continue
          if combat_val > 0.5:
              out_of_combat_ticks = 0
              combat_ticks += 1
          elif combat_val < 0.5:
              combat_ticks = 0
              out_of_combat_ticks += 1
          prev_combat_val = combat_val


  finally:
    release_all_holds(currently_held)
    listener.stop()
    print('Bot stopped safely and all keys released.', flush=True)

if __name__ == '__main__':
    main()