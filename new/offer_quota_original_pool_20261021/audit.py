"""Identify the original 100 parents and where quota 1 changes legality.

No new games, equilibrium search, training data selection or model calls.
"""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys

from new.offer_budget_mechanism_20261021.research import OfferQuotaRules, assert_factorized
from training.strategic_slices.pipeline_versions import registered_snapshot
from benac_p.schema import OfferProposal, PassProposal

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def digest(p):
    return sha256(p.read_bytes()).hexdigest()


def write(name, value):
    with (OUT / name).open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def main():
    for name in ('audit.json', 'pipeline_snapshot.json'):
        if (OUT / name).exists():
            raise FileExistsError('Closed outputs cannot be overwritten')
    active = registered_snapshot('terminal-node-regret-grpo-readable-v8', 'terminal-readable-named-v2')
    baseline = json.loads((ROOT / active['path']).read_text())
    pool = ROOT / 'new/local_data/strategic_slices_oracle_consistent_candidates_v4'
    selection = ROOT / 'new/local_data/strategic_slices_terminal_selected_v4/SELECTION.json'
    for rel, expected in baseline['data_selection_D_files'].items():
        assert digest(ROOT / rel) == expected, rel
    parents = [json.loads(s) for s in (pool/'parents.jsonl').read_text().splitlines()]
    refs = [json.loads(s) for s in (pool/'references.jsonl').read_text().splitlines()]
    chosen = json.loads(selection.read_text())
    assert len(parents) == len({p['id'] for p in parents}) == 100
    assert {r['parent_id'] for r in refs} == {p['id'] for p in parents}
    ref_by_parent = {r['parent_id']: r for r in refs}
    rows = []
    for parent in parents:
        raw = parent['raw']
        assert_factorized(raw)
        schedule = raw['game']['round_robin']
        counts = Counter(schedule)
        binding = max(counts.values()) > 1
        witness = None
        if binding:
            ordinary, limited = OfferQuotaRules(raw, None), OfferQuotaRules(raw, 1)
            a, b = ordinary.initial(), limited.initial()
            actor = ordinary.actor(a)
            offer = next(x for x in ordinary.actions(a) if isinstance(x, OfferProposal))
            a, b = ordinary._apply(a, offer), limited._apply(b, offer)
            reject = next(x for x in ordinary.actions(a) if x.to_dict().get('response') == 'REJECT')
            a, b = ordinary._apply(a, reject), limited._apply(b, reject)
            while ordinary.actor(a) != actor:
                a, b = ordinary._apply(a, PassProposal()), limited._apply(b, PassProposal())
            assert any(isinstance(x, OfferProposal) for x in ordinary.actions(a))
            assert not any(isinstance(x, OfferProposal) for x in limited.actions(b))
            witness = dict(actor=actor, second_proposal_turn=a.state.turn_index,
                first_offer=offer.to_dict(), first_response='REJECT', other_players='PASS until actor returns',
                offer_available_without_quota=True, offer_available_with_quota=False,
                scope='Legal public history only, not certified-profile reach or utility advantage')
        ref = ref_by_parent[parent['id']]
        assert digest(pool / ref['file']) == ref['sha256']
        rows.append(dict(parent_id=parent['id'], split=parent['split'], players=parent['players'],
            proposal_schedule=schedule, per_player_proposal_counts=dict(counts),
            quota1_changes_legal_tree=binding, legality_witness=witness,
            raw_sha256=sha256(json.dumps(raw,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            original_reference_file=ref['file'], original_reference_sha256=ref['sha256'],
            appears_in_old_selected_training_parent_ids=parent['id'] in chosen['parent_ids']))
    result = dict(status='original-100-parent-identity-and-legality-audit-complete', parents=rows,
        pool_parents=100, splits=dict(Counter(p['split'] for p in parents)),
        coverage=dict(Counter(f"{p['players']}p/{len(p['raw']['game']['round_robin'])//p['players']}r" for p in parents)),
        quota1_changes_legal_tree=sum(r['quota1_changes_legal_tree'] for r in rows),
        quota1_nonbinding=sum(not r['quota1_changes_legal_tree'] for r in rows),
        old_selected_training_slices=sum(chosen['actual']['k'].values()),
        old_selected_training_unique_parents=chosen['selected_parents'],
        selected_parent_ids_subset_of_pool=set(chosen['parent_ids']).issubset({p['id'] for p in parents}),
        all_catalogue_supports_factorized=True, all_reference_file_hashes_verified=True,
        all_parent_ids_preserved=True, new_parents_generated=False,
        quota_terminal_profiles_solved=0, new_C_S_or_D_measured=False, production_changed=False)
    write('audit.json', result)
    sources = [Path(__file__), ROOT/'new/offer_budget_mechanism_20261021/research.py',
               pool/'manifest.json', pool/'parents.jsonl',pool/'references.jsonl',selection]
    write('pipeline_snapshot.json',dict(status='completed-cpu-structural-audit-only',
        actual_argv=sys.argv, active_training=active,
        resolved_config=dict(pool=str(pool.relative_to(ROOT)),selection=str(selection.relative_to(ROOT)),
            offer_quota_per_player=1, quota_refund=False, investigation='unchanged',
            preference_generation='unchanged; verify factorized support',
            scope='All original parent ids, no filtering; schedule bound plus one legal counterexample for every potentially binding parent'),
        source_and_input_manifest={str(p.relative_to(ROOT)):digest(p) for p in sources},
        model_identity='none',sampling_reward_contract='no sampling/reward/advantage; no equilibrium or training',
        runtime=dict(python=sys.version,executable=sys.executable,platform=platform.platform()),
        result_sha256=digest(OUT/'audit.json')))
    print(json.dumps({k:v for k,v in result.items() if k!='parents'},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
