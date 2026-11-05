"""Shared actual request and score entry point for native800 D/validation/train adapters."""
from training.strategic_slices.common import decode
from training.strategic_slices.named_prompt_v7 import calls_for
from training.b_sft.social_private_teacher import observed_slots
from .prompt_v4 import request
from .scoring import score

VERSION='native800-request-score-binding-v4'


class Decision:
    def __init__(self,indexed,node_index,world,oracle_row,seed,temperature=1.):
        if node_index!=oracle_row['node']:raise ValueError('Oracle global node mismatch')
        rules=indexed.rules;node,_=indexed.find(node_index)
        actor=rules.actor(node)
        if actor!=oracle_row['actor']or node.state.turn_index!=oracle_row['turn']:
            raise ValueError('Oracle row does not describe this native decision')
        self.actions=list(rules.actions(node))
        if [a.to_dict()for a in self.actions]!=oracle_row['actions']:
            raise ValueError('Oracle/native action menu mismatch')
        if list(world[actor])!=oracle_row['own_type']:
            raise ValueError('Wrong own-information context')
        answers=[[p,g,world[p][g]]for p,g in observed_slots(node,actor)]
        if answers!=oracle_row['private_answers']:
            raise ValueError('Wrong direct-answer context')
        if oracle_row['counterfactual_mass']<=0 or oracle_row['Q_scope']!='contingent_BR':
            raise ValueError('Cannot score an unavailable zero-CF fallback as a fresh Oracle')
        world=tuple(tuple(row)for row in world)
        if world not in rules.worlds:raise ValueError('World outside this game')
        wi=rules.worlds.index(world)
        if not any(w==wi and mass>0 for w,mass in zip(oracle_row['world_ids'],oracle_row['posterior'])):
            raise ValueError('Realized world is outside the conditional entry posterior')
        self.row=oracle_row;self.action_calls=calls_for(rules,node)
        self.request=request(rules,node,world,seed,temperature)

    def score(self,output):
        if output.get('completion',{}).get('status')=='infrastructure_failure':
            raise RuntimeError('Infrastructure failure is not a game reward')
        action_index,status=decode(output,self.actions,self.action_calls)
        return score(self.row,action_index,status)
