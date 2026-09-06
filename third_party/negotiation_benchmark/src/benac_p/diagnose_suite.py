"""Factorial fixed-decision and active-evidence diagnostic suite; see protocol."""
from __future__ import annotations
import argparse
from dataclasses import dataclass, replace, field
import hashlib
from itertools import combinations
import json
import math
import os
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from benac_p.bayes_planner import BayesPlanner
from benac_p.belief import BeliefState, condition_belief
from benac_p.controlled import SoftProgressPolicy
from benac_p.menu_diagnose import fixture, RULES
from benac_p.observations import build_player_observation
from benac_p.schema import ActionRef, GameSpec, Goal, MenuOffer, OfferProposal, PassProposal, VALUE_TO_PREFERENCE, response_actions
from benac_p.state import GameState
from benac_p.diagnose_instances import dependency_candidate, screen

VERSION = 'factorial-diagnose-v1'
SYSTEM = RULES + ' joint_type_support[k][j] is the preference row for partner_ids[j] in hidden joint type k, in G0, G1, ... order. Use initial_probabilities for a history task and current_probabilities for a supplied-belief task. Never assume partners know other players preferences. Return only the requested JSON.'


def dump(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def probabilities(answer, n):
    values = np.asarray(answer['probabilities'], dtype=float)
    if values.shape != (n,) or not np.isfinite(values).all() or (values < 0).any() or not np.isclose(values.sum(), 1, atol=1e-8, rtol=0):
        raise ValueError('Expected a normalized finite nonnegative probability vector.')
    return values / values.sum()


def with_probabilities(belief, values):
    return replace(belief, log_probabilities=tuple(math.log(v) if v else -math.inf for v in values))


@dataclass
class Pack:
    id: str
    split: str
    spec: GameSpec
    prior: BeliefState
    policies: dict
    family: str = 'generated'
    screening: dict = field(default_factory=dict)


def generated_pack(seed, split):
    """Unfiltered generator: connected goals, two persistent joint types.

    Explicit correlated finite prior, NOT the default generator's IID prior.
    No model result or solver gap is used for selection.
    """
    rng = np.random.default_rng(seed)
    refs = [ActionRef(0, 0), ActionRef(0, 1), ActionRef(1, 0), ActionRef(1, 1), ActionRef(2, 0)]
    candidates = [r for k in (2, 3) for r in combinations(refs, k) if len({a.player_id for a in r}) > 1]
    spanning = [r for r in candidates if len({a.player_id for a in r}) == 3]
    first = spanning[int(rng.integers(len(spanning)))]
    other = [r for r in candidates if r != first]
    requirements = [first] + [other[i] for i in rng.choice(len(other), 3, replace=False)]
    goals = tuple(Goal(i, r) for i, r in enumerate(requirements))
    def row():
        values = rng.choice([-1, 0, 1], size=4)
        values[int(rng.integers(4))] = 1
        return tuple(int(v) for v in values)
    own = row()
    worlds = [(row(), row()), (row(), row())]
    while worlds[0] == worlds[1]:
        worlds[1] = (row(), row())
    weight = float(rng.choice([.25, .5, .75]))
    belief = BeliefState((1, 2), tuple(tuple(tuple(VALUE_TO_PREFERENCE[v] for v in r) for r in h) for h in worlds),
                         (math.log(weight), math.log(1-weight)))
    spec = GameSpec(3, (2, 2, 1), goals, np.array((own, *worlds[0])), (0, 0), 1, seed, menu_enabled=True)
    temperature = float(rng.choice([.25, .5, 1.]))
    policies = {i: SoftProgressPolicy(seed=seed+i, temperature=temperature) for i in (1, 2)}
    return Pack(f'g{seed}', split, spec, belief, policies)


def packs(n_games, seed):
    spec, prior, policies = fixture()
    yield Pack('anchor', 'calibration', spec, prior, policies, 'selected_positive_anchor')
    yield Pack('no_information', 'control', spec, prior,
               {i: SoftProgressPolicy(uniform_mix=1.) for i in (1, 2)}, 'no_information')
    yield Pack('known_type', 'control', spec,
               replace(prior, hypotheses=(prior.hypotheses[0],), log_probabilities=(0.,)), policies, 'known_type')
    for i in range(n_games):
        split='discovery' if i < n_games//2 else 'confirmation'
        if i%2==0:
            yield generated_pack(seed+i,split)
        else:
            for attempt in range(256):
                candidate_seed=seed+1_000_000+i*256+attempt
                ds,db,dp=dependency_candidate(candidate_seed)
                evidence=screen(ds,db,dp)
                if evidence['root_action_regret']>.005 and evidence['same_action_update_gain']>.02:
                    yield Pack(f'd{seed+i}',split,ds,db,dp,'dependency_screened',
                               dict(attempts=attempt+1,candidate_seed=candidate_seed,thresholds={'root_action_regret':.005,'same_action_update_gain':.02},**evidence))
                    break
            else:
                raise RuntimeError('Dependency stratum exhausted 256 candidates; no silent fallback.')


def action_branches(pack, action):
    """Exact do(action) distribution; own action contributes no likelihood."""
    state = GameState(pack.spec)
    if isinstance(action, PassProposal):
        state.apply_pass()
        return [(None, 1., pack.prior, state, np.ones(len(pack.prior.hypotheses)))]
    offer = action.offer
    actor = offer.partner_id
    obs = build_player_observation(state, actor, pending_proposer_id=0, pending_offer=offer)
    branches = []
    for response in response_actions(offer):
        likelihood = np.array([pack.policies[actor].response_probability(
            replace(obs, own_preferences=h[actor-1]), offer, response) for h in pack.prior.hypotheses])
        posterior, logp = condition_belief(pack.prior, likelihood)
        child = state.clone()
        child.resolve_offer(offer, response)
        branches.append((response, math.exp(logp), posterior, child, likelihood))
    return branches


def action_info(pack, action):
    return pack.prior.entropy - sum(p*b.entropy for _, p, b, _, _ in action_branches(pack, action))


def matched_menus(pack, actions):
    """Match partner, own option payoff and added-bit counts, NOT future state."""
    obs = build_player_observation(GameState(pack.spec), 0)
    groups = {}
    for action in actions:
        if not isinstance(action, OfferProposal) or not isinstance(action.offer, MenuOffer):
            continue
        signatures = []
        for option in action.offer.offers:
            projected = obs.commitments_if_accepted(option)
            signatures.append((obs.state_facts(projected)['your_utility_if_terminal'], sum(map(sum, projected))))
        key = (action.offer.partner_id, tuple(sorted(signatures)))
        groups.setdefault(key, []).append((action_info(pack, action), action))
    candidates = []
    for entries in groups.values():
        if len(entries) >= 2:
            entries.sort(key=lambda pair: pair[0])
            candidates.append((entries[-1][0]-entries[0][0], entries[-1], entries[0]))
    if not candidates:
        raise ValueError('No matched menu pair in this game.')
    gap, high, low = max(candidates, key=lambda c: c[0])
    return high[1], low[1], float(gap)


class Suite:
    def __init__(self, n_games=24, seed=10000):
        self.tasks = []
        self.labels = {}
        self.contexts = {}
        self.pack_map = {}
        self.certificates = []
        self.n_games = n_games
        self.seed = seed
        self.rng = np.random.default_rng(seed)

    def task(self, tid, kind, payload, label, *, parent=None):
        self.tasks.append(dict(id=tid, kind=kind, input=payload, parent=parent))
        self.labels[tid] = label

    def public(self, pack, state, *, history=True):
        obs = build_player_observation(state, 0)
        if not history:
            obs = replace(obs, transcript=())
        return dict(observation=obs.to_agent_dict(), partner_ids=list(pack.prior.partner_ids), joint_type_support=[h['preferences'] for h in pack.prior.to_dict()['joint']],
                    partner_policy={str(i): p.specification() for i, p in pack.policies.items()})

    def add_case(self, pack, cid, state, belief, *, likelihood=None, weight=1., arm='root'):
        planner = BayesPlanner(partner_policies=pack.policies)
        obs = build_player_observation(state, 0)
        oracle = planner.solve(obs, belief)
        order = self.rng.permutation(len(oracle.action_values))
        values = tuple(oracle.action_values[i] for i in order)
        actions = tuple(v.action for v in values)
        q = [v.value for v in values]
        context = dict(pack=pack, state=state, belief=belief, actions=actions, oracle=oracle)
        self.contexts[cid] = context
        label = dict(case=cid, game=pack.id, split=pack.split, family=pack.family, weight=weight,
                     arm=arm, q=q, optimum=max(q), posterior=list(belief.probabilities),
                     decision_range=max(q)-min(q))
        public = self.public(pack, state)
        public['initial_probabilities'] = list(pack.prior.probabilities)
        self.task(cid+'/belief', 'belief', public, dict(label))
        if likelihood is not None:
            table = dict(initial_probabilities=list(pack.prior.probabilities),
                         observed_event_likelihood_by_type=likelihood.tolist(),
                         instruction='Update the prior on this one observed event. Return probabilities in the same type order.')
            self.task(cid+'/bayes_arithmetic', 'belief', table, dict(label))
        bare = self.public(pack, state, history=False)
        bare['legal_actions'] = [a.to_dict() for a in actions]
        bare['instruction'] = 'Treat supplied current_probabilities as your complete current belief. Choose the action maximizing expected terminal own utility, including future partner actions.'
        for name, prob in [('oracle', belief.probabilities), ('prior', pack.prior.probabilities)]:
            self.task(cid+'/plan_'+name, 'planning', dict(bare, current_probabilities=list(prob)), dict(label))
        self.task(cid+'/plan_model', 'planning', dict(bare), dict(label), parent=cid+'/belief')
        self.task(cid+'/plan_history', 'planning', dict(public, legal_actions=[a.to_dict() for a in actions]), dict(label))
        return context

    def build(self):
        for pack in packs(self.n_games, self.seed):
            self.pack_map[pack.id] = pack
            state = GameState(pack.spec)
            root = self.add_case(pack, pack.id+'/root', state, pack.prior)
            if pack.screening and not math.isclose(root['oracle'].value,pack.screening['adaptive_value'],abs_tol=1e-8):
                raise AssertionError('Fast screening and full planner disagree.')
            actions = root['actions']
            high, low, info_gap = matched_menus(pack, actions)
            single = OfferProposal(high.offer.offers[0])
            arms = {'high': high, 'low': low, 'single': single, 'optimal': root['oracle'].action}
            info = {}
            for arm, action in arms.items():
                info[arm] = dict(action=action.to_dict(),information_gain=action_info(pack, action), branches=[])
                for response, probability, posterior, child, likelihood in action_branches(pack, action):
                    suffix = 'PASS' if response is None else response.value
                    cid = f'{pack.id}/{arm}/{suffix}'
                    self.add_case(pack, cid, child, posterior, likelihood=likelihood, weight=probability, arm=arm)
                    info[arm]['branches'].append(dict(case=cid, probability=probability))
            # Stop reward after first response but KEEP original partner kernel.
            immediate_q = [sum(p*child.reward(0) for _,p,_,child,_ in action_branches(pack,a)) for a in actions]
            root_payload = next(t['input'] for t in self.tasks if t['id']==pack.id+'/root/plan_oracle')
            stop_payload = dict(root_payload, instruction='In this evaluation the game terminates immediately after this proposal and partner response. The supplied partner policy still scores actions using the ORIGINAL schedule. Maximize own utility in that resulting state; there are no subsequent decisions.')
            stop_label = dict(self.labels[pack.id+'/root/plan_oracle'], q=immediate_q, optimum=max(immediate_q), decision_range=max(immediate_q)-min(immediate_q))
            self.task(pack.id+'/stop_after_response', 'planning', stop_payload, stop_label)
            menus = high.offer.offers
            obs = build_player_observation(state, 0)
            facts = [obs.state_facts(obs.commitments_if_accepted(o))['your_utility_if_terminal'] for o in menus]
            grounding = self.public(pack, state)
            grounding['options'] = [o.to_dict() for o in menus]
            grounding['instruction'] = 'For each option if accepted, compute your current utility if the game ended in that state. Return utilities, in option order.'
            self.task(pack.id+'/grounding', 'grounding', grounding, dict(game=pack.id, split=pack.split, family=pack.family, utilities=facts))
            prior_gaps = []
            for entry in info['high']['branches']:
                ctx=self.contexts[entry['case']]
                action=BayesPlanner(partner_policies=pack.policies).act(build_player_observation(ctx['state'],0), pack.prior)
                prior_gaps.append(ctx['oracle'].regret(action))
            self.certificates.append(dict(game=pack.id, split=pack.split, family=pack.family,
                spec=pack.spec.to_dict(include_private=False), prior=pack.prior.to_dict(),
                policy={str(i):p.specification() for i,p in pack.policies.items()}, matched_information_gap=info_gap, arms=info,
                belief_changes_decision=any(g>1e-8 for g in prior_gaps), screening=pack.screening,
                oracle_long_vs_stop_action_gap=max(root['oracle'].value-next(v.value for v in root['oracle'].action_values if v.action==actions[i])
                    for i,q in enumerate(immediate_q) if max(immediate_q)-q<1e-10)))
            print(f'Prepared {pack.id}: {len(self.tasks)} tasks', flush=True)
        # Pure planning control: all partner types known, reward requires P2's
        # future turn. A matched short schedule cannot complete the same goal.
        goals=(Goal(0,tuple(ActionRef(i,0) for i in range(3))),)
        prefs=np.ones((3,1),dtype=int)
        known=BeliefState((1,2), (((VALUE_TO_PREFERENCE[1],),(VALUE_TO_PREFERENCE[1],)),), (0.,))
        for name,schedule in [('long',(0,2)),('short',(0,))]:
            spec=GameSpec(3,(1,1,1),goals,prefs,schedule,1,0,menu_enabled=True)
            pack=Pack('horizon_'+name,'control',spec,known,{i:SoftProgressPolicy() for i in (1,2)},'known_horizon')
            self.pack_map[pack.id]=pack
            self.add_case(pack,pack.id+'/root',GameState(spec),known)
        return self

    def add_model_branches(self, records):
        """Second stage: intervene on the model's selected first action.

        Regenerated deterministically on resume, after the fixed task stage.
        Every response is evaluated, not just a lucky sampled trajectory.
        """
        for cert in self.certificates:
            pack = self.pack_map[cert['game']]
            record = records.get(pack.id+'/root/plan_oracle')
            if record is None or record['status'] != 'ok':
                cert['model_arm_status'] = 'invalid_root_choice'
                continue
            action = self.contexts[pack.id+'/root']['actions'][record['answer']['action_index']]
            info = dict(action=action.to_dict(), information_gain=action_info(pack,action), branches=[])
            for response, probability, posterior, child, likelihood in action_branches(pack,action):
                suffix = 'PASS' if response is None else response.value
                cid = f'{pack.id}/model/{suffix}'
                self.add_case(pack,cid,child,posterior,likelihood=likelihood,weight=probability,arm='model')
                info['branches'].append(dict(case=cid,probability=probability))
            cert['arms']['model'] = info

    def manifest(self):
        return dict(version=VERSION, n_games=self.n_games, seed=self.seed, tasks=len(self.tasks), games=len(self.pack_map),
                    task_hash=digest(self.tasks), calibration_excluded_from_confirmation=True,
                    model_calls_static=len(self.tasks), model_calls_additional_per_game_upper_bound=18,
                    model_calls_total_upper_bound=len(self.tasks)+18*len(self.certificates),
                    population='alternating unfiltered games and oracle-screened dependency family; separate estimates',
                    causal_scope='Explicit belief interface and do(negotiation action); not internal neural mediation.')


def request_payload(task, answers):
    payload = dict(task['input'])
    if task['parent']:
        parent = answers.get(task['parent'])
        if parent is None or parent.get('status') != 'ok':
            raise ValueError('Missing or invalid parent belief; no oracle fallback.')
        payload['current_probabilities'] = parent['answer']['probabilities']
    schema = {'belief': {'probabilities': 'normalized numeric array in type order'},
              'planning': {'action_index': 'zero-based integer index into legal_actions'},
              'grounding': {'utilities': 'numeric array in option order'}}[task['kind']]
    return dict(problem=payload, output_schema=schema)


def validate_answer(task, answer, label):
    if not isinstance(answer, dict):raise ValueError('Output must be a JSON object.')
    if task['kind'] == 'belief':return {'probabilities': probabilities(answer,len(label['posterior'])).tolist()}
    if task['kind'] == 'planning':
        index = answer['action_index']
        if type(index) is not int or not 0 <= index < len(label['q']):raise ValueError('Invalid action index.')
        return {'action_index': index}
    values = np.asarray(answer['utilities'], dtype=float)
    if values.shape != (len(label['utilities']),) or not np.isfinite(values).all():raise ValueError('Invalid utility array.')
    return {'utilities': values.tolist()}


def score(suite, records):
    results=[]
    for task in suite.tasks:
        tid=task['id']; label=suite.labels[tid]; record=records.get(tid)
        row=dict(id=tid, kind=task['kind'], game=label['game'], split=label['split'],family=label['family'],
                 status='missing' if record is None else record['status'],case=label.get('case'), weight=label.get('weight',1.))
        if record is not None and record['status']=='ok':
            answer=record['answer']
            if task['kind']=='belief':
                p=np.array(answer['probabilities']); q=np.array(label['posterior'])
                row.update(tv=float(np.abs(p-q).sum()/2), excess_brier=float(np.square(p-q).sum()))
                row['kl_clipped']=float(sum(qi*math.log(qi/max(pi,1e-12)) for qi,pi in zip(q,p) if qi))
                ctx=suite.contexts[label['case']]
                planner=BayesPlanner(partner_policies=ctx['pack'].policies)
                estimated=with_probabilities(ctx['belief'],p)
                chosen=planner.act(build_player_observation(ctx['state'],0),estimated)
                row['oracle_planner_regret']=ctx['oracle'].regret(chosen)
            elif task['kind']=='planning':
                idx=answer['action_index']; row['regret']=max(0.,label['optimum']-label['q'][idx])
                row['decision_range']=label['decision_range'];row['optimal']=row['regret']<=1e-8
                if tid.endswith('/plan_model'):
                    ctx=suite.contexts[label['case']];p=records[task['parent']]['answer']['probabilities']
                    result=BayesPlanner(partner_policies=ctx['pack'].policies).solve(build_player_observation(ctx['state'],0),with_probabilities(ctx['belief'],p))
                    row['regret_under_supplied_belief']=result.regret(ctx['actions'][idx])
            else:row['exact']=bool(np.allclose(answer['utilities'],label['utilities'],atol=1e-8,rtol=0))
        results.append(row)
    index={r['id']:r for r in results};factorial=[]
    for cid,ctx in suite.contexts.items():
        rows=[index[cid+'/'+suffix] for suffix in ('belief','plan_model','plan_oracle','plan_prior')]
        if not all(r['status']=='ok' for r in rows):
            factorial.append(dict(case=cid,game=ctx['pack'].id,split=ctx['pack'].split,family=ctx['pack'].family,weight=rows[0]['weight'],status='incomplete'))
            continue
        b,ll,ol,placebo=rows;lo=b['oracle_planner_regret'];llr=ll['regret'];olr=ol['regret']
        factorial.append(dict(case=cid,game=ctx['pack'].id,split=ctx['pack'].split,family=ctx['pack'].family,weight=b['weight'],
                              LL=llr,OL=olr,LO=lo,OO=0.,belief_repair_effect=llr-olr,planner_repair_effect=llr-lo,
                              interaction=llr-olr-lo,prior_repair_effect=placebo['regret']-olr))
    active=[]
    for cert in suite.certificates:
        arm_scores={}
        for arm,info in cert['arms'].items():
            weighted_error=weighted_loss=expected_proper=0.;valid=True; model_planning_loss=0.; model_planning_valid=True
            for branch in info['branches']:
                r=index[branch['case']+'/belief']
                if r['status']!='ok':valid=False;break
                weighted_error+=branch['probability']*r['excess_brier']
                weighted_loss+=branch['probability']*r['oracle_planner_regret']
                posterior=suite.contexts[branch['case']]['belief'].probabilities
                expected_proper+=branch['probability']*(r['excess_brier']+1-sum(p*p for p in posterior))
                continuation=index[branch['case']+'/plan_model']
                if continuation['status']=='ok':model_planning_loss+=branch['probability']*continuation['regret']
                else:model_planning_valid=False
            if valid:arm_scores[arm]=dict(expected_belief_error=weighted_error,expected_continuation_regret=weighted_loss,
                                         expected_proper_brier=expected_proper,
                                         full_continuation_regret=model_planning_loss if model_planning_valid else None,
                                         information_gain=info['information_gain'])
        root=suite.contexts[cert['game']+'/root']
        chooser_matrix={}
        for arm,chooser in [('optimal','O'),('model','L')]:
            if arm not in arm_scores:continue
            action_dict=cert['arms'][arm]['action']
            root_value=next(v.value for v in root['oracle'].action_values if v.action.to_dict()==action_dict)
            chooser_matrix[chooser+'O']=root_value
            chooser_matrix[chooser+'L']=root_value-arm_scores[arm]['expected_continuation_regret']
        entry=dict(game=cert['game'],split=cert['split'],family=cert['family'],arms=arm_scores,
                   chooser_updater_utility=chooser_matrix,matched_information_gap=cert['matched_information_gap'])
        if all(k in chooser_matrix for k in ('LL','OL','LO','OO')):
            entry['chooser_repair_effect']=chooser_matrix['OL']-chooser_matrix['LL']
            entry['updater_repair_effect']=chooser_matrix['LO']-chooser_matrix['LL']
            entry['chooser_updater_interaction']=chooser_matrix['OO']-chooser_matrix['OL']-chooser_matrix['LO']+chooser_matrix['LL']
        if 'high' in arm_scores and 'low' in arm_scores:
            entry['forced_menu_brier_reduction']=arm_scores['low']['expected_proper_brier']-arm_scores['high']['expected_proper_brier']
        stop=records.get(cert['game']+'/stop_after_response')
        long=records.get(cert['game']+'/root/plan_oracle')
        if stop and long and stop['status']==long['status']=='ok':
            a=root['actions'][long['answer']['action_index']];b=root['actions'][stop['answer']['action_index']]
            entry['objective_intervention_action_changed']=a!=b
            entry['objective_intervention_information_change']=action_info(root['pack'],a)-action_info(root['pack'],b)
        active.append(entry)
    return dict(results=results,factorial=factorial,active=active)


def cluster_summary(rows, metric, seed=0):
    grouped={}; incomplete=set()
    for r in rows:
        if metric not in r:incomplete.add(r['game'])
        else:grouped.setdefault(r['game'],[]).append((r.get('weight',1.),r[metric]))
    for game in incomplete:grouped.pop(game,None)
    values=np.array([sum(w*v for w,v in rs)/sum(w for w,_ in rs) for rs in grouped.values()])
    if not len(values):return {'n_games':0,'mean':None,'ci95':None,'excluded_incomplete_games':len(incomplete)}
    rng=np.random.default_rng(seed)
    ci=None if len(values)<2 else np.quantile(np.mean(rng.choice(values,size=(2000,len(values))),axis=1),[.025,.975]).tolist()
    return dict(n_games=len(values),mean=float(values.mean()),ci95=ci,excluded_incomplete_games=len(incomplete))


def summarize(suite, scored):
    summaries={}
    for split in ('calibration','control','discovery','confirmation'):
        rows=[r for r in scored['results'] if r['split']==split]
        main=[r for r in rows if '/high/' in r['id']]
        relevant=[r for r in rows if '/optimal/' in r['id']]
        factor=[r for r in scored['factorial'] if r['split']==split and '/optimal/' in r['case']]
        reverse=[r for r in scored['active'] if r['split']==split]
        good_games={r['game'] for r in rows if r['id'].endswith('/grounding') and r.get('exact')}
        family_summaries={}
        for family in sorted({r['family'] for r in rows}):
            family_summaries[family]=dict(
                belief=cluster_summary([r for r in main if r['family']==family and r['id'].endswith('/belief')],'excess_brier'),
                planning=cluster_summary([r for r in relevant if r['family']==family and r['id'].endswith('/plan_oracle')],'regret'),
                belief_repair=cluster_summary([r for r in factor if r['family']==family],'belief_repair_effect'),
                chooser_repair=cluster_summary([r for r in reverse if r['family']==family],'chooser_repair_effect'))
        summaries[split]=dict(by_family=family_summaries,
            forced_menu_brier_reduction=cluster_summary(reverse,'forced_menu_brier_reduction'),
            chooser_repair=cluster_summary(reverse,'chooser_repair_effect'),
            updater_repair=cluster_summary(reverse,'updater_repair_effect'),
            chooser_updater_interaction=cluster_summary(reverse,'chooser_updater_interaction'),
            objective_information_effect=cluster_summary(reverse,'objective_intervention_information_change'),
            grounding_qualified_planning=cluster_summary([r for r in relevant if r['id'].endswith('/plan_oracle') and r['game'] in good_games],'regret'),
            n_screened_games=sum(p.split==split and p.family=='dependency_screened' for p in suite.pack_map.values()),
            requested=len(rows),valid=sum(r['status']=='ok' for r in rows),
            belief=cluster_summary([r for r in main if r['id'].endswith('/belief')],'excess_brier'),
            belief_arithmetic=cluster_summary([r for r in main if r['id'].endswith('/bayes_arithmetic')],'excess_brier'),
            independent_planning=cluster_summary([r for r in relevant if r['id'].endswith('/plan_oracle')],'regret'),
            belief_decision_cost=cluster_summary([r for r in relevant if r['id'].endswith('/belief')],'oracle_planner_regret'),
            grounding=cluster_summary([r for r in rows if r['id'].endswith('/grounding')],'exact'),
            belief_repair=cluster_summary(factor,'belief_repair_effect'),planner_repair=cluster_summary(factor,'planner_repair_effect'),
            interaction=cluster_summary(factor,'interaction'),
            active_planning_regret=cluster_summary([r for r in rows if r['id'].endswith('/root/plan_oracle')],'regret'))
    return summaries


def report(suite, scored, summaries, path):
    lines=['# BENAC-P full diagnosis report','',
           'Hypothesis tests, not guaranteed positive findings. Confirmation games are disjoint from discovery; selected anchor excluded.','',
           '| Split | Valid / requested | Belief excess Brier | Oracle-belief planning regret | Belief repair effect |',
           '|---|---:|---:|---:|---:|']
    def fmt(x):return 'NA' if x is None else f'{x:.6f}'
    for split,s in summaries.items():
        lines.append(f"| {split} | {s['valid']} / {s['requested']} | {fmt(s['belief']['mean'])} | {fmt(s['independent_planning']['mean'])} | {fmt(s['belief_repair']['mean'])} |")
    lines += ['', '| Split | Forced-menu Brier reduction | Chooser repair | Updater repair |',
              '|---|---:|---:|---:|']
    for split,s in summaries.items():
        lines.append(f"| {split} | {fmt(s['forced_menu_brier_reduction']['mean'])} | {fmt(s['chooser_repair']['mean'])} | {fmt(s['updater_repair']['mean'])} |")
    lines += ['', '## Family-specific readings', '']
    for split,s in summaries.items():
        for family,metrics in s['by_family'].items():
            lines.append(f"- {split} / {family}: belief error {fmt(metrics['belief']['mean'])}; planning regret {fmt(metrics['planning']['mean'])}; belief repair {fmt(metrics['belief_repair']['mean'])}; chooser repair {fmt(metrics['chooser_repair']['mean'])}.")
    lines+=['','Read summary.json for game-cluster confidence intervals; scores.json contains cells and controls.',
            'Belief-only error measures posterior reporting. Oracle-belief planning regret tests planning given correct belief. Paired belief repair identifies an effect through the supplied belief interface, not an internal neural mechanism.',
            'Factorial interaction can be positive, negative or zero. Zero interaction does not imply absence of temporal dependency.',
            'Menu interventions identify action-dependent evidence. Physical states differ, so reward differences are not pure information causal effects.',
            'Insufficient valid coverage or insufficient decision gaps makes a conclusion inconclusive. One model does not establish a universal MAS deficit.',
            f"Unfiltered games with high-menu belief-dependent decisions: {sum(c['belief_changes_decision'] for c in suite.certificates if c['family']=='generated')}.",
            f"Pre-screened task-relevant games: {sum(c['family']=='dependency_screened' for c in suite.certificates)}. Interpret this stratum conditional on the declared screening rule."]
    Path(path).write_text('\n'.join(lines)+'\n')


def run_tasks(suite,tasks,records,client,out,workers=4):
    pending=[t for t in tasks if t['id'] not in records or records[t['id']]['status']=='transport_error']
    np.random.default_rng(suite.seed+1).shuffle(pending)
    def infer(task,payload):
        start=time.monotonic()
        try:
            raw=client.complete([{'role':'system','content':SYSTEM},{'role':'user','content':json.dumps(payload)}],response_format={'type':'json_object'})
        except Exception as exc:
            return dict(status='transport_error',error=type(exc).__name__)
        try:
            answer=validate_answer(task,json.loads(raw),suite.labels[task['id']])
            return dict(status='ok',answer=answer,raw=raw,seconds=time.monotonic()-start)
        except (KeyError,ValueError,TypeError) as exc:
            return dict(status='invalid',raw=raw,error=str(exc),seconds=time.monotonic()-start)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while pending:
            ready=[t for t in pending if not t['parent'] or t['parent'] in records][:workers]
            if not ready:raise RuntimeError('Unresolved task dependency.')
            futures={}
            for task in ready:
                pending.remove(task)
                try:payload=request_payload(task,records)
                except ValueError as exc:
                    records[task['id']]=dict(status='blocked_parent',error=str(exc));continue
                futures[pool.submit(infer,task,payload)]=task
            failures=[]
            for future in as_completed(futures):
                tid=futures[future]['id'];records[tid]=future.result()
                dump(out/'answers.json',records)
                print(f"{len(records)}/{len(suite.tasks)} {tid}: {records[tid]['status']}",flush=True)
                if records[tid]['status']=='transport_error':failures.append(tid)
            dump(out/'answers.json',records)
            if failures:raise RuntimeError(f'Inference failed on {failures}; saved. Fix service and use --resume.')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--n-games',type=int,default=24);parser.add_argument('--seed',type=int,default=10000)
    parser.add_argument('--base-url');parser.add_argument('--model')
    parser.add_argument('--export-only',action='store_true');parser.add_argument('--resume',action='store_true')
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--max-tokens',type=int,default=2048);parser.add_argument('--temperature',type=float,default=0.)
    args=parser.parse_args(argv)
    if args.workers<1:parser.error('--workers must be positive')
    if args.n_games<0:parser.error('--n-games must be nonnegative')
    out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
    suite=Suite(args.n_games,args.seed).build();manifest=suite.manifest()
    manifest.update(model=args.model,base_url=args.base_url,max_tokens=args.max_tokens,temperature=args.temperature,workers=args.workers)
    if (out/'manifest.json').exists():
        old=json.loads((out/'manifest.json').read_text())
        if not args.resume:parser.error('Output exists; use a new directory or --resume.')
        if old!=manifest:parser.error('Resume manifest mismatch; model, inputs and settings must match.')
    dump(out/'manifest.json',manifest);dump(out/'tasks.json',dict(system=SYSTEM,tasks=suite.tasks))
    dump(out/'oracle_labels.json',suite.labels);dump(out/'certificates.json',suite.certificates)
    if args.export_only:print(json.dumps(manifest));return
    if not(args.base_url and args.model):parser.error('Supply --base-url and --model, or --export-only')
    from methods.vllm_client import OpenAICompatibleNegotiationClient
    client=OpenAICompatibleNegotiationClient(args.base_url,args.model,api_key=os.environ.get('BENAC_P_VLLM_API_KEY','EMPTY'),max_tokens=args.max_tokens,temperature=args.temperature)
    records={}
    if (out/'answers.json').exists():records=json.loads((out/'answers.json').read_text())
    run_tasks(suite,list(suite.tasks),records,client,out,args.workers)
    fixed_count=len(suite.tasks)
    suite.add_model_branches(records)
    dump(out/'dynamic_tasks.json',suite.tasks[fixed_count:])
    dump(out/'oracle_labels.json',suite.labels)
    dump(out/'certificates.json',suite.certificates)
    run_tasks(suite,suite.tasks[fixed_count:],records,client,out,args.workers)
    scored=score(suite,records);summaries=summarize(suite,scored)
    dump(out/'scores.json',scored);dump(out/'summary.json',summaries);report(suite,scored,summaries,out/'report.md')
    print(f'Completed diagnosis: {out}/report.md')


if __name__=='__main__':main()
