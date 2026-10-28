"""Native online B/P interaction with explicit learner interventions.

This is an environment/scoring adapter, not a PPO trainer. Old frozen-window
labels are not reused. Every learner action preserves the current type support
and restarts the common partner window at the actual resulting history.
"""
from copy import deepcopy
import time
import numpy as np

from training.b_sft.shared_teacher import SharedGame, SearchLimit, specification
from training.b_sft.social_cases import B_INSTRUCTION, p_input
from training.b_sft.social_task import fixed_context
from training.b_sft.social_rollout import queries_for
from training.b_sft.favored_belief import marginal, score_belief
from benac_p.endgame_diagnose import decode_action

VERSION = 'online-social-interventions-v1'


class OnlineSocial:
    def __init__(self, raw, prefix=(), *, turns=2, max_nodes=10000, seconds=5):
        if raw.get('history'):
            raise ValueError('Do not silently reuse a legacy observed history. Start from history=[] and replay versioned online events.')
        self.raw = deepcopy(raw)
        self.raw.pop('teacher_model', None)  # Explicit new protocol; never reuse static labels.
        self.game = SharedGame(self.raw, turns=turns, max_nodes=max_nodes, seconds=seconds)
        self.node = self.game.rules.initial(); self.worlds = self.game.worlds
        self.history = []; self.events = []; self.position = None
        self.invalid_reason = None; self.fragile = False
        self.prefix = deepcopy(list(prefix)); self.budgets = dict(turns=turns, max_nodes=max_nodes, seconds=seconds)
        for raw_action in prefix:
            action = decode_action(raw_action)
            actor = self.game.rules.actor(self.node)
            self.node = self.game.rules._apply(self.node, action)
            self.history.append(action.to_dict())
            self.events.append(dict(kind='setup', actor=actor, action=action.to_dict()))

    @classmethod
    def replay_events(cls, raw, events, *, protocol, **budgets):
        if protocol != VERSION: raise ValueError('Old teacher histories require regeneration under the online protocol')
        prefix = []; rest = list(events)
        while rest and rest[0]['kind'] == 'setup': prefix.append(rest.pop(0)['action'])
        env = cls(raw, prefix, **budgets)
        for event in rest:
            if event['kind'] not in ('learner', 'partner') or event['actor'] != env.actor:
                raise ValueError('Invalid event provenance/actor')
            if event.get('unavailable'): env.invalid_reason = event['unavailable']; env.position = None
            env.step(event['action'], kind=event['kind'])
        return env

    @property
    def actor(self): return self.game.rules.actor(self.node)

    @property
    def terminal(self): return self.node.state.is_terminal

    def fork(self):
        other = object.__new__(type(self))
        other.__dict__ = self.__dict__.copy()
        other.history = deepcopy(self.history); other.events = deepcopy(self.events)
        # Native transitions clone state. Certified trees/cache are immutable.
        return other

    def ensure_teacher(self):
        if self.terminal or self.invalid_reason: return False
        if self.position is None:
            try:
                tree = self.game.window(self.node, self.worlds)
                self.position = tree, 0, tuple(range(len(tree.worlds)))
            except SearchLimit as exc:
                self.invalid_reason = str(exc)
                return False
        return True

    def context(self):
        if self.terminal: raise ValueError('No decision prompt after terminal')
        if self.actor != self.raw['ego']: raise ValueError('Learner prompt requested on partner turn')
        return fixed_context(dict(player=self.actor, own_preferences=self.raw['own_preferences'],
                    game=self.game.rules.spec.to_dict(include_private=False),
                    public_state=self.node.state.public_state(),
                    pending_offer=None if self.node.pending is None else self.node.pending.to_dict(),
                    history=deepcopy(self.history), public_type_catalogues=self.raw['type_catalogues'],
                    legal_actions=[a.to_dict() for a in self.game.rules.actions(self.node)],
                    public_setup=dict(intervention_prefix=self.prefix, independent_of_private_types=True),
                    partner_model=specification(self.budgets['turns']),
                    runtime_protocol=dict(version=VERSION,
                        learner_actions='External interventions, not evidence about unknown partner preferences. Restart the common partner window after each learner action.',
                        partner_actions='Filter current worlds only by the actual certified partner policy, within its frozen window.',
                        failure='Unavailable/incompatible teacher disables local supervision; deterministic PASS/REJECT continuation is diagnostic only.',
                        diagnostic_only=bool(self.invalid_reason)), instruction=B_INSTRUCTION))

    def belief_table(self):
        if self.invalid_reason: return None
        return [dict(**q, **marginal(self.worlds, q['player'], q['goal']))
                for q in queries_for(self.game.catalogues, self.raw['ego'])]

    def score_b(self, answer):
        table = self.belief_table()
        usable = table is not None and not self.fragile
        gold = {} if table is None else {(b['player'], b['goal']): b['answer'] for b in table}
        eligible = {(q['player'], q['goal']) for q in queries_for(self.game.catalogues, self.raw['ego'])}
        errors = []; grouped = {}
        if not isinstance(answer, list):
            errors.append('expected_judgment_list'); answer = []
        for item in answer:
            if (not isinstance(item, dict) or type(item.get('player')) is not int
                    or type(item.get('goal')) is not int):
                errors.append('malformed_target'); continue
            target = item['player'], item['goal']
            if target not in eligible:
                errors.append('unexpected_target'); continue
            grouped.setdefault(target, []).append(item)
        marks = []
        for p, g in sorted(eligible):
            items = grouped.get((p, g), [])
            reason = 'missing_target' if not items else 'duplicate_target' if len(items) != 1 else None
            item = items[0] if len(items) == 1 else None
            if item is not None and set(item) != {'player','goal','possible_preferences','favored'}:
                reason = 'malformed_judgment'
            assessment = (dict(score=-1. if usable else None, format_valid=False) if reason else
                score_belief({k:item[k] for k in ('possible_preferences','favored')}, gold[(p,g)] if usable else None))
            if not assessment['format_valid']:
                errors.append(reason or 'invalid_preference_fields')
            marks.append(dict(player=p,goal=g,assessment=assessment,reason=reason))
        mask = usable and bool(marks)
        return dict(mask=mask, score=sum(m['assessment']['score'] for m in marks)/len(marks) if mask else None,
                    format_valid=not errors, selected=marks, protocol_errors=errors,
                    protocol_score=-1. if errors else 0.,
                    reason='; '.join(errors) if errors else self.invalid_reason or ('Residual native-order evidence' if self.fragile else None))

    def reference_action(self, own):
        if not self.ensure_teacher():
            return self.game.rules.actions(self.node)[0]
        t, i, _ = self.position
        return t.action(i, own)

    def step(self, raw_action, *, kind):
        """Invalid actions leave state unchanged. Legal off-policy actions execute."""
        if self.terminal: raise ValueError('Episode already terminal')
        expected = 'learner' if self.actor == self.raw['ego'] else 'partner'
        if kind != expected: raise ValueError('Wrong actor kind')
        action = decode_action(raw_action) if isinstance(raw_action, dict) else raw_action
        legal = self.game.rules.actions(self.node)
        if action not in legal: raise ValueError('Illegal native action')
        actor = self.actor; before = len(self.worlds); diagnostic = None
        if kind == 'partner' and self.ensure_teacher():
            t, i, possible = self.position; entry = t.entries[i]; ai = entry.actions.index(action)
            remaining = tuple(j for j in possible if int(t.policy[i][j]) == ai)
            if not remaining:
                self.invalid_reason = 'Legal partner action incompatible with declared policy; posterior unavailable, not reset to prior'
                self.position = None
            else:
                diagnostic = self.game.evidence(self.position, action)
                self.fragile |= diagnostic['exclusion_reasons']['residual_native_order'] > 0
                self.worlds = tuple(t.worlds[j] for j in remaining)
                child = entry.children[ai]
                self.position = None if t.entries[child].actor is None else (t, child, remaining)
        else:
            # In particular, NEVER call SharedGame.advance for a learner action.
            self.position = None
        self.node = self.game.rules._apply(self.node, action)
        self.history.append(action.to_dict())
        self.events.append(dict(kind=kind, actor=actor, action=action.to_dict(),
                                worlds_before=before, worlds_after=len(self.worlds),
                                evidence=diagnostic, unavailable=self.invalid_reason))

    def finish_reference(self, world, deadline=None):
        """Reference future for a P diagnostic, not the LM's unknown future policy."""
        while not self.terminal:
            if deadline is not None and time.monotonic() >= deadline:
                raise SearchLimit('Reference wall budget exceeded')
            p = self.actor
            action = self.reference_action(world[p])
            self.step(action, kind='learner' if p == self.raw['ego'] else 'partner')
        return self.outcome(world)

    def outcome(self, world):
        if not self.terminal: raise ValueError('Only real terminal utility is an outcome')
        if world not in self.game.worlds: raise ValueError('Environment world outside public catalogue')
        return (np.array(world) @ self.node.state.goal_satisfaction()).tolist()

    def p_reference_values(self, *, max_rollouts=40, seconds=10):
        if self.actor != self.raw['ego']: raise ValueError('P values only at learner decisions')
        actions = self.game.rules.actions(self.node)
        children = [self.game.rules._apply(self.node, a) for a in actions]
        if all(child.state.is_terminal for child in children):
            # Own terminal utility does not require a posterior or partner solver.
            reliable = not (self.invalid_reason or self.fragile)
            rows = []
            for action, child in zip(actions, children):
                sat = child.state.goal_satisfaction()
                own = float(np.array(self.raw['own_preferences']) @ sat)
                others = (float(np.mean([sum(float(np.array(prefs) @ sat) for p,prefs in enumerate(w)
                                           if p != self.raw['ego']) for w in self.worlds])) if reliable else None)
                rows.append(dict(action=action.to_dict(), value=own, others_value=others))
            return dict(mask=True, values=rows, basis='direct_terminal', others_mask=reliable,
                        scope='Exact own terminal utility from public commitments and own preferences; no partner belief required.')
        if self.invalid_reason or self.fragile:
            return dict(mask=False, values=None, reason=self.invalid_reason or 'Fragile type support')
        if len(actions)*len(self.worlds) > max_rollouts:
            return dict(mask=False, values=None, reason='Reference rollout budget exceeded')
        deadline = time.monotonic()+seconds; rows = []
        for action in actions:
            payoffs = []; other_payoffs = []
            for world in self.worlds:
                if time.monotonic() >= deadline:
                    return dict(mask=False, values=None, reason='Reference wall budget exceeded; discard partial rankings')
                future = self.fork(); future.step(action, kind='learner')
                try: outcome = future.finish_reference(world, deadline)
                except SearchLimit:
                    return dict(mask=False, values=None, reason='Reference wall budget exceeded; discard partial rankings')
                if time.monotonic() >= deadline:
                    return dict(mask=False, values=None, reason='Reference wall budget exceeded; discard partial rankings')
                if future.invalid_reason:
                    return dict(mask=False, values=None, reason='A reference continuation was unavailable; discard partial rankings')
                payoffs.append(outcome[self.raw['ego']])
                other_payoffs.append(sum(v for p,v in enumerate(outcome) if p != self.raw['ego']))
            rows.append(dict(action=action.to_dict(), value=float(np.mean(payoffs)),
                             others_value=float(np.mean(other_payoffs))))
        return dict(mask=True, values=rows, basis='reference_continuation', others_mask=True,
                    scope='All future learner actions use the reference policy; partners use the online restart protocol. '
                          'This is a local reference regret target, NOT an on-policy advantage or realized LM outcome.')


def run_episode(raw, prefix, world, b_callback, p_callback, *, score_p=False, **budgets):
    env = OnlineSocial(raw, prefix, **budgets); records = []
    if world not in env.game.worlds: raise ValueError('Environment world outside catalogue')
    while not env.terminal:
        if env.actor == raw['ego']:
            env.ensure_teacher(); context = env.context()
            b = b_callback(deepcopy(context))
            # Even an incorrect/malformed B is not replaced with oracle output.
            p = p_callback(p_input(context, b))
            b_score = env.score_b(b)
            teacher_b = env.belief_table()
            p_values = env.p_reference_values() if score_p else dict(mask=False, values=None, reason='Not requested')
            before = len(env.events)
            env.step(p, kind='learner')
            p_score = None
            if p_values['mask']:
                chosen = next(x['value'] for x in p_values['values'] if x['action'] == p)
                p_score = chosen-max(x['value'] for x in p_values['values'])
            records.append(dict(input=context, model_B=b, model_P=p, B_score=b_score,
                                teacher_B=teacher_b, P_reference=p_values, P_score=p_score, event_index=before))
        else:
            action = env.reference_action(world[env.actor])
            env.step(action, kind='partner')
    return dict(status='terminal', protocol=VERSION, history=env.history, events=env.events, records=records,
                environment_world=world, utilities=env.outcome(world),
                usable_for_training=env.invalid_reason is None, unavailable_reason=env.invalid_reason,
                actual_LM=False)  # Connector/trainer must identify real model calls separately.
