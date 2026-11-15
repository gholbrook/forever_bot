import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd

# Action columns the neural network will learn to predict
HOLD_ACTIONS = [
    'forward',
    'backward',
    'turn_left',
    'turn_right',
    'strafe_left',
    'strafe_right',
]
TAP_ACTIONS = [
    'target_tab',
    'jump',
    'auto_attack',
    'heroic_strike',
    'charge',
    'thunder_clap',
    'rend',
    'hamstring',
    'overpower',
    'cleave',
    'slam',
    'victory_rush',
    'sunder_armor',
    'execute',
    'battle_shout',
    'bloodrage',
    'demoralizing_shout',
    'shoot_gun',
    'recover',
]
ALL_ACTIONS = HOLD_ACTIONS + TAP_ACTIONS


def parse_boxes(box_json):
  """Extract count, closest enemy center (x, y), and largest box width."""
  if pd.isna(box_json) or not box_json:
    return 0, 0.5, 0.5, 0.0
  boxes = json.loads(box_json)
  if not boxes:
    return 0, 0.5, 0.5, 0.0
  # Larger width = closer enemy nameplate
  largest = max(boxes, key=lambda b: b[2] * b[3])
  x, y, w, h = largest
  # Normalize assuming 1920x1080 (or relative to screen center)
  cx = (x + w / 2.0) / 1920.0
  cy = (y + h / 2.0) / 1080.0
  return len(boxes), cx, cy, w / 1920.0


def encode_signal(val):
  if val == 'yes':
    return 1.0
  if val == 'no':
    return 0.0
  return -1.0  # 'unknown' or 'unreadable'


def main():
  p = argparse.ArgumentParser()
  p.add_argument(
      'obs_dir', type=Path, help='Path to observation_YYYYMMDD_HHMMSS folder'
  )
  p.add_argument('--out', type=Path, default=Path('training_data.parquet'))
  args = p.parse_args()

  states = pd.read_csv(args.obs_dir / 'states.csv').sort_values('unix_ns')
  scene = pd.read_csv(args.obs_dir / 'enemy_scene.csv').sort_values('unix_ns')
  nav = pd.read_csv(args.obs_dir / 'navigation_inputs.csv').sort_values(
      'unix_ns'
  )
  keys = pd.read_csv(args.obs_dir / 'key_attempts.csv').sort_values('unix_ns')

  # 1. Merge states with closest enemy_scene snapshot
  df = pd.merge_asof(
      states, scene, on='unix_ns', direction='nearest', tolerance=150_000_000
  )

  def combine_boxes(row):
      u = (
          json.loads(row['enemy_marker_boxes'])
          if pd.notna(row['enemy_marker_boxes']) and row['enemy_marker_boxes']
          else []
      )
      s = (
          json.loads(row['selected_marker_boxes'])
          if pd.notna(row['selected_marker_boxes'])
             and row['selected_marker_boxes']
          else []
      )
      return json.dumps(u + s)

  all_boxes_col = df.apply(combine_boxes, axis=1)
  enemy_feats = all_boxes_col.apply(parse_boxes)
  df['enemy_count'] = [f[0] for f in enemy_feats]
  df['nearest_enemy_x'] = [f[1] for f in enemy_feats]
  df['nearest_enemy_y'] = [f[2] for f in enemy_feats]
  df['nearest_enemy_w'] = [f[3] for f in enemy_feats]

  sel_feats = df['selected_marker_boxes'].apply(parse_boxes)
  df['sel_enemy_x'] = [f[1] for f in sel_feats]
  df['sel_enemy_y'] = [f[2] for f in sel_feats]

  # 2. Encode boolean/signal columns into clean floats
  df['combat'] = (
      df['combat']
      .astype(str)
      .str.lower()
      .map({
          'in_combat': 1.0,
          'combat': 1.0,
          'true': 1.0,
          '1': 1.0,
          'out_of_combat': 0.0,
          'false': 0.0,
          '0': 0.0,
      })
      .fillna(0.0)
  )
  df['target'] = (
      df['target']
      .astype(str)
      .str.lower()
      .map({
          'has_target': 1.0,
          'target': 1.0,
          'yes': 1.0,
          'true': 1.0,
          '1': 1.0,
          'no_target': 0.0,
          'none': 0.0,
          'no': 0.0,
          'false': 0.0,
          '0': 0.0,
      })
      .fillna(0.0)
  )
  df['health_fraction'] = pd.to_numeric(
      df['health_fraction'], errors='coerce'
  ).fillna(1.0)
  df['rage_fraction'] = pd.to_numeric(
      df['rage_fraction'], errors='coerce'
  ).fillna(0.0)
  df['target_health_fraction'] = pd.to_numeric(
      df['target_health_fraction'], errors='coerce'
  ).fillna(0.0)

  for col in df.columns:
    if col.startswith('signal_') and col not in (
        'signal_pos_x',
        'signal_pos_y',
    ):
      df[col] = df[col].apply(encode_signal)

  # 3. Coordinate features & velocity (stuck detection features)
  df['pos_x'] = pd.to_numeric(df['signal_pos_x'], errors='coerce').ffill().bfill()
  df['pos_y'] = pd.to_numeric(df['signal_pos_y'], errors='coerce').ffill().bfill()
  df['dx'] = df['pos_x'].diff().fillna(0.0)
  df['dy'] = df['pos_y'].diff().fillna(0.0)
  df['speed'] = np.sqrt(df['dx'] ** 2 + df['dy'] ** 2)

  # 4. Enemy radar features
  enemy_feats = df['enemy_marker_boxes'].apply(parse_boxes)
  df['enemy_count'] = [f[0] for f in enemy_feats]
  df['nearest_enemy_x'] = [f[1] for f in enemy_feats]
  df['nearest_enemy_y'] = [f[2] for f in enemy_feats]
  df['nearest_enemy_w'] = [f[3] for f in enemy_feats]

  sel_feats = df['selected_marker_boxes'].apply(parse_boxes)
  df['sel_enemy_x'] = [f[1] for f in sel_feats]
  df['sel_enemy_y'] = [f[2] for f in sel_feats]

  # 5. Reconstruct held keys & tapped actions at each timestamp
  timestamps = df['unix_ns'].values
  labels = {act: np.zeros(len(df), dtype=np.float32) for act in ALL_ACTIONS}

  # Track key_down / key_up intervals for movement
  active_holds = {}
  nav_idx = 0
  nav_rows = list(nav.itertuples(index=False))

  for i, ts in enumerate(timestamps):
    while nav_idx < len(nav_rows) and nav_rows[nav_idx].unix_ns <= ts:
      row = nav_rows[nav_idx]
      if row.event == 'key_down' and row.action in HOLD_ACTIONS:
        active_holds[row.action] = True
      elif row.event == 'key_up' and row.action in HOLD_ACTIONS:
        active_holds[row.action] = False
      elif row.event == 'key_down' and row.action in TAP_ACTIONS:
        # Mark tap action active for the next ~250ms window
        labels[row.action][i] = 1.0
      nav_idx += 1
    for act, is_down in active_holds.items():
      if is_down:
        labels[act][i] = 1.0

  # Mark spell key_attempts onto the state frame immediately preceding the press
  for row in keys.itertuples(index=False):
    if row.action in TAP_ACTIONS:
      idx = np.searchsorted(timestamps, row.unix_ns) - 1
      if 0 <= idx < len(df):
        labels[row.action][idx] = 1.0

  for act, arr in labels.items():
    df[f'act_{act}'] = arr

  # Drop raw text columns and save clean tabular dataset
  drop_cols = [
      'unix_ns',
      'enemy_marker_boxes',
      'selected_marker_boxes',
      'signal_pos_x',
      'signal_pos_y',
  ]
  clean_df = df.drop(columns=[c for c in drop_cols if c in df.columns])
  clean_df.to_parquet(args.out, index=False)
  print(
      f'Saved {len(clean_df)} training frames with {clean_df.shape[1]} columns'
      f' to {args.out}'
  )


if __name__ == '__main__':
  main()
