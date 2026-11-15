SPELLBOOK OBSERVER — READ-ONLY COLLECTION

This separate addon discovers normal learned player spellbook entries, regardless of whether they are on an action bar. It samples their reported usability, insufficient-resource flag, target range, and cooldown-active flag once per second; it also attempts to capture player spellcast-success, failure and interrupt events. It never casts, moves, targets, or sends inputs. It does not fine-tune any model.

INSTALL
1. Close WoW. Copy the entire SpellbookObserver folder into your WoW Forever installation's Interface\AddOns folder. Do not replace your existing EngageIndicator addon. The .toc interface is 16001; if your client reports it outdated, check your game build.
2. Launch WoW and enable Spellbook Observer on the character-select AddOns screen.

RECORD
1. While out of combat, type /sbo start. It scans spellbook tabs including profession tabs where available. It prints the number discovered. Starting a new recording replaces this addon's previous samples in memory.
2. Play normally. You can use unbound abilities by clicking the spellbook yourself; the addon observes all discovered spells whether or not they are cast. No per-screenshot labels are needed. It samples once a second. /sbo status shows progress.
3. Type /sbo stop, then type /reload (or log out) to persist the recording. WoW SavedVariables files update on reload/logout, not continuously. It stores at most 1,800 samples (roughly 30 minutes) or 3,600 cast events and stops when either limit is reached. /sbo start resets old observations; copy/convert before starting again.

EXPORT CSV
For a standard Windows install, from the folder containing convert_spellbook_observer.py:

.\.venv\Scripts\python convert_spellbook_observer.py --find

For a custom installation or if multiple accounts exist, find SpellbookObserver.lua in your Forever account's WTF\Account\<account>\SavedVariables folder. This addon declares an account-level variable. Then use:

.\.venv\Scripts\python convert_spellbook_observer.py "C:\path\to\WTF\Account\YOUR_ACCOUNT\SavedVariables\SpellbookObserver.lua"

Adjust the path to the actual SavedVariables file. The script outputs spellbook_observations\spellbook_manifest.csv, spellbook_samples.csv and spell_cast_events.csv. Re-running overwrites these three CSVs; use --output ANOTHER_FOLDER for each session.

LIMITATIONS
This is an untested Forever-client prototype: API behavior and available data depend on the client. It includes normal spellbook spell entries and may omit flyout contents, hidden spells, items, equipment use, and future/unlearned spells. Restricted or missing information is '?'; 1 means true and 0 false. Usability is not a complete can-cast check: it does not by itself establish target validity, range, cooldown, proc, or success. Range '?' is not out of range. The cooldown-active field can include the global cooldown and may be restricted. A cast-success event reports a cast, not necessarily a hit or damage; queued attacks may differ. Events may be missing or secret. Data contains only the sampled states and cast events the game exposes, not every attempted input, enemy position, or idle/action labels.

Game time is recorded as whole epoch seconds plus GetTime uptime seconds. The epoch portion is coarse; do not treat it as subsecond alignment with the separate Python recorder without an explicit sync. The addon does not save screenshots or send data to a server.
