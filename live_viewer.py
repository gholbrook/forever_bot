"""Live, read-only WoW UI viewer using the user's existing calibrations."""
import argparse
import json
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import mss
import numpy as np
import cv2

from state_reader import crop, health, classify as compare_states
from ability_states import read
from priority_replay import classify as compare_icon, priority
from target_examples import load_examples, classify_target
from combat_signal import classify_color as classify_combat_indicator

CAL = Path('calibration')
ICONS = ('overpower', 'victory_rush', 'heroic_strike', 'charge')


def load_json(name):
    return json.loads((CAL / name).read_text(encoding='utf-8'))


def load_calibrations():
    cfg = {'base': load_json('config.json'), 'extra': load_json('extra.json'),
           'icons': load_json('ability_icons.json'), 'overpower': load_json('overpower_icon.json')}
    cfg['calm'] = read(CAL / 'out_of_combat.png')
    cfg['combat'] = read(CAL / 'combat.png')
    cfg['absent'] = read(CAL / 'target_absent.png')
    cfg['present'] = read(CAL / 'target_present.png')
    cfg['target_examples'] = load_examples()
    cfg['refs'] = {name: (read(CAL / f'{name}_bright.png'), read(CAL / f'{name}_dim.png')) for name in ICONS}
    return cfg


def configure_combat_indicator(cfg):
    indicator = load_json('combat_signal.json')
    if indicator.get('screen') != cfg['base']['screen']:
        raise ValueError('Combat indicator calibration uses a different monitor; recalibrate it.')
    rect = indicator.get('rect')
    screen = cfg['base']['screen']
    if not isinstance(rect, list) or len(rect) != 4 or any(not isinstance(n, int) for n in rect):
        raise ValueError('Invalid combat indicator rectangle; recalibrate it.')
    x, y, w, h = rect
    if x < 0 or y < 0 or w < 3 or h < 3 or x + w > screen['width'] or y + h > screen['height']:
        raise ValueError('Combat indicator rectangle is outside the monitor; recalibrate it.')
    cfg['combat_signal'] = indicator


def red_fill_fraction(columns, max_gap=2):
    """Estimate a left-anchored fill, ignoring tiny gaps and trailing specks."""
    last_match = -1
    gap = 0
    for index, matched in enumerate(columns):
        if matched:
            last_match = index
            gap = 0
        else:
            gap += 1
            if gap > max_gap:
                break
    return (last_match + 1) / len(columns) if columns else 0.0


def strict_rage(frame, rect, min_saturation=180, min_value=90):
    image = crop(frame, rect)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    low = cv2.inRange(hsv, np.array([0, min_saturation, min_value], np.uint8), np.array([8, 255, 255], np.uint8))
    high = cv2.inRange(hsv, np.array([172, min_saturation, min_value], np.uint8), np.array([179, 255, 255], np.uint8))
    columns = ((low | high) > 0).mean(axis=0) >= .50
    return red_fill_fraction(columns.tolist())


def view_state(frame, cfg, rage_saturation=180):
    base, extra, icons = cfg['base'], cfg['extra'], cfg['icons']
    hp, _ = health(frame, base['health_rect'])
    rage_value = strict_rage(frame, extra['rage_rect'], rage_saturation)
    if 'combat_signal' in cfg:
        combat = classify_combat_indicator(frame, cfg['combat_signal']['rect'])
    else:
        combat, _, _ = compare_states(crop(frame, base['combat_rect']), cfg['calm'], cfg['combat'])
    target, _, _ = classify_target(crop(frame, extra['target_rect']), cfg['target_examples'])
    target_hp = health(frame, extra['target_health_rect'])[0] if target == 'present' else None
    row = {'combat_estimate': combat, 'target_presence_estimate': target}
    for name in ICONS:
        settings = cfg['overpower'] if name == 'overpower' else icons[name]
        bright, dim = cfg['refs'][name]
        appearance, _, _ = compare_icon(crop(frame, settings['rect']), bright, dim, settings['separation'])
        row[name + '_appearance'] = appearance
    action, reason = priority(row)
    if combat == 'out_of_combat' and target == 'present':
        action, reason = 'wait', 'Selected target seen; engagement is not implemented.'
    elif combat == 'out_of_combat' and hp < .90:
        action, reason = 'wait', 'Low health estimate; recovery conditions are not verified.'
    return {'health': hp, 'rage': rage_value, 'combat': combat, 'target': target,
            'target_health': target_hp, 'icons': row, 'action': action, 'reason': reason}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interval', type=float, default=.5, help='Seconds between updates (minimum 0.2)')
    parser.add_argument('--rage-saturation', type=int, default=180, help='Minimum red saturation (0-255; default 180)')
    parser.add_argument('--combat-indicator', action='store_true', help='Use the calibrated addon square for combat state.')
    args = parser.parse_args()
    if args.interval < .2:
        parser.error('--interval must be at least 0.2 seconds')
    if not 0 <= args.rage_saturation <= 255:
        parser.error('--rage-saturation must be from 0 to 255')
    cfg = load_calibrations()
    if args.combat_indicator:
        configure_combat_indicator(cfg)
    capture = mss.mss()
    mon_num = cfg['base']['monitor']
    if mon_num < 1 or mon_num >= len(capture.monitors):
        raise ValueError('Calibrated monitor no longer exists. Recalibrate on the current setup.')
    monitor = capture.monitors[mon_num]
    if monitor != cfg['base']['screen']:
        raise ValueError('Monitor geometry changed since calibration. Recalibrate before running.')
    size = (monitor['width'], monitor['height'])
    for name in ('extra', 'icons', 'overpower'):
        if (cfg[name]['width'], cfg[name]['height']) != size:
            raise ValueError(f'{name} calibration resolution does not match the monitor.')

    root = tk.Tk()
    root.title('WoW observer — READ ONLY')
    root.attributes('-topmost', True)
    root.geometry('500x350+40+40')
    text = tk.StringVar(value='Starting...')
    tk.Label(root, text='READ ONLY — no keys or clicks sent', fg='darkgreen', font=('Segoe UI', 11, 'bold')).pack(pady=6)
    tk.Label(root, textvariable=text, justify='left', anchor='nw', font=('Consolas', 11)).pack(fill='both', expand=True, padx=12)
    tk.Button(root, text='Stop viewer', command=root.destroy, width=18).pack(pady=8)

    def update():
        try:
            frame = np.asarray(capture.grab(monitor))[:, :, :3].copy()
            state = view_state(frame, cfg, args.rage_saturation)
            icons = state['icons']
            enemy_hp = f"{state['target_health']:.0%}" if state['target_health'] is not None else 'unknown'
            keys = {'overpower':'7', 'victory_rush':'0', 'heroic_strike':'2', 'wait':'—'}
            text.set(f"Your health: ~{state['health']:.0%}   Rage: ~{state['rage']:.0%}\n"
                     f"Combat: {state['combat']}\nTarget: {state['target']}   Target health: {enemy_hp}\n\n"
                     f"Overpower:     {icons['overpower_appearance']}\n"
                     f"Victory Rush:  {icons['victory_rush_appearance']}\n"
                     f"Heroic Strike: {icons['heroic_strike_appearance']}\n\n"
                     f"Proposed: {state['action']} (key {keys[state['action']]})\n"
                     f"{state['reason']}\nUpdated: {time.strftime('%H:%M:%S')}")
            root.after(int(args.interval*1000), update)
        except Exception as exc:
            text.set(f'Viewer stopped due to an error:\n{exc}\n\nClose this window and check calibrations.')
    try:
        root.after(50, update)
        root.mainloop()
    finally:
        capture.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Error: {exc}')
