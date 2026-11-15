"""Read-only red-nameplate candidate preview. No mouse or keyboard input is sent."""
import argparse
import json
import time
from pathlib import Path
import cv2
import mss
import numpy as np


def find_candidates(frame):
    height, width = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    lo = cv2.inRange(hsv, np.array([0, 125, 65], np.uint8), np.array([10, 255, 255], np.uint8))
    hi = cv2.inRange(hsv, np.array([170, 125, 65], np.uint8), np.array([179, 255, 255], np.uint8))
    mask = lo | hi
    # Exclude most fixed UI. These bounds intentionally favor the world center.
    mask[:int(height*.12), :] = 0
    mask[int(height*.82):, :] = 0
    mask[:, :int(width*.04)] = 0
    mask[:, int(width*.89):] = 0
    # Horizontal bars are more plausible than isolated red pixels.
    kernel_width = max(5, int(width / 400))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    boxes = []
    for x, y, w, h, area in stats[1:n]:
        if not (max(10, width*.005) <= w <= width*.09 and 1 <= h <= max(4, height*.025)):
            continue
        if w / max(h, 1) < 3 or area < w:
            continue
        boxes.append((int(x), int(y), int(w), int(h)))
    return boxes


def draw(frame, boxes):
    output = frame.copy()
    for index, (x, y, w, h) in enumerate(boxes, 1):
        cv2.rectangle(output, (x-3, y-4), (x+w+3, y+h+4), (0, 255, 255), 2)
        cv2.putText(output, str(index), (x, max(18, y-8)), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(output, f'{len(boxes)} candidates; not verified enemies; Q or Esc quits', (15, 30), cv2.FONT_HERSHEY_SIMPLEX, .6, (0,255,255), 2, cv2.LINE_AA)
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', type=Path, help='Analyze one existing screenshot instead of live monitor')
    p.add_argument('--output', type=Path, help='Save annotated image (requires --image)')
    args = p.parse_args()
    if args.output and not args.image:
        p.error('--output requires --image')
    if args.image:
        frame = cv2.imread(str(args.image))
        if frame is None:
            raise SystemExit(f'Cannot open image: {args.image}')
        boxes = find_candidates(frame)
        print(f'Found {len(boxes)} possible bars: {boxes}')
        annotated = draw(frame, boxes)
        if args.output:
            if not cv2.imwrite(str(args.output), annotated):
                raise SystemExit(f'Could not save {args.output}')
            print('Saved', args.output)
        else:
            cv2.namedWindow('Nameplate candidates', cv2.WINDOW_NORMAL)
            cv2.imshow('Nameplate candidates', annotated)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        return
    cfg = json.loads(Path('calibration/config.json').read_text(encoding='utf-8'))
    with mss.mss() as sct:
        monitor = sct.monitors[cfg['monitor']]
        if monitor != cfg['screen']:
            raise SystemExit('Monitor geometry differs from calibration.')
        cv2.namedWindow('Nameplate candidates', cv2.WINDOW_NORMAL)
        cv2.resizeWindow('Nameplate candidates', 1024, 400)
        print('Move preview to another monitor if possible; it can obscure the captured image. Q or Esc exits.')
        try:
            while True:
                frame = np.asarray(sct.grab(monitor))[:, :, :3].copy()
                boxes = find_candidates(frame)
                cv2.imshow('Nameplate candidates', draw(frame, boxes))
                if cv2.waitKey(1) & 0xff in (27, ord('q')):
                    break
                time.sleep(.25)
        finally:
            cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
