"""Native games, identical action interface, and frozen-reference loading."""
from copy import deepcopy
from collections import OrderedDict
import hashlib
import json
from pathlib import Path

import numpy as np
from training.b_sft.social_private_teacher import PrivateEpisode, PrivateInvestigationRules, PrivateWindow, observed_slots
from training.b_sft.social_b_oracle import NAMES

VERSION = 'strategic-slices-v1'


def stable(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(stable(value).encode()).hexdigest()


def file_hash(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def seed_for(*parts):
    return int(digest(parts)[:8], 16)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def write_rows(path, rows):
    Path(path).write_text(''.join(stable(r) + '\n' for r in rows))


def request(rules, node, world, seed, temperature=1.0, cutoff=None, remaining_decisions=None):
    actor = rules.actor(node)
    visible = rules.observation(node, actor, world[actor])
    visible['game'] = rules.public_game()
    # Public support is an explicit game assumption, identical in both arms.
    visible['public_preference_support'] = {
        str(p): [[NAMES[v] for v in row] for row in rows]
        for p, rows in rules.catalogues.items()
    }
    visible['background_prior'] = getattr(rules, 'background_prior', {'weights': {'want': 1, 'neutral': 1, 'avoid': 1}})
    actions = [a.to_dict() for a in rules.actions(node)]
    visible['legal_actions'] = [dict(index=i, action=a) for i, a in enumerate(actions)]
    system = (
        'Play this finite mixed-incentive negotiation game to maximize your own terminal utility. '
        'WANT=+1, NEUTRAL=0, AVOID=-1. A binary goal contributes only when ALL its requirements '
        'are committed; a linear goal contributes its committed fraction. Add contributions across goals. '
        'Commitments are irreversible and do not exclude other commitments. Only accepted offers bind. '
        'Investigation consumes your current proposal opportunity and your one investigation budget; '
        'only you see its answer. Preferences are fixed. The public support lists possible types, '
        'not the partners\' actual types. Background weights apply jointly over this support; '
        'observed behavior and private answers may change your belief. '
        'Use the public history, your own preferences and your private answers. '
        'Give brief reasoning, then call act exactly once with the index of a listed legal action.'
    )
    if cutoff is not None:
        system = system.replace('maximize your own terminal utility.',
            'maximize your own commitment utility at the specified cutoff.')
        visible['evaluation_window'] = dict(absolute_proposal_cutoff=cutoff,
            remaining_controlled_decisions=remaining_decisions,
            stop='Finish any pending response at the cutoff; score only commitments already made.',
            continuation='Other players, and you after your controlled decisions, follow a fixed certified reference until this cutoff.')
    return dict(messages=[dict(role='system', content=system), dict(role='user', content=stable(visible))],
                tools=[dict(type='function', function=dict(name='act', description='Execute the indexed legal action.',
                    parameters=dict(type='object', properties=dict(action_index=dict(type='integer', enum=list(range(len(actions))))),
                                    required=['action_index'], additionalProperties=False)))],
                seed=seed, temperature=temperature)


def decode(output, actions):
    completion = output['completion']
    if output.get('finish_reason', completion.get('finish_reason')) == 'length':
        return None, 'truncated'
    calls = completion.get('raw_message', {}).get('tool_calls') or []
    try:
        if len(calls) != 1 or calls[0]['function']['name'] != 'act':
            raise ValueError('Exactly one act call required')
        args = json.loads(calls[0]['function']['arguments'])
        index = args['action_index']
        if set(args) != {'action_index'} or type(index) is not int or not 0 <= index < len(actions):
            raise ValueError('Illegal index')
        return index, 'ok'
    except (ValueError, KeyError, TypeError):
        return None, 'invalid_action'


def save_reference(path, tree):
    flat = np.concatenate([p.ravel() for p in tree.policy if p is not None])
    np.savez_compressed(path, probabilities=flat)


class Dataset:
    def __init__(self, path, splits=('train', 'validation')):
        self.root = Path(path).resolve()
        self.manifest = json.loads((self.root / 'manifest.json').read_text())
        if self.manifest['version'] != VERSION or not (self.root / 'COMPLETE.json').is_file():
            raise ValueError('Incomplete or unsupported dataset')
        self.sha = file_hash(self.root / 'manifest.json')
        if json.loads((self.root / 'COMPLETE.json').read_text())['manifest_sha256'] != self.sha:
            raise ValueError('Dataset completion identity changed')
        self.parents, self.slices, self.cache = {}, {}, OrderedDict()
        for split in splits:
            for kind, target in [('parents', self.parents), ('slices', self.slices)]:
                name = f'{split}_{kind}.jsonl'
                if file_hash(self.root / name) != self.manifest['files'][name]['sha256']:
                    raise ValueError('Dataset hash mismatch: ' + name)
                target[split] = [json.loads(line) for line in (self.root / name).read_text().splitlines()]
                if any(r['split'] != split for r in target[split]):
                    raise ValueError('Split mismatch')
        self.by_id = {p['id']: p for ps in self.parents.values() for p in ps}
        for split, slices in self.slices.items():
            ids = {p['id'] for p in self.parents[split]}
            if {s['parent_id'] for s in slices} != ids:
                raise ValueError('Every shared parent must have at least one slice')
        for a in splits:
            for b in splits:
                if a != b and {p['family'] for p in self.parents[a]} & {p['family'] for p in self.parents[b]}:
                    raise ValueError('Structural family leaks across splits')

    def rules(self, parent):
        rules = PrivateInvestigationRules(parent['raw'])
        rules.background_prior = parent['raw']['background_prior']
        return rules

    def tree(self, parent):
        if parent.get('reference_backend', 'synchronous-certified-v1') == 'fixed-myopic-v1':
            raise ValueError('Fixed references do not construct a full public game tree; use reference(parent)')
        if parent['id'] not in self.cache:
            path = self.root / parent['reference_file']
            if file_hash(path) != parent['reference_sha256']:
                raise ValueError('Reference changed')
            rules = self.rules(parent)
            tree = PrivateWindow(rules, rules.initial(), rules.worlds,
                                 world_weights=parent['world_weights'], max_nodes=self.manifest['config']['max_nodes'],
                                 seconds=120, max_sweeps=128)
            flat = np.load(path, allow_pickle=False)['probabilities']
            cursor = 0
            for index, entry in enumerate(tree.entries):
                if entry.actor is not None:
                    size = len(entry.actions) * tree.w
                    tree.policy[index] = flat[cursor:cursor + size].reshape(len(entry.actions), tree.w)
                    cursor += size
            if cursor != len(flat):
                raise ValueError('Reference/tree shape mismatch')
            tree.certificate = deepcopy(parent['certificate'])
            actual, _ = tree.reference_identity()
            if actual != tree.certificate['policy_sha256']:
                raise ValueError('Reference policy identity mismatch')
            self.cache[parent['id']] = tree
            while len(self.cache) > 4:
                self.cache.popitem(last=False)
        self.cache.move_to_end(parent['id'])
        return self.cache[parent['id']]

    def reference(self, parent, slice_record=None):
        """Load the declared reference without changing older frozen datasets."""
        backend = parent.get('reference_backend', 'synchronous-certified-v1')
        if backend == 'bounded-next-own-v1':
            from .bounded_data import CONTRACT, load_reference
            if self.manifest.get('training_contract') != CONTRACT:
                raise ValueError('Missing or changed bounded training contract')
            reference_id = (slice_record['reference_id'] if slice_record is not None else
                            next(iter(parent['bounded_references'])))
            key = (parent['id'], reference_id)
            if key not in self.cache:
                self.cache[key] = load_reference(self, parent, parent['bounded_references'][reference_id])
                while len(self.cache) > 4:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(key)
            tree = self.cache[key]
            if slice_record is not None and (slice_record['history'] != parent['bounded_references'][reference_id]['history']
                    or slice_record['absolute_cutoff'] != tree.cutoff or slice_record['root_index'] != 0):
                raise ValueError('Bounded slice entrance or cutoff mismatch')
            return tree
        if backend in ('synchronous', 'synchronous-certified-v1'):
            return self.tree(parent)
        if backend != 'fixed-myopic-v1':
            raise ValueError('Unsupported reference backend: ' + backend)
        if self.manifest['config'].get('reference_policy') != backend:
            raise ValueError('Reference backend differs from dataset contract')
        if parent['id'] not in self.cache:
            from .reference import FixedReference
            reference = FixedReference(self.rules(parent), background_prior=parent['raw']['background_prior'])
            expected = parent['certificate'].get('contract_sha256')
            if expected is None or reference.certificate['contract_sha256'] != expected:
                raise ValueError('Fixed reference contract identity mismatch')
            self.cache[parent['id']] = reference
            while len(self.cache) > 4:
                self.cache.popitem(last=False)
        self.cache.move_to_end(parent['id'])
        return self.cache[parent['id']]


def materialize_node(tree, index, world):
    node = deepcopy(tree.entries[index].node)
    node.state.private_results = tuple(
        tuple((p, g, world[p][g]) for p, g in observed_slots(node, actor))
        for actor in range(tree.n))
    return node


def replay_node(rules, history, world=None):
    """Replay native action indices, delivering answers only in a realized world."""
    node = rules.initial()
    for index in history:
        actions = rules.actions(node)
        if type(index) is not int or not 0 <= index < len(actions):
            raise ValueError('Invalid native entrance history')
        node = (rules._apply(node, actions[index]) if world is None else
                rules.step(node, actions[index], realized_world=world))
    return node
