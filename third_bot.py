from collections import deque
import json
import math
from pathlib import Path
import random
import time

import mss
import numpy as np
import pydirectinput
from pynput import keyboard, mouse

from live_viewer import configure_combat_indicator, load_calibrations, view_state
from one_fight import foreground
from signal_panel import find_markers, read_panel

mouse_controller = mouse.Controller()

# --- CONFIGURATION ---
WINDOW_TITLE = 'Warcraft'
LOOP_INTERVAL = 0.20  # 5 Hz tick rate
MAX_RADIUS = 3.5  # Map units allowed from starting spot before turning back
STUCK_SECONDS = 2.0  # Trigger unstuck if moving forward without progress

# Screen coordinates (5120x1440 ultrawide)
CENTER_X = 2550
DEADZONE_X = 100  # 2450 to 2650 deadzone for facing enemy
LOOT_COORDS = (2552, 761)

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
    'reckless_swings': ('9', False),
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


# --- BOT STATE ---
class BotState:

  def __init__(self):
    self.was_focused = False
    self.prev_x = None
    self.prev_y = None
    self.home_pos = None
    self.prev_combat = False
    self.recovering = False
    self.combat_ticks = 0
    self.out_of_combat_ticks = 0
    self.battle_shout_timer = time.monotonic() - 180
    self.currently_held = set()
    self.pos_history = deque(maxlen=int(STUCK_SECONDS / LOOP_INTERVAL))
    self.prev_target_health = 1.0
    self.no_damage_ticks = 0
    self.last_reclick_time = 0.0
    self.gun_pull_attempts = 0
    self.leash_state = 'idle'
    self.leash_probe_start = None
    self.leash_probe_time = 0.0
    self.leash_turns = 0


# --- INPUT & MOVEMENT HELPERS ---
def hold_key(key: str, held_set: set):
  if key not in held_set:
    pydirectinput.keyDown(key)
    held_set.add(key)


def release_key(key: str, held_set: set):
  if key in held_set:
    pydirectinput.keyUp(key)
    held_set.remove(key)


def release_all_holds(held_set: set):
  for key in list(held_set):
    print(f'[KEY UP]   {key}', flush=True)
    pydirectinput.keyUp(key)
  held_set.clear()


def press_tap(key, shift=False):
  if isinstance(key, tuple):
    key, shift = key
  if shift:
    pydirectinput.keyDown('shift')
    time.sleep(0.02)
  pydirectinput.press(key)
  if shift:
    time.sleep(0.02)
    pydirectinput.keyUp('shift')


def right_click(coords, hold=0.06):
  mouse_controller.position = coords
  time.sleep(0.03)
  mouse_controller.press(mouse.Button.right)
  try:
    time.sleep(hold)
  finally:
    mouse_controller.release(mouse.Button.right)


def clear_target():
  pydirectinput.keyDown('shift')
  time.sleep(0.02)
  pydirectinput.press('7')
  time.sleep(0.02)
  pydirectinput.keyUp('shift')


def run_unstuck(held_set: set):
  print('[SAFETY] Obstacle detected! Running unstuck maneuver...', flush=True)
  release_all_holds(held_set)
  pydirectinput.keyDown('s')
  time.sleep(0.35)
  pydirectinput.keyUp('s')
  pydirectinput.press('space')
  pydirectinput.keyDown('d')
  pydirectinput.keyDown('e')
  time.sleep(0.65)
  pydirectinput.keyUp('e')
  pydirectinput.keyUp('d')


MOVEMENT_KEYS = {'w', 'a', 's', 'd', 'q', 'e'}


def stop_movement(held_set: set, settle_time: float = 0.15):
  """Force-releases movement keys and taps 's' to cancel WoW right-click movement."""
  for key in MOVEMENT_KEYS:
    pydirectinput.keyUp(key)
    held_set.discard(key)

  # Tap 's' briefly to cancel WoW's automatic run-to-target from right-clicking
  pydirectinput.keyDown('s')
  time.sleep(0.05)
  pydirectinput.keyUp('s')

  if settle_time > 0:
    time.sleep(settle_time)


def walk_backwards(held_set: set, seconds: int):
  release_all_holds(held_set)
  time.sleep(0.05)
  pydirectinput.keyDown('s')
  time.sleep(random.randint(seconds, seconds * 2))
  pydirectinput.keyUp('s')


def face_enemy(enemy_position):
  x, _ = enemy_position
  if x > CENTER_X + DEADZONE_X:
    pydirectinput.keyDown('d')
    time.sleep(random.uniform(0.1, 0.4))
    pydirectinput.keyUp('d')
  elif x < CENTER_X - DEADZONE_X:
    pydirectinput.keyDown('a')
    time.sleep(random.uniform(0.1, 0.4))
    pydirectinput.keyUp('a')


def perform_stationary_action(held_set: set, action_fn, *args, **kwargs):
  """Stops movement first, then executes the given action function."""
  stop_movement(held_set)
  return action_fn(*args, **kwargs)


def loot_once():
  print('[LOOT] Looting once...', flush=True)
  time.sleep(random.uniform(0.4, 0.9))
  right_click(LOOT_COORDS)
  time.sleep(random.uniform(0.8, 1.4))


def is_not_attacking(
    obs: dict, bot: BotState, timeout_ticks: int = 12
) -> bool:
  """Returns True if the bot has a living target but hasn't landed an attack."""
  if not obs['has_target'] or obs['target_health'] <= 0.01:
    bot.no_damage_ticks = 0
    bot.prev_target_health = 1.0
    return False

  # 1. Check if target health dropped since last tick
  if obs['target_health'] < bot.prev_target_health - 0.001:
    bot.no_damage_ticks = 0
  else:
    bot.no_damage_ticks += 1

  bot.prev_target_health = obs['target_health']

  # 2. Check addon melee-range / auto-attack signals if available
  signals = obs['signals']
  out_of_melee = (
      signals.get('heroic_strike_usable') == 'no'
      and signals.get('auto_attack_active') == 'no'
  )

  return (bot.no_damage_ticks >= timeout_ticks) or (
      out_of_melee and bot.no_damage_ticks >= 6
  )



def combat_loop(enemy_position, health, signals, combat_ticks):
  time.sleep(0.5)
  face_enemy(enemy_position)

  if health < 0.30:
    press_tap(TAP_KEYMAP['recover'])
  if signals.get('elunes_light_ready') == 'yes':
    press_tap(TAP_KEYMAP['elunes_light'])
  if signals.get('victory_rush_usable') == 'yes':
    press_tap(TAP_KEYMAP['victory_rush'])
  if signals.get('overpower_usable') == 'yes':
    press_tap(TAP_KEYMAP['overpower'])
  if signals.get('execute_usable') == 'yes':
    press_tap(TAP_KEYMAP['execute'])
  if 0 < combat_ticks < 10:
    if signals.get('thunder_clap_ready') == 'yes':
      press_tap(TAP_KEYMAP['thunder_clap'])
    if signals.get('demoralizing_shout_ready') == 'yes':
      press_tap(TAP_KEYMAP['demoralizing_shout'])
  if signals.get('heroic_strike_usable') == 'yes':
    press_tap(TAP_KEYMAP['heroic_strike'])

  if random.randint(1, 10) == 5:
    pydirectinput.keyDown('s')
    time.sleep(0.33)
    pydirectinput.keyUp('s')


# --- PERCEPTION ---
def parse_boxes(boxes):
  if not boxes:
    return 0, (CENTER_X, 733)
  largest = max(boxes, key=lambda b: b[2] * b[3])
  x, y, w, h = largest
  # Click center-x and slightly below nameplate (y + h/2 + 120px)
  target_px = (x + w / 2.0, (y + h / 2.0) + 120)
  return len(boxes), target_px


def read_observation(capture, monitor, cfg, panel, bot: BotState) -> dict:
  frame = np.asarray(capture.grab(monitor))[:, :, :3].copy()
  state = view_state(frame, cfg)
  signals = read_panel(frame, panel['rect'], panel.get('cell_count', 18))

  px = signals.get('pos_x')
  py = signals.get('pos_y')
  if not isinstance(px, (int, float)):
    px = bot.prev_x if bot.prev_x is not None else 50.0
  if not isinstance(py, (int, float)):
    py = bot.prev_y if bot.prev_y is not None else 50.0

  if bot.home_pos is None and isinstance(signals.get('pos_x'), (int, float)):
    bot.home_pos = (px, py)
    print(
        f'[LEASH] Home anchor set to ({px:.2f}, {py:.2f}) with radius'
        f' {MAX_RADIUS}',
        flush=True,
    )

  bot.prev_x, bot.prev_y = px, py

  in_combat = str(state['combat']).lower() in (
      'in_combat',
      'combat',
      'true',
      '1',
  )

  unselected_boxes = find_markers(frame, selected=False)
  selected_boxes = find_markers(frame, selected=True)

  enemy_count, nearest_enemy = parse_boxes(unselected_boxes + selected_boxes)
  sel_count, selected_enemy = parse_boxes(selected_boxes)

  has_target = (
          str(state['target']).lower() in ('has_target', 'target', 'yes', 'true', '1')
          or signals.get('target') in ('yes', '1', 'true', True)
          or sel_count > 0  # If cyan box is visible, we definitely have a target!
  )

  return {
      'health': float(state['health'] or 1.0),
      'in_combat': in_combat,
      'has_target': has_target,
      'target_health': float(state['target_health'] or 0.0),
      'px': px,
      'py': py,
      'position_valid': (isinstance(signals.get('pos_x'), (int, float))
                        and isinstance(signals.get('pos_y'), (int, float))
                        and math.isfinite(px) and math.isfinite(py)),
      'enemy_count': enemy_count,
      'nearest_enemy': nearest_enemy,
      'has_cyan_box': sel_count > 0,
      'cyan_enemy': selected_enemy,
      'selected_enemy': selected_enemy if sel_count > 0 else nearest_enemy,
      'signals': signals,
  }


# --- DECISION ENGINE (STRICT PRIORITY ORDER) ---
def decide_action(obs: dict, bot: BotState, now: float):
  in_combat = obs['in_combat']
  has_target = obs['has_target']
  health = obs['health']
  signals = obs['signals']

  # 1. JUST LEFT COMBAT -> Loot first, then clear dead target
  if bot.prev_combat and not in_combat:
    release_all_holds(bot.currently_held)
    loot_once()
    clear_target()
    return

  # 2. IN COMBAT -> Execute combat rotation
  if in_combat:
      bot.recovering = False
      bot.leash_state = 'idle'
      bot.leash_probe_start = None
      bot.leash_turns = 0
      if not bot.prev_combat or 'w' in bot.currently_held:
          print('[COMBAT] Stopping forward and click-to-move movement.', flush=True)
          stop_movement(bot.currently_held)

      if not has_target:
          print(
              '[COMBAT] In combat with no target! Tab-targeting attacker...',
              flush=True,
          )
          press_tap(TAP_KEYMAP['target_tab'])
          press_tap(TAP_KEYMAP['auto_attack'])
          return

      if obs['target_health'] <= 0.01 and bot.out_of_combat_ticks > 0:
          print(
              '[COMBAT] Target dead but still in combat. Backing up and tabbing.',
              flush=True,
          )
          walk_backwards(bot.currently_held, 1)
          press_tap(TAP_KEYMAP['target_tab'])
          press_tap(TAP_KEYMAP['heroic_strike'])
          return

      if is_not_attacking(obs, bot):
          print(
              '[COMBAT] Not hitting target! Re-engaging and tapping'
              ' auto-attack...',
              flush=True,
          )
          press_tap(TAP_KEYMAP['auto_attack'])
          if obs['has_cyan_box']:
              right_click(obs['cyan_enemy'])
              stop_movement(bot.currently_held)
          elif obs['enemy_count'] > 0:
              right_click(obs['nearest_enemy'])
              stop_movement(bot.currently_held)
          bot.no_damage_ticks = 0
          return

      combat_loop(obs['nearest_enemy'], health, signals, bot.combat_ticks)
      return

  # 3. RECOVERY -> Stay seated until 95% HP (never interrupted by patrol/loot)
  if bot.recovering:
    if health < 0.95:
      return
    print('[RECOVER] Health restored. Resuming patrol.', flush=True)
    bot.recovering = False

  if health < 0.50:
    release_all_holds(bot.currently_held)
    print(f'[RECOVER] Low health ({health:.0%}). Sitting to recover...', flush=True)
    bot.recovering = True
    press_tap(TAP_KEYMAP['recover'])
    return

  # 4. BUFFS
  if (now - bot.battle_shout_timer) > 179 and signals.get(
      'battle_shout_ready'
  ) == 'yes':
    press_tap(TAP_KEYMAP['battle_shout'])
    bot.battle_shout_timer = now
    return

  # 5. SAFETY: STUCK DETECTION & GEOFENCE LEASH
  if bot.leash_state == 'idle' and len(bot.pos_history) == bot.pos_history.maxlen:
    oldest_x, oldest_y, _, _ = bot.pos_history[0]
    was_pushing = all(h and not c for _, _, h, c in bot.pos_history)
    if (
        was_pushing
        and math.hypot(obs['px'] - oldest_x, obs['py'] - oldest_y) < 0.03
    ):
      run_unstuck(bot.currently_held)
      bot.pos_history.clear()
      return

  if bot.home_pos is not None and (bot.leash_state != 'idle' or not has_target):
    dist_from_home = math.hypot(
        obs['px'] - bot.home_pos[0], obs['py'] - bot.home_pos[1]
    )
    if bot.leash_state != 'idle' and not obs['position_valid']:
      release_all_holds(bot.currently_held)
      bot.leash_probe_start = None
      bot.leash_state = 'waiting'
      return
    if bot.leash_state != 'idle' and dist_from_home <= MAX_RADIUS * .8:
      release_all_holds(bot.currently_held)
      bot.leash_state = 'idle'
      bot.leash_probe_start = None
      bot.leash_turns = 0
      bot.pos_history.clear()
      print('[LEASH] Returned inside the patrol area.', flush=True)
    elif dist_from_home > MAX_RADIUS or bot.leash_state != 'idle':
      if not obs['position_valid']:
        release_all_holds(bot.currently_held)
        bot.leash_state = 'waiting'
        return
      if bot.leash_probe_start is None:
        release_all_holds(bot.currently_held)
        bot.leash_state = 'probe'
        bot.leash_probe_start = (obs['px'], obs['py'])
        bot.leash_probe_time = now
        hold_key('w', bot.currently_held)
        print(f'[LEASH] Measuring direction toward home ({dist_from_home:.2f} away).', flush=True)
        return
      dx = obs['px'] - bot.leash_probe_start[0]
      dy = obs['py'] - bot.leash_probe_start[1]
      travelled = math.hypot(dx, dy)
      if travelled < .03:
        if now - bot.leash_probe_time > 3:
          release_all_holds(bot.currently_held)
          bot.leash_state = 'idle'
          bot.leash_probe_start = None
          raise RuntimeError('Leash return stopped: no reliable movement in map coordinates.')
        return
      home_x = bot.home_pos[0] - obs['px']
      home_y = bot.home_pos[1] - obs['py']
      error = math.atan2(dx * home_y - dy * home_x, dx * home_x + dy * home_y)
      release_key('w', bot.currently_held)
      bot.leash_probe_start = None
      if abs(error) <= .35:
        bot.leash_turns = 0
        print('[LEASH] Heading toward home.', flush=True)
      else:
        bot.leash_turns += 1
        if bot.leash_turns > 16:
          bot.leash_state = 'idle'
          raise RuntimeError('Leash return could not establish a heading toward home.')
        turn = 'd' if error > 0 else 'a'
        print(f'[LEASH] Correcting heading with {turn}.', flush=True)
        try:
          pydirectinput.keyDown(turn)
          time.sleep(min(.25, max(.06, abs(error) * .12)))
        finally:
          pydirectinput.keyUp(turn)
      bot.pos_history.clear()
      return

  # 6. ENGAGE SELECTED TARGET OR NEARBY ENEMY
  if has_target:
    # Only stop and shoot if > 2 enemies are nearby AND the gun is usable/in range
    can_shoot = (
            signals.get('shoot_gun_usable') == 'yes'
            and signals.get('shoot_gun_range', 'yes') == 'yes'
    # Defaults to 'yes' if you don't have a separate range cell
    )

    if obs['enemy_count'] > 2 and can_shoot and bot.gun_pull_attempts < 2:
        print(
            f"[PULL] Shooting gun ({obs['enemy_count']} enemies nearby)...",
            flush=True,
        )
        stop_movement(bot.currently_held)
        face_enemy(obs['selected_enemy'])
        press_tap(TAP_KEYMAP['shoot_gun'])
        bot.gun_pull_attempts += 1
        time.sleep(random.uniform(1.2, 1.6))
        return

    # Charge if usable and in range
    if (
            signals.get('charge_usable') == 'yes'
            and signals.get('charge_range') == 'yes'
    ):
        print('[PULL] Charging target!', flush=True)
        press_tap(TAP_KEYMAP['charge'])
        return

    # Periodically re-click the cyan box (or nearest enemy box if cyan isn't detected)
    if (now - bot.last_reclick_time) >= 0.40:
        if obs['has_cyan_box']:
            print(
                f"[PULL] Re-clicking cyan box at {obs['cyan_enemy']}",
                flush=True,
            )
            right_click(obs['cyan_enemy'])
            bot.last_reclick_time = now
        elif obs['enemy_count'] > 0:
            print(
                f"[PULL] Re-clicking nearest box at {obs['nearest_enemy']}",
                flush=True,
            )
            right_click(obs['nearest_enemy'])
            bot.last_reclick_time = now
        else:
            # Target is selected, but nameplate is temporarily off-screen -> move forward
            hold_key('w', bot.currently_held)
    return

  # No target selected yet -> keep clicking nearest visible enemy every 0.40s
  if obs['enemy_count'] > 0:
    release_key('w', bot.currently_held)
    if (now - bot.last_reclick_time) >= 0.40:
        print(f"[PULL] Acquiring target at {obs['nearest_enemy']}", flush=True)
        right_click(obs['nearest_enemy'])
        bot.last_reclick_time = now
    return

  # 7. DEFAULT: PATROL FORWARD
  hold_key('w', bot.currently_held)

  # --- MAIN ENTRY POINT ---
def main():
  pydirectinput.PAUSE = 0.0
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

  bot = BotState()
  print(
      'Bot armed! Switch to WoW window. Press [ or F12 at any time to stop.',
      flush=True,
  )

  try:
      with mss.mss() as capture:
          monitor = capture.monitors[cfg['base']['monitor']]
          while not stop_flag:
              loop_start = time.monotonic()
              hwnd, title = foreground()

              if not (hwnd and WINDOW_TITLE.lower() in title.lower()):
                  if bot.was_focused:
                      print(
                          f'[FOCUS] Lost WoW focus (active: "{title}"). Pausing...',
                          flush=True,
                      )
                      bot.was_focused = False
                  release_all_holds(bot.currently_held)
                  time.sleep(0.25)
                  continue

              if not bot.was_focused:
                  print(f'[FOCUS] Attached to "{title}". Running policy...', flush=True)
                  bot.was_focused = True

              obs = read_observation(capture, monitor, cfg, panel, bot)
              decide_action(obs, bot, loop_start)

              # Guaranteed bookkeeping at the end of EVERY tick
              bot.pos_history.append(
                  (obs['px'], obs['py'], 'w' in bot.currently_held, obs['in_combat'])
              )
              if obs['in_combat']:
                  bot.out_of_combat_ticks = 0
                  bot.combat_ticks += 1
              else:
                  bot.combat_ticks = 0
                  bot.out_of_combat_ticks += 1
              bot.prev_combat = obs['in_combat']

              # Maintain consistent 5 Hz loop pacing
              elapsed = time.monotonic() - loop_start
              if elapsed < LOOP_INTERVAL:
                  time.sleep(LOOP_INTERVAL - elapsed)

  finally:
      release_all_holds(bot.currently_held)
      listener.stop()
      print('Bot stopped safely.', flush=True)


if __name__ == '__main__':
  main()
