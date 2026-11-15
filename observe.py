"""Manual demonstration recorder and health-bar calibration viewer for Windows."""
import argparse
import csv
import json
import os
import queue
import time
from datetime import datetime

import cv2
import mss
import numpy as np
from pynput import keyboard, mouse

KEYS = set('wasdqet1234567890-=')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--monitor', type=int, default=2, help='MSS monitor number; default 1')
    parser.add_argument('--fps', type=float, default=2)
    args = parser.parse_args()
    if args.fps <= 0 or args.fps > 10:
        parser.error('fps must be between 0 and 10')
    events = queue.Queue()
    stopped = False

    def on_press(key):
        nonlocal stopped
        if key == keyboard.Key.f8:
            stopped = True
            return False
        char = '\t' if key == keyboard.Key.tab else getattr(key, 'char', None)
        if char == '\t':
            events.put((time.time_ns(), 'key_down', 'tab'))
            return
        if char and char.lower() in KEYS:
            events.put((time.time_ns(), 'key_down', char.lower()))

    def on_release(key):
        char = '\t' if key == keyboard.Key.tab else getattr(key, 'char', None)
        if char == '\t':
            events.put((time.time_ns(), 'key_up', 'tab'))
            return
        if char and char.lower() in KEYS:
            events.put((time.time_ns(), 'key_up', char.lower()))

    def on_click(x, y, button, pressed):
        if button == mouse.Button.right:
            events.put((time.time_ns(), 'right_down' if pressed else 'right_up', f'{x},{y}'))

    folder = 'recording_' + datetime.now().strftime('%Y%m%d_%H%M%S')
    os.makedirs(folder, exist_ok=False)
    with mss.mss() as capture, open(os.path.join(folder, 'events.csv'), 'w', newline='', encoding='utf-8') as f:
        if args.monitor < 1 or args.monitor >= len(capture.monitors):
            raise SystemExit(f'Invalid monitor; available: 1..{len(capture.monitors)-1}')
        region = capture.monitors[args.monitor]
        with open(os.path.join(folder, 'metadata.json'), 'w', encoding='utf-8') as meta:
            json.dump({'monitor': region, 'fps': args.fps, 'timestamp_unit': 'unix_nanoseconds',
                       'note': 'Mouse coordinates are desktop coordinates; frames use monitor-relative coordinates.'}, meta, indent=2)
        writer = csv.writer(f)
        writer.writerow(['unix_ns', 'type', 'value'])
        kl = keyboard.Listener(on_press=on_press, on_release=on_release)
        ml = mouse.Listener(on_click=on_click)
        kl.start(); ml.start()
        print(f'Recording {folder}. Play manually. F8 stops recording.', flush=True)
        i = 0
        try:
            while not stopped:
                start = time.monotonic()
                before = time.time_ns()
                frame = np.asarray(capture.grab(region))[:, :, :3]
                after = time.time_ns()
                name = f'frame_{i:06d}.jpg'
                if not cv2.imwrite(os.path.join(folder, name), frame, [cv2.IMWRITE_JPEG_QUALITY, 90]):
                    raise RuntimeError('Could not write frame')
                writer.writerow([(before + after) // 2, 'frame', name])
                while not events.empty():
                    writer.writerow(events.get_nowait())
                f.flush()
                i += 1
                time.sleep(max(0, 1 / args.fps - (time.monotonic() - start)))
        finally:
            kl.stop(); ml.stop()
            while not events.empty():
                writer.writerow(events.get_nowait())
    print(f'Saved {i} frames in {folder}')


if __name__ == '__main__':
    main()
