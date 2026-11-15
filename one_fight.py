"""One-fight experiment: default dry run; optionally send a few bound keys on Windows."""
import argparse
import ctypes
import csv
from contextlib import nullcontext
from time import time_ns
import math
import threading
import time

import mss
import numpy as np
from pynput import keyboard, mouse
from live_viewer import load_calibrations, view_state

KEYS = {'overpower': '7', 'victory_rush': '0', 'heroic_strike': '2', 'execute': '='}
RECOVERY_HEALTH = .50
user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]


def foreground():
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, len(buf))
    return hwnd, buf.value


def validate_state(state, min_health, require_target=True):
    health = state.get('health')
    if health is None or not math.isfinite(health) or not 0 <= health <= 1:
        return 'Player health could not be read.'
    if health <= min_health:
        return f'Health estimate at or below {min_health:.0%}.'
    if state.get('combat') not in ('combat', 'out_of_combat'):
        return 'Combat state is unknown.'
    if require_target and state.get('target') != 'present':
        return 'Target not confidently detected.'
    return None


def parse_hotkey(text):
    name = text.strip().lower()
    if len(name) == 1 and 33 <= ord(name) <= 126:
        return name
    if name.startswith('f') and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        return name
    raise ValueError('Hotkeys must be a single printable character or F1 through F24.')


def matches_hotkey(key, name):
    if name.startswith('f') and len(name) > 1:
        return key == getattr(keyboard.Key, name, None)
    char = getattr(key, 'char', None)
    return char is not None and char.lower() == name


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


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live', action='store_true', help='Actually send game inputs (default is dry run).')
    p.add_argument('--execute', action='store_true', help='Use Execute with an eight-cell addon calibration.')
    p.add_argument('--log-csv', help='Write a new CSV of state samples, inputs, and fight events.')
    p.add_argument('--loot', action='store_true', help='Right-click once at the existing cursor position after confirmed combat exit.')
    p.add_argument('--recover', action='store_true', help='After combat, use = once if needed and wait for health recovery.')
    p.add_argument('--auto-target', action='store_true', help='Attempt to select one enemy using Tab.')
    p.add_argument('--charge', action='store_true', help='Try Charge (key 3) as the opening action.')
    p.add_argument('--approach', action='store_true', help='Experimentally move forward in short pulses while trying to Charge.')
    p.add_argument('--marker-move', action='store_true', help='One click-to-move approach using a detected marker.')
    p.add_argument('--shoot-pull', action='store_true', help='Use Shoot Gun instead of Charge in keyboard approach.')
    p.add_argument('--keyboard-approach', action='store_true', help='Steer toward enemy markers with A, D and W.')
    p.add_argument('--face-target', '--track-fleeing', dest='face_target', action='store_true',
                   help='Keep turning toward the selected enemy throughout combat.')
    p.add_argument('--marker-offset-y', type=int, help='Pixels below marker for the previously previewed click point.')
    p.add_argument('--marker-timeout', type=float, default=8.0, help='Maximum seconds to wait for engagement after click.')
    p.add_argument('--search-seconds', type=int, help='Optional search limit (0 disables searching). Default: unlimited in keyboard mode, 10 seconds in click mode.')
    p.add_argument('--fights', type=int, default=1, help='Maximum fights in this run (1-5; repeat requires calibrated addon signals).')
    p.add_argument('--combat-indicator', action='store_true', help='Read combat state from the calibrated addon square.')
    p.add_argument('--max-forward-seconds', type=float, default=2.0, help='Maximum total W time during approach (default 2).')
    p.add_argument('--engage-timeout', type=float, default=8.0, help='Maximum time to detect combat after opening (default 8).')
    p.add_argument('--recovery-timeout', type=float, default=60, help='Maximum seconds to wait for recovery (default 60).')
    p.add_argument('--window-title', default='Warcraft', help='Required substring of foreground game window title.')
    p.add_argument('--stop-health', type=float, default=.15, help='Stop at or below this fraction (default .15).')
    p.add_argument('--min-start-health', type=float, default=.90)
    p.add_argument('--max-seconds', type=float, default=30)
    p.add_argument('--interval', type=float, default=.25)
    p.add_argument('--ability-spacing', type=float, default=1.5)
    p.add_argument('--press-ms', type=int, default=100, help='Duration of synthetic key presses in milliseconds (30-300).')
    p.add_argument('--rage-saturation', type=int, default=180)
    p.add_argument('--start-key', default='f7', help='Single character or F-key used to start (default F7).')
    p.add_argument('--stop-key', default='f8', help='Single character or F-key used to stop (default F8).')
    args = p.parse_args()
    try:
        start_key, stop_key = parse_hotkey(args.start_key), parse_hotkey(args.stop_key)
    except ValueError as exc:
        p.error(str(exc))
    if start_key == stop_key:
        p.error('Start and stop keys must differ.')
    if start_key in {'1', '2', '3', '7', '0'} or stop_key in {'1', '2', '3', '7', '0'}:
        p.error('Start/stop keys cannot be one of the keys this controller sends: 1, 2, 3, 7, 0.')
    if (args.recover or args.execute) and any(key in ('=', '+') for key in (start_key, stop_key)):
        p.error('Start/stop keys cannot be = or + when recovery or Execute is enabled.')
    if args.approach and not args.charge:
        p.error('--approach requires --charge')
    if args.shoot_pull and not args.keyboard_approach:
        p.error('--shoot-pull requires --keyboard-approach')
    if args.keyboard_approach and not args.marker_move:
        p.error('--keyboard-approach requires --marker-move')
    if args.face_target and not args.keyboard_approach:
        p.error('--face-target requires --keyboard-approach')
    if args.marker_move and (args.auto_target or args.charge or args.approach):
        p.error('--marker-move cannot be combined with --auto-target, --charge, or --approach')
    if not 1 <= args.fights <= 5:
        p.error('--fights must be between 1 and 5')
    if args.fights > 1 and not (args.marker_move and args.combat_indicator and args.loot and args.recover):
        p.error('--fights greater than 1 requires --marker-move --combat-indicator --loot --recover')
    if args.marker_move and not args.combat_indicator:
        p.error('--marker-move requires --combat-indicator')
    if args.marker_move and (args.marker_offset_y is None or not 0 <= args.marker_offset_y <= 500):
        p.error('--marker-move requires --marker-offset-y between 0 and 500')
    if not 1 <= args.marker_timeout <= 20:
        p.error('--marker-timeout must be between 1 and 20 seconds')
    if args.marker_move and {'a', 'd', 's'}.intersection((start_key, stop_key)):
        p.error('A, D and S cannot be start/stop hotkeys when marker movement is enabled.')
    if args.search_seconds is None and not args.keyboard_approach:
        args.search_seconds = 10
    if args.search_seconds is not None and not 0 <= args.search_seconds <= 60:
        p.error('--search-seconds must be between 0 and 60.')
    if (args.approach or (args.marker_move and (args.search_seconds or args.keyboard_approach))) and 'w' in (start_key, stop_key):
        p.error('Start/stop keys cannot be W when walking is enabled.')
    if not args.window_title.strip(): p.error('window title must not be empty')
    if not 0 < args.stop_health < args.min_start_health <= 1: p.error('Require 0 < stop health < start health <= 1')
    if not 0 < args.max_seconds <= 120 or args.interval < .2 or args.ability_spacing < 1:
        p.error('max seconds must be 0..120, interval >= .2, ability spacing >= 1')
    if not 0 <= args.rage_saturation <= 255: p.error('rage saturation must be 0..255')
    if not 30 <= args.press_ms <= 300: p.error('press-ms must be between 30 and 300')
    if not 0 < args.recovery_timeout <= 300: p.error('recovery timeout must be between 0 and 300 seconds')
    if not 0 < args.max_forward_seconds <= 10: p.error('max-forward-seconds must be greater than 0 and at most 10')
    if not 0 < args.engage_timeout <= args.max_seconds: p.error('engage-timeout must be positive and no greater than max-seconds')
    cfg = load_calibrations()
    if args.combat_indicator:
        from live_viewer import configure_combat_indicator
        configure_combat_indicator(cfg)
        print('Combat source: calibrated addon indicator.', flush=True)
    else:
        print('Combat source: portrait border.', flush=True)
    import json
    from pathlib import Path
    panel_config = None
    panel_path = Path('calibration/signal_panel.json')
    if args.fights > 1 or args.execute or args.keyboard_approach or (args.marker_move and panel_path.exists()):
        panel_config = json.loads(panel_path.read_text(encoding='utf-8'))
        if panel_config.get('screen') != cfg['base']['screen']:
            raise ValueError('Addon signal-panel calibration uses a different monitor; recalibrate it.')
    if args.execute and panel_config.get('cell_count', 7) < 8:
        raise ValueError('Execute requires the updated addon and at least an eight-cell signal panel calibration.')
    if args.shoot_pull and panel_config.get('cell_count', 7) < 9:
        raise ValueError('Shoot Gun requires a signal panel calibrated with the SG cell.')
    stop = threading.Event()
    arm = threading.Event()
    def on_press(key):
        if matches_hotkey(key, stop_key):
            stop.set()
        elif matches_hotkey(key, start_key):
            arm.set()
    listener = keyboard.Listener(on_press=on_press)
    controller = keyboard.Controller()
    mouse_controller = mouse.Controller()
    log = open(args.log_csv, 'x', encoding='utf-8', newline='') if args.log_csv else nullcontext()
    with log as log_file, mss.mss() as capture:
        fight_number = 0
        latest_state = {}
        latest_sample_ns = None
        state_fields = ('health', 'rage', 'combat', 'target', 'target_health', 'action')
        writer = csv.writer(log_file) if log_file else None
        if writer:
            writer.writerow(['unix_ns', 'fight', 'mode', 'event', 'detail', 'sample_unix_ns', *state_fields])
            print(f'Recording run to {args.log_csv}', flush=True)

        def record(event, detail=''):
            if writer:
                writer.writerow([time_ns(), fight_number, 'live' if args.live else 'dry_run',
                                 event, detail, latest_sample_ns,
                                 *(latest_state.get(field) for field in state_fields)])
                log_file.flush()

        listener.start()
        index = cfg['base']['monitor']
        if index < 1 or index >= len(capture.monitors):
            raise ValueError('Calibrated monitor unavailable.')
        mon = capture.monitors[index]
        if mon != cfg['base']['screen']:
            raise ValueError('Monitor geometry differs from calibration.')
        size = (mon['width'], mon['height'])
        for name in ('extra', 'icons', 'overpower'):
            if (cfg[name]['width'], cfg[name]['height']) != size:
                raise ValueError(f'{name} calibration resolution differs from monitor.')
        print('LIVE INPUT ENABLED' if args.live else 'DRY RUN: NO INPUT WILL BE SENT', flush=True)
        if args.marker_move:
            print('Place cursor over character for later looting and face a clear path toward marked enemies.', flush=True)
        elif args.auto_target:
            print('Clear your target, face one nearby ordinary enemy, and start at full health and out of combat.', flush=True)
        else:
            print('Select ONE nearby hostile enemy; be in melee range, full health, and out of combat.', flush=True)
        print(f'Focus the game window (title contains {args.window_title!r}), then press {start_key}. {stop_key} stops.', flush=True)
        while not stop.is_set() and not arm.wait(.1):
            pass
        if stop.is_set():
            print('Stopped before starting.')
            return
        hwnd, title = foreground()
        if not hwnd or args.window_title.lower() not in title.lower():
            raise ValueError(f'Foreground title {title!r} does not match --window-title {args.window_title!r}; no input sent.')
        print('Armed for window:', title, flush=True)

        def focused():
            return foreground()[0] == hwnd

        def sample():
            return sample_with_frame()[1]

        def sample_with_frame():
            nonlocal latest_state, latest_sample_ns
            if stop.is_set(): raise RuntimeError(f'{stop_key} emergency stop.')
            if not focused(): raise RuntimeError('Game lost foreground focus.')
            frame = np.asarray(capture.grab(mon))[:, :, :3].copy()
            captured_at = time_ns()
            result = view_state(frame, cfg, args.rage_saturation)
            if not focused() or stop.is_set(): raise RuntimeError('Stopped or focus changed during capture.')
            latest_state, latest_sample_ns = result, captured_at
            record('state')
            return frame, result

        def addon_target_signals():
            from signal_panel import read_panel
            frame, state = sample_with_frame()
            problem = validate_state(state, args.stop_health, require_target=False)
            if problem:
                raise RuntimeError('Addon target check stopped: ' + problem)
            if panel_config.get('cell_count', 7) == 7:
                readings = read_panel(frame, panel_config['rect'])
            else:
                readings = read_panel(frame, panel_config['rect'], panel_config['cell_count'])
            return state, readings

        def verify_attackable_target():
            for _ in range(2):
                state, signals = addon_target_signals()
                if state['combat'] != 'combat' or signals.get('target') != 'yes' or signals.get('hostile') != 'yes':
                    raise RuntimeError('Target is not confidently confirmed attackable during combat; stopped.')
                time.sleep(args.interval)

        def tap(key):
            if stop.is_set() or not focused(): raise RuntimeError('Stopped or game lost focus before input.')
            if not args.live:
                record('planned_key', str(key))
                print(f'WOULD PRESS {key}', flush=True)
                return
            try:
                controller.press(key)
                record('key_sent', str(key))
                deadline = time.monotonic() + args.press_ms/1000
                while time.monotonic() < deadline:
                    if stop.is_set() or not focused():
                        raise RuntimeError('Stopped or focus changed during key press.')
                    time.sleep(min(.02, max(0, deadline-time.monotonic())))
            finally:
                controller.release(key)
            print(f'PRESSED {key} for {args.press_ms} ms (game acceptance not verified)', flush=True)

        def tap_shifted(key):
            label = f'Shift+{key}'
            if stop.is_set() or not focused(): raise RuntimeError('Stopped or game lost focus before input.')
            if not args.live:
                record('planned_key', label)
                print(f'WOULD PRESS {label}', flush=True)
                return
            shift_down = False
            key_down = False
            try:
                controller.press(keyboard.Key.shift)
                shift_down = True
                if stop.is_set() or not focused(): raise RuntimeError('Stopped or focus changed during key press.')
                controller.press(key)
                key_down = True
                record('key_sent', label)
                deadline = time.monotonic() + args.press_ms/1000
                while time.monotonic() < deadline:
                    if stop.is_set() or not focused(): raise RuntimeError('Stopped or focus changed during key press.')
                    time.sleep(min(.02, max(0, deadline-time.monotonic())))
            finally:
                try:
                    if key_down: controller.release(key)
                finally:
                    if shift_down: controller.release(keyboard.Key.shift)
            print(f'PRESSED {label} for {args.press_ms} ms (game acceptance not verified)', flush=True)

        def loot_once():
            if stop.is_set() or not focused():
                raise RuntimeError('Stopped or game lost focus before looting.')
            position = mouse_controller.position
            if not args.live:
                record('planned_loot_click', str(position))
                print(f'WOULD RIGHT-CLICK at {position} (not verified as a corpse).', flush=True)
                return
            try:
                mouse_controller.press(mouse.Button.right)
                record('loot_click_sent', str(position))
            finally:
                mouse_controller.release(mouse.Button.right)
            print(f'RIGHT-CLICKED at {position}; loot success is not verified.', flush=True)

        def move_forward(duration):
            if stop.is_set() or not focused():
                raise RuntimeError('Stopped or focus lost before movement.')
            if not args.live:
                print(f'WOULD HOLD W for {duration:.2f}s; move forward yourself for dry run.', flush=True)
                return
            print(f'Moving forward for up to {duration:.2f}s.', flush=True)
            try:
                controller.press('w')
                record('key_sent', 'w')
                until = time.monotonic() + duration
                while time.monotonic() < until:
                    if stop.is_set() or not focused():
                        raise RuntimeError('Stopped or focus lost during movement.')
                    time.sleep(min(.05, max(0, until-time.monotonic())))
            finally:
                controller.release('w')

        def recover_once():
            deadline = time.monotonic() + args.recovery_timeout
            last_print = None
            full_count = 0
            attempted = False
            while time.monotonic() < deadline:
                current = sample()
                problem = validate_state(current, args.stop_health, require_target=False)
                if problem:
                    raise RuntimeError('Recovery stopped: ' + problem)
                if current['combat'] != 'out_of_combat':
                    raise RuntimeError('Recovery stopped: combat resumed or is uncertain.')
                hp = current['health']
                if hp >= RECOVERY_HEALTH:
                    full_count += 1
                    if full_count >= 3:
                        record('recovery_threshold_met')
                        print('Recovery complete: health estimate at least 50% for three readings.', flush=True)
                        return
                else:
                    full_count = 0
                    if not attempted:
                        print('Health below 50%; attempting recovery macro once.', flush=True)
                        tap_shifted('=')
                        attempted = True
                        if not args.live:
                            print('Dry run: use your recovery macro manually so health can change.', flush=True)
                rounded = round(hp * 100)
                if rounded != last_print:
                    print(f'Recovery health estimate: {rounded}%', flush=True)
                    last_print = rounded
                time.sleep(args.interval)
            raise RuntimeError('Recovery timed out; full health was not verified.')

        def approach_with_keyboard(min_start_health):
            search_deadline = (None if args.search_seconds is None
                               else time.monotonic() + args.search_seconds)
            approach_deadline = None
            walking = False
            charge_attempted = False
            shot_sent = False
            shots_attempted = 0
            shoot_after = 0.0
            next_target_attempt = 0.0
            target_attempts = 0
            try:
                while True:
                    frame, state = sample_with_frame()
                    problem = validate_state(state, args.stop_health, require_target=False)
                    if problem:
                        raise RuntimeError('Keyboard approach stopped: ' + problem)
                    if state['combat'] == 'combat':
                        record('keyboard_engaged')
                        return
                    if shot_sent:
                        if time.monotonic() < approach_deadline:
                            time.sleep(args.interval)
                            continue
                        if shots_attempted >= 3:
                            raise RuntimeError('Shoot Gun did not start combat after three attempts.')
                        shot_sent = False
                        approach_deadline = None
                        search_deadline = (None if args.search_seconds is None
                                           else time.monotonic() + args.search_seconds)
                        target_attempts = 0
                        next_target_attempt = 0.0
                        record('shoot_gun_retry', 'No combat after shot; rechecking aim and range')
                        print('Shot did not start combat; checking aim and range again.', flush=True)
                    if state['health'] < min_start_health:
                        raise RuntimeError('Keyboard approach stopped: health below start threshold.')
                    point = marker_click_point(frame, args.marker_offset_y)
                    now = time.monotonic()
                    if point is None and approach_deadline is not None:
                        approach_deadline = None
                        search_deadline = None if args.search_seconds is None else now + args.search_seconds
                        record('keyboard_search_resumed', 'Enemy marker lost before engagement')
                        target_attempts = 0
                    elif point is not None and approach_deadline is None:
                        approach_deadline = now + args.marker_timeout
                    deadline = approach_deadline if point is not None else search_deadline
                    if deadline is not None and now >= deadline:
                        raise RuntimeError('Keyboard approach timed out before combat.')
                    turn = None
                    charge_ready = False
                    shoot_ready = False
                    select_target = False
                    if point is not None:
                        horizontal_error = point[0] / mon['width'] - .5
                        if abs(horizontal_error) > .04:
                            turn = 'a' if horizontal_error < 0 else 'd'
                        elif args.shoot_pull:
                            from signal_panel import read_panel
                            signals = read_panel(frame, panel_config['rect'], panel_config['cell_count'])
                            living_target = (signals.get('target') == signals.get('hostile') == 'yes'
                                             and state['target'] == 'present' and (state.get('target_health') or 0) > .02)
                            shoot_ready = living_target and signals.get('shoot_gun_ready') == 'yes'
                            select_target = not living_target and target_attempts < 2 and now >= next_target_attempt
                        elif not charge_attempted and state['target'] == 'present' and (state.get('target_health') or 0) > .02:
                            from signal_panel import read_panel
                            signals = read_panel(frame, panel_config['rect'], panel_config.get('cell_count', 7))
                            charge_ready = all(signals.get(key) == 'yes' for key in
                                               ('target', 'hostile', 'charge_usable', 'charge_range'))
                    if (turn or charge_ready or shoot_ready or select_target) and walking:
                        if args.live:
                            controller.release('w')
                        walking = False
                        shoot_after = time.monotonic() + .5
                    if turn:
                        record('keyboard_steer', turn)
                        tap(turn)
                        shoot_after = time.monotonic() + .5
                    elif shoot_ready:
                        remaining = shoot_after - time.monotonic()
                        if remaining > 0:
                            record('shoot_gun_settling')
                            time.sleep(min(args.interval, remaining))
                            continue
                        record('shoot_gun_ready', 'Centered marker and selected hostile target in gun range')
                        tap_shifted('0')
                        shot_sent = True
                        shots_attempted += 1
                        approach_deadline = time.monotonic() + args.engage_timeout
                    elif select_target:
                        tap(keyboard.Key.tab)
                        target_attempts += 1
                        next_target_attempt = time.monotonic() + 1
                    elif charge_ready:
                        record('charge_ready', 'hostile selected target, usable and in range')
                        tap('3')
                        charge_attempted = True
                        time.sleep(.5)
                    elif not walking:
                        if stop.is_set() or not focused():
                            raise RuntimeError('Stopped or focus lost before movement.')
                        if args.live:
                            controller.press('w')
                            walking = True
                            record('key_sent', 'w')
                        else:
                            walking = True
                            record('planned_key', 'w')
                            print('DRY RUN: hold W to walk toward the marker.', flush=True)
                    time.sleep(args.interval)
            finally:
                if walking and args.live:
                    controller.release('w')

        def run_one_fight(min_start_health):
            # Require multiple consecutive fresh readings before the one and only auto-attack press.
            for _ in range(3):
                s = sample()
                problem = validate_state(s, args.stop_health, require_target=not (args.auto_target or args.marker_move))
                if problem: raise RuntimeError('Start refused: ' + problem)
                if s['health'] < min_start_health or s['combat'] != 'out_of_combat':
                    raise RuntimeError('Start refused: health below start threshold or already in combat.')
                time.sleep(args.interval)
            marker_engaged = False
            marker_started_by_charge = False
            if args.marker_move:
                if args.keyboard_approach:
                    approach_with_keyboard(min_start_health)
                    marker_engaged = True
                else:
                    walking = False
                    deadline = time.monotonic() + args.search_seconds
                    try:
                        while True:
                            frame, s = sample_with_frame()
                            problem = validate_state(s, args.stop_health, require_target=False)
                            if problem or s['combat'] != 'out_of_combat' or s['health'] < min_start_health:
                                raise RuntimeError('Enemy search stopped: ' + (problem or 'combat active or health below start threshold.'))
                            point = marker_click_point(frame, args.marker_offset_y)
                            if point is not None:
                                break
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise RuntimeError('Enemy search ended: no eligible marker in view.')
                            if not walking:
                                if stop.is_set() or not focused():
                                    raise RuntimeError('Stopped or focus lost before movement.')
                                if args.live:
                                    controller.press('w')
                                    walking = True
                                    record('key_sent', 'w')
                                    print('Walking forward while scanning for enemies.', flush=True)
                                else:
                                    print('DRY RUN: walk forward manually to test enemy search.', flush=True)
                                walking = True
                            time.sleep(min(.25, remaining))
                    finally:
                        if walking and args.live:
                            controller.release('w')
                    move_deadline = time.monotonic() + args.marker_timeout
                    last_click = None
                    next_redirect = 0.0
                    stationary_retry_used = False
                    charge_attempted = False
                    turn_attempts = 0
                    try:
                        while True:
                            now = time.monotonic()
                            if s['combat'] == 'combat':
                                marker_engaged = True
                                marker_started_by_charge = charge_attempted and last_click is None
                                print('Combat detected; stopping click-to-move.', flush=True)
                                break
                            if now >= move_deadline:
                                raise RuntimeError('No combat detected before movement timeout.')
                            if stop.is_set() or not focused():
                                raise RuntimeError('Stopped or focus lost before approach input.')
                            charge_ready = False
                            if point is not None and panel_config and not charge_attempted and s['target'] == 'present':
                                from signal_panel import read_panel
                                signals = read_panel(frame, panel_config['rect'], panel_config.get('cell_count', 7))
                                charge_ready = all(signals.get(key) == 'yes' for key in
                                                   ('target', 'hostile', 'charge_usable', 'charge_range'))
                            moved = point is not None and (last_click is None or math.dist(point, last_click) >= 24)
                            retry = (point is not None and not moved and not stationary_retry_used
                                     and now >= next_redirect + 1.25)
                            horizontal_error = point[0] / mon['width'] - .5 if point is not None else 0
                            aligned = abs(horizontal_error) <= .04
                            if charge_ready and not aligned and turn_attempts < 8:
                                turn_key = 'a' if horizontal_error < 0 else 'd'
                                record('turn_before_charge', turn_key)
                                tap(turn_key)
                                turn_attempts += 1
                            elif charge_ready and aligned:
                                record('charge_ready', 'hostile selected target, usable and in range')
                                print('Charge available and in range on selected hostile target.', flush=True)
                                tap('3')
                                charge_attempted = True
                                next_redirect = time.monotonic() + .75
                            elif now >= next_redirect and (moved or retry):
                                if retry:
                                    stationary_retry_used = True
                                    record('approach_retry', 'No combat after previous click')
                                px, py = point
                                destination = (mon['left'] + px, mon['top'] + py)
                                print(f'Marker click point: {destination}', flush=True)
                                if args.live:
                                    original = mouse_controller.position
                                    try:
                                        mouse_controller.position = destination
                                        if stop.is_set() or not focused():
                                            raise RuntimeError('Stopped or focus lost before click.')
                                        try:
                                            mouse_controller.press(mouse.Button.right)
                                            record('approach_click_sent', str(destination))
                                        finally:
                                            mouse_controller.release(mouse.Button.right)
                                    finally:
                                        mouse_controller.position = original
                                else:
                                    record('planned_approach_click', str(destination))
                                    print('DRY RUN: click toward the marker yourself.', flush=True)
                                last_click = point
                                next_redirect = time.monotonic() + .75
                            time.sleep(args.interval)
                            frame, s = sample_with_frame()
                            problem = validate_state(s, args.stop_health, require_target=False)
                            if problem:
                                raise RuntimeError('Movement stopped: ' + problem)
                            if s['combat'] == 'out_of_combat':
                                point = marker_click_point(frame, args.marker_offset_y)
                    finally:
                        if focused() and args.live:
                            try:
                                controller.press('s')
                                record('key_sent', 's')
                            finally: controller.release('s')
                            print('Tapped S to cancel movement; cancellation not verified.', flush=True)
                        elif not focused() and args.live:
                            print('Game lost focus; movement was NOT cancelled. Stop it manually.', flush=True)
                        elif not args.live:
                            print('DRY RUN: stop your movement manually.', flush=True)
                s = sample()
                problem = validate_state(s, args.stop_health, require_target=False)
                if problem or s['combat'] != 'combat':
                    raise RuntimeError('Target acquisition stopped: ' + (problem or 'combat no longer active.'))
                needs_target = s['target'] != 'present'
                if args.keyboard_approach and not needs_target:
                    s, signals = addon_target_signals()
                    needs_target = (signals.get('hostile') != 'yes' or (s.get('target_health') or 0) <= .02)
                if needs_target:
                    print('No target confidently detected; attempting Tab once.', flush=True)
                    tap(keyboard.Key.tab)
                    if not args.live:
                        print('DRY RUN: select the enemy yourself now.', flush=True)
                    deadline = time.monotonic() + 3
                    confirmed = 0
                    while time.monotonic() < deadline:
                        s = sample()
                        problem = validate_state(s, args.stop_health, require_target=False)
                        if problem or s['combat'] != 'combat':
                            raise RuntimeError('Target acquisition stopped: ' + (problem or 'combat no longer active.'))
                        target_ready = s['target'] == 'present'
                        if args.keyboard_approach and target_ready:
                            s, signals = addon_target_signals()
                            target_ready = (s['combat'] == 'combat' and signals.get('hostile') == 'yes'
                                            and (s.get('target_health') or 0) > .02)
                        confirmed = confirmed + 1 if target_ready else 0
                        if confirmed >= 2: break
                        time.sleep(args.interval)
                    else:
                        raise RuntimeError('Target not confidently detected after Tab; fight stopped.')
                if args.fights > 1 or args.keyboard_approach:
                    verify_attackable_target()
                if args.keyboard_approach:
                    tap('1')
                elif not marker_started_by_charge:
                    print('Combat and target detected; relying on the initial right-click to start auto-attack. Key 1 will not be pressed.', flush=True)
            if args.auto_target:
                print('Attempting Tab once. A visible target frame does not prove a safe enemy was selected.', flush=True)
                tap(keyboard.Key.tab)
                if not args.live:
                    print('Dry run: press Tab yourself within 3 seconds to select an enemy.', flush=True)
                time.sleep(3 if not args.live else .75)
                target_deadline = time.monotonic() + 3.0
                target_confirmations = 0
                last_target_reading = None
                while time.monotonic() < target_deadline:
                    s = sample()
                    problem = validate_state(s, args.stop_health, require_target=False)
                    if problem or s['combat'] != 'out_of_combat':
                        raise RuntimeError('After Tab: ' + (problem or 'combat already started.'))
                    if s['target'] != last_target_reading:
                        print(f"After Tab: target reading is {s['target']}; checking again.", flush=True)
                        last_target_reading = s['target']
                    target_confirmations = target_confirmations + 1 if s['target'] == 'present' else 0
                    if target_confirmations >= 2:
                        print('Target frame detected in two consecutive readings.', flush=True)
                        break
                    time.sleep(args.interval)
                else:
                    raise RuntimeError('After Tab: target not confidently detected within 3 seconds; no movement or attacks attempted.')
            print(f'Starting one fight; press {stop_key} at any time to stop.', flush=True)
            last_charge = None
            charge_attempts = 0
            if marker_engaged:
                pass  # Marker right-click is expected to have started auto-attack.
            elif args.charge:
                s = sample()
                problem = validate_state(s, args.stop_health)
                if problem or s['combat'] != 'out_of_combat':
                    raise RuntimeError('Charge refused: ' + (problem or 'combat is not confirmed inactive.'))
                if s['icons'].get('charge_appearance') != 'bright_like' and not args.approach:
                    raise RuntimeError('Charge icon is dim or uncertain. Target may be out of range; no movement attempted.')
                if s['icons'].get('charge_appearance') == 'bright_like':
                    print('Charge looks bright; range and path are not verified.', flush=True)
                    tap('3')
                    last_charge = time.monotonic()
                    charge_attempts += 1
                    print('Waiting for combat to confirm engagement.', flush=True)
                    if not args.live:
                        print('Dry run: press Charge yourself so combat can begin.', flush=True)
                else:
                    print('Charge looks dim or uncertain; beginning bounded approach.', flush=True)
            else:
                tap('1')
            started = time.monotonic()
            combat_seen = marker_engaged
            auto_attack_sent = (not marker_started_by_charge) if marker_engaged else (not args.charge)
            out_since = None
            target_lost_at = None
            retarget_attempts = 0
            next_retarget = 0.0
            targets_reacquired = 0
            saw_selected_marker = False
            last_turn = 'd'
            offscreen_since = None
            combat_unknown_at = None
            last_ability = 0.0
            previous = None
            forward_total = 0.0
            while not stop.is_set():
                now = time.monotonic()
                if now-started > args.max_seconds:
                    raise RuntimeError('Time limit reached.')
                if panel_config:
                    frame, s = sample_with_frame()
                else:
                    s = sample()
                # The health bar and combat indicator can both disappear for
                # a frame. Recheck before acting on a low or unreadable value.
                for _ in range(2):
                    hp = s.get('health')
                    if hp is not None and math.isfinite(hp) and args.stop_health < hp <= 1:
                        break
                    record('health_recheck', 'Low or unreadable health; inputs paused')
                    time.sleep(.15)
                    frame, s = sample_with_frame()
                if s['combat'] not in ('combat', 'out_of_combat'):
                    # A transient border transition is ambiguous. Do not attack,
                    # loot, or recover until a fresh, known combat state returns.
                    problem = validate_state({**s, 'combat': 'out_of_combat'}, args.stop_health, require_target=False)
                    if problem:
                        raise RuntimeError(problem)
                    out_since = None
                    if combat_unknown_at is None:
                        combat_unknown_at = now
                        print('Combat state uncertain: inputs paused while checking again.', flush=True)
                    if now-combat_unknown_at >= 4:
                        raise RuntimeError('Combat state remained unknown for 4 seconds; no loot attempted.')
                    time.sleep(args.interval)
                    continue
                combat_unknown_at = None
                problem = validate_state(s, args.stop_health, require_target=not combat_seen and s['combat'] != 'combat')
                if problem: raise RuntimeError(problem)
                if s['combat'] == 'combat':
                    combat_seen = True
                    out_since = None
                    target_hp = s.get('target_health')
                    health_readable = target_hp is not None and math.isfinite(target_hp)
                    signals = {}
                    if panel_config:
                        from signal_panel import read_panel
                        signals = read_panel(frame, panel_config['rect'], panel_config.get('cell_count', 7))
                    target_ready = s['target'] == 'present' and (
                        (health_readable and target_hp > 0)
                        or (args.execute and signals.get('execute_usable') == 'yes')
                    )
                    if panel_config:
                        target_ready = signals.get('target') == signals.get('hostile') == 'yes'
                    confirmed_lost = (signals.get('target') == 'no' or
                                      (signals.get('target') == 'yes' and signals.get('hostile') == 'no'))
                    if not target_ready:
                        if target_lost_at is None:
                            target_lost_at = now
                            retarget_attempts = 0
                            next_retarget = now + .75
                            record('combat_target_lost')
                            print('Target unavailable: attacks paused while checking combat.', flush=True)
                        if now - target_lost_at >= 8:
                            raise RuntimeError('Combat continued but no usable target could be reacquired.')
                        if not confirmed_lost:
                            next_retarget = now + .75
                        if confirmed_lost and retarget_attempts < 3 and now >= next_retarget:
                            tap(keyboard.Key.tab)
                            retarget_attempts += 1
                            next_retarget = now + 1
                            record('combat_retarget_attempt', str(retarget_attempts))
                    else:
                        if target_lost_at is not None:
                            if retarget_attempts:
                                targets_reacquired += 1
                                auto_attack_sent = False
                                saw_selected_marker = False
                                offscreen_since = None
                                record('combat_target_reacquired', str(targets_reacquired))
                                print('Target reacquired while combat was still active.', flush=True)
                            target_lost_at = None
                        if args.face_target:
                            from signal_panel import find_markers
                            selected = find_markers(frame, selected=True)
                            turn = None
                            if len(selected) == 1:
                                saw_selected_marker = True
                                offscreen_since = None
                                x, _, width, _ = selected[0]
                                error = (x + width / 2) / mon['width'] - .5
                                if abs(error) > .04:
                                    turn = 'a' if error < 0 else 'd'
                                    last_turn = turn
                            elif not selected and saw_selected_marker:
                                if offscreen_since is None:
                                    offscreen_since = now
                                if now - offscreen_since < 7:
                                    turn = last_turn
                            if turn:
                                record('combat_turn', turn)
                                tap(turn)
                                time.sleep(args.interval)
                                continue
                        action = s['action']
                        if action == 'victory_rush' and signals.get('victory_rush_usable') != 'yes':
                            action = 'heroic_strike' if s['icons'].get('heroic_strike_appearance') == 'bright_like' else 'wait'
                        if args.execute and action in ('heroic_strike', 'wait'):
                            if signals['target'] == signals['hostile'] == signals['execute_usable'] == 'yes':
                                action = 'execute'
                        if action != 'execute' and not panel_config:
                            if not health_readable:
                                raise RuntimeError('Target health is missing or uncertain.')
                            if target_hp <= .02:
                                action = 'wait'
                        if not auto_attack_sent and (panel_config or (health_readable and target_hp > .02)):
                            tap('1')
                            auto_attack_sent = True
                        if action in KEYS and now-last_ability >= args.ability_spacing:
                            record('ability_selected', action)
                            tap(KEYS[action])
                            last_ability = now
                elif combat_seen:
                    target_lost_at = None
                    if out_since is None: out_since = now
                    if now-out_since >= 1:
                        record('combat_ended')
                        print('Combat ended; enemy death is not verified.', flush=True)
                        if args.loot:
                            loot_once()
                        if args.recover:
                            recover_once()
                        record('fight_cycle_complete')
                        print('One-fight test complete.', flush=True)
                        return
                elif now-started > args.engage_timeout:
                    raise RuntimeError(f'Combat did not start within {args.engage_timeout:g} seconds; Charge success was not confirmed.')
                elif args.charge and args.approach:
                    # Leave time after a Charge attempt for combat to appear, then
                    # walk only a bounded amount; no obstacle or cliff sensing.
                    if last_charge is None or now-last_charge >= 1.5:
                        if forward_total >= args.max_forward_seconds:
                            raise RuntimeError('Approach limit reached without confirmed combat.')
                        step = min(.25, args.max_forward_seconds-forward_total)
                        move_forward(step)
                        forward_total += step
                        next_state = sample()
                        problem = validate_state(next_state, args.stop_health)
                        if problem:
                            raise RuntimeError('Approach stopped: ' + problem)
                        if next_state['combat'] == 'combat':
                            print('Combat detected during approach.', flush=True)
                        elif next_state['icons'].get('charge_appearance') == 'bright_like' and charge_attempts < 3:
                            tap('3')
                            last_charge = time.monotonic()
                            charge_attempts += 1
                            print(f'Charge attempt {charge_attempts}/3; waiting for combat.', flush=True)
                        else:
                            print(f'Charge not confirmed ready; walked {forward_total:.2f}/{args.max_forward_seconds:.2f} seconds.', flush=True)
                signature = (round(s['health']*100), s['combat'], s['target'], s['action'])
                if signature != previous:
                    print(f"Health {s['health']:.0%} | {s['combat']} | target {s['target']} | proposed {s['action']}", flush=True)
                    previous = signature
                time.sleep(args.interval)
            print(f'{stop_key} emergency stop.', flush=True)

        for fight_number in range(1, args.fights + 1):
            if stop.is_set():
                print(f'{stop_key} emergency stop.', flush=True)
                break
            print(f'Fight {fight_number}/{args.fights}', flush=True)
            min_start_health = args.min_start_health if fight_number == 1 else RECOVERY_HEALTH
            latest_state, latest_sample_ns = {}, None
            record('fight_started')
            try:
                run_one_fight(min_start_health)
            except (Exception, KeyboardInterrupt) as exc:
                record('stopped', str(exc) or 'Ctrl+C')
                raise
            if stop.is_set():
                record('stopped', 'emergency stop')
                break
            if fight_number < args.fights:
                print('Ready to check the next fight.', flush=True)
    listener.stop()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped by Ctrl+C.')
    except Exception as exc:
        print(f'STOPPED: {exc}')
