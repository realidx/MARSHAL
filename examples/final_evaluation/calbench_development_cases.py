"""Researcher-authored development cases, fixed before any model results."""
from copy import deepcopy


def blocked(a, s):
    return dict(errand_id=1000 + a*8+s, cost=1, blocked=True)


def build_case(name):
    calendars=[[blocked(a,s) for s in range(8)] for a in range(4)]
    if name=='cost_conflict':
        calendars[0][:3]=[None,dict(errand_id=10,cost=3),None]
        calendars[1][:2]=[dict(errand_id=11,cost=8),None]
        calendars[1][3]=None
        calendars[2][:3]=[None,dict(errand_id=12,cost=1),None]
        meeting=dict(id=1,participants=[0,1,2],duration=1,cost=1)
        prior=[]
        reference=dict(minimum_team_cost=4,meeting_slot=1,alternative_slot=0,alternative_team_cost=8,
                       scope='one incoming meeting; native CP-SAT exact for this case')
    elif name=='prior_commitment':
        for a in (0,1,2):
            calendars[a][0]=dict(meeting_id=100,cost=1)
            calendars[a][1]=None
        calendars[3][0]=None
        meeting=dict(id=1,participants=[1,2,3],duration=1,cost=1)
        prior=[dict(id=100,participants=[0,1,2],slot=0,duration=1,cost=1)]
        reference=dict(minimum_team_cost=3,meeting_slot=0,prior_target_slot=1,external_agent=0,
                       scope='all three prior meeting copies must move; validated by native engine replay',
                       native_static_oracle_is_complete=False)
    else:
        raise ValueError(name)
    scenario=dict(seed=2026091801,calendars=calendars,meetings=[meeting],prior_meetings=prior)
    # Native engine accepts precomputed reference schedules, as in its own prior-meeting fixture.
    assignments={1:reference['meeting_slot']}
    if prior:assignments[100]=1
    scenario['optimal']=dict(cost=reference['minimum_team_cost'],assignments=assignments)
    return dict(name=name,stage='development',formal_test=False,origin='authored before model evaluation',
                scenario=scenario,reference=reference)


def validate_cases():
    """Verify structure and replay successful/failed coordinated actions in native rules."""
    from examples.final_evaluation.calbench_local import verify_source
    verify_source()
    from calendar_game.solver import solve_optimal, _slot_cost
    from calendar_game.game import CalendarGame
    from calendar_game.agents import Agent, BaseClient, TurnResult, DecideResult
    from calendar_game.calendar import Calendar

    cost=build_case('cost_conflict')
    s=cost['scenario'];oracle=solve_optimal(s['calendars'],s['meetings'],8)
    assert oracle['cost']==4 and oracle['assignments'][1]==1
    slot_costs=[_slot_cost(s['calendars'],[0,1,2],slot) for slot in range(8)]
    assert slot_costs==[8,4,None,None,None,None,None,None]
    cross=build_case('prior_commitment');s=cross['scenario']
    # Agent 3's immovable commitments force the incoming meeting to slot 0.
    assert s['calendars'][3][0] is None
    assert all(x.get('blocked') for x in s['calendars'][3][1:])
    common=[slot for slot in range(8) if all(s['calendars'][a][slot] is None for a in (0,1,2))]
    assert common==[1]
    static=solve_optimal(s['calendars'],s['meetings'],8)
    assert static['cost']==2  # Known limitation: omits external agent 0's required move.

    def replay(case, contact=True, chosen_slot=None):
        scenario=deepcopy(case['scenario'])
        is_prior=case['name']=='prior_commitment'
        target=case['reference']['meeting_slot'] if chosen_slot is None else chosen_slot
        class Client(BaseClient):
            def register(self,aid,config):self.aid=aid
            def start_round(self,*args):pass
            def turn(self,messages,*args,**kwargs):
                actions=[dict(type='dm',to=0,content='Move prior meeting 100 to slot 1.')] if is_prior and contact and self.aid==1 else []
                return TurnResult(actions,None,None,None,None,None)
            def decide(self,meeting,calendar_render):
                actions=[]
                item=scenario['calendars'][self.aid][target]
                if item is not None:
                    dest=1 if is_prior else (3 if self.aid==1 else 2)
                    actions.append(dict(type='reschedule',item_id=item.get('meeting_id',item.get('errand_id')),
                                        from_slot=target,to_slot=dest,justification='Development replay'))
                actions.append(dict(type='schedule',meeting_id=1,slot=target))
                return DecideResult(actions,None,None,None,None,None)
            def voluntary_decide(self,meeting,calendar_render):
                return DecideResult([dict(type='reschedule',item_id=100,from_slot=0,to_slot=1,
                                          justification='Development replay')],None,None,None,None,None)
        agents=[]
        for a in range(4):
            agent=Agent(Client());agent.calendar=Calendar(8);agent.calendar.slots=deepcopy(scenario['calendars'][a]);agents.append(agent)
        game=CalendarGame(dict(num_agents=4,num_slots=8,num_meetings=1,max_turns_per_round=1,
                               decision_retries=0,enable_fallback=False,enable_reflection=False))
        return game._run_with_agents(agents,scenario)
    low=replay(cost);high=replay(cost,chosen_slot=0)
    yes=replay(cross);no=replay(cross,contact=False)
    assert low.metrics['meetings_scheduled']==high.metrics['meetings_scheduled']==1
    assert low.metrics['realized_cost']==4 and high.metrics['realized_cost']==8
    assert yes.metrics['meetings_scheduled']==1 and yes.metrics['realized_cost']==3
    assert no.metrics['meetings_scheduled']==0
    assert any(e.type=='consistency_violation' for e in no.events)
    return dict(cost_slot_costs=slot_costs,cost_optimal=oracle,prior_static_oracle=static,
                prior_verified_team_cost=3,prior_without_external_coordination_success=False,
                native_replays_passed=4)


if __name__=='__main__':
    import json
    print(json.dumps(validate_cases(),indent=2))
