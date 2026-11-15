"""Record game-state estimates and action-key attempts without controlling WoW."""
import argparse
import csv
import json
import queue
import time
from datetime import datetime
from pathlib import Path

import mss
import numpy as np
from pynput import keyboard, mouse

from live_viewer import load_calibrations, configure_combat_indicator, view_state
from one_fight import foreground
from signal_panel import ALL_SIGNALS, find_markers, read_panel

MAIN = {'1':'auto_attack', '2':'heroic_strike', '3':'charge', '4':'thunder_clap',
        '5':'rend', '6':'hamstring', '7':'overpower', '8':'cleave', '9':'slam',
        '0':'victory_rush', '-':'sunder_armor', '=':'execute'}
SHIFTED = {'1':'shadowmeld', '2':'battle_shout', '3':'elunes_light', '4':'bloodrage',
           '5':'demoralizing_shout', '6':'mocking_blow', '7':'shield_bash',
           '8':'retaliation', '9':'intimidating_shout', '0':'shoot_gun', '=':'recover'}
SHIFT_CHARS = dict(zip('!@#$%^&*()_+', '1234567890-='))
MOVEMENT = {'w':'forward', 's':'backward', 'a':'turn_left', 'd':'turn_right',
            'q':'strafe_left', 'e':'strafe_right'}
SPECIAL_INPUTS = {keyboard.Key.tab:'target_tab', keyboard.Key.space:'jump',
                  keyboard.Key.up:'forward', keyboard.Key.down:'backward',
                  keyboard.Key.left:'turn_left', keyboard.Key.right:'turn_right'}


def navigation_action(key):
    if key in SPECIAL_INPUTS:
        return SPECIAL_INPUTS[key]
    char = getattr(key, 'char', None)
    return MOVEMENT.get(char.lower()) if char else None


def identify(key, shift):
    """Accept either a Windows virtual key or a shifted character from pynput."""
    vk = getattr(key, 'vk', None)
    char = getattr(key, 'char', None)
    if vk is not None and 48 <= vk <= 57:
        base = chr(vk)
    elif vk in (187, 189):
        base = '=' if vk == 187 else '-'
    elif char in SHIFT_CHARS:
        base, shift = SHIFT_CHARS[char], True
    else:
        base = char
    if not base:
        return None
    action = (SHIFTED if shift else MAIN).get(base)
    return (('Shift+' if shift else '') + base, action) if action else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interval', type=float, default=.5, help='Seconds between state samples (minimum 0.2).')
    parser.add_argument('--window-title', default='Warcraft', help='Part of the game window title.')
    parser.add_argument('--output', type=Path, help='New output folder; default is a timestamped folder.')
    parser.add_argument('--selection', action='store_true',
                        help='Record visible enemy markers and navigation inputs.')
    args = parser.parse_args()
    if args.interval < .2: parser.error('interval must be at least 0.2 seconds')
    if not args.window_title.strip(): parser.error('window title must not be empty')
    cfg = load_calibrations()
    configure_combat_indicator(cfg)
    panel = json.loads(Path('calibration/signal_panel.json').read_text(encoding='utf-8'))
    if panel.get('screen') != cfg['base']['screen']:
        raise ValueError('Signal panel and monitor calibrations do not match.')
    output = args.output or Path('observation_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    output.mkdir(parents=True, exist_ok=False)
    events = queue.Queue()
    navigation = queue.Queue()
    navigation_down = {}
    shifts = set()
    down = set()
    shift_keys = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}

    def game_focused():
        hwnd, title = foreground()
        return hwnd and args.window_title.lower() in title.lower()

    def pressed(key):
        if key in shift_keys:
            shifts.add(key)
            return
        if key in down: return
        down.add(key)
        action = navigation_action(key) if args.selection else None
        if action and game_focused():
            navigation_down[key] = action
            navigation.put((time.time_ns(), 'key_down', action, '', ''))
        match = identify(key, bool(shifts))
        if match and game_focused():
            events.put((time.time_ns(), *match))

    def released(key):
        shifts.discard(key)
        down.discard(key)
        action = navigation_down.pop(key, None)
        if action:
            navigation.put((time.time_ns(), 'key_up', action, '', ''))

    def clicked(x, y, button, pressed):
        if pressed and button in (mouse.Button.left, mouse.Button.right) and game_focused():
            navigation.put((time.time_ns(), 'click', button.name,
                            x - monitor['left'], y - monitor['top']))

    with mss.mss() as capture:
        index = cfg['base']['monitor']
        if index < 1 or index >= len(capture.monitors) or capture.monitors[index] != cfg['base']['screen']:
            raise ValueError('Calibrated monitor is unavailable or its geometry changed.')
        monitor = capture.monitors[index]
        metadata = {'timestamp_unit':'unix_nanoseconds', 'sample_interval_seconds':args.interval,
                    'window_title_filter':args.window_title, 'monitor':monitor,
                    'selection_recording':args.selection,
                    'coordinates':'Marker boxes and mouse clicks are relative to the calibrated monitor.',
                    'notes':'Key presses are attempts, not confirmed casts. Keys typed in game chat may also appear. Screen values are estimates. Addon timestamps are only coarse absolute seconds; do not assume exact alignment.'}
        (output/'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        from contextlib import ExitStack
        with ExitStack() as stack:
            def output_csv(name):
                handle = stack.enter_context((output/name).open('w', newline='', encoding='utf-8'))
                return csv.writer(handle)

            sf = stack.enter_context((output/'states.csv').open('w', newline='', encoding='utf-8'))
            ef = stack.enter_context((output/'key_attempts.csv').open('w', newline='', encoding='utf-8'))
            states, keys = csv.writer(sf), csv.writer(ef)
            if args.selection:
                scene = output_csv('enemy_scene.csv')
                inputs = output_csv('navigation_inputs.csv')
                scene.writerow(['unix_ns', 'enemy_marker_boxes', 'selected_marker_boxes'])
                inputs.writerow(['unix_ns', 'event', 'action', 'x', 'y'])
                mouse_listener = mouse.Listener(on_click=clicked)
                mouse_listener.start()
                stack.callback(mouse_listener.stop)
            names = ALL_SIGNALS
            states.writerow(['unix_ns','health_fraction','rage_fraction','combat','target','target_health_fraction', *['signal_'+n for n in names]])
            keys.writerow(['unix_ns','key','action'])
            listener = keyboard.Listener(on_press=pressed, on_release=released)
            listener.start()
            print(f'READ ONLY: recording to {output}. Play normally; Ctrl+C in this window stops.', flush=True)
            count = 0
            try:
                while True:
                    began = time.monotonic()
                    hwnd, title = foreground()
                    if hwnd and args.window_title.lower() in title.lower():
                        before = time.time_ns()
                        frame = np.asarray(capture.grab(monitor))[:,:,:3].copy()
                        after = time.time_ns()
                        _, title_after = foreground()
                        if args.window_title.lower() in title_after.lower():
                            state = view_state(frame, cfg)
                            signals = read_panel(frame, panel['rect'], panel.get('cell_count', 7))
                            states.writerow([(before+after)//2,state['health'],state['rage'],state['combat'],state['target'],state['target_health'],*[signals.get(n, 'unknown') for n in names]])
                            if args.selection:
                                scene.writerow([(before+after)//2, json.dumps(find_markers(frame)),
                                                json.dumps(find_markers(frame, selected=True))])
                            count += 1
                    while not events.empty(): keys.writerow(events.get_nowait())
                    if args.selection:
                        while not navigation.empty(): inputs.writerow(navigation.get_nowait())
                    sf.flush(); ef.flush()
                    time.sleep(max(0, args.interval-(time.monotonic()-began)))
            except KeyboardInterrupt:
                pass
            finally:
                listener.stop()
                while not events.empty(): keys.writerow(events.get_nowait())
                if args.selection:
                    mouse_listener.stop()
                    while not navigation.empty(): inputs.writerow(navigation.get_nowait())
            print(f'Saved {count} state samples in {output}.')


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError) as exc: raise SystemExit(f'Error: {exc}')
