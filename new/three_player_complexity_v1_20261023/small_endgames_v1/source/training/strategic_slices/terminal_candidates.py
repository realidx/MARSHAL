"""Terminal candidate review format: singleton or collective entry distributions.

This loader deliberately does not use Dataset's training-ready contract.
A collective information contrast is stored once, never copied to its members.
"""
from collections import OrderedDict, Counter
import json
from pathlib import Path
import numpy as np
from training.b_sft.preference_contract import world_weights
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from .bounded import BoundedPrivateWindow
from .common import file_hash, replay_node, stable
from .values import window_values

VERSION = 'terminal-candidate-distributions-v1'
LEGACY_ENTRANCE_CONTRACT = 'terminal-neighborhood-three-proposals-v1'
LOCAL_DECISION_ENTRANCE_CONTRACT = 'initial-terminal-local-decisions-v2'


def restore_reference(raw, record, path):
    rules = PrivateInvestigationRules(raw)
    rules.background_prior = raw['background_prior']
    certificate = record['certificate']
    weights = record.get('world_weights', world_weights(rules.worlds, raw['background_prior']))
    tree = BoundedPrivateWindow(rules, replay_node(rules, record['history']), rules.worlds,
        world_weights=weights, lookahead_rr=certificate['lookahead_rr'],
        max_nodes=160000, seconds=120,
        max_candidates=certificate.get('max_candidates',6),
        max_joint_cells=certificate.get('max_joint_cells',4096),
        max_joint_evaluations=certificate.get('max_joint_evaluations',160),
        large_tree_ordered_sweeps=certificate.get('large_tree_ordered_sweeps',2))
    with np.load(path, allow_pickle=False) as saved:
        flat = saved['probabilities']
    cursor = 0
    for i, entry in enumerate(tree.entries):
        if entry.actor is not None:
            size = len(entry.actions)*tree.w
            tree.policy[i] = flat[cursor:cursor+size].reshape(len(entry.actions),tree.w)
            cursor += size
    if cursor != len(flat):
        raise ValueError('Reference size differs from native tree')
    tree.certificate = certificate
    if tree.reference_identity()[0] != certificate['policy_sha256']:
        raise ValueError('Reference policy identity mismatch')
    audit = tree.audit_native()
    if audit['cutoff_leaves'] or not all(e.node.state.is_terminal for e in tree.entries if e.actor is None):
        raise ValueError('Terminal candidates cannot contain cutoff leaves')
    if not certificate.get('verified') or certificate['max_own_deviation_gain'] > certificate['numerical_epsilon']:
        raise ValueError('Missing valid certificate')
    return tree


def validate_distribution(row):
    contract = row.get('entrance_contract', LEGACY_ENTRANCE_CONTRACT)
    if contract not in (LEGACY_ENTRANCE_CONTRACT, LOCAL_DECISION_ENTRANCE_CONTRACT):
        raise ValueError('Unknown entrance contract')
    if contract == LOCAL_DECISION_ENTRANCE_CONTRACT and (type(row.get('k')) is not int or not 1 <= row['k'] <= 3):
        raise ValueError('Expanded entrance requires k=1/2/3')
    members = row['members']
    if not members:
        raise ValueError('Empty entrance distribution')
    joint = np.asarray([m['joint_world_masses'] for m in members], dtype=float)
    if joint.ndim != 2 or not np.isfinite(joint).all() or (joint < 0).any() or abs(joint.sum()-1)>1e-9:
        raise ValueError('Invalid joint entrance/world distribution')
    if len({m['root_index'] for m in members}) != len(members):
        raise ValueError('Repeated entrance')
    for m, masses in zip(members, joint):
        probability = masses.sum()
        if probability <= 0 or abs(probability-m['probability'])>1e-9:
            raise ValueError('Member probability differs from joint mass')
        if not np.allclose(masses/probability, m['world_weights'], atol=1e-9, rtol=0):
            raise ValueError('Member posterior differs from joint mass')
        remaining = m['remaining_proposals']
        if type(remaining) is not int or remaining < 1 or (contract == LEGACY_ENTRANCE_CONTRACT and remaining > 3):
            raise ValueError('Entrance outside terminal neighborhood')
    for key in ('V_star', 'V_min', 'C_span'):
        expected = sum(m['probability']*m[key] for m in members)
        if abs(expected-row[key])>1e-7:
            raise ValueError('Collective value differs from member expectation: '+key)
    if abs(row['C_span']-(row['V_star']-row['V_min']))>1e-7 or row['C_span']<=.1:
        raise ValueError('Invalid C span')
    if any(v is not None and (not np.isfinite(v) or v < -1e-7) for v in row['information_channels'].values()):
        raise ValueError('Invalid information value')
    return joint


def sample_member_world(row, rng):
    """Draw from p(history, world), not uniform histories or averaged posteriors."""
    joint = validate_distribution(row)
    flat_index = int(rng.choice(joint.size, p=joint.ravel()))
    member_index, world_index = divmod(flat_index, joint.shape[1])
    return member_index, world_index


class TerminalCandidates:
    def __init__(self, path):
        self.root = Path(path)
        self.manifest = json.loads((self.root/'manifest.json').read_text())
        if self.manifest['version'] != VERSION:
            raise ValueError('Unsupported candidate format')
        for name, checksum in self.manifest['files'].items():
            if file_hash(self.root/name) != checksum:
                raise ValueError('Candidate file changed: '+name)
        parent_rows = self._rows('parents.jsonl')
        reference_rows = self._rows('references.jsonl')
        self.candidates = self._rows('candidates.jsonl')
        for rows in (parent_rows, reference_rows, self.candidates):
            if len({r['id'] for r in rows}) != len(rows):
                raise ValueError('Duplicate candidate/parent/reference identity')
        self.parents = {r['id']:r for r in parent_rows}
        self.references = {r['id']:r for r in reference_rows}
        if max(Counter(r['parent_id'] for r in self.candidates).values(), default=0)>self.manifest.get('selection',{}).get('max_per_parent',8):
            raise ValueError('Parent window cap exceeded')
        if max(Counter(r['family'] for r in parent_rows).values(), default=0)>8:
            raise ValueError('Family parent cap exceeded')
        if any(p.get('calibration_family') and p['split']!='train' for p in parent_rows):
            raise ValueError('Calibration parent outside train')
        if self.manifest.get('oracle_contract')=='initial-terminal-oracle-consistent-v1':
            if any(ref['history'] or ref['belief_regime']!='initial-prior-plus-reference-reach' for ref in reference_rows):
                raise ValueError('Oracle-consistent corpus requires initial-root references')
            for pid in self.parents:
                rows=[r for r in self.candidates if r['parent_id']==pid]
                if len(rows)<2 or len({r['reference_id'] for r in rows})!=1:
                    raise ValueError('Each parent requires multiple slices and one reference')
        self.cache = OrderedDict()
        family_splits = {}
        for p in self.parents.values():
            previous = family_splits.setdefault(p['family'],p['split'])
            if previous != p['split']:
                raise ValueError('Structural family crosses splits')
        for r in self.candidates:
            manifest_contract = self.manifest.get('entrance_contract', LEGACY_ENTRANCE_CONTRACT)
            contract = r.get('entrance_contract', LEGACY_ENTRANCE_CONTRACT)
            allowed = ((LEGACY_ENTRANCE_CONTRACT, LOCAL_DECISION_ENTRANCE_CONTRACT)
                       if manifest_contract == LOCAL_DECISION_ENTRANCE_CONTRACT else (manifest_contract,))
            if contract not in allowed:
                raise ValueError('Candidate entrance contract differs from manifest')
            validate_distribution(r)
            p = self.parents[r['parent_id']]; ref = self.references[r['reference_id']]
            if contract == LOCAL_DECISION_ENTRANCE_CONTRACT:
                certificate = ref['certificate']
                if (ref['history'] or not certificate.get('verified') or certificate.get('cutoff_leaves') != 0
                        or not certificate.get('remaining_game_terminal_scope')
                        or self.manifest.get('oracle_contract') != 'initial-terminal-oracle-consistent-v1'):
                    raise ValueError('Expanded candidate requires an initial terminal reference')
                if any(m['remaining_proposals'] > len(p['raw']['game']['round_robin']) for m in r['members']):
                    raise ValueError('Entrance extends beyond parent schedule')
            if r['split'] != p['split'] or r['family'] != p['family'] or ref['parent_id'] != p['id']:
                raise ValueError('Candidate parent/reference mismatch')
        self.entry_answer_relations = []
        if (self.root/'entry_answer_relations.jsonl').exists():
            from .entry_answers import action_information_value
            self.entry_answer_relations = self._rows('entry_answer_relations.jsonl')
            candidates = {r['id']: r for r in self.candidates}
            for group in self.entry_answer_relations:
                ids = group['candidate_ids']
                if len(set(ids)) != len(ids) or len(ids) != len(group['members']) or len(ids) < 2:
                    raise ValueError('Invalid entry-answer relation members')
                if not set(ids) <= candidates.keys():
                    raise ValueError('Entry-answer contrast lost a member')
                for cid, member in zip(ids, group['members']):
                    row = candidates[cid]
                    if (member['candidate_id'] != cid or row['parent_id'] != group['parent_id']
                            or row['reference_id'] != group['reference_id'] or row['split'] != group['split']
                            or row['ego'] != group['ego'] or row['k'] != 1 or len(row['members']) != 1):
                        raise ValueError('Entry-answer relation crosses reference or information scope')
                    actual = row['members'][0]
                    if (actual['root_index'] != group['root_index']
                            or stable(actual['history']) != stable(member['history'])
                            or not np.allclose(actual['world_weights'], member['world_weights'], atol=1e-9, rtol=0)
                            or not np.allclose(actual['root_Q'], member['root_Q'], atol=1e-8, rtol=0)
                            or not np.allclose(member['joint_world_masses'], np.asarray(member['world_weights'])*member['probability'], atol=1e-9, rtol=0)):
                        raise ValueError('Entry-answer relation disagrees with singleton question')
                metric = action_information_value([m['root_Q'] for m in group['members']],
                    [m['probability'] for m in group['members']], group['epsilon'])
                if any(abs(metric[key]-group[key]) > 1e-8 for key in ('V_full', 'V_masked', 'S')):
                    raise ValueError('Entry-answer information value mismatch')
                if metric['must_change_pairs'] != group['must_change_pairs']:
                    raise ValueError('Entry-answer must-change certificate mismatch')

    def _rows(self,name):
        return [json.loads(line) for line in (self.root/name).read_text().splitlines()]

    def reference(self, row):
        rid = row['reference_id']
        if rid not in self.cache:
            ref = self.references[rid]
            self.cache[rid] = restore_reference(self.parents[row['parent_id']]['raw'], ref, self.root/ref['file'])
            while len(self.cache)>2:
                self.cache.popitem(last=False)
        self.cache.move_to_end(rid)
        return self.cache[rid]

    def audit_values(self):
        checked=0
        for row in sorted(self.candidates, key=lambda r:r['reference_id']):
            tree=self.reference(row)
            for member in row['members']:
                node=tree.rules.initial()
                for action in member['history']:
                    actions=tree.rules.actions(node)
                    ai=(next(i for i,a in enumerate(actions) if stable(a.to_dict())==stable(action))
                        if member['history_encoding']=='native-action-dicts' else action)
                    node=tree.rules._apply(node,actions[ai])
                actual=tree.entries[member['root_index']]
                if node.state.public_state()!=actual.node.state.public_state() or actual.actor!=row['ego']:
                    raise ValueError('Member history differs from reference entrance')
                if len(tree.rules.spec.round_robin)-node.state.turn_index!=member['remaining_proposals']:
                    raise ValueError('Remaining native horizon mismatch')
                metric=window_values(tree,row['ego'],member['root_index'],member['world_weights'],row['k'])
                for key in ('V_star','V_min','C_span'):
                    if abs(metric[key]-member[key])>1e-7:
                        raise ValueError('Saved metric differs from native reference: '+key)
                checked+=1
        return dict(candidates=len(self.candidates),member_values_checked=checked,
                    native_terminal_only=True,policy_hashes_verified=True,joint_distributions_verified=True)
