"""Experimental one-click movement test. Preview by default; --live sends input."""
import argparse
import ctypes
import json
import math
import threading
import time
from pathlib import Path

import cv2
import mss
import numpy as np
from pynput import keyboard, mouse
from state_reader import health
from combat_signal import classify_color
from signal_panel import find_markers
from one_fight import foreground, matches_hotkey, parse_hotkey


def choose_candidate(frame, offset):
    h, w = frame.shape[:2]
    options = []
    for x, y, bw, bh in find_markers(frame):
        px, py = x + bw//2, y + bh + offset
        # Keep candidate and click away from screen edges and common UI areas.
        if .08*w <= px <= .88*w and .12*h <= py <= .80*h:
            options.append((x,y,bw,bh,px,py))
    if not options:
        raise ValueError('No marker with a click point inside the central screen area.')
    # Center-most horizontally, not assumed nearest in 3D.
    return min(options, key=lambda b: abs(b[4] - w/2))


def annotated(frame, candidate):
    x,y,w,h,px,py = candidate
    img = frame.copy()
    cv2.rectangle(img,(x-4,y-4),(x+w+4,y+h+4),(0,255,255),2)
    cv2.line(img,(px,y+h),(px,py),(255,255,0),2)
    cv2.drawMarker(img,(px,py),(0,255,255),cv2.MARKER_CROSS,24,2)
    cv2.putText(img, 'YELLOW CROSS = proposed click; Q closes', (15,30),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,255,255),2)
    return img


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live', action='store_true', help='Actually move cursor and right-click once.')
    p.add_argument('--offset-y', type=int, required=True, help='Pixels below bottom of marker for proposed click.')
    p.add_argument('--start-key', default='[', help='Single printable start key or F-key.')
    p.add_argument('--stop-key', default=']', help='Single printable stop key or F-key.')
    p.add_argument('--timeout', type=float, default=8.0)
    p.add_argument('--stop-health', type=float, default=.70)
    p.add_argument('--window-title', default='Warcraft')
    args=p.parse_args()
    if args.offset_y < 0 or args.offset_y > 500: p.error('--offset-y must be 0 to 500 pixels')
    if not 1 <= args.timeout <= 20: p.error('--timeout must be between 1 and 20 seconds')
    if not 0 < args.stop_health < 1: p.error('--stop-health must be between 0 and 1')
    start, stop_key = parse_hotkey(args.start_key), parse_hotkey(args.stop_key)
    if start == stop_key or start in ('w','s') or stop_key in ('w','s'):
        p.error('Start and stop keys must differ and cannot be W or S.')
    if not args.window_title.strip(): p.error('window title must not be empty')
    base=json.loads(Path('calibration/config.json').read_text(encoding='utf-8'))
    signal=json.loads(Path('calibration/combat_signal.json').read_text(encoding='utf-8'))
    if base['screen'] != signal['screen']: raise ValueError('Combat signal and monitor calibrations differ.')
    stop=threading.Event(); start_event=threading.Event()
    def on_press(key):
        if matches_hotkey(key,stop_key): stop.set()
        elif matches_hotkey(key,start): start_event.set()
    listener=keyboard.Listener(on_press=on_press); listener.start()
    pointer=mouse.Controller(); keys=keyboard.Controller()
    try:
        with mss.mss() as capture:
            if not 1 <= base['monitor'] < len(capture.monitors): raise ValueError('Calibrated monitor unavailable.')
            mon=capture.monitors[base['monitor']]
            if mon != base['screen']: raise ValueError('Monitor geometry changed; recalibrate.')
            print('LIVE: ONE CLICK WILL BE SENT' if args.live else 'PREVIEW ONLY: NO INPUT WILL BE SENT',flush=True)
            print(f'Focus WoW and press {start} to capture; {stop_key} stops.',flush=True)
            while not stop.is_set() and not start_event.wait(.1): pass
            if stop.is_set(): print('Stopped before start.'); return
            hwnd,title=foreground()
            if not hwnd or args.window_title.lower() not in title.lower():
                raise ValueError(f'Foreground window {title!r} does not match title filter.')
            def focused(): return foreground()[0] == hwnd
            def capture_state():
                if stop.is_set(): raise RuntimeError('Stop key pressed.')
                if not focused(): raise RuntimeError('Game lost focus.')
                img=np.asarray(capture.grab(mon))[:,:,:3].copy()
                hp,_=health(img,base['health_rect'])
                combat=classify_color(img,signal['rect'])
                if not focused() or stop.is_set(): raise RuntimeError('Stopped or focus changed during capture.')
                if not math.isfinite(hp) or not 0 <= hp <= 1 or hp <= args.stop_health:
                    raise RuntimeError('Health low or unreadable.')
                return img,hp,combat
            frame,hp,combat=capture_state()
            if combat != 'out_of_combat': raise RuntimeError(f'Combat state is {combat}; test requires out of combat.')
            marker=choose_candidate(frame,args.offset_y)
            print(f'Marker {marker[:4]}; proposed monitor-relative click ({marker[4]}, {marker[5]}).',flush=True)
            if not args.live:
                cv2.namedWindow('Movement point preview',cv2.WINDOW_NORMAL)
                cv2.imshow('Movement point preview',annotated(frame,marker))
                print('Yellow cross is the proposed point. Close preview with any key.',flush=True)
                cv2.waitKey(0); cv2.destroyAllWindows(); return
            original=pointer.position
            desktop=(mon['left']+marker[4],mon['top']+marker[5])
            if stop.is_set() or not focused(): raise RuntimeError('Stopped or focus changed before clicking.')
            try:
                pointer.position=desktop
                if stop.is_set() or not focused(): raise RuntimeError('Stopped or focus changed before clicking.')
                try: pointer.press(mouse.Button.right)
                finally: pointer.release(mouse.Button.right)
            finally:
                pointer.position=original
            print(f'Right-click sent at {desktop}; cursor restored. Monitoring combat.',flush=True)
            started=time.monotonic(); reason='time limit reached'
            try:
                while time.monotonic()-started < args.timeout:
                    if stop.is_set(): reason='stop key'; break
                    try: _,hp,combat=capture_state()
                    except RuntimeError as exc: reason=str(exc); break
                    if combat == 'combat': reason='combat detected'; break
                    if combat != 'out_of_combat': reason='combat indicator unknown'; break
                    time.sleep(.2)
            finally:
                # A short backwards key press may cancel click-to-move. This is
                # best-effort and cannot safely be sent to a different window.
                if focused():
                    try: keys.press('s')
                    finally: keys.release('s')
                    print(f'Stopping: {reason}; tapped S to cancel movement (not verified).',flush=True)
                else:
                    print(f'Stopping: {reason}; game lost focus, so movement was NOT cancelled. Stop it manually.',flush=True)
            print('Test ended. No combat or looting commands were issued.',flush=True)
    finally:
        listener.stop()


if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: print('\nStopped.')
    except Exception as exc: print(f'STOPPED: {exc}')
