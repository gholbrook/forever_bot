"""Offline imitation-learning experiment from decision_replay_with_abilities.csv.

Uses only Python's standard library. Never sends game input.
"""
import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

FEATURES = ['health_fraction_estimate', 'rage_fraction_estimate', 'target_health_fraction_estimate',
            'combat_estimate', 'target_presence_estimate', 'heroic_strike_appearance',
            'charge_appearance', 'victory_rush_appearance']
NUMERIC = set(FEATURES[:3])
LABELS = {'auto_attack', 'heroic_strike', 'charge', 'thunderclap', 'rend', 'hamstring',
          'overpower', 'cleave', 'slam', 'victory_rush', 'sunder_armor', 'recovery'}


def features(row):
    result = []
    for name in FEATURES:
        value = row.get(name, '').strip()
        if name in NUMERIC:
            try:
                value = float(value)
                value = str(min(4, int(value * 5))) if math.isfinite(value) and 0 <= value <= 1 else 'unknown'
            except ValueError:
                value = 'unknown'
        elif not value:
            value = 'unknown'
        result.append(value)
    return result


def load(path):
    kept, skipped = [], Counter()
    with path.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        required = set(FEATURES + ['observed_action', 'state_frame', 'state_age_ms', 'action_unix_ns', 'state_unix_ns'])
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError('Missing columns: ' + ', '.join(sorted(missing)))
        for row in reader:
            label = row['observed_action'].strip()
            if label not in LABELS:
                skipped['other_input'] += 1
                continue
            try:
                timestamp = int(row['action_unix_ns'])
                state_time = int(row['state_unix_ns'])
                age = float(row['state_age_ms'])
            except ValueError:
                skipped['missing_timestamp_or_age'] += 1
                continue
            if not row['state_frame'] or state_time > timestamp or not math.isfinite(age) or age < 0 or age > 1000 or timestamp-state_time > 1_000_000_000:
                skipped['missing_future_or_stale_state'] += 1
                continue
            kept.append({'time': timestamp, 'frame': row['state_frame'], 'label': label, 'features': features(row)})
    kept.sort(key=lambda x: x['time'])
    return kept, skipped


def fit(rows):
    labels = Counter(r['label'] for r in rows)
    values = [set() for _ in FEATURES]
    counts = defaultdict(Counter)
    for row in rows:
        for i, value in enumerate(row['features']):
            values[i].add(value)
            counts[(row['label'], i)][value] += 1
    return {'labels': dict(labels), 'vocabulary': [sorted(v) for v in values],
            'counts': {f'{label}|{i}': dict(counts[(label, i)]) for label in labels for i in range(len(FEATURES))},
            'feature_names': FEATURES, 'type': 'categorical_naive_bayes_laplace_v1'}


def predict(model, row):
    total = sum(model['labels'].values())
    scored = []
    for label, n in model['labels'].items():
        score = math.log(n / total)
        for i, value in enumerate(row['features']):
            counts = model['counts'][f'{label}|{i}']
            vocabulary = model['vocabulary'][i]
            # One extra slot for unseen categories in the test set.
            score += math.log((counts.get(value, 0) + 1) / (n + len(vocabulary) + 1))
        scored.append((score, label))
    return max(scored)[1]


def metrics(expected, predicted):
    correct = sum(x == y for x, y in zip(expected, predicted))
    per_class = {}
    for label in sorted(set(expected)):
        total = sum(x == label for x in expected)
        hit = sum(x == label and y == label for x, y in zip(expected, predicted))
        per_class[label] = {'examples': total, 'correct': hit, 'recall': round(hit / total, 4)}
    return {'accuracy': round(correct / len(expected), 4), 'correct': correct, 'count': len(expected),
            'balanced_accuracy': round(sum(v['recall'] for v in per_class.values()) / len(per_class), 4), 'per_class': per_class}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('recording', type=Path)
    p.add_argument('--test-fraction', type=float, default=.25)
    p.add_argument('--gap-seconds', type=float, default=2.0)
    args = p.parse_args()
    if not .05 <= args.test_fraction <= .5 or args.gap_seconds < 0:
        p.error('test fraction must be 0.05 to 0.5; gap must be nonnegative')
    path = args.recording / 'decision_replay_with_abilities.csv'
    data, skipped = load(path)
    if len(data) < 20:
        raise ValueError(f'Only {len(data)} usable action rows; need at least 20 for this initial experiment. Skipped: {dict(skipped)}')
    cut = min(len(data)-1, max(1, int(len(data)*(1-args.test_fraction))))
    boundary = data[cut]['time']
    gap_ns = int(args.gap_seconds * 1e9)
    train = [r for r in data if r['time'] < boundary-gap_ns]
    test = [r for r in data if r['time'] >= boundary]
    if len(train) < 10 or len(test) < 3:
        raise ValueError(f'After the chronological split and {args.gap_seconds:g}s gap: {len(train)} training and {len(test)} test rows. Need at least 10 and 3; record more or use a smaller --gap-seconds.')
    if len(set(r['label'] for r in train)) < 2:
        raise ValueError('Training data has only one action class; need at least two distinct actions.')
    model = fit(train)
    baseline = Counter(r['label'] for r in train).most_common(1)[0][0]
    truth = [r['label'] for r in test]
    predicted = [predict(model, r) for r in test]
    labels_train = sorted(model['labels'])
    unseen = sorted(set(truth)-set(labels_train))
    report = {'source': str(path), 'task': 'predict recorded combat/recovery key conditional on a recorded input',
              'split': {'method': 'chronological', 'test_fraction_requested': args.test_fraction, 'gap_seconds': args.gap_seconds,
                        'train_count': len(train), 'gap_count': len(data)-len(train)-len(test), 'test_count': len(test),
                        'train_last_ns': train[-1]['time'], 'test_first_ns': test[0]['time']},
              'skipped_rows': dict(skipped), 'training_class_counts': dict(Counter(r['label'] for r in train)),
              'test_class_counts': dict(Counter(truth)), 'unseen_test_classes': unseen, 'baseline_action': baseline,
              'model_metrics': metrics(truth, predicted), 'baseline_metrics': metrics(truth, [baseline]*len(test)),
              'limitations': ['Within-session split is exploratory; use separate sessions for stronger evaluation.',
                              'Inputs are attempted actions, not verified outcomes.', 'No wait/no-action samples, movement or loot labels.',
                              'Accuracy is agreement with your recorded inputs, not combat success or safety.',
                              'Pre-action frames can include capture timing uncertainty; icon appearance is not guaranteed usability.']}
    out = args.recording / 'decision_training'
    out.mkdir(exist_ok=True)
    (out/'model.json').write_text(json.dumps(model, indent=2), encoding='utf-8')
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    with (out/'test_predictions.csv').open('w', newline='', encoding='utf-8') as f:
        w=csv.writer(f); w.writerow(['action_unix_ns','state_frame','observed_action','model_prediction','baseline_prediction','model_correct'])
        for row, pred in zip(test, predicted):
            w.writerow([row['time'], row['frame'], row['label'], pred, baseline, pred == row['label']])
    print(f'Training: {len(train)} actions; gap: {report["split"]["gap_count"]}; test: {len(test)} actions')
    print(f'Model agreement: {report["model_metrics"]["accuracy"]:.1%}; majority baseline: {report["baseline_metrics"]["accuracy"]:.1%}')
    print('Unseen test actions:', ', '.join(unseen) if unseen else 'none')
    print('Results saved to', out)
    print('Exploratory only: this does not measure combat success and does not control the game.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f'Error: {exc}')
