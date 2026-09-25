"""Audit reusable held-out triplets; never relabel imposed events as observations."""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = ROOT / 'examples/social_mixed/paired_bank_v2/tasks.jsonl'

def main():
    rows = [json.loads(line) for line in SOURCE.read_text().splitlines()]
    train = {r['canonical_id'] for r in rows if r['split'] == 'train'}
    groups = defaultdict(dict)
    for row in rows:
        if row['split'] == 'validation':
            groups[row['canonical_id']][row['paired_view']] = row
    records = []
    for parent, views in sorted(groups.items()):
        b = views['B']; inp = b['input']; query = inp['queries'][0]
        def matches(fact):
            return all(fact.get(key) == query[key] for key in ('player', 'goal'))
        direct = any(matches(fact) for fact in inp.get('private_results', []))
        public = any(matches(fact) for fact in inp.get('public_preferences', []))
        setup = inp.get('imposed_setup', [])
        history = inp.get('voluntary_history', [])
        record = dict(canonical_id=parent, b_id=b['id'], source=b.get('source'),
            views='|'.join(sorted(views)), same_bank_train_overlap=parent in train,
            players=inp['game']['n_players'], goals=len(inp['game']['goals']),
            imposed_events=len(setup), voluntary_events=len(history),
            private_results=len(inp.get('private_results', [])),
            queried_preference_privately_observed=direct,
            queried_preference_public=public,
            support='|'.join(b['teacher']['gold']['possible_preferences']),
            favored=b['teacher']['gold']['favored'],
            p_eligible=views.get('Pplus', {}).get('p_train_eligible', False),
            disposition=('requires_history_reconstruction' if setup else
                         'candidate_requires_teacher_and_cross_bank_audit'))
        records.append(record)
    with (HERE/'source_inventory.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader(); writer.writerows(records)
    summary = dict(status='DESIGN_ONLY_NOT_FROZEN_NOT_RUNNABLE',
        source=str(SOURCE.relative_to(ROOT)),
        source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        validation_parents=len(records),
        counts={key:dict(Counter(str(r[key]) for r in records)) for key in
                ('disposition','support','favored','players',
                 'queried_preference_privately_observed','queried_preference_public',
                 'same_bank_train_overlap','p_eligible')},
        limitations=['Validation has been used for monitoring; it is not an untouched test.',
                    'No full teacher replay or cross-bank training leakage audit performed.',
                    'A private result may concern a different preference from the B query.',
                    'Existing P eligibility does not establish the full B-to-P mediation contract.'])
    (HERE/'source_audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
