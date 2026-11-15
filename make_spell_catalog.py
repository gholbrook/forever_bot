"""Build a first-pass, reviewable catalog from Spellbook Observer CSVs."""
import argparse
import collections
import csv
from pathlib import Path

CATEGORIES = {
    'Attack':'Basic attack', 'Heroic Strike':'Damage', 'Cleave':'Damage', 'Slam':'Damage',
    'Execute':'Damage', 'Rend':'Damage', 'Thunder Clap':'Damage', 'Overpower':'Damage',
    'Revenge':'Damage', 'Sunder Armor':'Damage and debuffs', 'Hamstring':'Damage and control',
    'Victory Rush':'Damage and recovery', 'Charge':'Approach and movement',
    'Battle Shout':'Buffs and resources', 'Demoralizing Shout':'Buffs and debuffs', 'Bloodrage':'Buffs and resources',
    'Defensive Stance':'Stances', 'Battle Stance':'Stances',
    'Shield Bash':'Defense and control', 'Shield Block':'Defense and control', 'Disarm':'Defense and control',
    'Intimidating Shout':'Defense and control', 'Taunt':'Defense and control', 'Mocking Blow':'Defense and control',
    'Retaliation':'Defense and control', 'Throw':'Ranged actions', 'Shoot Gun':'Ranged actions',
    'Shoot Crossbow':'Ranged actions', 'Cooking':'Professions', 'Blacksmithing':'Professions',
    'First Aid':'Professions', 'Smelting':'Professions', 'Find Minerals':'Professions',
    'Shadowmeld':'Racial', 'Elune_s Light':'Racial',
}


def read(path):
    if not path.exists(): return []
    with path.open(newline='',encoding='utf-8-sig') as f: return list(csv.DictReader(f))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('observations',type=Path)
    p.add_argument('--output',type=Path,default=Path('spell_catalog.md'))
    args=p.parse_args()
    spells=read(args.observations/'spellbook_manifest.csv')
    if not spells: raise ValueError('No spellbook_manifest.csv entries found.')
    events=read(args.observations/'spell_cast_events.csv')
    samples=read(args.observations/'spellbook_samples.csv')
    descriptions={row['spell_id']:row for row in read(args.observations/'spell_descriptions.csv')}
    success=collections.Counter(row['spell_id'] for row in events if row.get('event')=='UNIT_SPELLCAST_SUCCEEDED')
    failed=collections.Counter(row['spell_id'] for row in events if row.get('event')=='UNIT_SPELLCAST_FAILED')
    known={s['spell_id'] for s in spells}
    groups=collections.defaultdict(list)
    for s in spells:
        category='Passive' if s.get('passive')=='1' else CATEGORIES.get(s['name'],'Other or unclassified')
        groups[category].append(s)
    lines=['# Spellbook catalog', '',
           f"{len(spells)} discovered spellbook entries. Categories are a human-readable first pass, not an action priority.",
           'A recorded successful cast is not proof of a hit or a recommendation to cast.',
           'Descriptions come from the client when exported; missing text is explicitly marked.', '']
    for category in sorted(groups):
        lines.extend([f'## {category}', '', '| Ability | Rank or type | Spell ID | Recorded successes | Client description |', '|---|---|---:|---:|---|'])
        for s in sorted(groups[category],key=lambda r:r['name'].lower()):
            desc=descriptions.get(s['spell_id'],{}).get('description','').strip() or 'Not captured yet'
            desc=desc.replace('|','/').replace('\n',' ')
            lines.append(f"| {s['name'].replace('_',' ')} | {s.get('subname','') or '—'} | {s['spell_id']} | {success[s['spell_id']]} | {desc} |")
        lines.append('')
    unmatched=sorted(set(row['spell_id'] for row in events if row.get('spell_id') not in known and row.get('spell_id') not in ('','?')))
    lines += ['## Capture notes', '', f"- {len(samples)} per-spell samples and {len(events)} cast-event rows are present.",
              '- Sampled availability, range, and cooldown signals can be unknown or restricted. Usability alone does not establish range or success.',
              '- Spellbook flyouts, hidden spells, item actions, and abilities the client does not expose may be absent.',
              '- Current-health values and spellcast events may be missing or restricted; do not infer zero from unknown.']
    if unmatched:
        lines.append('- Cast-event spell IDs not in the manifest (not automatically added as learned abilities):')
        for spell_id in unmatched:
            info = descriptions.get(spell_id, {})
            name = info.get('name', '').strip() or 'Name not captured yet'
            description = info.get('description', '').strip() or 'Description not captured yet'
            lines.append(f'  - {spell_id}: {name} — {description}')
    else: lines.append('- No unmatched spell IDs in recorded cast events.')
    args.output.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f'Wrote {len(spells)} entries to {args.output}; {len(unmatched)} unmatched event IDs.')


if __name__=='__main__':
    try: main()
    except (OSError,ValueError,KeyError) as exc: raise SystemExit(f'Error: {exc}')
