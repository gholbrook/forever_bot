"""Join recorded actions to the most recent preceding screen observation."""
import argparse
import bisect
import csv
from collections import Counter
from pathlib import Path

KEYS = {'1': 'auto_attack', '2': 'heroic_strike', '3': 'charge', '4': 'thunderclap',
        '5': 'rend', '6': 'hamstring', '7': 'overpower', '8': 'cleave', '9': 'slam',
        '0': 'victory_rush', '-': 'sunder_armor', '=': 'recovery', 'tab': 'target_nearest',
        'w': 'forward', 's': 'backward', 'a': 'turn_left', 'd': 'turn_right',
        'q': 'strafe_left', 'e': 'strafe_right'}
FIELDS = ['frame', 'unix_ns', 'health_fraction_estimate', 'combat_estimate',
          'rage_fraction_estimate', 'target_presence_estimate', 'target_health_fraction_estimate']


def rows(path, required):
    with path.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        missing = set(required) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f'{path}: missing columns: {", ".join(sorted(missing))}')
        return list(reader)


def number(value):
    try:
        n = float(value)
        return n if 0 <= n <= 1 else None
    except (ValueError, TypeError):
        return None


def baseline(state):
    # Intentionally narrow: no range, cooldown, threat, corpse or cast visibility.
    hp = number(state.get('health_fraction_estimate'))
    combat = state.get('combat_estimate')
    target = state.get('target_presence_estimate')
    if hp is None or combat not in ('combat', 'out_of_combat') or target not in ('present', 'absent'):
        return 'abstain', 'Missing or uncertain observations.'
    if combat == 'combat':
        return 'abstain', 'Combat: range, cooldowns and threats are not observed.'
    if hp < .90:
        return 'recovery', 'Out of combat and health below 90%; inspect before use.'
    return 'abstain', 'No validated decision for this situation.'


def run(folder, max_age):
    state_rows = rows(folder / 'state_analysis.csv', FIELDS[:4])
    extra_rows = rows(folder / 'extra_state_analysis.csv', ['frame', 'unix_ns'] + FIELDS[4:])
    events = rows(folder / 'events.csv', ['unix_ns', 'type', 'value'])
    extra = {}
    for row in extra_rows:
        if row['frame'] in extra:
            raise ValueError(f'Duplicate frame in extra state: {row["frame"]}')
        extra[row['frame']] = row
    observations, skipped = [], 0
    for s in state_rows:
        e = extra.get(s['frame'])
        if not e or not s['unix_ns'] or not e['unix_ns']:
            skipped += 1
            continue
        t = int(s['unix_ns'])
        if int(e['unix_ns']) != t:
            raise ValueError(f'Timestamp disagreement for {s["frame"]}; check that CSVs came from the same recording.')
        observations.append((t, {**s, **{k: e[k] for k in FIELDS[4:]}}))
    observations.sort(key=lambda x: x[0])
    if not observations:
        raise ValueError('No timestamped frames matched between the state files.')
    ts = [x[0] for x in observations]
    valid_events = []
    for event in events:
        if event['type'] == 'key_down' and event['value'] in KEYS:
            action = KEYS[event['value']]
        elif event['type'] == 'right_down':
            action = 'right_click'
        else:
            continue
        valid_events.append((int(event['unix_ns']), event, action))
    valid_events.sort(key=lambda x: x[0])
    output = folder / 'decision_replay.csv'
    headers = ['action_unix_ns', 'action_type', 'action_raw', 'observed_action', 'state_frame', 'state_unix_ns', 'state_age_ms',
               'health_fraction_estimate', 'combat_estimate', 'rage_fraction_estimate', 'target_presence_estimate',
               'target_health_fraction_estimate', 'recommendation', 'reason']
    counts = Counter()
    with output.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for t, event, action in valid_events:
            idx = bisect.bisect_right(ts, t) - 1
            row = {'action_unix_ns': t, 'action_type': event['type'], 'action_raw': event['value'], 'observed_action': action}
            if idx < 0:
                row.update(recommendation='abstain', reason='No earlier observed frame.')
            else:
                frame_t, s = observations[idx]
                age = (t - frame_t) / 1e6
                row.update(state_frame=s['frame'], state_unix_ns=frame_t, state_age_ms=f'{age:.1f}')
                for name in FIELDS[2:]:
                    row[name] = s.get(name, '')
                if age > max_age:
                    row.update(recommendation='abstain', reason='Most recent observation is too old.')
                else:
                    row['recommendation'], row['reason'] = baseline(s)
            counts[row['recommendation']] += 1
            writer.writerow(row)
    print(f'Wrote {len(valid_events)} input rows to {output}')
    print(f'Matched frames: {len(observations)}; skipped incomplete frames: {skipped}; recommendations: {dict(counts)}')
    print('Rows are input events, not confirmed game actions. Right-click is not necessarily loot.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    parser.add_argument('--max-age-ms', type=float, default=1000.0)
    args = parser.parse_args()
    if args.max_age_ms <= 0:
        parser.error('--max-age-ms must be positive')
    try:
        run(args.recording, args.max_age_ms)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'Error: {exc}\n')
