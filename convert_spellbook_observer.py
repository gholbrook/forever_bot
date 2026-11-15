"""Convert SpellbookObserver SavedVariables into reviewable CSV files.

Only extracts the addon's constrained record strings; does not execute Lua.
"""
import argparse
import csv
import os
import re
from pathlib import Path

RECORD = re.compile(r'"((?:M1|S1|E1|D1)\|[^"\\]*)"')


def convert(source, destination):
    raw = source.read_text(encoding='utf-8-sig', errors='replace')
    records = RECORD.findall(raw)
    if not records:
        raise ValueError('No SpellbookObserver records found. Stop recording and /reload or log out to save first.')
    destination.mkdir(parents=True, exist_ok=True)
    manifest, events, samples, descriptions = [], [], [], []
    for record in records:
        fields = record.split('|')
        if fields[0] == 'M1' and len(fields) == 5:
            manifest.append(fields[1:])
        elif fields[0] == 'E1' and len(fields) == 5:
            events.append(fields[1:])
        elif fields[0] == 'D1' and len(fields) == 4:
            descriptions.append(fields[1:])
        elif fields[0] == 'S1' and len(fields) == 8:
            epoch, uptime, combat, hp, hpmax, target, entries = fields[1:]
            for item in entries.split(';'):
                bits = item.split(':')
                if len(bits) == 5:
                    samples.append([epoch, uptime, combat, hp, hpmax, target, *bits])
    def write(name, columns, rows):
        with (destination/name).open('w', encoding='utf-8', newline='') as f:
            writer=csv.writer(f); writer.writerow(columns); writer.writerows(rows)
    write('spellbook_manifest.csv', ['spell_id','name','subname','passive'], manifest)
    write('spellbook_samples.csv', ['epoch_seconds','game_uptime_seconds','combat','player_health','player_max_health','target_exists','spell_id','usable','insufficient_power','in_range','cooldown_active'], samples)
    write('spell_cast_events.csv', ['epoch_seconds','game_uptime_seconds','event','spell_id'], events)
    if descriptions:
        write('spell_descriptions.csv', ['spell_id','name','description'], descriptions)
    print(f'Converted {len(manifest)} spell entries, {len(samples)} per-spell observations, and {len(events)} cast events into {destination}')
    print(f'Descriptions: {sum(bool(r[2]) for r in descriptions)}/{len(descriptions)}; empty descriptions remain unknown.')
    print('0=false, 1=true, ?=unknown. Event timestamps do not prove damage or a successful hit.')
    if not samples:
        print('No samples found; start recording, play, stop, and /reload before converting.')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('saved_variables', type=Path, nargs='?', help='SpellbookObserver.lua in the WoW account SavedVariables folder')
    p.add_argument('--find', action='store_true', help='Look for the file in the standard Windows Forever install.')
    p.add_argument('--output', type=Path, default=Path('spellbook_observations'))
    args=p.parse_args()
    if bool(args.saved_variables) == bool(args.find):
        p.error('Provide either a SavedVariables file path or --find.')
    try:
        source = args.saved_variables
        if args.find:
            program_files = os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')
            account_dir = Path(program_files)/'World of Warcraft'/'_forever_'/'WTF'/'Account'
            matches = sorted(account_dir.glob('*/SavedVariables/SpellbookObserver.lua'))
            if not matches:
                raise ValueError(f'No saved file found under {account_dir}. Use /sbo stop then /reload; use an explicit path for a custom installation.')
            if len(matches) > 1:
                raise ValueError('Multiple accounts found. Pass the exact path for your account:\n' + '\n'.join(str(x) for x in matches))
            source = matches[0]
        convert(source,args.output)
    except (OSError,ValueError) as exc: p.exit(1,f'Error: {exc}\n')
