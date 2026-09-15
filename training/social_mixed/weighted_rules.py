"""Outcome environment with an explicit nonuniform public generation contract."""
from copy import deepcopy
from training.social_mixed.frozen.outcome_rules import OutcomeRules as LegacyRules,generation_rule
from training.b_sft.preference_contract import VERSION,world_weights
class OutcomeRules(LegacyRules):
 def __init__(self,raw):
  law=raw['preference_generation']
  if law.get('version')!=VERSION:
   super().__init__(raw);return
  prior=law['background_prior'];values=[v for n,v in [('avoid',-1),('neutral',0),('want',1)] if prior['weights'][n]>0]
  if law.get('values')!=values:raise ValueError('Public support disagrees with weights')
  if values not in ([0,1],[-1,0,1]):raise ValueError('Unsupported outcome support')
  legacy=deepcopy(raw);legacy['preference_generation']=generation_rule('foundation' if values==[0,1] else 'adaptation')
  super().__init__(legacy);self.generation=deepcopy(law)
  self.background_world_weights=world_weights(self.worlds,prior)
