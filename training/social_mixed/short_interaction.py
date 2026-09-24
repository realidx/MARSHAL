"""Offline candidate: native two-player closed-loop O against selected-policy partner.
No runtime training defaults are changed. Agent returns a native action dict.
"""
from copy import deepcopy
import random
import numpy as np
from training.b_sft.debug.audit_readable_pretraining import reconstruct
from training.b_sft.social_private_teacher import PrivateEpisode, observed_slots
from training.b_sft.social_b_oracle import canonical, NAMES

VERSION = 'short-native-interaction-candidate-v1'

class ShortInteraction:
    def __init__(self, task, max_decisions=3, **budgets):
        if task.get('paired_view') != 'O' or task['input']['game']['n_players'] != 2:
            raise ValueError('Requires a two-player O parent')
        if max_decisions not in (2, 3): raise ValueError('Two or three ego decisions only')
        self.task=deepcopy(task); inp=task['input']; raw,own=reconstruct(inp)
        raw['background_prior']=inp['background_prior']
        self.episode=PrivateEpisode(raw,inp.get('imposed_setup',[]),**budgets)
        for action in inp.get('voluntary_history',[]): self.episode.observe(action)
        self.tree=self.episode.tree; self.root=self.episode.index; self.ego=inp['player']
        root=self.tree.entries[self.root]
        if root.actor!=self.ego: raise ValueError('Start must be an ego decision')
        if root.node.state.public_state()!=inp['current_state']: raise ValueError('State reconstruction mismatch')
        if self.tree.certificate['policy_sha256']!=task['teacher']['policy_sha256']:
            raise ValueError('Teacher identity mismatch')
        facts=tuple((r['player'],r['goal'],{'want':1,'neutral':0,'avoid':-1}[r['preference']]) for r in inp.get('private_results',[]))
        self.weights=self.episode._weights(self.ego,own,facts)
        def depth(i):
            e=self.tree.entries[i]
            return (0 if e.actor is None else int(e.actor==self.ego)+max(depth(c) for c in e.children))
        self.max_decisions=depth(self.root)
        if not 2<=self.max_decisions<=max_decisions: raise ValueError(f'Not a bounded multi-decision window: {self.max_decisions}')

    def rollout(self, agent, seed=0, world_index=None):
        rng=random.Random(seed)
        if world_index is None:world_index=rng.choices(range(len(self.weights)),weights=self.weights)[0]
        if not 0<=world_index<len(self.weights) or self.weights[world_index]<=0:raise ValueError('Incompatible world')
        world=self.tree.worlds[world_index]; i=self.root; node=deepcopy(self.tree.entries[i].node)
        node.state.private_results=tuple(tuple((p,g,world[p][g]) for p,g in observed_slots(node,a)) for a in range(2))
        events=deepcopy(self.task['input'].get('voluntary_history',[])); records=[]
        while self.tree.entries[i].actor is not None:
            entry=self.tree.entries[i]; actor=entry.actor
            if actor==self.ego:
                inp=deepcopy(self.task['input']);inp.update(current_state=node.state.public_state(),
                    private_results=[dict(player=p,goal=g,preference=NAMES[v]) for p,g,v in node.state.private_results[actor]],
                    pending_offer=None if node.pending is None else node.pending.to_dict(),
                    voluntary_history=deepcopy(events),legal_actions=[a.to_dict() for a in entry.actions])
                # Callback receives visible data only, never teacher/world/values.
                action=agent(deepcopy(inp))
                lookup={canonical(a.to_dict()):j for j,a in enumerate(entry.actions)}
                if canonical(action) not in lookup:
                    return dict(status='invalid_action',terminal_utility=None,decisions=records)
                j=lookup[canonical(action)];records.append(dict(input=inp,action=deepcopy(action)))
            else:
                ids=next(ids for ids in self.tree.information_groups[i] if world_index in ids)
                probs=self.tree.policy[i][:,world_index]
                # Partner must not distinguish worlds in the same private information set.
                np.testing.assert_allclose(self.tree.policy[i][:,ids],np.repeat(probs[:,None],len(ids),axis=1),atol=1e-8)
                j=rng.choices(range(len(probs)),weights=probs)[0]
                action=entry.actions[j].to_dict()
            node=self.episode.rules.step(node,entry.actions[j],realized_world=world)
            events.append(deepcopy(action));i=entry.children[j]
            assert node.state.public_state()==self.tree.entries[i].node.state.public_state()
        return dict(status='terminal',terminal_utility=self.episode.rules.terminal_payoffs(node,world)[self.ego],
                    decisions=records,ego_decisions=len(records),final_state=node.state.public_state(),
                    policy_sha256=self.tree.certificate['policy_sha256'])


def trajectory_advantages(results):
    """Require completed legal trajectories; protocol failures need separate handling."""
    if not results or any(r['status']!='terminal' for r in results):raise ValueError('No fabricated terminal reward for failed rollouts')
    rewards=np.array([r['terminal_utility'] for r in results],float)
    return ((rewards-rewards.mean())/(rewards.std()+1e-6)).tolist()


def decision_request(inp, variant=0):
    """Render the live observation with the existing native O interface."""
    from training.social_mixed.prompt_clarification import request
    task=dict(task='P',skill='history_action',input=deepcopy(inp),prompt_clarification='required-commitments-v1')
    task['input']['belief_source']='history'
    task['input']['supplied_belief']=dict(known_preferences=[],unresolved_preferences=[],support='')
    payload=request(task,arm='action_tools',variant=variant)
    # Static teacher-argmax tolerance is not a trajectory reward contract.
    payload['messages'][1]['content']=payload['messages'][1]['content'].replace(
        'An action is acceptable if it loses at most 0.1 goal-completion points compared with the best action. When responses are equally good for you, the allowance for helping others is also 0.1 points in total.',
        'Your performance is evaluated by your final game payoff after the remaining interaction.')
    return payload


def decode_action(inp, completion, variant=0):
    """Strict native tool decoding; maps display names back to environment actions."""
    import json
    from training.b_sft import social_named_probe as named
    if completion.get('finish_reason')=='length':raise ValueError('Truncated answer')
    calls=completion['raw_message'].get('tool_calls') or []
    if len(calls)!=1:raise ValueError('Expected exactly one native action call')
    call=calls[0]['function'];args=json.loads(call['arguments'])
    visible=named.present(dict(task='P',skill='history_action',input=inp),variant)
    for native,display in zip(inp['legal_actions'],visible['legal_actions']):
        name,expected=named.action_call(display)
        if name==call['name'] and args==expected:return deepcopy(native)
    raise ValueError('Illegal action')


def collect_group(env, complete, seed=0, size=8, variant=0):
    """Model-ready collector. complete(request)->normalized completion.

    Returns entire trajectories, not independent decision rewards. Failed calls
    remain explicit and are not silently resampled or assigned terminal utility.
    This does not replace the existing trainer's sequence packing/loss pipeline.
    """
    results=[]
    for replica in range(size):
        calls=[]
        def agent(inp):
            payload=decision_request(inp,variant)
            completion=complete(deepcopy(payload))
            calls.append(dict(request=payload,completion=deepcopy(completion)))
            try:return decode_action(inp,completion,variant)
            except (ValueError,KeyError,TypeError):return {'action':'INVALID_SUBMISSION'}
        result=env.rollout(agent,seed+replica)
        result['calls']=calls;results.append(result)
    advantages=trajectory_advantages(results) if all(r['status']=='terminal' for r in results) else None
    return dict(trajectories=results,trajectory_advantages=advantages,
                status='complete' if advantages is not None else 'protocol_failure_requires_handling')
