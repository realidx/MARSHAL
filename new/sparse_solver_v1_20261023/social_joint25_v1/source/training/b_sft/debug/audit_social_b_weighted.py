"""Audit v4 development labels without LM calls or training.

Recompute posterior mass with exact fractions from the final lexicographic
action sets, check native replay in both action orders, and export a few
inspectable witnesses. Equal-weight resets below are teacher diagnostics only.
"""
import argparse
from collections import Counter
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

from training.b_sft.social_b_oracle import BeliefOracle, VERSION, canonical
from training.b_sft.social_b_dataset import observer_belief, judgment, fork
from training.b_sft.social_b_evaluation import request, score_attempt
from training.b_sft.social_b_curriculum import family
from training.b_sft.shared_teacher import SearchLimit, TOL


def read(folder, name):
    return [json.loads(line) for line in (folder/name).read_text().splitlines()]


def exact_posterior(oracle):
    masses = {w: Fraction(1,len(oracle.initial_worlds)) for w in oracle.initial_worlds}
    for event in oracle.events:
        before = event['information_before']
        assert len(before['public_worlds']) == len(masses)
        for world, weight in zip(before['public_worlds'], before['public_world_weights']):
            assert math.isclose(float(masses[tuple(map(tuple,world))]), weight, abs_tol=1e-9, rel_tol=0)
        if event['kind']=='partner':
            likelihoods = {}
            for comparison in event['comparisons']:
                values = comparison['values']
                own_max = max(v['own'] for v in values)
                best = [v for v in values if v['own']>=own_max-TOL]
                others_max = max(v['others'] for v in best)
                final = {canonical(v['action']) for v in best if v['others']>=others_max-TOL}
                assert final == {canonical(a) for a in comparison['admissible_actions']}
                probability = Fraction(1,len(final)) if canonical(event['action']) in final else Fraction(0)
                assert float(probability)==comparison['observed_action_likelihood']
                likelihoods[tuple(comparison['own_type'])] = probability
            masses = {world: mass*likelihoods[world[event['actor']]] for world,mass in masses.items()
                      if likelihoods[world[event['actor']]] > 0}
            total = sum(masses.values())
            assert total > 0
            masses = {world:mass/total for world,mass in masses.items()}
        assert set(masses)=={tuple(map(tuple,w)) for w in event['public_worlds_after']}
        for world,weight in zip(event['public_worlds_after'],event['public_world_weights_after']):
            assert math.isclose(float(masses[tuple(map(tuple,world))]),weight,abs_tol=1e-9,rel_tol=0)
    return masses


def audit(folder):
    summary=json.loads((folder/'summary.json').read_text())
    if summary['version']!=VERSION: raise ValueError('Only v4 data can be audited here')
    for path,checksum in summary['source_hashes'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=checksum:
            raise ValueError(f'Data source changed: {path}')
    sources={s['id']:s for s in read(folder,'sources.jsonl')}
    labels={r['id']:r for r in read(folder,'B_labels.jsonl')}
    inputs=read(folder,'B_inputs.jsonl')
    pairs=read(folder,'pairs.jsonl')
    counts=Counter(); failures=[]; examples=[]; decisions=[]; comparison_failures=[]
    witness_ids=set()
    for kind in ('formation','update','strength_change','maintain'):
        eligible=[p for p in pairs if p['category']==kind]
        eligible.sort(key=lambda p:(not(p.get('changes',{}).get('favored_changed') and
                                       not p.get('changes',{}).get('support_changed')),p['after']))
        for p in eligible[:2]:
            witness_ids.update((p['before'],p['after']))
    decision_attempts=0
    for item in inputs:
        tid=item['id']; raw=sources[item['source']]['raw']; inp=item['input']
        prefix=sources[item['source']]['prefix']; history=inp['history']; q=inp['queries'][0]
        events=[dict(action=a,kind='setup' if i<len(prefix) else 'partner') for i,a in enumerate(history)]
        try:
            o=BeliefOracle.replay(raw,events,max_nodes=3000,seconds=2)
            reverse=BeliefOracle.replay(raw,events,max_nodes=3000,seconds=2,reverse_actions=True)
            exact=exact_posterior(o)
            assert set(o.worlds)==set(reverse.worlds)
            reverse_mass=dict(zip(reverse.worlds,reverse.weights))
            for w,weight in zip(o.worlds,o.weights):
                assert math.isclose(weight,float(exact[w]),abs_tol=1e-9,rel_tol=0)
                assert math.isclose(weight,reverse_mass[w],abs_tol=1e-9,rel_tol=0)
            own=tuple(raw['own_preferences'])
            exact={w:mass for w,mass in exact.items() if w[raw['ego']]==own}
            total=sum(exact.values()); assert total>0
            marginal={name:sum(m for w,m in exact.items() if w[q['player']][q['goal']]==v)/total
                      for v,name in ((1,'want'),(0,'neutral'),(-1,'avoid'))}
            gold=observer_belief(o,q['player'],q['goal'])
            assert judgment(gold)==judgment(labels[tid]['answer'])
            assert judgment(gold)==judgment(observer_belief(reverse,q['player'],q['goal']))
            assert set(gold['possible_preferences'])=={v for v,m in marginal.items() if m>0}
            for v,m in marginal.items():
                assert math.isclose(gold['preference_weights'][v],float(m),abs_tol=1e-9,rel_tol=0)
            leaders=[v for v,m in marginal.items() if float(max(marginal.values())-m)<=TOL]
            assert gold['favored']==(leaders[0] if len(leaders)==1 else 'undetermined')
            task=dict(id=tid,family=family(raw),input=inp,gold=dict(judgments=[dict(**q,**judgment(gold))]))
            req=request(task)
            public=json.loads(req['messages'][-1]['content'])
            assert not {'gold','joint_belief','preference_weights','worlds','values'} & public.keys()
            completion=dict(message=dict(tool_calls=[dict(function=dict(name='SUBMIT_BELIEFS',arguments=json.dumps(task['gold'])))]))
            assert score_attempt(task,completion)['exact']
            counts['validated_questions']+=1
            counts['posterior_event_checks']+=len(events)
            counts['multi_possible_favored']+=len(gold['possible_preferences'])>1 and gold['favored']!='undetermined'
            if tid in witness_ids:
                examples.append(dict(id=tid,source=item['source'],query=q,request=req,
                    teacher=gold,joint_belief=o.joint_belief(observer=raw['ego'],own=raw['own_preferences']),
                    last_event=o.events[-1] if o.events else None))
        except (AssertionError,SearchLimit,ValueError) as exc:
            failures.append(dict(id=tid,error=type(exc).__name__,detail=str(exc)));continue
        # Inspect a bounded number of nonuniform roots for a genuine effect on
        # planning. Never use a reset world distribution to generate gold.
        if not o.node.state.is_terminal and max(o.weights)-min(o.weights)>TOL and decision_attempts<40:
            decision_attempts+=1
            try:
                reset=fork(o);reset.weights=tuple([1/len(o.worlds)]*len(o.worlds));reset._tree=None
                actor=o.rules.actor(o.node)
                for own in dict.fromkeys(w[actor] for w in o.worlds):
                    actual=o.choices(own); counterfactual=reset.choices(own)
                    a={canonical(x) for x in actual['admissible_actions']}
                    b={canonical(x) for x in counterfactual['admissible_actions']}
                    if a!=b:
                        decisions.append(dict(id=tid,source=item['source'],actor=actor,own_type=own,
                            retained_weights=list(o.weights),retained_decision=actual,reset_decision=counterfactual))
            except (SearchLimit,ValueError) as exc:
                comparison_failures.append(dict(id=tid,detail=str(exc)))
    result=dict(oracle=VERSION,passed=not failures,training_ready=False,actual_LM=False,
        counts=dict(counts),failures=failures,coverage=summary['coverage_after_selection'],
        screened_categories=summary['screened_categories'],screened_update_favored=summary['screened_update_favored'],
        planning_reset_comparisons=decision_attempts,planning_changed_actions=len(decisions),
        planning_comparison_failures=comparison_failures,
        scope='Exact posterior arithmetic plus native replay/action-order checks under one declared solver; not proof of behavioral realism or equilibrium uniqueness.')
    for name,data in [('weighted_audit.json',result),('weighted_examples.json',dict(checkpoints=examples,
            pairs=[p for p in pairs if p['before'] in witness_ids and p['after'] in witness_ids],
            teacher_weight_reset_witnesses=decisions))]:
        (folder/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))
    if failures: raise RuntimeError('Weighted dataset audit failed; do not train on this pack')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path)
    audit(parser.parse_args().folder)
