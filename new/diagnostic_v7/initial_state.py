"""Exogenous starting bindings, followed only by genuine observed choices.

Isolated diagnostic implementation: does not change any training teacher.
"""
from copy import deepcopy
import numpy as np
from training.b_sft.social_private_teacher import PrivateEpisode, PrivateInvestigationRules, PrivateWindow
from training.b_sft.preference_contract import world_weights
from benac_p.endgame_diagnose import decode_action


class StartingRules(PrivateInvestigationRules):
    def __init__(self, raw, initial):
        super().__init__(raw)
        self.start = deepcopy(initial)
        if set(initial) - {'commitments', 'turn_index', 'pending_offer', 'investigation_remaining'} or 'commitments' not in initial:
            raise ValueError('Only exogenous commitments are supported; no hidden history/private knowledge')
        rows = initial['commitments']
        if len(rows) != self.spec.n_players:
            raise ValueError('Wrong player count')
        for p, row in enumerate(rows):
            if len(row) != self.spec.n_actions_per_player[p] or any(v not in (0, 1) for v in row):
                raise ValueError('Invalid initial commitments')
        turn = initial.get('turn_index', 0)
        if not isinstance(turn, int) or not 0 <= turn < len(self.spec.round_robin):
            raise ValueError('Invalid starting decision index')
        # Also let the native state validate goal evaluation on these bindings.
        self.initial().state.public_state()

    def initial(self):
        root = super().initial()
        root.state.turn_index = self.start.get('turn_index', 0)
        for p, row in enumerate(self.start['commitments']):
            root.state.commitments[p, :len(row)] = row
        remaining = self.start.get('investigation_remaining', [1]*self.spec.n_players)
        if len(remaining)!=self.spec.n_players or any(v not in (0,1) for v in remaining):
            raise ValueError('Invalid investigation quota')
        root.state.investigation_used = tuple(not v for v in remaining)
        if self.start.get('pending_offer'):
            event=dict(self.start['pending_offer'],action='OFFER')
            proposal=decode_action(event)
            root.state.validate_offer(proposal.offer)
            root.pending=proposal.offer
        return root


class InitialEpisode(PrivateEpisode):
    def __init__(self, raw, initial, **budgets):
        if raw.get('history'):
            raise ValueError('Starting state cannot hide a behavioral history')
        self.raw = deepcopy(raw)
        self.rules = StartingRules(raw, initial)
        root = self.rules.initial()
        if raw.get('background_prior'):
            if 'world_weights' in budgets:
                raise ValueError('Two priors')
            budgets['world_weights'] = world_weights(root.worlds, raw['background_prior'])
        self.tree = PrivateWindow(self.rules, root, root.worlds, **budgets).solve()
        self.index = 0
        self.weights = self.tree.world_weights.copy()


def materialize_start(raw, setup):
    """Use a legacy setup only to specify physical starting bindings.

    Pending offers and past private investigations cannot be silently erased.
    The original schedule is retained with an explicit starting decision index. This is a
    NEW instance, requiring a new teacher solve, never a claim of old equality.
    """
    rules = PrivateInvestigationRules(raw)
    root = rules.initial()
    for event in setup:
        if event.get('action') == 'INVESTIGATE' or 'revealed_preference' in event:
            raise ValueError('Past investigation requires explicit information-state redesign')
        action = decode_action(event)
        if action not in rules.actions(root):
            raise ValueError('Illegal legacy setup')
        root = rules._apply(root, action)
    if root.pending is not None:
        raise ValueError('Pending partner offer must be retained as an actual event')
    remaining = list(rules.spec.round_robin[root.state.turn_index:])
    if not remaining:
        raise ValueError('No remaining decision')
    rebuilt = deepcopy(raw)
    rebuilt['history'] = []
    return rebuilt, {'commitments': root.state.public_state()['commitments'], 'turn_index':root.state.turn_index}


def request(task, initial):
    """Render B or native O; controlled P is constructed separately."""
    from new.diagnostic_v2.composition.prepare import request as native_request
    from new.diagnostic_v6.build import REFERENCE_POLICY_NOTE
    from training.b_sft.social_named_probe import present
    from training.b_sft.review_prompt import state_table
    if task['input'].get('imposed_setup'):
        raise ValueError('Do not pass legacy imposed events to the model')
    task = deepcopy(task)
    task['input']['initial_commitments'] = deepcopy(initial['commitments'])
    task['input']['initial_turn_index'] = initial.get('turn_index', 0)
    req = native_request(task)
    v = present(task, 0)
    names = list(v['commitments_available'])
    binding = {name:[a for a,bit in zip(v['commitments_available'][name],initial['commitments'][p]) if bit]
               for p,name in enumerate(names)}
    block = '\n'.join(state_table(v,binding,'INITIAL STATE AT GAME START'))
    block += ('\nThese binding commitments are starting conditions, assigned independently of private preferences. '
              'No player actions precede this game. Only the events below occurred after the start.\n')
    text = req['messages'][1]['content']
    text = text.replace(REFERENCE_POLICY_NOTE,
        'For this diagnostic, initialize legal choices uniformly at the stated initial state and synchronously '
        'update player best responses until stable; randomize uniformly among remaining optimal choices.\n')
    req['messages'][1]['content'] = text.replace('EVENTS IN ORDER',block+'\nEVENTS SINCE GAME START')
    if any(x in req['messages'][1]['content'].lower() for x in ('preset','imposed')):
        raise ValueError('Legacy provenance wording remains in prompt')
    return req
