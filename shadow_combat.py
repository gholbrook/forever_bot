"""Write read-only Laya combat predictions alongside a manual recording."""
import argparse
import csv
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path


LIVE_SIGNALS = {
    'Heroic Strike': 'signal_heroic_strike_usable',
    'Overpower': 'signal_overpower_usable',
    'Victory Rush': 'signal_victory_rush_usable',
    'Execute': 'signal_execute_usable',
    'Rend': 'signal_rend_ready',
    'Thunder Clap': 'signal_thunder_clap_ready',
    'Bloodrage': 'signal_bloodrage_ready',
    'Demoralizing Shout': 'signal_demoralizing_shout_ready',
    'Cleave': 'signal_cleave_ready',
    "Elune's Light": 'signal_elunes_light_ready',
    'Battle Shout': 'signal_battle_shout_ready',
}
FIELDS = ['usable', 'low_resource', 'in_range', 'cooldown']


def build_context(row, choices):
    def fraction(key):
        value = row.get(key)
        return round(float(value), 2) if value else None

    flags = {'yes': '1', 'no': '0'}
    availability = {ability: flags.get(row.get(LIVE_SIGNALS.get(ability)), '?')
                    for ability in choices}
    return {
        'health': fraction('health_fraction'),
        'rage': fraction('rage_fraction'),
        'target_health': fraction('target_health_fraction'),
        'ability_status_fields': FIELDS,
        'ability_status': {name: [flag, '?', '?', '?'] for name, flag in availability.items()},
    }


def wait_for_recording(path, process, timeout=30):
    deadline = time.monotonic() + timeout
    while not path.exists():
        if process.poll() is not None:
            raise RuntimeError(f'Recorder exited before creating {path.name}.')
        if time.monotonic() >= deadline:
            raise RuntimeError(f'Recorder did not create {path.name} within {timeout:g} seconds.')
        time.sleep(.1)


def follow(path, process):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        header = None
        while True:
            position = handle.tell()
            line = handle.readline()
            if line.endswith(('\n', '\r')):
                values = next(csv.reader([line]))
                if header is None:
                    header = values
                elif len(values) == len(header):
                    yield dict(zip(header, values))
            else:
                if process.poll() is not None:
                    break
                handle.seek(position)
                time.sleep(.08)


def predict_rows(rows, output, agent, questions, max_rows, live):
    count = 0
    previous = None
    with output.open('x', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['sample_unix_ns', 'prediction_unix_ns', 'ability', 'confidence',
                         'live_usable_signal', 'decision', 'gate_reason', 'context'])
        for row in rows:
            if row.get('combat') != 'combat' or row.get('signal_hostile') != 'yes':
                previous = None
                continue
            stamp = int(row['unix_ns'])
            if live and time.time_ns() - stamp > 2_000_000_000:
                continue
            state = build_context(row, questions['ability']['criteria'])
            if state['health'] is None or not 0 < state['health'] <= 1:
                continue
            context = json.dumps(state, separators=(',', ':'))
            answer = agent.predict(context, questions)['answers']['ability']
            ability = answer['choice']
            status = row.get(LIVE_SIGNALS.get(ability), 'unknown')
            decision = ability if status == 'yes' else 'wait'
            reason = {'yes': 'ready', 'no': 'unavailable'}.get(status, 'unknown_readiness')
            writer.writerow([stamp, time.time_ns(), ability, answer.get('confidence'),
                             status, decision, reason, context])
            handle.flush()
            count += 1
            if live and (ability, status) != previous:
                confidence = answer.get('confidence')
                score = f'{confidence:.0%}' if confidence is not None else 'unknown'
                print(f'Shadow: {decision} | model chose {ability} ({score}) | {reason}',
                      flush=True)
                previous = (ability, status)
            if max_rows and count >= max_rows:
                break
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', required=True, type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--recorder-folder', type=Path)
    source.add_argument('--replay', type=Path, help='Existing states.csv for offline checks.')
    parser.add_argument('--output', type=Path, help='New prediction CSV path in replay mode.')
    parser.add_argument('--max-rows', type=int, help='End after this many predictions.')
    args = parser.parse_args()
    if args.replay and not args.output:
        parser.error('--replay requires --output')
    if args.recorder_folder and args.output:
        parser.error('Live predictions are saved in the new observation folder.')
    import laya

    questions = json.loads((args.checkpoint / 'questions.json').read_text(encoding='utf-8'))
    print('Loading the Laya combat checkpoint...', flush=True)
    agent = laya.load(str(args.checkpoint.resolve()), device='cuda')
    if args.replay:
        with args.replay.open(encoding='utf-8-sig', newline='') as handle:
            count = predict_rows(csv.DictReader(handle), args.output, agent, questions,
                                 args.max_rows, live=False)
        print(f'Saved {count} predictions to {args.output}', flush=True)
        return

    folder = args.recorder_folder.resolve()
    session = folder / datetime.now().strftime('observation_shadow_%Y%m%d_%H%M%S')
    recorder = folder / '.venv' / 'Scripts' / 'python.exe'
    if not recorder.is_file() or not (folder / 'record_observations.py').is_file():
        raise SystemExit('Recorder Python or record_observations.py was not found.')
    process = subprocess.Popen([str(recorder), str(folder / 'record_observations.py'),
                                '--selection', '--output', str(session)], cwd=folder)
    print(f'Shadow mode: play manually. Predictions go to {session / "shadow_predictions.csv"}.',
          flush=True)
    try:
        states = session / 'states.csv'
        wait_for_recording(states, process)
        rows = follow(states, process)
        predict_rows(rows, session / 'shadow_predictions.csv', agent, questions, args.max_rows, live=True)
    except KeyboardInterrupt:
        pass
    finally:
        # In a shared console Ctrl+C reaches both processes. Give the recorder
        # time to close its CSVs before forcing a stop if it is still running.
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait()
        print(f'Shadow session: {session}', flush=True)


if __name__ == '__main__':
    main()
