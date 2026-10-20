"""Exact-rational mechanism witness, separate from the production native game.

Two proposal opportunities for A, at most one accepted contract, B has one of
three public joint types. A query reveals ONE selected preference and consumes
one opportunity. Responders compare their final score, then the other score.
No artificial offer penalty, query bonus, GPU, learned policy or cutoff value.
"""
from fractions import Fraction as F
from itertools import product
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
PROJECTS=('X','Y','Z')
TYPES=((1,-1,-1),(0,1,-1),(-1,-1,1))
PRIOR=(F(1,3),)*3
PROFITS=(F(1),F(2),F(2))
ACTIONS=(None,0,1,2)


def mean(values,weights=PRIOR):return sum((p*v for p,v in zip(weights,values)),F(0))
def final(t,j,profits=PROFITS,types=TYPES):
    if j is None:return (F(0),F(0))
    u=types[t][j]
    # Reject gives (0,0). Positive proposer payoff resolves a neutral response.
    return (profits[j],F(u)) if u>=0 else (F(0),F(0))
def acceptable_response(accept,reject):
    keys=((reject[1],reject[0]),(accept[1],accept[0]))
    best=max(keys)
    return {i for i,k in enumerate(keys) if k==best}


def query_value(slot,types=TYPES,profits=PROFITS,masked=False):
    signals={None} if masked else {r[slot] for r in types};policies={};total=F(0)
    for signal in sorted(signals,key=str):
        ids=[t for t,r in enumerate(types) if masked or r[slot]==signal]
        masses=sum((PRIOR[t] for t in ids),F(0))
        vals={j:sum((PRIOR[t]*final(t,j,profits,types)[0] for t in ids),F(0))/masses for j in ACTIONS}
        j=max(ACTIONS,key=lambda a:vals[a]);total+=masses*vals[j]
        policies[str(signal)]=dict(types=ids,chosen='PASS' if j is None else PROJECTS[j],value=vals[j])
    return total,policies


def relaxed_no_query_upper_bound(opportunities=2,types=TYPES,profits=PROFITS):
    if opportunities!=2:raise ValueError('This exact relaxed bound is for two opportunities')
    results=[]
    for first in range(3):
        for replies in product((0,1),repeat=3):
            # A rational responder never takes a negative contract: rejecting
            # every remaining offer guarantees zero. Neutral/positive replies
            # are unrestricted, a relaxation of strategic response rationality.
            if any(reply and types[t][first]<0 for t,reply in enumerate(replies)):continue
            for later in ACTIONS:
                payoff=mean([profits[first] if replies[t] else final(t,later,profits,types)[0] for t in range(3)])
                results.append(dict(first=PROJECTS[first],first_accept_by_type=list(replies),
                    after_reject='PASS' if later is None else PROJECTS[later],value=payoff))
    best=max(r['value'] for r in results)
    return best,[r for r in results if r['value']==best],len(results)


def sequential_offer_branches():
    results={}
    for first in range(3):
        candidates=[]
        for replies in product((0,1),repeat=3):
            reject=[t for t in range(3) if not replies[t]]
            mass=sum((PRIOR[t] for t in reject),F(0))
            belief=tuple(PRIOR[t]/mass if t in reject else F(0) for t in range(3)) if mass else PRIOR
            values={j:mean([final(t,j)[0] for t in range(3)],belief) for j in ACTIONS}
            for later in ACTIONS:
                if values[later]!=max(values.values()):continue
                if any(replies[t] not in acceptable_response((PROFITS[first],F(TYPES[t][first])),final(t,later)) for t in range(3)):continue
                payoff=mean([PROFITS[first] if replies[t] else final(t,later)[0] for t in range(3)])
                candidates.append(dict(first=PROJECTS[first],first_accept_by_type=list(replies),
                    after_reject='PASS' if later is None else PROJECTS[later],posterior_after_reject=belief,value=payoff))
        assert candidates
        results[PROJECTS[first]]=dict(candidates=candidates,selected=max(candidates,key=lambda r:r['value']))
    return results


def serialize(value):
    if isinstance(value,F):return dict(exact=str(value),decimal=float(value))
    if isinstance(value,dict):return {str(k):serialize(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [serialize(v) for v in value]
    return value


def main():
    query,query_policy=query_value(0);masked,_=query_value(0,masked=True)
    upper,upper_policies,count=relaxed_no_query_upper_bound();branches=sequential_offer_branches()
    offer_values={j:r['selected']['value'] for j,r in branches.items()}
    assert query==F(5,3) and upper==F(4,3)
    assert max(offer_values.values())==upper
    assert query-upper==F(1,3) and query-masked==1
    assert masked==F(2,3)
    root={f'INVESTIGATE_{PROJECTS[g]}':query_value(g)[0] for g in range(3)}
    root.update({f'OFFER_{j}':v for j,v in offer_values.items()})
    root['PASS']=max(mean([final(t,j)[0] for t in range(3)]) for j in ACTIONS)
    assert {a for a,v in root.items() if v==max(root.values())}=={'INVESTIGATE_X'}
    # All second-stage A information sets choose an expected-payoff optimum.
    # First B responses are individually own-first/other-second optimal for
    # every type in each selected branch, including off-path first offers.
    # Final responses are checked directly against the same lexicographic rule.
    for t,j in product(range(3),range(3)):
        actual=1 if TYPES[t][j]>=0 else 0
        assert actual in acceptable_response((PROFITS[j],F(TYPES[t][j])),(F(0),F(0)))
    # One query trait becomes binary: more correlation alone is insufficient.
    binary=((1,-1,-1),(-1,1,-1),(-1,-1,1))
    binary_queries={PROJECTS[g]:query_value(g,types=binary)[0] for g in range(3)}
    binary_upper,_,_=relaxed_no_query_upper_bound(types=binary)
    assert max(binary_queries.values())==binary_upper==F(4,3)
    # With three opportunities, Y -> Z -> X serves each type at its best
    # contract. At every response, accepting a positive contract dominates
    # waiting for this particular continuation; negative offers are rejected.
    for i,first in enumerate((1,2,0)):
        for t in range(3):
            if any(TYPES[t][prior]>=0 for prior in (1,2,0)[:i]):continue
            continuation=(F(0),F(0))
            for later in (1,2,0)[i+1:]:
                if TYPES[t][later]>=0:continuation=final(t,later);break
            chosen=1 if TYPES[t][first]>=0 else 0
            assert chosen in acceptable_response((PROFITS[first],F(TYPES[t][first])),continuation)
    three_offers=mean([final(t,(0,1,2)[t])[0] for t in range(3)])
    assert three_offers==query
    results=dict(status='exact-rational-synthetic-witness-verified',
        scope='New two-person asymmetric bargaining mechanism; NOT native BENAC-P, not an activated dataset or existing oracle certificate',
        types=TYPES,prior=PRIOR,A_profits=PROFITS,proposal_opportunities=2,agreement_capacity=1,
        query_observation='One true want/neutral/avoid preference, selected by the investigator; X distinguishes these three joint types',
        query_consumes_one_opportunity=True,rejection_penalty=0,query_utility_bonus=0,
        root_Q_under_constructed_sequential_assessment=root,
        investigate_X=query,best_no_query=upper,strict_acquisition_gap=query-upper,
        masked_same_query_action=masked,answer_value_holding_action_and_cost_fixed=query-masked,
        mixed_policy_bound='Relaxation permits arbitrary first acceptance of neutral/positive offers. Payoff is bilinear in first response probabilities and last-offer mixture, so maximum is attained at enumerated vertices. Negative initial acceptance is dominated by rejecting all offers for zero.',
        relaxed_deterministic_vertices_checked=count,upper_bound_witnesses=upper_policies,
        sequential_offer_branches=branches,query_X_conditional_policy=query_policy,
        verification=dict(full_two_opportunity_horizon=True,private_types_not_revealed_to_A_before_query=True,
            A_root_best_response_gain=0,B_typewise_response_deviation_gain=0,
            second_stage_A_belief_best_responses_verified=True,response_social_ties_verified=True,
            note='Constructed toy-game assessment with explicit off-path beliefs; no claim of a unique equilibrium or production solver certification'),
        controls=dict(binary_private_traits=dict(types=binary,query_values=binary_queries,best_no_query=binary_upper,
            acquisition_gap=max(binary_queries.values())-binary_upper),
            three_proposal_opportunities=dict(no_query_offer_sequence=['Y','Z','X'],no_query_value=three_offers,query_value=query,gap=query-three_offers)),
        model_called=False,gpu_used=False,production_rules_changed=False)
    (OUT/'witness_results.json').write_text(json.dumps(serialize(results),indent=2)+'\n')
    print(json.dumps(serialize({k:results[k] for k in ('status','root_Q_under_constructed_sequential_assessment','strict_acquisition_gap','answer_value_holding_action_and_cost_fixed','relaxed_deterministic_vertices_checked','controls')}),indent=2))


if __name__=='__main__':main()
