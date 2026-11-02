"""Small-model native sequential CalBench suite; no model-based selection."""
import argparse
from copy import deepcopy
from itertools import permutations
import json
from pathlib import Path
import random

from examples.final_evaluation.calbench_formal import dump, sha, load_frozen as _load

HERE = Path(__file__).resolve().parent
FROZEN = HERE / 'calbench_stream_v1'
CONFIG = dict(num_agents=4, num_slots=8, num_meetings=3, num_participants=3,
              max_turns_per_round=4, decision_retries=1, enable_fallback=False,
              enable_reflection=False, communication_protocol='dm', meeting_cost_level=1)
SAMPLING = dict(temperature=0.0, max_tokens=4096, max_model_len=32768)
PARTICIPANTS = [[0, 1, 2], [1, 2, 3], [0, 2, 3]]


def load_frozen(path=FROZEN):
    return _load(path)


def plans(scenario):
    """Exact final-placement lower bound; native replay certifies attainability."""
    calendars = scenario['calendars']
    candidates = []
    # All participant sets intersect, hence the three meeting slots are distinct.
    for slots in permutations(range(8), 3):
        cost = 0
        for m, slot in zip(scenario['meetings'], slots):
            for a in m['participants']:
                item = calendars[a][slot]
                if item and item.get('blocked'):
                    break
                cost += item['cost'] if item else 0
            else:
                continue
            break
        else:
            candidates.append((cost, slots))
    return sorted(candidates)


def replay(scenario, slots, replan=False, contact=True):
    from calendar_game.game import CalendarGame
    from calendar_game.agents import Agent, BaseClient, TurnResult, DecideResult
    from calendar_game.calendar import Calendar
    agents = []
    class Client(BaseClient):
        def register(self, aid, config): self.aid = aid
        def start_round(self, meeting, *args): self.meeting = meeting
        def turn(self, *args, **kwargs):
            actions = []
            if replan and contact and self.meeting['id'] == 2 and self.aid == 1:
                actions = [dict(type='dm', to=0, content='Move meeting 1 to its agreed replacement slot.')]
            return TurnResult(actions, None, None, None, None, None)
        def actions(self, meeting):
            a = self.aid
            moves = []
            current = deepcopy(agents[a].calendar.slots)
            if replan and meeting['id'] == 2 and a in PARTICIPANTS[0]:
                src, dest = slots[1], slots[0]
                moves.append(dict(type='reschedule', item_id=1, from_slot=src, to_slot=dest, justification='Coordinate existing meeting'))
                current[dest], current[src] = current[src], None
            if a in meeting['participants']:
                slot = slots[meeting['id'] - 1]
                if replan and meeting['id'] == 1: slot = slots[1]
                item = current[slot]
                if item:
                    reserved = {slots[i] for i, m in enumerate(scenario['meetings']) if a in m['participants']}
                    dest = next(i for i, x in enumerate(current) if x is None and i not in reserved)
                    moves.append(dict(type='reschedule', item_id=item['errand_id'], from_slot=slot, to_slot=dest, justification='Clear meeting slot'))
                moves.append(dict(type='schedule', meeting_id=meeting['id'], slot=slot, cost=1))
            return DecideResult(moves, None, None, None, None, None)
        def decide(self, meeting, *args): return self.actions(meeting)
        def voluntary_decide(self, meeting, *args): return self.actions(meeting)
    for row in scenario['calendars']:
        agent = Agent(Client()); agent.calendar = Calendar(8)
        agent.calendar.slots = deepcopy(row); agents.append(agent)
    return CalendarGame(dict(CONFIG, seed=scenario['seed']))._run_with_agents(agents, deepcopy(scenario))


def replan_scenario(seed, varied):
    """Meeting 1 can occupy 0 or 1; meeting 2 needs 0; meeting 3 needs 2.

    Initial placement at 0 makes contacting the now-external player necessary.
    Seed changes private occupancy as well as costs, not just identifiers.
    """
    rng = random.Random(seed)
    calendars = [[dict(errand_id=100+a*8+s, cost=1, blocked=True) for s in range(8)] for a in range(4)]
    for a, free in enumerate(([0,1,2], [0,1], [0,1,2], [0,2])):
        for s in free: calendars[a][s] = None
        # Extra private space differs across seeds without creating a common slot.
        extra = rng.choice([3+a, (4+a)%5+3])
        calendars[a][extra] = dict(errand_id=200+a, cost=rng.randint(1,8) if varied else 1)
    return dict(seed=seed, calendars=calendars, meetings=[dict(id=i+1, participants=p,
        speaker_order=p, duration=1, cost=1) for i,p in enumerate(PARTICIPANTS)])


def freeze(output):
    from examples.final_evaluation.calbench_local import verify_source
    verify_source()
    from calendar_game.scenario import generate_scenario
    from calendar_game.solver import solve_optimal
    output = Path(output)
    if output.exists(): raise FileExistsError(output)
    cases = []; certificates = {}
    for condition, density, blocked in [('loose',.6,0), ('dense',1.0,0), ('blocked',1.0,2), ('replan',None,None)]:
        for costs in ('uniform','varied'):
            for replica, seed in enumerate((2026091901,2026091902,2026091903),1):
                name = f'{condition}_{costs}_s{replica}'
                varied = costs == 'varied'
                if condition == 'replan':
                    scenario = replan_scenario(seed,varied)
                else:
                    scenario = generate_scenario(seed,4,8,density,3,3,participant_lists=PARTICIPANTS,
                        errand_cost_level=8 if varied else 1,meeting_cost_level=1,
                        blocked_errands_per_agent=blocked)
                candidates = plans(scenario)
                assert candidates, name
                optimum, slots = candidates[0]
                scenario['optimal'] = dict(cost=optimum, assignments={i+1:s for i,s in enumerate(slots)})
                native = solve_optimal(scenario['calendars'],scenario['meetings'],8)
                assert native['cost'] == optimum, (name,native,optimum)
                trace = replay(scenario,slots)
                assert trace.metrics['meetings_scheduled']==3, (name,trace.metrics)
                assert trace.metrics['realized_cost']==optimum, (name,trace.metrics,optimum)
                assert not any(e.type in ('batch_rejected','consistency_violation','invalid_tool_call') for e in trace.events), name
                checks = [dict(kind='optimal_complete_stream', trace=json.loads(trace.model_dump_json()))]
                if condition == 'replan':
                    # This path demonstrates endogenous commitment revision;
                    # it is not forced on evaluated models or disclosed to them.
                    for contact in (True,False):
                        t = replay(scenario,(1,0,2),replan=True,contact=contact)
                        assert (t.metrics['meetings_scheduled']==3) == contact, (name,contact,t.metrics)
                        if contact: assert t.metrics['realized_cost']==3
                        else: assert any(e.type=='consistency_violation' for e in t.events)
                        checks.append(dict(kind='replan_contact' if contact else 'replan_missing_contact',trace=json.loads(t.model_dump_json())))
                cases.append(dict(id=name,family=condition,structure_group=f'{condition}_{costs}',
                    scenario_seed=seed,cost_regime=costs,scenario=scenario,
                    provenance='Native generator without model-based filtering' if condition!='replan' else 'Authored sequential commitment-revision control',
                    reference=dict(minimum_team_cost=optimum,assignments_examined=336,
                        scope='Full-stream hindsight lower bound; future meetings are not disclosed to players',
                        proof='Enumerated distinct final meeting slots; displaced initial errands give a lower bound attained by native sequential replay.')))
                certificates[name]=checks
                print(name,optimum,flush=True)
    output.mkdir(); (output/'cases').mkdir(); (output/'certificates').mkdir()
    for c in cases:
        (output/'cases'/f"{c['id']}.json").write_text(dump(c))
        (output/'certificates'/f"{c['id']}.json").write_text(dump(certificates[c['id']]))
    (output/'generator.py.snapshot').write_bytes(Path(__file__).read_bytes())
    (output/'reporting_protocol.md').write_bytes((HERE/'CALBENCH_STREAM.md').read_bytes())
    (output/'metrics.py.snapshot').write_bytes((HERE/'calbench_stream_metrics.py').read_bytes())
    (output/'source.json').write_bytes((HERE/'calbench_source.json').read_bytes())
    files={str(p.relative_to(output)):sha(p.read_bytes()) for p in sorted(output.rglob('*')) if p.is_file()}
    manifest=dict(suite='calbench_stream_v1',stage='formal',case_ids=[c['id'] for c in cases],
        config=CONFIG,sampling=SAMPLING,files=files,reporting_revision=2,
        evaluation_claim='homogeneous_team_transfer',primary_output_budget=4096,vps_status='not_measured',scenario_seeds=[2026091901,2026091902,2026091903],
        note='8 conditions x 3 scenario seeds. Paired cost regimes and shared seeds are not independent structural families. DM only; no claim of full original benchmark replication.')
    (output/'manifest.json').write_text(dump(manifest))
    (output/'MANIFEST.sha256').write_text(sha((output/'manifest.json').read_bytes())+'  manifest.json\n')
    load_frozen(output)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--freeze',type=Path); g.add_argument('--verify',type=Path)
    args=p.parse_args()
    if args.freeze: freeze(args.freeze)
    else:
        manifest,cases=load_frozen(args.verify)
        print(manifest['suite'],len(cases))
