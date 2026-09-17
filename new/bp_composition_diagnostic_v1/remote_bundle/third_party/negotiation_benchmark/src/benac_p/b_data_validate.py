"""Independent public-history B replay, grounded SFT export and token audit.

Does not trust stored support certificates or realized partner preferences.
Recomputes support using the fixed policy, checks all unique questions, and
exports only selected source-disjoint records with explicit game grounding.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from benac_p.b_training_data import (
    canonical, digest, make_game, payload, to_chat_sample,
)
from benac_p.mcts_bp_audit import write_json, write_jsonl
from benac_p.mcts_oracle import Budget
from benac_p.private_game_pilot import apply
from benac_p.state import GameState


GROUNDED_SYSTEM = '''You control only learner_id in the provided multiplayer game.
Your own_preferences belong only to learner_id. The query names a DIFFERENT
player and one of that player's private goal preferences.

Game rules:
- Preference encoding: 1 = want, 0 = neutral, -1 = avoid.
- A goal is achieved only when ALL its required player/commitment pairs are
  bound. Every player's terminal utility is the sum of THEIR OWN preference
  values over achieved goals. A goal's requirements do not say who wants it.
- Commitments start at zero and can only change from 0 to 1, irreversibly.
- round_robin lists the proposer for each turn. PASS consumes a proposer turn.
- An OFFER gives full final commitment vectors for proposer and partner;
  at most max_changes new commitments per player may be added. ACCEPT binds
  them; REJECT binds nothing. Either response completes that proposer turn.
- A MENU contains two offers to the same partner. CHOOSE_1 or CHOOSE_2 binds
  only the selected option; REJECT binds neither. These also complete the turn.
- The next scheduled proposer acts after the response. pending_offer is the
  current offer if a response has not yet occurred. history includes explicit
  proposals and responses; do not count a proposal and its response as two
  proposer turns. Other players actively propose as well as respond.

Private prior and evidence:
- Each player independently draws a uniformly distributed background_rows row.
  null denotes an independently drawn goal, NOT a neutral preference.
- Each independent_goal_ids slot independently draws want/neutral/avoid with
  equal weight. These draws are independent of the background and each other.
  Identifying a background alone never identifies an independent goal value.
- All players retain their own private preferences; no realized partner row is
  revealed. initially_possible_preferences applies before the entire history.
- Partner actions follow the fixed partner_policy described in the input.
  Retain every private row compatible with all observed oracle actions under
  that policy, then report the possible values at the queried goal.
- Learner actions are interventions: they change the physical state and what
  partners can observe, but are not evidence excluding learner preference types.
- Do not assume an accepted offer means want: other goals and future actions
  can affect the decision. Do not eliminate possibilities without evidence.

Return the full nonempty possible preference set via SUBMIT_JUDGMENT. Brief
reasoning is allowed, but probabilities, utilities, Q values and plan variables
are not requested.'''


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def grounded_chat(record):
    chat = to_chat_sample(record)
    chat['messages'][0]['content'] = GROUNDED_SYSTEM
    return chat


def revalidate_game(game, records, manifest):
    start = time.perf_counter()
    configuration = manifest['configuration']
    budget = Budget(**manifest['fixed_policy_budget'])
    spec, oracle, actual, focal, public = make_game(game['seed'], game['cell'], budget,
        configuration['backgrounds'], configuration['focal_goals'])
    learner = game['learner']
    root = GameState(spec)
    cache = {(): ((0, 0, None), oracle.prior, root, None)}
    counts = Counter()
    for record in records:
        data = record['input']
        events = data['history']
        key = ()
        for event in events:
            next_key = key + (canonical(event),)
            if next_key not in cache:
                node, domains, native, pending = cache[key]
                assert oracle.actor(node) == event['player_id']
                action = next(a for a in oracle.actions(node)
                              if oracle.native_action(node, a).to_dict() == event['action'])
                # Recompute exact likelihood from all remaining private rows;
                # stored action partitions and support_type_ids are not consulted.
                after = oracle.update(node, action, domains, learner)
                clone = deepcopy(native)
                new_pending = apply(clone, pending, oracle.native_action(node, action))
                new_node = oracle.step(node, action)
                native_rows = [[int(bool(new_node[0] & (1 << (oracle.offsets[p] + a))))
                                for a in range(spec.n_actions_per_player[p])] for p in range(spec.n_players)]
                assert native_rows == clone.public_state()['commitments']
                assert new_node[1] == clone.turn_index
                assert (new_node[2] is None) == (new_pending is None)
                cache[next_key] = new_node, after, clone, new_pending
            key = next_key
        node, domains, _, _ = cache[key]
        target, goal = data['query']['player_id'], data['query']['goal_id']
        assert target != learner and goal in focal[target]
        expected = payload(oracle, public, node, learner, actual[learner], events, target, goal)
        assert canonical(expected) == canonical(data), 'Input contains unverified or inconsistent public/private fields'
        assert digest(data) == record['id']
        gold = oracle.semantic_support(domains, target, goal)
        assert record['answer'] == dict(possible_preferences=gold), 'B answer failed public-history replay'
        counts[len(gold)] += 1
    result = dict(source_id=game['source_id'], verified_questions=len(records),
                  verified_public_prefixes=len(cache), support_size_counts=dict(counts),
                  seconds=time.perf_counter()-start,
                  certificate_fields_trusted=False, partner_realization_used_for_label=False)
    oracle.clear_caches()
    return result


def token_audit(samples, tokenizer_dir):
    """Render the local official Qwen template without downloading model weights."""
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    from tokenizers import Tokenizer
    configuration = json.loads((tokenizer_dir / 'tokenizer_config.json').read_text())
    tokenizer = Tokenizer.from_file(str(tokenizer_dir / 'tokenizer.json'))
    environment = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    environment.filters['tojson'] = lambda value, **kwargs: json.dumps(value, ensure_ascii=False, **kwargs)
    def raise_exception(message):
        raise ValueError(message)
    environment.globals['raise_exception'] = raise_exception
    template_path = tokenizer_dir/'chat_template.jinja'
    template_text = template_path.read_text() if template_path.exists() else configuration['chat_template']
    template = environment.from_string(template_text)
    records = []
    for sample in samples:
        full = template.render(messages=sample['messages'], tools=sample['tools'], add_generation_prompt=False)
        prompt = template.render(messages=sample['messages'][:-1], tools=sample['tools'], add_generation_prompt=True)
        assert full.startswith(prompt)
        completion = full[len(prompt):]
        call = completion.split('<tool_call>\n', 1)[1].split('\n</tool_call>', 1)[0]
        parsed = json.loads(call)
        expected = sample['messages'][-1]['tool_calls'][0]['function']
        assert parsed == dict(name='SUBMIT_JUDGMENT', arguments=json.loads(expected['arguments']))
        full_ids = tokenizer.encode(full, add_special_tokens=False).ids
        prompt_ids = tokenizer.encode(prompt, add_special_tokens=False).ids
        assert full_ids[:len(prompt_ids)] == prompt_ids, 'Token boundary does not align with assistant completion'
        records.append(dict(id=sample['id'], prompt_tokens=len(prompt_ids),
                            target_tokens=len(full_ids)-len(prompt_ids), total_tokens=len(full_ids)))
    def describe(key):
        values = [r[key] for r in records]
        return dict(min=min(values), median=float(np.median(values)),
                    p95=float(np.percentile(values, 95)), max=max(values)) if values else {}
    provenance_path = tokenizer_dir/'provenance.json'
    return dict(provenance=json.loads(provenance_path.read_text()) if provenance_path.exists() else
                dict(local_tokenizer_dir=str(tokenizer_dir), revision_not_recorded=True),
                tokenizer_sha256=hashlib.sha256((tokenizer_dir/'tokenizer.json').read_bytes()).hexdigest(),
                chat_template_sha256=hashlib.sha256(template_text.encode()).hexdigest(),
                samples=len(records), prompt_tokens=describe('prompt_tokens'),
                target_tokens=describe('target_tokens'), total_tokens=describe('total_tokens'),
                assistant_boundary_verified=True, rendered_tool_calls_verified=True,
                over_4096=sum(r['total_tokens'] > 4096 for r in records),
                over_8192=sum(r['total_tokens'] > 8192 for r in records), records=records)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--tokenizer-dir', type=Path)
    parser.add_argument('--verified-base', type=Path,
                        help='Reuse a previously verified corpus only for byte-identical source games and records.')
    args = parser.parse_args(argv)
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error('Use a fresh output directory.')
    manifest = json.loads((args.source_dir/'manifest.json').read_text())
    summary = json.loads((args.source_dir/'summary.json').read_text())
    assert summary['complete']
    for name, expected in manifest['source_sha256'].items():
        assert hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() == expected, name
    for name, expected in json.loads((args.source_dir/'checksums.json').read_text()).items():
        assert hashlib.sha256((args.source_dir/name).read_bytes()).hexdigest() == expected, name
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir/'manifest.json', dict(source_manifest=manifest,
        validator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        source_checksums_sha256=hashlib.sha256((args.source_dir/'checksums.json').read_bytes()).hexdigest(),
        supervision='B-only verified tool call; no reasoning targets; no GPU training',
        grounded_system=GROUNDED_SYSTEM))
    all_rows = load_jsonl(args.source_dir/'b_all_unique.jsonl')
    by_id = {r['id']: r for r in all_rows}
    assert len(by_id) == len(all_rows)
    reusable = {}
    if args.verified_base:
        base_manifest = json.loads((args.verified_base/'manifest.json').read_text())
        for name, checksum in json.loads((args.verified_base/'checksums.json').read_text()).items():
            assert hashlib.sha256((args.verified_base/name).read_bytes()).hexdigest() == checksum
        for name, checksum in base_manifest['source_manifest']['source_sha256'].items():
            assert manifest['source_sha256'][name] == checksum, 'Base policy/generation source changed'
        base_source = Path(base_manifest['source_manifest']['configuration']['output_dir'])
        assert hashlib.sha256((base_source/'checksums.json').read_bytes()).hexdigest() == base_manifest['source_checksums_sha256']
        for name, checksum in json.loads((base_source/'checksums.json').read_text()).items():
            assert hashlib.sha256((base_source/name).read_bytes()).hexdigest() == checksum
        base_rows = load_jsonl(base_source/'b_all_unique.jsonl')
        for result in json.loads((args.verified_base/'validation.json').read_text())['public_history_replay']:
            source = result['source_id']
            questions = [r for r in base_rows if r['source_id'] == source]
            reusable[source] = (result, digest(sorted(questions, key=lambda r: r['id'])),
                hashlib.sha256((base_source/'games'/f'{source}.json').read_bytes()).hexdigest())
    verified = []
    for path in sorted((args.source_dir/'games').glob('*.json')):
        game = json.loads(path.read_text())
        questions = [r for r in all_rows if r['source_id'] == game['source_id']]
        if game['source_id'] in reusable:
            old, question_digest, game_digest = reusable[game['source_id']]
            assert digest(sorted(questions, key=lambda r: r['id'])) == question_digest
            assert hashlib.sha256(path.read_bytes()).hexdigest() == game_digest
            result = dict(old, seconds=0.0, reused_verified_source=True,
                          original_validation_seconds=old['seconds'])
            print('REUSE_VERIFIED', game['source_id'], flush=True)
        else:
            print('REPLAY', game['source_id'], flush=True)
            result = revalidate_game(game, questions, manifest)
        verified.append(result)
        write_json(args.output_dir/'replay_progress.json', verified)
        print(json.dumps(result), flush=True)
    pairs = load_jsonl(args.source_dir/'update_pairs.jsonl')
    for pair in pairs:
        before, after = by_id[pair['before']], by_id[pair['after']]
        assert before['source_id'] == after['source_id'] == pair['source_id']
        assert before['input']['history'] == after['input']['history'][:-1]
        assert before['input']['query'] == after['input']['query']
        assert set(after['answer']['possible_preferences']) <= set(before['answer']['possible_preferences'])
        if pair['transition'] == 'intervention_unchanged':
            assert before['answer'] == after['answer']
    chats, split_ids = [], {}
    for split in ('train', 'validation', 'test'):
        rows = load_jsonl(args.source_dir/f'b_{split}.jsonl')
        assert all(by_id[r['id']] == r for r in rows)
        assert all(summary['source_split'][r['source_id']] == split for r in rows)
        split_ids[split] = {r['id'] for r in rows}
        samples = [grounded_chat(r) for r in rows]
        chats.extend(samples)
        write_jsonl(args.output_dir/f'{split}.jsonl', samples)
        # Gold labels are separate from model-facing prompt exports.
        write_jsonl(args.output_dir/f'{split}_prompts.jsonl', [dict(
            id=s['id'], source_id=s['source_id'], messages=s['messages'][:-1], tools=s['tools']) for s in samples])
        write_jsonl(args.output_dir/f'{split}_gold.jsonl', [dict(
            id=r['id'], source_id=r['source_id'], answer=r['answer']) for r in rows])
    assert not (split_ids['train'] & split_ids['validation'] or split_ids['train'] & split_ids['test']
                or split_ids['validation'] & split_ids['test'])
    tokens = token_audit(chats, args.tokenizer_dir) if args.tokenizer_dir else None
    if tokens:
        write_json(args.output_dir/'token_lengths.json', tokens)
    report = dict(public_history_replay=verified, verified_unique_questions=len(all_rows),
                  verified_update_pairs=len(pairs), exported_samples=len(chats),
                  splits={name: len(ids) for name, ids in split_ids.items()},
                  source_disjoint=True, token_audit=None if tokens is None else {k: v for k, v in tokens.items() if k != 'records'},
                  training_started=False, model_accuracy_measured=False,
                  remaining='Model preflight and B-only SFT effectiveness; long-horizon uncertainty and cross-policy transfer remain experimental questions.')
    write_json(args.output_dir/'validation.json', report)
    files = sorted(p for p in args.output_dir.rglob('*') if p.is_file())
    write_json(args.output_dir/'checksums.json', {str(p.relative_to(args.output_dir)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
